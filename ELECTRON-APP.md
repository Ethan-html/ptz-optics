# PTZ-Optics as a Windows app (Electron)

This project is a **Flask** web server (Python) plus a static **HTML** UI. The Electron shell starts the Python backend, opens a normal desktop window, and **does not show** the usual application menu bar (File, Edit, View, …)—only your page and the standard window title bar (minimize / maximize / close).

The server still listens on **`0.0.0.0`** (all interfaces), so other computers on your LAN can open **`http://<this-PCs-LAN-IP>:8080`** in a browser while the app is running.

---

## What you need installed

1. **Node.js** (LTS recommended) — includes `npm`.
2. **Python 3** — available as `python` on your PATH (on some systems use the `py` launcher; see below).
3. Python packages (from the project folder):

   ```bat
   cd /d C:\path\to\ptz-optics
   python -m pip install -r requirements.txt
   ```

   The `keyboard` library often needs **administrator** rights or appropriate permissions to simulate hotkeys on Windows.

---

## One-time setup (Node dependencies)

From the project root (where `package.json` lives):

```bat
npm install
```

---

## Run as a desktop app (development)

```bat
npm start
```

This will:

- Start Flask on **port 8080** (unless you set `PORT`).
- Store settings and preset images under Electron’s **user data** folder (not next to `app.py`), via the `PTZ_DATA_DIR` environment variable—so the installed `.exe` can write data without touching read-only install folders.

To use another port (must match in the browser if you open the LAN URL manually):

```bat
set PORT=9090
npm start
```

---

## Build a Windows installer / `.exe` (packaging)

```bat
npm run dist
```

Output appears under **`dist\`**. You get an NSIS installer (and unpacked artifacts depending on configuration) you can copy to other PCs.

**Important:** The packaged app still **runs `python app.py`** from the copied `backend` resources. The target machine must have:

- Python 3 on PATH as `python`, **or**
- You can point to a specific interpreter before launching (PowerShell example):

  ```powershell
  $env:PTZ_PYTHON = "C:\Path\To\python.exe"
  ```

  The Electron main process uses `PTZ_PYTHON` when set (Windows), otherwise `python`.

If you later want a **single** installer with no separate Python install, you would bundle an embedded Python or use PyInstaller for the backend—this is not set up in the repo; the steps above are the supported path today.

---

## Network access (other computers)

1. Start the app (or run `RUN.bat` / `python app.py` without Electron).
2. On this PC, find its IPv4 address (e.g. `ipconfig`).
3. On another device on the same network, open:

   `http://192.168.x.x:8080`

   (Replace with your real IP; use the same **port** as `PORT`, default **8080**.)

4. **Windows Firewall:** allow inbound connections for **Python** or for **TCP port 8080** when prompted, or add a rule manually.

---

## Behavior notes

| Topic | Behavior |
|--------|----------|
| **Menu bar** | Removed with `Menu.setApplicationMenu(null)` and `setMenuBarVisibility(false)` so you do not get File/Edit/etc. |
| **Window** | Normal framed window (`BrowserWindow`), not a custom frameless shell—looks like a typical Windows program. |
| **Backend bind address** | Flask uses `host="0.0.0.0"` so LAN access works. |
| **Data when using Electron** | `PTZ_DATA_DIR` is set to Electron `userData`; `settings.json`, `presets.json`, and `presets\` images go there. |
| **Data when using `RUN.bat` only** | No `PTZ_DATA_DIR`; files stay in the project folder next to `app.py`. |

To migrate data from a folder install to the Electron app, copy `settings.json`, `presets.json`, and the `presets` folder into the Electron `userData` directory for this app (path is under `%APPDATA%` for Electron apps; exact folder name matches `productName` / `appId`).

---

## Optional: app icon

1. Add a Windows icon file, e.g. `build\icon.ico`.
2. In `package.json`, under `"build"`, add:

   ```json
   "win": {
     "icon": "build/icon.ico"
   }
   ```

Rebuild with `npm run dist`.

---

## Optional: `python` vs `py` launcher

If `python` is not on PATH but the Windows Store / `py` launcher works, either:

- Add Python to PATH, or  
- Set `PTZ_PYTHON` to the full path of `python.exe`, or  
- Create a small wrapper `python.cmd` on PATH that calls `py`.

---

## Troubleshooting

- **Blank window or immediate exit:** Confirm `python -m pip install -r requirements.txt` succeeded and `python app.py` runs without errors from the `backend` folder.
- **Port already in use:** Another process is using `8080`. Stop it or set `PORT` to a free port for both Electron and any manual browser URL.
- **Hotkeys not firing:** `keyboard` may need elevated privileges on Windows.
