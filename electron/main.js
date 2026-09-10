const { app, BrowserWindow, shell, Tray, Menu, nativeImage, ipcMain } = require('electron');
const { autoUpdater } = require('electron-updater');
const path = require('path');
const { spawn, fork } = require('child_process');
const net = require('net');

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
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (!mainWindow.isVisible()) mainWindow.show();
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    // Opt-in OS Auto-start support
    app.setLoginItemSettings({
      openAtLogin: false, // Default to false per plan, can be toggled via user settings later
      openAsHidden: true
    });
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
    
    // Find free ports
    const pythonPort = await findFreePort();
    const nextPort = await findFreePort();
    
    // Determine paths
    const userDataPath = app.getPath('userData');
    
    // In dev mode, use the repository's massive data.db so you don't lose data.
    // In production, use the OS-safe AppData folder so installations don't crash from read-only permissions.
    const dbPath = isDev 
      ? path.join(app.getAppPath(), 'backend', 'data.db') 
      : path.join(userDataPath, 'data.db');
      
    const logDir = isDev
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

    console.log(`Starting Python backend on port ${pythonPort}...`);
    pythonProcess = spawn(pythonCmd, pythonArgs, {
      env: {
        ...process.env,
        PORT: pythonPort.toString(),
        DB_PATH: dbPath,
        LOG_DIR: logDir,
        ENV: isDev ? 'development' : 'production',
        ADMIN_PASSWORD: process.env.ADMIN_PASSWORD || 'admin'
      },
      stdio: 'inherit'
    });

    pythonProcess.on('error', (err) => {
      console.error('Failed to start python backend:', err);
    });

    // 2. Start Next.js Frontend
    const serverJsPath = isDev 
      ? path.join(__dirname, '..', 'server.js')
      : path.join(process.resourcesPath, 'app.asar', 'server.js');

    console.log(`Starting Next.js frontend on port ${nextPort}...`);
    nextProcess = fork(serverJsPath, [], {
      env: {
        ...process.env,
        PORT: nextPort.toString(),
        PYTHON_BACKEND_URL: `http://127.0.0.1:${pythonPort}`,
        NODE_ENV: 'production' // Force production mode since Next.js dev server has issues
      },
      stdio: 'inherit'
    });

    nextProcess.on('error', (err) => {
      console.error('Failed to start Next.js process:', err);
    });

    // 3. Wait for Next.js to be ready (poll)
    await waitForServer(`http://127.0.0.1:${nextPort}/api/openalgo/health`, 30000);

    // 4. Create Main Window
    mainWindow = new BrowserWindow({
      width: 1400,
      height: 900,
      title: "BLM Terminal",
      autoHideMenuBar: true,
      icon: path.join(__dirname, 'icon.ico'),
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        preload: path.join(__dirname, 'preload.js')
      }
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

    if (!isDev) {
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