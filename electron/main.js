const { app, BrowserWindow, shell, Tray, Menu, nativeImage, ipcMain } = require('electron');
const { autoUpdater } = require('electron-updater');
const path = require('path');
const fs = require('fs');
const { spawn, fork } = require('child_process');
const net = require('net');

// ── File-based logger (writes to %APPDATA%/blm_terminal/logs/electron.log) ──
const logDir = path.join(app.getPath('userData'), 'logs');
try { fs.mkdirSync(logDir, { recursive: true }); } catch {}
const logFile = path.join(logDir, 'electron.log');
// Truncate on every fresh launch so the log stays small & relevant
try { fs.writeFileSync(logFile, `=== BLM Terminal electron main.js started at ${new Date().toISOString()} ===\n`); } catch {}

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  try { fs.appendFileSync(logFile, line); } catch {}
  console.log(msg);
}

log(`app.isPackaged=${app.isPackaged}  argv=${JSON.stringify(process.argv)}`);
log(`process.resourcesPath=${process.resourcesPath}`);
log(`__dirname=${__dirname}`);
log(`cwd=${process.cwd()}`);
log(`userData=${app.getPath('userData')}`);

// Setup auto-updater logger
autoUpdater.logger = console;
autoUpdater.autoDownload = true;
autoUpdater.autoInstallOnAppQuit = true;

let mainWindow;
let tray = null;
let isQuitting = false;
let pythonProcess = null;
let nextProcess = null;

// Ensure single instance
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  log('Another instance already running — quitting.');
  app.quit();
} else {
  log('Got single-instance lock.');
  app.on('second-instance', () => {
    log('second-instance event fired — focusing existing window.');
    if (mainWindow) {
      if (!mainWindow.isVisible()) mainWindow.show();
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    log('app.whenReady resolved — calling startApp()');
    startApp();
  });

  app.on('window-all-closed', () => {
    // In desktop daemon mode, keep backend alive in system tray
  });
  
  app.on('before-quit', () => {
    isQuitting = true;
    cleanupProcesses();
  });
}

function cleanupProcesses() {
  if (pythonProcess) {
    try {
      // On Windows, SIGTERM maps to TerminateProcess — force-kill immediately.
      // Graceful shutdown is handled via the HTTP shutdown endpoint if available.
      pythonProcess.kill();
    } catch (e) {
      // already dead
    }
    pythonProcess = null;
  }
  if (nextProcess) {
    try {
      nextProcess.kill();
    } catch (e) {
      // already dead
    }
    nextProcess = null;
  }
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer((sock) => {
      sock.end();
    });
    srv.listen(0, () => {
      const port = srv.address().port;
      srv.close((err) => {
        if (err) reject(err);
        else resolve(port);
      });
    });
    srv.on('error', reject);
  });
}

async function startApp() {
  try {
    const isDev = !app.isPackaged;
    log(`startApp() called — isDev=${isDev}`);
    
    // Find free ports
    const pythonPort = await findFreePort();
    const nextPort = await findFreePort();
    log(`Ports allocated — python=${pythonPort}, next=${nextPort}`);
    
    // Determine paths
    const userDataPath = app.getPath('userData');
    
    // In dev mode, use the repository's massive data.db so you don't lose data.
    // In production, use the OS-safe AppData folder so installations don't crash from read-only permissions.
    const dbPath = isDev 
      ? path.join(app.getAppPath(), 'backend', 'data.db') 
      : path.join(userDataPath, 'data.db');
      
    const backendLogDir = isDev
      ? path.join(app.getAppPath(), 'backend', 'logs')
      : path.join(userDataPath, 'logs');
    
    // 1. Start Python Backend
    let pythonCmd;
    let pythonArgs = [];

    if (isDev) {
      // In dev, run directly via the local virtual environment
      const isWindows = process.platform === 'win32';
      pythonCmd = path.join(
        app.getAppPath(), 
        'backend', 
        '.venv', 
        isWindows ? 'Scripts' : 'bin', 
        isWindows ? 'python.exe' : 'python'
      );
      pythonArgs = [path.join(app.getAppPath(), 'backend', 'main.py')];
    } else {
      // Packaged app path — electron-builder.json places exe at blm-backend/blm-backend.exe
      pythonCmd = path.join(process.resourcesPath, 'blm-backend', 'blm-backend.exe');
    }

    log(`Python cmd: ${pythonCmd}  exists=${fs.existsSync(pythonCmd)}`);
    log(`DB path: ${dbPath}`);
    log(`Backend log dir: ${backendLogDir}`);

    pythonProcess = spawn(pythonCmd, pythonArgs, {
      env: {
        ...process.env,
        PORT: pythonPort.toString(),
        DB_PATH: dbPath,
        LOG_DIR: backendLogDir,
        ENV: isDev ? 'development' : 'production',
        ADMIN_PASSWORD: process.env.ADMIN_PASSWORD || 'admin',
        SECRET_KEY: 'desktop_terminal_local_secret_key_123456789'
      },
      stdio: 'ignore',
      windowsHide: true
    });

    log(`Python process spawned — pid=${pythonProcess.pid}`);

    pythonProcess.on('error', (err) => {
      log(`PYTHON PROCESS ERROR: ${err.message}`);
    });
    pythonProcess.on('exit', (code, signal) => {
      log(`PYTHON PROCESS EXITED: code=${code} signal=${signal}`);
    });

    // 2. Start Next.js Frontend
    const serverJsPath = isDev 
      ? path.join(__dirname, '..', 'server.js')
      : path.join(process.resourcesPath, 'app.asar', 'server.js');

    // Tell Next.js to look for .next and public in the ASAR archive
    const nextDir = isDev
      ? path.join(__dirname, '..')
      : path.join(process.resourcesPath, 'app.asar');

    log(`Next.js server.js path: ${serverJsPath}`);
    log(`Next.js NEXT_DIR: ${nextDir}`);
    try {
      // For ASAR paths, fs.existsSync is monkey-patched by Electron to look inside
      const exists = fs.existsSync(serverJsPath);
      log(`server.js exists (via patched fs): ${exists}`);
      // Also check .next/BUILD_ID which Next.js needs (on real fs or patched fs)
      const buildIdPath = path.join(nextDir, '.next', 'BUILD_ID');
      const buildIdExists = fs.existsSync(buildIdPath);
      log(`.next/BUILD_ID exists in NEXT_DIR: ${buildIdExists}`);
    } catch (e) {
      log(`existence check error: ${e.message}`);
    }

    log(`Forking Next.js process...`);
    nextProcess = fork(serverJsPath, [], {
      env: {
        ...process.env,
        PORT: nextPort.toString(),
        PYTHON_BACKEND_URL: `http://127.0.0.1:${pythonPort}`,
        NODE_ENV: 'production',
        NEXT_DIR: nextDir
      },
      stdio: 'pipe',
      windowsHide: true
    });

    log(`Next.js process forked — pid=${nextProcess.pid}`);

    if (nextProcess.stdout) {
      nextProcess.stdout.on('data', (d) => {
        const msg = d.toString().trim();
        log(`[Next.js stdout]: ${msg}`);
      });
    }
    if (nextProcess.stderr) {
      nextProcess.stderr.on('data', (d) => {
        const msg = d.toString().trim();
        log(`[Next.js stderr]: ${msg}`);
      });
    }

    nextProcess.on('error', (err) => {
      log(`NEXT.JS PROCESS ERROR: ${err.message}`);
    });
    nextProcess.on('exit', (code, signal) => {
      log(`NEXT.JS PROCESS EXITED: code=${code} signal=${signal}`);
    });

    // 3. Wait for Next.js to be ready (poll)
    log(`Waiting for Next.js at http://127.0.0.1:${nextPort} (timeout 30s)...`);
    await waitForServer(`http://127.0.0.1:${nextPort}`, 30000);
    log(`Next.js is ready!`);

    // 4. Create Main Window
    mainWindow = new BrowserWindow({
      width: 1400,
      height: 900,
      title: "BLM Terminal",
      autoHideMenuBar: true,
      show: true,
      icon: path.join(__dirname, 'icon.ico'),
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        preload: path.join(__dirname, 'preload.js')
      }
    });

    mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription, validatedURL) => {
      console.error(`Failed to load ${validatedURL}: ${errorDescription} (${errorCode})`);
    });

    // Multi-Window Pop-out Interceptor
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
      // If the frontend calls window.open (e.g. for popped out widgets or OAuth)
      if (url.includes('/widget/')) {
        const widgetWindow = new BrowserWindow({
          width: 900,
          height: 650,
          titleBarStyle: 'hidden',
          titleBarOverlay: {
            color: '#121212',
            symbolColor: '#ffb000',
            height: 32
          },
          webPreferences: {
            nodeIntegration: false,
            contextIsolation: true
          }
        });

        // Add DevTools support for widget windows too
        widgetWindow.webContents.on('before-input-event', (event, input) => {
          if (input.key === 'F12') {
            widgetWindow.webContents.toggleDevTools();
            event.preventDefault();
          }
        });

        widgetWindow.loadURL(url);
        return { action: 'deny' }; // Prevent default pop-up
      }
      
      if (url.includes('accounts.google.com/o/oauth2')) {
        // Open OAuth in default system browser
        shell.openExternal(url);
        return { action: 'deny' };
      }

      return { action: 'allow' };
    });

    // Add F12 DevTools toggle for main window
    mainWindow.webContents.on('before-input-event', (event, input) => {
      if (input.key === 'F12') {
        mainWindow.webContents.toggleDevTools();
        event.preventDefault();
      }
    });

    // Intercept window close to minimize to System Tray instead of quitting.
    // If tray creation failed (e.g. icon missing on Windows), fall back to quitting.
    mainWindow.on('close', (event) => {
      if (!isQuitting) {
        if (tray) {
          event.preventDefault();
          mainWindow.hide();
        }
        // else: no tray, allow normal quit
      }
    });

    // 5. System Tray Integration
    try {
      let icon;
      const iconPath = path.join(__dirname, 'icon.ico');
      try {
        icon = nativeImage.createFromPath(iconPath);
        if (icon.isEmpty()) throw new Error('empty icon');
      } catch {
        icon = nativeImage.createEmpty();
      }
      tray = new Tray(icon);
      const contextMenu = Menu.buildFromTemplate([
        {
          label: 'Show BLM Terminal',
          click: () => {
            if (mainWindow) {
              mainWindow.show();
              mainWindow.focus();
            }
          }
        },
        { type: 'separator' },
        {
          label: 'Quit',
          click: () => {
            isQuitting = true;
            app.quit();
          }
        }
      ]);
      tray.setToolTip('BLM Terminal');
      tray.setContextMenu(contextMenu);
      tray.on('double-click', () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      });
    } catch (err) {
      console.warn('System tray initialization warning:', err);
    }

    mainWindow.loadURL(`http://127.0.0.1:${nextPort}`);

    // Auto Updater Setup
    function sendStatusToWindow(status, data) {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('updater-message', { status, data });
      }
    }

    autoUpdater.on('checking-for-update', () => sendStatusToWindow('checking'));
    autoUpdater.on('update-available', (info) => sendStatusToWindow('available', info));
    autoUpdater.on('update-not-available', (info) => sendStatusToWindow('not-available', info));
    autoUpdater.on('error', (err) => sendStatusToWindow('error', err?.message || String(err)));
    autoUpdater.on('download-progress', (progressObj) => sendStatusToWindow('progress', progressObj));
    autoUpdater.on('update-downloaded', (info) => sendStatusToWindow('downloaded', info));

    ipcMain.handle('check-for-updates', () => autoUpdater.checkForUpdates());
    ipcMain.handle('install-update', () => {
      isQuitting = true;
      cleanupProcesses();
      autoUpdater.quitAndInstall(true, true);
    });

    if (!isDev && process.env.GH_TOKEN) {
      setTimeout(() => {
        autoUpdater.checkForUpdatesAndNotify().catch(console.error);
      }, 5000);
    }

  } catch (error) {
    console.error('App failed to start:', error);
    app.quit();
  }
}

function waitForServer(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const http = url.startsWith('https') ? require('https') : require('http');
    const interval = setInterval(() => {
      const req = http.get(url, (res) => {
        res.resume(); // consume response to release socket
        clearInterval(interval);
        resolve();
      }).on('error', () => {
        if (Date.now() - start > timeoutMs) {
          clearInterval(interval);
          reject(new Error(`Server at ${url} did not respond within ${timeoutMs}ms`));
        }
      });
      req.on('error', () => {}); // ignore per-tick errors
    }, 1000);
  });
}