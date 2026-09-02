const { app, BrowserWindow, shell, session, dialog } = require('electron');
const path = require('path');
const { spawn, fork } = require('child_process');
const http = require('http');
const { autoUpdater } = require('electron-updater');

let nextProcess = null;
let pythonProcess = null;
let mainWindow = null;

// Configure Auto-Updater
function setupAutoUpdater() {
  if (!app.isPackaged) return;

  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('update-available', (info) => {
    console.log('[electron] Update available:', info.version);
  });

  autoUpdater.on('update-downloaded', (info) => {
    console.log('[electron] Update downloaded:', info.version);
    dialog
      .showMessageBox({
        type: 'info',
        title: 'Update Ready',
        message: `Version ${info.version} has been downloaded. Restart the application now to apply the update?`,
        buttons: ['Restart', 'Later'],
        defaultId: 0,
        cancelId: 1,
      })
      .then((returnValue) => {
        if (returnValue.response === 0) {
          autoUpdater.quitAndInstall();
        }
      });
  });

  autoUpdater.on('error', (err) => {
    console.warn('[electron] Auto-updater error:', err?.message || err);
  });

  autoUpdater.checkForUpdatesAndNotify().catch((err) => {
    console.warn('[electron] Check for updates failed:', err?.message || err);
  });
}

// Determine environment
const isDev = process.env.NODE_ENV !== 'production' && !app.isPackaged;
const appDataPath = app.getPath('userData');
const dbPath = path.join(appDataPath, 'data.db');
const logDir = path.join(appDataPath, 'logs');

async function getAvailablePort(defaultPort) {
  try {
    const getPortModule = await import('get-port');
    const getPort = getPortModule.default;
    return await getPort({ port: getPortModule.portNumbers(defaultPort, defaultPort + 100) });
  } catch (err) {
    console.warn(`[electron] get-port failed, falling back to ${defaultPort}:`, err);
    return defaultPort;
  }
}

function waitForHttp(url, timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    const startTime = Date.now();
    const interval = 500;

    const check = () => {
      const req = http.get(url, (res) => {
        if (res.statusCode && res.statusCode < 500) {
          resolve(true);
        } else {
          retry();
        }
      });

      req.on('error', () => {
        retry();
      });

      req.setTimeout(2000, () => {
        req.destroy();
        retry();
      });
    };

    const retry = () => {
      if (Date.now() - startTime > timeoutMs) {
        reject(new Error(`Timeout waiting for ${url}`));
      } else {
        setTimeout(check, interval);
      }
    };

    check();
  });
}

async function startPythonBackend(port) {
  return new Promise((resolve, reject) => {
    console.log(`[electron] Starting Python backend on port ${port}...`);

    let binaryPath;
    let spawnArgs = [];

    if (app.isPackaged) {
      // In production packaged app, blm-backend.exe is placed in extraResources / dist
      binaryPath = path.join(process.resourcesPath, 'blm-backend', 'blm-backend.exe');
      if (!require('fs').existsSync(binaryPath)) {
        binaryPath = path.join(process.resourcesPath, 'blm-backend.exe');
      }
    } else {
      const distBackend = path.join(__dirname, '..', 'dist-backend', 'blm-backend.exe');
      const venvPython = path.join(__dirname, '..', 'backend', '.venv', 'Scripts', 'python.exe');
      if (require('fs').existsSync(distBackend)) {
        binaryPath = distBackend;
      } else if (require('fs').existsSync(venvPython)) {
        binaryPath = venvPython;
        spawnArgs = [path.join(__dirname, '..', 'backend', 'main.py')];
      } else {
        binaryPath = 'python';
        spawnArgs = [path.join(__dirname, '..', 'backend', 'main.py')];
      }
    }

    const env = {
      ...process.env,
      PORT: String(port),
      DB_PATH: dbPath,
      LOG_DIR: logDir,
      PYTHONUNBUFFERED: '1',
      ADMIN_PASSWORD: process.env.ADMIN_PASSWORD || 'admin',
    };

    console.log(`[electron] Spawning backend: ${binaryPath} with DB_PATH=${dbPath} LOG_DIR=${logDir}`);

    pythonProcess = spawn(binaryPath, spawnArgs, {
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });

    pythonProcess.stdout.on('data', (data) => {
      console.log(`[python] ${data.toString().trim()}`);
    });

    pythonProcess.stderr.on('data', (data) => {
      console.error(`[python-err] ${data.toString().trim()}`);
    });

    pythonProcess.on('error', (err) => {
      console.error('[electron] Python backend failed to spawn:', err);
      reject(err);
    });

    pythonProcess.on('exit', (code, signal) => {
      console.log(`[electron] Python backend exited with code ${code}, signal ${signal}`);
    });

    // Wait for backend /api/system-config or health check
    waitForHttp(`http://127.0.0.1:${port}/api/system-config`, 30000)
      .then(() => {
        console.log('[electron] Python backend is ready.');
        resolve(true);
      })
      .catch((err) => {
        console.error('[electron] Backend wait timeout:', err);
        // Do not silently proceed with a broken backend; reject so Electron logs the reason
        reject(err);
      });
  });
}

async function startNextServer(nextPort, pythonPort) {
  return new Promise((resolve, reject) => {
    console.log(`[electron] Starting Next.js server on port ${nextPort}...`);

    const serverScript = path.join(__dirname, '..', 'server.js');
    // If NODE_ENV is explicitly provided in env (e.g. cross-env NODE_ENV=production), respect it.
    // If not packaged and not set, check if .next production build exists; if so, default to production
    // to avoid the Turbopack dev server hang.
    let nodeEnv = process.env.NODE_ENV;
    if (!nodeEnv) {
      if (app.isPackaged) {
        nodeEnv = 'production';
      } else {
        const dotNextExists = require('fs').existsSync(path.join(__dirname, '..', '.next'));
        nodeEnv = dotNextExists ? 'production' : 'development';
      }
    }

    const env = {
      ...process.env,
      NODE_ENV: nodeEnv,
      PORT: String(nextPort),
      PYTHON_BACKEND_URL: `http://127.0.0.1:${pythonPort}`,
    };

    nextProcess = fork(serverScript, [], {
      env,
      silent: false,
      cwd: path.join(__dirname, '..'),
    });

    nextProcess.on('error', (err) => {
      console.error('[electron] Next.js server failed to fork:', err);
      reject(err);
    });

    nextProcess.on('exit', (code, signal) => {
      console.log(`[electron] Next.js server exited with code ${code}, signal ${signal}`);
    });

    waitForHttp(`http://127.0.0.1:${nextPort}/`, 60000)
      .then(() => {
        console.log('[electron] Next.js server is ready.');
        resolve(true);
      })
      .catch((err) => {
        console.error('[electron] Next.js server startup failed:', err);
        reject(err);
      });
  });
}

function createMainWindow(nextPort) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: 'BLM Terminal',
    backgroundColor: '#0a0a0a',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });

  // Intercept window.open calls from frontend (pop-out widgets)
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const parsedUrl = new URL(url);
      const isInternal =
        parsedUrl.hostname === '127.0.0.1' ||
        parsedUrl.hostname === 'localhost' ||
        parsedUrl.origin === `http://127.0.0.1:${nextPort}`;

      if (isInternal) {
        return {
          action: 'allow',
          overrideBrowserWindowOptions: {
            width: 1000,
            height: 700,
            backgroundColor: '#0a0a0a',
            autoHideMenuBar: true,
            title: 'BLM Widget',
            webPreferences: {
              nodeIntegration: false,
              contextIsolation: true,
              sandbox: true,
            },
          },
        };
      }

      // External link: open in OS default browser
      shell.openExternal(url);
      return { action: 'deny' };
    } catch {
      return { action: 'deny' };
    }
  });

  mainWindow.loadURL(`http://127.0.0.1:${nextPort}/`);

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function killProcesses() {
  console.log('[electron] Tearing down child processes...');
  if (nextProcess) {
    try {
      nextProcess.kill('SIGTERM');
    } catch (e) {
      console.error('[electron] Error killing Next.js process:', e);
    }
    nextProcess = null;
  }

  if (pythonProcess) {
    try {
      if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', String(pythonProcess.pid), '/f', '/t']);
      } else {
        pythonProcess.kill('SIGTERM');
      }
    } catch (e) {
      console.error('[electron] Error killing Python process:', e);
    }
    pythonProcess = null;
  }
}

app.on('before-quit', () => {
  killProcesses();
});

app.on('will-quit', () => {
  killProcesses();
});

app.on('window-all-closed', () => {
  killProcesses();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.whenReady().then(async () => {
  try {
    const pythonPort = await getAvailablePort(4455);
    const nextPort = await getAvailablePort(3000);

    console.log(`[electron] Ports allocated -> Next.js: ${nextPort}, Python: ${pythonPort}`);

    await startPythonBackend(pythonPort);
    await startNextServer(nextPort, pythonPort);

    createMainWindow(nextPort);
    setupAutoUpdater();
  } catch (err) {
    console.error('[electron] Fatal startup error:', err);
    killProcesses();
    app.quit();
  }
});
