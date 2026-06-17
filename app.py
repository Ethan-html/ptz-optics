import json
import os
from base64 import b64encode
from http.client import InvalidURL
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import requests
from requests.auth import HTTPDigestAuth

import keyboard
from flask import Flask, Response, jsonify, request, send_from_directory

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
_data_dir = os.environ.get("PTZ_DATA_DIR", "").strip()
DATA_DIR = Path(_data_dir) if _data_dir else BASE_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

PRESETS_DIR = DATA_DIR / "presets"
PRESETS_FILE = DATA_DIR / "presets.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
key_map = [
    "q", "w", "e", "r", "t", "y", "u", "i", "o", "p",
    "a", "s", "d", "f", "g", "h", "j", "k", "l",
    "z", "x", "c", "v", "b", "n", "m",
]

PRESETS_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return default
def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_settings():
    return load_json(
        SETTINGS_FILE,
        {"ip": "", "user": "", "pass": "", "sceneCount": 30},
    )


def normalize_settings(payload):
    ip = str(payload.get("ip", "")).strip()
    if ip.startswith("http://") or ip.startswith("https://"):
        parsed = urlparse(ip)
        ip = parsed.netloc or parsed.path

    user = str(payload.get("user", "")).strip()
    password = str(payload.get("pass", "")).strip()

    try:
        page_zoom = int(payload.get("pageZoom", 100))
    except (TypeError, ValueError):
        page_zoom = 100
    page_zoom = max(50, min(200, page_zoom))

    return {
        "ip": ip,
        "user": user,
        "pass": password,
        "sceneCount": int(payload.get("sceneCount", 30) or 30),
        "pageZoom": page_zoom,
    }


def camera_base_url(settings):
    ip = str(settings.get("ip", "")).strip()
    if not ip:
        raise ValueError("Camera IP is not configured")
    return f"http://{ip}"


def camera_auth_header(settings):
    user = str(settings.get("user", "")).strip()
    password = str(settings.get("pass", "")).strip()
    if not user:
        return {}
    token = b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def camera_get(path_with_query: str, timeout: int = 4) -> bytes:
    settings = get_settings()

    url = (
        f"{camera_base_url(settings)}/"
        f"{path_with_query.lstrip('/')}"
    )

    response = requests.get(
        url,
        auth=HTTPDigestAuth(
            settings.get("user", ""),
            settings.get("pass", "")
        ),
        timeout=timeout,
    )

    response.raise_for_status()
    return response.content


def upsert_preset(num: str, name: str | None = None, bump_version: bool = True):
    data = load_json(PRESETS_FILE, {})
    item = data.get(num, {"name": f"Preset {num}", "img": "", "version": 0})
    if name:
        item["name"] = name
    item["img"] = f"/presets/{num}.jpg"
    if bump_version:
        item["version"] = int(item.get("version", 0)) + 1
    data[num] = item
    save_json(PRESETS_FILE, data)
    return item

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/icon.ico")
def app_icon():
    icon = BASE_DIR / "icon.ico"
    if icon.is_file():
        return send_from_directory(BASE_DIR, "icon.ico", mimetype="image/x-icon")
    return Response(status=204)


@app.route("/presets.json")
def get_presets():
    return jsonify(load_json(PRESETS_FILE, {}))
@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "GET":
        settings_data = get_settings()
        safe = {
            "ip": settings_data.get("ip", ""),
            "user": settings_data.get("user", ""),
            "pass": settings_data.get("pass", ""),
            "sceneCount": settings_data.get("sceneCount", 30),
        }
        if "pageZoom" in settings_data and settings_data.get("pageZoom") is not None:
            try:
                pz = int(settings_data["pageZoom"])
                safe["pageZoom"] = max(50, min(200, pz))
            except (TypeError, ValueError):
                pass
        return jsonify(safe)

    payload = request.get_json(silent=True) or {}
    settings_data = normalize_settings(payload)
    save_json(SETTINGS_FILE, settings_data)
    return jsonify({"status": "ok", "settings": settings_data})
@app.route("/api/camera/status")
def camera_status():
    try:
        camera_get("status")
        return jsonify({"online": True})
    except HTTPError as exc:
        # Old behavior: any HTTP response (including 404/401/etc) means camera is reachable.
        return jsonify({"online": True, "code": exc.code})
    except Exception:
        return jsonify({"online": False})
@app.route("/api/presets/<int:preset_num>/recall", methods=["POST"])
def recall_preset(preset_num: int):
    try:
        camera_get(f"cgi-bin/ptzctrl.cgi?ptzcmd&poscall&{preset_num}")
        return jsonify({"status": "ok"})
    except (ValueError, HTTPError, URLError, OSError, InvalidURL) as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
@app.route("/api/presets/<int:preset_num>/save", methods=["POST"])
def save_preset(preset_num: int):
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", f"Preset {preset_num}")).strip() or f"Preset {preset_num}"
    try:
        camera_get(f"cgi-bin/ptzctrl.cgi?ptzcmd&posset&{preset_num}")
        jpg = camera_get("snapshot.jpg", timeout=8)
    except (ValueError, HTTPError, URLError, OSError, InvalidURL) as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    image_path = PRESETS_DIR / f"{preset_num}.jpg"
    image_path.write_bytes(jpg)
    item = upsert_preset(str(preset_num), name=name, bump_version=True)
    return jsonify({"status": "ok", "preset": item})
@app.route("/api/hotkey/<int:num>")
def hotkey(num):
    if 0 <= num < len(key_map):
        key = key_map[num]
        keyboard.press_and_release(f"ctrl+alt+{key}")
        return f"Hotkey {num} triggered: Ctrl+Alt+{key}", 200
    return "Invalid hotkey", 400


@app.route("/presets/<path:filename>")
def serve_image(filename):
    return send_from_directory(PRESETS_DIR, filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)