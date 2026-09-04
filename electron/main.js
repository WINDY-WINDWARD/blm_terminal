const { app, BrowserWindow, shell } = require('electron');
const path = require('path');
const { spawn, fork } = require('child_process');
const net = require('net');

let mainWindow;
let pythonProcess = null;
let nextProcess = null;

// Ensure single instance
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(startApp);

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
      app.quit();
    }
  });
  
  app.on('before-quit', cleanupProcesses);
}

function cleanupProcesses() {
  if (pythonProcess) {
    pythonProcess.kill();
    pythonProcess = null;
  }
  if (nextProcess) {
    nextProcess.kill();
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
      // Packaged app path
      pythonCmd = path.join(process.resourcesPath, 'backend.exe');
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
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true
      }
    });

    // Multi-Window Pop-out Interceptor
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
      // If the frontend calls window.open (e.g. for popped out widgets or OAuth)
      if (url.includes('/widget/')) {
        const widgetWindow = new BrowserWindow({
          width: 800,
          height: 600,
          frame: false, // Optional: make widget windows frameless
          titleBarStyle: 'hidden',
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

    mainWindow.loadURL(`http://127.0.0.1:${nextPort}`);

  } catch (error) {
    console.error('App failed to start:', error);
    app.quit();
  }
}

function waitForServer(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const interval = setInterval(() => {
      const http = url.startsWith('https') ? require('https') : require('http');
      const req = http.get(url, (res) => {
        clearInterval(interval);
        resolve();
      }).on('error', (err) => {
        if (Date.now() - start > timeoutMs) {
          clearInterval(interval);
          reject(new Error(`Server at ${url} did not respond within ${timeoutMs}ms`));
        }
      });
      req.end();
    }, 1000);
  });
}