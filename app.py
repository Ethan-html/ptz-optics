import json
import logging
import os
import re
import sys
import threading
import time
from http.client import InvalidURL
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

import keyboard
import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from requests.auth import HTTPDigestAuth

app = Flask(__name__)
# Held PTZ buttons send many requests; don't log every one.
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# When frozen with PyInstaller, bundled files (index.html, icon.ico) live in sys._MEIPASS.
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
BASE_DIR = RESOURCE_DIR
_data_dir = os.environ.get("PTZ_DATA_DIR", "").strip()
DATA_DIR = Path(_data_dir) if _data_dir else Path(__file__).resolve().parent
DATA_DIR.mkdir(parents=True, exist_ok=True)

PRESETS_DIR = DATA_DIR / "presets"
PRESETS_FILE = DATA_DIR / "presets.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
PRESETS_DIR.mkdir(parents=True, exist_ok=True)

key_map = [
    "q", "w", "e", "r", "t", "y", "u", "i", "o", "p",
    "a", "s", "d", "f", "g", "h", "j", "k", "l",
    "z", "x", "c", "v", "b", "n", "m",
]

DEFAULT_SETTINGS = {
    "ip": "",
    "user": "",
    "pass": "",
    "sceneCount": 30,
    "pageZoom": 100,
    # END Stream: on/off switch + ordered list of hotkeys.
    # Each step presses `keys`, then waits `delay` seconds before the NEXT step.
    "endEnabled": True,
    "endSteps": [],
}

DEFAULT_DELAY = 5
MAX_STEPS = 12
KEY_TOKEN = r"(?:[a-z0-9]{1,10}(?: [a-z0-9]{1,10})?|[-=\[\];',./\\`])"
KEYS_RE = re.compile(r"^" + KEY_TOKEN + r"(\+" + KEY_TOKEN + r"){0,4}$")


# ---------------------------------------------------------------- helpers
def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return default


def save_json(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)  # atomic: a crash mid-write can't corrupt the file


def clean_steps(raw):
    """Keep only valid, non-empty hotkey steps. Empty boxes are dropped, never saved."""
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        keys = str(item.get("keys", "")).strip().lower()
        if not keys or not KEYS_RE.match(keys):
            continue
        try:
            delay = float(item.get("delay", DEFAULT_DELAY))
        except (TypeError, ValueError):
            delay = DEFAULT_DELAY
        delay = max(0.0, min(600.0, delay))
        out.append({"keys": keys, "delay": int(delay) if delay == int(delay) else round(delay, 1)})
        if len(out) >= MAX_STEPS:
            break
    return out


def get_settings():
    data = load_json(SETTINGS_FILE, {})
    merged = {**DEFAULT_SETTINGS, **data}
    if "endSteps" not in data:
        # Upgrade from the old two-hotkey format (endHotkeyA / endDelay / endHotkeyB).
        a = clamp_int(data.get("endHotkeyA"), 0, len(key_map) - 1, 4)
        b = clamp_int(data.get("endHotkeyB"), 0, len(key_map) - 1, 18)
        d = clamp_int(data.get("endDelay"), 0, 600, DEFAULT_DELAY)
        merged["endSteps"] = [
            {"keys": f"ctrl+alt+{key_map[a]}", "delay": d},
            {"keys": f"ctrl+alt+{key_map[b]}", "delay": DEFAULT_DELAY},
        ]
    else:
        merged["endSteps"] = clean_steps(merged["endSteps"])
    merged["endEnabled"] = bool(merged.get("endEnabled", True))
    return merged


def clamp_int(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def normalize_settings(payload, existing):
    ip = str(payload.get("ip", "")).strip()
    if ip.startswith(("http://", "https://")):
        parsed = urlparse(ip)
        ip = parsed.netloc or parsed.path

    password = str(payload.get("pass", "")).strip()
    if not password:  # blank = keep the saved one (GET never sends it back)
        password = existing.get("pass", "")

    return {
        "ip": ip,
        "user": str(payload.get("user", "")).strip(),
        "pass": password,
        "sceneCount": clamp_int(payload.get("sceneCount"), 1, 50, 30),
        "pageZoom": clamp_int(payload.get("pageZoom"), 50, 200, 100),
        "endEnabled": bool(payload.get("endEnabled", True)),
        "endSteps": clean_steps(payload.get("endSteps", [])),
    }


# One session per (ip, user, pass) so Digest auth reuses its nonce instead of
# doing a 401 round-trip on every single request. This matters for PTZ moves.
_session_lock = threading.Lock()
_session = None
_session_key = None


def camera_session(settings):
    global _session, _session_key
    key = (settings.get("ip"), settings.get("user"), settings.get("pass"))
    with _session_lock:
        if _session is None or key != _session_key:
            s = requests.Session()
            s.auth = HTTPDigestAuth(settings.get("user", ""), settings.get("pass", ""))
            _session, _session_key = s, key
        return _session


def camera_get(path_with_query: str, timeout: int = 4) -> bytes:
    settings = get_settings()
    ip = str(settings.get("ip", "")).strip()
    if not ip:
        raise ValueError("Camera IP is not configured")
    url = f"http://{ip}/{path_with_query.lstrip('/')}"
    response = camera_session(settings).get(url, timeout=timeout)
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


CAMERA_ERRORS = (ValueError, requests.RequestException, HTTPError, URLError, OSError, InvalidURL)


def press_hotkey(num: int):
    if not (0 <= num < len(key_map)):
        raise ValueError("Invalid hotkey")
    keyboard.press_and_release(f"ctrl+alt+{key_map[num]}")


def press_keys(keys: str):
    """Press an arbitrary combo such as 'ctrl+alt+t' or 'f9'."""
    if not KEYS_RE.match(keys):
        raise ValueError(f"Invalid hotkey: {keys}")
    keyboard.press_and_release(keys)


# ---------------------------------------------------------------- pages
@app.route("/")
def index():
    return send_from_directory(RESOURCE_DIR, "index.html")


@app.route("/icon.ico")
def app_icon():
    if (RESOURCE_DIR / "icon.ico").is_file():
        return send_from_directory(RESOURCE_DIR, "icon.ico", mimetype="image/x-icon")
    return Response(status=204)


@app.route("/presets.json")
def get_presets():
    return jsonify(load_json(PRESETS_FILE, {}))


@app.route("/presets/<path:filename>")
def serve_image(filename):
    return send_from_directory(PRESETS_DIR, filename)


# ---------------------------------------------------------------- settings
@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    current = get_settings()
    if request.method == "GET":
        # The password is never sent back to the browser.
        out = {k: v for k, v in current.items() if k != "pass"}
        out["hasPass"] = bool(current.get("pass"))
        return jsonify(out)

    payload = request.get_json(silent=True) or {}
    new = normalize_settings(payload, current)
    save_json(SETTINGS_FILE, new)
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------- camera
@app.route("/api/camera/status")
def camera_status():
    try:
        camera_get("status")
        return jsonify({"online": True})
    except HTTPError as exc:
        return jsonify({"online": True, "code": exc.code})
    except requests.HTTPError:
        return jsonify({"online": True})  # got an HTTP answer, so it's reachable
    except Exception:
        return jsonify({"online": False})


# Live preview: the camera's snapshot.jpg, cached for a moment so several viewers
# (PC + phone) don't multiply the load on the camera.
_snap_lock = threading.Lock()
_snap = {"t": 0.0, "data": b""}


@app.route("/api/camera/snapshot")
def camera_snapshot():
    try:
        with _snap_lock:
            if time.monotonic() - _snap["t"] > 0.25 or not _snap["data"]:
                _snap["data"] = camera_get("snapshot.jpg", timeout=3)
                _snap["t"] = time.monotonic()
            data = _snap["data"]
    except CAMERA_ERRORS as exc:
        return jsonify({"status": "error", "message": str(exc)}), 502
    resp = Response(data, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/presets/<int:preset_num>/recall", methods=["POST"])
def recall_preset(preset_num: int):
    try:
        camera_get(f"cgi-bin/ptzctrl.cgi?ptzcmd&poscall&{preset_num}")
        return jsonify({"status": "ok"})
    except CAMERA_ERRORS as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route("/api/presets/<int:preset_num>/save", methods=["POST"])
def save_preset(preset_num: int):
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", f"Preset {preset_num}")).strip() or f"Preset {preset_num}"
    try:
        camera_get(f"cgi-bin/ptzctrl.cgi?ptzcmd&posset&{preset_num}")
        jpg = camera_get("snapshot.jpg", timeout=8)
    except CAMERA_ERRORS as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    (PRESETS_DIR / f"{preset_num}.jpg").write_bytes(jpg)
    item = upsert_preset(str(preset_num), name=name, bump_version=True)
    return jsonify({"status": "ok", "preset": item})


# ---------------------------------------------------------------- live PTZ control
# PTZOptics HTTP-CGI: /cgi-bin/ptzctrl.cgi?ptzcmd&<action>&<pan speed 1-24>&<tilt speed 1-20>
MOVE_ACTIONS = {
    "up", "down", "left", "right",
    "leftup", "leftdown", "rightup", "rightdown",
}


@app.route("/api/ptz/move", methods=["POST"])
def ptz_move():
    p = request.get_json(silent=True) or {}
    action = str(p.get("action", ""))
    try:
        if action == "home":
            camera_get("cgi-bin/ptzctrl.cgi?ptzcmd&home")
        elif action == "stop":
            camera_get("cgi-bin/ptzctrl.cgi?ptzcmd&ptzstop")
        elif action in MOVE_ACTIONS:
            pan = clamp_int(p.get("panSpeed"), 1, 24, 8)
            tilt = clamp_int(p.get("tiltSpeed"), 1, 20, 8)
            camera_get(f"cgi-bin/ptzctrl.cgi?ptzcmd&{action}&{pan}&{tilt}", timeout=2)
        else:
            return jsonify({"status": "error", "message": "Invalid move action"}), 400
        return jsonify({"status": "ok"})
    except CAMERA_ERRORS as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route("/api/ptz/zoom", methods=["POST"])
def ptz_zoom():
    p = request.get_json(silent=True) or {}
    action = str(p.get("action", ""))
    speed = clamp_int(p.get("speed"), 1, 7, 3)
    try:
        if action in ("zoomin", "zoomout"):
            camera_get(f"cgi-bin/ptzctrl.cgi?ptzcmd&{action}&{speed}", timeout=2)
        elif action == "zoomstop":
            camera_get("cgi-bin/ptzctrl.cgi?ptzcmd&zoomstop")
        else:
            return jsonify({"status": "error", "message": "Invalid zoom action"}), 400
        return jsonify({"status": "ok"})
    except CAMERA_ERRORS as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route("/api/ptz/focus", methods=["POST"])
def ptz_focus():
    p = request.get_json(silent=True) or {}
    action = str(p.get("action", ""))
    speed = clamp_int(p.get("speed"), 1, 7, 3)
    try:
        if action in ("focusin", "focusout"):
            camera_get(f"cgi-bin/ptzctrl.cgi?ptzcmd&{action}&{speed}", timeout=2)
        elif action == "focusstop":
            camera_get("cgi-bin/ptzctrl.cgi?ptzcmd&focusstop")
        elif action == "autofocus":
            camera_get("cgi-bin/ptzctrl.cgi?ptzcmd&unlock_mfocus")
        elif action == "manualfocus":
            camera_get("cgi-bin/ptzctrl.cgi?ptzcmd&lock_mfocus")
        else:
            return jsonify({"status": "error", "message": "Invalid focus action"}), 400
        return jsonify({"status": "ok"})
    except CAMERA_ERRORS as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route("/api/ptz/stopall", methods=["POST"])
def ptz_stop_all():
    """Safety net: stop pan/tilt, zoom and focus in one call."""
    errors = []
    for cmd in ("ptzstop", "zoomstop", "focusstop"):
        try:
            camera_get(f"cgi-bin/ptzctrl.cgi?ptzcmd&{cmd}", timeout=2)
        except CAMERA_ERRORS as exc:
            errors.append(str(exc))
    if errors:
        return jsonify({"status": "error", "message": errors[0]}), 400
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------- hotkeys
@app.route("/api/hotkey/<int:num>")
def hotkey(num):
    try:
        press_hotkey(num)
    except ValueError:
        return "Invalid hotkey", 400
    except Exception as exc:  # e.g. keyboard lib permission problems
        return f"Hotkey failed: {exc}", 500
    return f"Hotkey {num} triggered: Ctrl+Alt+{key_map[num]}", 200


# ---------------------------------------------------------------- END Stream macro
# Runs on the server so it still finishes if the window is closed/refreshed,
# and can be cancelled during any wait.
_end_lock = threading.Lock()
_end_state = {"state": "idle", "step": "", "index": 0, "total": 0,
              "remaining": 0, "progress": 0.0, "error": ""}
_end_cancel = threading.Event()


def _set_end(**kw):
    with _end_lock:
        _end_state.update(kw)


def _run_end_stream(steps):
    n = len(steps)
    total_wait = sum(float(s["delay"]) for s in steps[:-1])
    waited = 0.0
    try:
        for i, step in enumerate(steps):
            _set_end(state="running", index=i, total=n, step=f"Step {i + 1}/{n}", error="")
            press_keys(step["keys"])
            if i == n - 1:
                break
            delay = float(step["delay"])
            end_at = time.monotonic() + delay
            while True:
                left = end_at - time.monotonic()
                if left <= 0:
                    break
                if _end_cancel.is_set():
                    _set_end(state="cancelled", step=f"Cancelled after step {i + 1}", remaining=0)
                    return
                done = waited + (delay - left)
                _set_end(step=f"Step {i + 1}/{n} done, waiting",
                         remaining=int(left) + 1,
                         progress=(done / total_wait) if total_wait else 1.0)
                time.sleep(0.15)
            waited += delay
        _set_end(state="done", step="Stream ended", remaining=0, progress=1.0)
    except Exception as exc:
        _set_end(state="error", step="Failed", error=str(exc))


@app.route("/api/endstream/start", methods=["POST"])
def endstream_start():
    s = get_settings()
    steps = s["endSteps"]
    if not s["endEnabled"] or not steps:
        return jsonify({"status": "error", "message": "END Stream is off or has no hotkeys"}), 400
    with _end_lock:
        if _end_state["state"] == "running":
            return jsonify({"status": "error", "message": "Already running"}), 409
        _end_state.update(state="running", step="Starting...", index=0, total=len(steps),
                          remaining=0, progress=0.0, error="")
    _end_cancel.clear()
    threading.Thread(target=_run_end_stream, args=(steps,), daemon=True).start()
    return jsonify({"status": "ok"})


@app.route("/api/endstream/cancel", methods=["POST"])
def endstream_cancel():
    _end_cancel.set()
    return jsonify({"status": "ok"})


@app.route("/api/endstream/status")
def endstream_status():
    with _end_lock:
        return jsonify(dict(_end_state))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    # threaded so a held PTZ button and status polling never block each other
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
