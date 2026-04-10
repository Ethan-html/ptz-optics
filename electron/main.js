/**
 * PTZ-Optics desktop shell: starts the Flask backend and opens the UI with no app menu bar.
 */
const { app, BrowserWindow, Menu } = require("electron");
const fs = require("fs");
const path = require("path");
const http = require("http");
const { spawn } = require("child_process");

function windowIconPath() {
  const candidates = [
    path.join(__dirname, "..", "icon.ico"),
    path.join(process.resourcesPath, "icon.ico"),
  ];
  for (const p of candidates) {
    try {
      if (fs.existsSync(p)) return p;
    } catch (_) {
      /* ignore */
    }
  }
  return undefined;
}

const BACKEND_PORT = process.env.PORT || "8080";
const START_URL = `http://127.0.0.1:${BACKEND_PORT}/`;

let mainWindow = null;
let backendProcess = null;

function backendRoot() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "backend");
  }
  return path.join(__dirname, "..");
}

function waitForServer(url, maxAttempts = 80) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const tryOnce = () => {
      const req = http.get(url, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        attempts += 1;
        if (attempts >= maxAttempts) {
          reject(new Error("Backend did not become ready in time."));
        } else {
          setTimeout(tryOnce, 250);
        }
      });
    };
    tryOnce();
  });
}

function startBackend() {
  const root = backendRoot();
  const script = path.join(root, "app.py");
  const userData = app.getPath("userData");

  const env = {
    ...process.env,
    PORT: BACKEND_PORT,
    FLASK_DEBUG: "0",
    PTZ_DATA_DIR: userData,
  };

  const python =
    process.platform === "win32"
      ? process.env.PTZ_PYTHON || "python"
      : process.env.PTZ_PYTHON || "python3";

  backendProcess = spawn(python, [script], {
    cwd: root,
    env,
    stdio: "pipe",
    windowsHide: true,
  });

  backendProcess.on("error", (err) => {
    console.error("Failed to start Python backend:", err);
  });
}

function stopBackend() {
  if (!backendProcess) return;
  try {
    backendProcess.kill();
  } catch (_) {
    /* ignore */
  }
  backendProcess = null;
}

function createWindow() {
  const icon = windowIconPath();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    show: false,
    autoHideMenuBar: true,
    ...(icon ? { icon } : {}),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.setMenuBarVisibility(false);
  mainWindow.loadURL(START_URL);
  mainWindow.once("ready-to-show", () => mainWindow.show());

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  startBackend();

  waitForServer(START_URL)
    .then(() => createWindow())
    .catch((err) => {
      console.error(err);
      stopBackend();
      app.quit();
    });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      waitForServer(START_URL).then(() => createWindow());
    }
  });
});

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  stopBackend();
});
