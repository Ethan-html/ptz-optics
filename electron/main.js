/**
 * PTZ-Optics desktop shell: starts the backend and opens the UI with no app menu bar.
 *
 * Backend lookup order (packaged app):
 *   1. resources/backend/ptz-backend.exe  <- bundled by build.bat (no Python needed)
 *   2. python app.py                      <- fallback / development
 */
const { app, BrowserWindow, Menu, dialog } = require("electron");
const fs = require("fs");
const path = require("path");
const http = require("http");
const { spawn } = require("child_process");

const BACKEND_PORT = process.env.PORT || "8080";
const START_URL = `http://127.0.0.1:${BACKEND_PORT}/`;

let mainWindow = null;
let backendProcess = null;
let backendLog = null;

// Only one copy of the app at a time (a 2nd copy would fight over port 8080).
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

function windowIconPath() {
  const candidates = [
    path.join(__dirname, "..", "icon.ico"),
    path.join(process.resourcesPath || "", "icon.ico"),
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

function backendRoot() {
  if (app.isPackaged) return path.join(process.resourcesPath, "backend");
  return path.join(__dirname, "..");
}

function waitForServer(url, maxAttempts = 120) {
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
          reject(new Error("The camera controller backend did not start in time."));
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
  const userData = app.getPath("userData");
  fs.mkdirSync(userData, { recursive: true });

  const env = {
    ...process.env,
    PORT: BACKEND_PORT,
    FLASK_DEBUG: "0",
    PTZ_DATA_DIR: userData,
  };

  const bundledExe = path.join(root, "ptz-backend.exe");
  let command;
  let args;
  if (process.platform === "win32" && fs.existsSync(bundledExe)) {
    command = bundledExe;
    args = [];
  } else {
    command =
      process.platform === "win32"
        ? process.env.PTZ_PYTHON || "python"
        : process.env.PTZ_PYTHON || "python3";
    args = [path.join(root, "app.py")];
  }

  // Send backend output to a log file. (An unread pipe eventually fills up and freezes the backend.)
  try {
    backendLog = fs.openSync(path.join(userData, "backend.log"), "a");
  } catch (_) {
    backendLog = "ignore";
  }

  backendProcess = spawn(command, args, {
    cwd: root,
    env,
    stdio: ["ignore", backendLog, backendLog],
    windowsHide: true,
  });

  backendProcess.on("error", (err) => {
    console.error("Failed to start backend:", err);
    dialog.showErrorBox(
      "PTZ-Optics Controller",
      "Could not start the backend.\n\n" +
        err.message +
        "\n\nIf you are running from source, make sure Python 3 is installed and on PATH " +
        "(or set PTZ_PYTHON)."
    );
    app.quit();
  });

  backendProcess.on("exit", (code) => {
    backendProcess = null;
    if (code && mainWindow) {
      dialog.showErrorBox(
        "PTZ-Optics Controller",
        `The backend stopped unexpectedly (exit code ${code}).\n\nLog: ${path.join(userData, "backend.log")}`
      );
    }
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
  if (!app.hasSingleInstanceLock()) return;
  Menu.setApplicationMenu(null);
  startBackend();

  waitForServer(START_URL)
    .then(() => createWindow())
    .catch((err) => {
      dialog.showErrorBox("PTZ-Optics Controller", err.message);
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
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => stopBackend());
