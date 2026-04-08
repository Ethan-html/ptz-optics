from pathlib import Path
from http.client import InvalidURL
from base64 import b64encode
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request, send_from_directory
import json
import keyboard 

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
PRESETS_DIR = BASE_DIR / "presets"
PRESETS_FILE = BASE_DIR / "presets.json"
SETTINGS_FILE = BASE_DIR / "settings.json"
key_map = ["q","w","e","r","t","y","u","i","o","p","a","s","d","f","g","h","j","k","l","z","x","c","v","b","n","m"]

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

    return {
        "ip": ip,
        "user": user,
        "pass": password,
        "sceneCount": int(payload.get("sceneCount", 30) or 30),
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
    base = camera_base_url(settings)
    url = f"{base}/{path_with_query.lstrip('/')}"
    req = Request(url, headers=camera_auth_header(settings), method="GET")
    with urlopen(req, timeout=timeout) as response:
        return response.read()
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

# Legacy endpoints kept for compatibility with old UI flow.
@app.route("/saveSnapshot", methods=["POST"])
def save_snapshot_legacy():
    num = str(request.args.get("num", "")).strip()
    if not num:
        return "Missing preset number", 400
    if "file" not in request.files:
        return "No file uploaded", 400

    request.files["file"].save(PRESETS_DIR / f"{num}.jpg")
    upsert_preset(num, bump_version=True)
    return jsonify({"status": "ok"})
@app.route("/updatePreset", methods=["POST"])
def update_preset_legacy():
    data_in = request.get_json(silent=True) or {}
    num = str(data_in.get("num", "")).strip()
    if not num:
        return jsonify({"status": "error", "message": "Missing preset number"}), 400
    name = str(data_in.get("name", f"Preset {num}")).strip()
    upsert_preset(num, name=name or f"Preset {num}", bump_version=True)
    return jsonify({"status": "ok"})
@app.route("/presets/<path:filename>")
def serve_image(filename):
    return send_from_directory(PRESETS_DIR, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)