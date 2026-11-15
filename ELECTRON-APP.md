# PTZ-Optics Controller — build, install, and run

## A. Build the installer (do this once, on YOUR dev PC)

You need these installed **only on the PC that builds**:

| Tool | Get it from | Note |
|------|-------------|------|
| Python 3.10+ | python.org | tick **Add python.exe to PATH** |
| Node.js LTS | nodejs.org | includes `npm` |

Then just double-click **`build.bat`** (or run it from a terminal in the project folder).
It does four things for you:

1. installs the Python packages (`requirements.txt` + PyInstaller)
2. bundles the Python backend into `ptz-backend.exe` (so **other PCs do not need Python**)
3. runs `npm install`
4. runs `npm run dist` to make the installers

When it finishes, the `dist\` folder contains:

* `PTZ-Optics-Controller-Setup-<version>.exe` — normal installer (Start menu + desktop shortcut, uninstaller)
* `PTZ-Optics-Controller-Portable-<version>.exe` — one file, no install, just double-click

Build takes a few minutes the first time. Re-run `build.bat` whenever you change code.
**Bump `"version"` in `package.json` before each build** so you can tell builds apart.

---

## B. Install on another computer

1. Copy the **Setup** `.exe` (or the **Portable** one) to the other PC (USB stick, shared drive, etc.).
2. Double-click it.
   * **"Windows protected your PC" (SmartScreen):** the app isn't code-signed, so this is expected.
     Click **More info → Run anyway**. (Removing the warning needs a paid code-signing certificate.)
3. Open **PTZ-Optics Controller** → **Settings** → enter the camera **IP, username, password** → Save.
   Settings are stored **per computer**, so each PC needs this once.
4. First launch may show a **Windows Firewall** prompt. Local use works either way.
   Click **Allow** only if you want other devices (phone, Stream Deck, another PC) to open
   `http://<this-pc-ip>:8080`.

The other PC needs: Windows 10/11 64-bit and network access to the camera. Nothing else.

### Hotkeys / END Stream on the other PC
The app presses **Ctrl+Alt+letter** to control your streaming software.
* The streaming software must be set up with the same hotkeys on that PC.
* If the streaming software runs **as Administrator**, this app must also run as Administrator,
  otherwise Windows blocks the key presses. (Right-click the app → Run as administrator.)
* The END Stream button can be switched on/off in **Settings → END Stream**, and its hotkey list (click a box, press the keys, set the wait) is edited there too.

### Copying your scenes to the new PC
Scene names/thumbnails are saved in the app's data folder (`settings.json`, `presets.json`, `presets\`).
To move them: on the old PC press `Win+R`, type `%APPDATA%`, find the folder that contains
`presets.json`, and copy `presets.json` + the `presets` folder to the same place on the new PC
(run the app once there first so the folder exists).

---

## C. Run without installing (development)

```bat
pip install -r requirements.txt
npm install
npm start
```
or just double-click `RUN.vbs` / `RUN.bat` to run the web page version in your browser.

---

## D. Updating other PCs
Build a new installer with a higher version number and run it on the other PC — it upgrades in place
and keeps that PC's settings and scenes.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Blank window / "backend did not start" | Look at `backend.log` in the app data folder (`%APPDATA%`, folder containing `settings.json`). Make sure nothing else uses port 8080. |
| Port 8080 already in use | Close the other program, or set environment variable `PORT=9090` before launching. |
| Camera dot stays red | Check IP in Settings; the PC and camera must be on the same network. |
| Camera moves but won't stop | Press **STOP ALL MOVEMENT** in the sidebar; check network quality to the camera. |
| Hotkeys do nothing | See "Hotkeys" above (Administrator / same hotkeys in streaming software). |
| `build.bat` fails at step 2 | Run `py -m pip install pyinstaller` manually and re-run; antivirus can also quarantine PyInstaller output — add the project folder as an exclusion. |
