const { app, BrowserWindow, shell, Tray, Menu, nativeImage, ipcMain, screen, clipboard } = require('electron');
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
autoUpdater.logger = {
  info: (msg) => log(`[autoUpdater INFO] ${typeof msg === 'object' ? JSON.stringify(msg) : msg}`),
  warn: (msg) => log(`[autoUpdater WARN] ${typeof msg === 'object' ? JSON.stringify(msg) : msg}`),
  error: (msg) => log(`[autoUpdater ERROR] ${typeof msg === 'object' ? JSON.stringify(msg) : msg}`),
  debug: (msg) => log(`[autoUpdater DEBUG] ${typeof msg === 'object' ? JSON.stringify(msg) : msg}`)
};
autoUpdater.autoDownload = false;
autoUpdater.autoInstallOnAppQuit = false;

let mainWindow;
let tray = null;
let isQuitting = false;
let pythonProcess = null;
let nextProcess = null;

// ── Persistent Window State & Popouts Registry ──
const stateDir = app.getPath('userData');
const mainBoundsFile = path.join(stateDir, 'main-bounds.json');
const popoutsFile = path.join(stateDir, 'popouts.json');
const terminalStorageFile = path.join(stateDir, 'terminal-storage.json');

function loadTerminalStorage() {
  try {
    if (fs.existsSync(terminalStorageFile)) {
      const data = JSON.parse(fs.readFileSync(terminalStorageFile, 'utf8'));
      if (data && typeof data === 'object' && !Array.isArray(data)) {
        return data;
      }
    }
  } catch (e) {
    log(`Failed to load terminal-storage.json: ${e.message}`);
  }
  return {};
}

let terminalStorageData = loadTerminalStorage();
let saveTerminalStorageTimer = null;
function saveTerminalStorage() {
  if (saveTerminalStorageTimer) clearTimeout(saveTerminalStorageTimer);
  saveTerminalStorageTimer = setTimeout(() => {
    try {
      fs.writeFileSync(terminalStorageFile, JSON.stringify(terminalStorageData, null, 2));
    } catch (e) {
      log(`Failed to save terminal-storage.json: ${e.message}`);
    }
  }, 200);
}

function loadMainBounds() {
  try {
    if (fs.existsSync(mainBoundsFile)) {
      const data = JSON.parse(fs.readFileSync(mainBoundsFile, 'utf8'));
      if (typeof data.width === 'number' && typeof data.height === 'number') {
        return { width: data.width, height: data.height };
      }
    }
  } catch (e) {
    log(`Failed to load main window bounds: ${e.message}`);
  }
  return { width: 1400, height: 900 };
}

let saveMainBoundsTimer = null;
function saveMainBounds(width, height) {
  if (saveMainBoundsTimer) clearTimeout(saveMainBoundsTimer);
  saveMainBoundsTimer = setTimeout(() => {
    try {
      fs.writeFileSync(mainBoundsFile, JSON.stringify({ width, height }, null, 2));
    } catch (e) {
      log(`Failed to save main window bounds: ${e.message}`);
    }
  }, 300);
}

function isPositionOnAnyDisplay(x, y, width = 100, height = 100) {
  try {
    const displays = screen.getAllDisplays();
    return displays.some((d) => {
      const { x: dx, y: dy, width: dw, height: dh } = d.bounds;
      // Check if at least an identifiable part (e.g. top banner) of the window is within this display
      return (
        x + width > dx + 50 &&
        x < dx + dw - 50 &&
        y + height > dy + 30 &&
        y < dy + dh - 30
      );
    });
  } catch {
    return false;
  }
}

function loadPopoutsRegistry() {
  try {
    if (fs.existsSync(popoutsFile)) {
      const data = JSON.parse(fs.readFileSync(popoutsFile, 'utf8'));
      if (data && typeof data === 'object' && !Array.isArray(data)) {
        return data;
      }
    }
  } catch (e) {
    log(`Failed to load popouts registry: ${e.message}`);
  }
  return {};
}

let savePopoutsTimer = null;
let popoutsRegistry = {};

function savePopoutsRegistry() {
  if (savePopoutsTimer) clearTimeout(savePopoutsTimer);
  savePopoutsTimer = setTimeout(() => {
    try {
      fs.writeFileSync(popoutsFile, JSON.stringify(popoutsRegistry, null, 2));
    } catch (e) {
      log(`Failed to save popouts registry: ${e.message}`);
    }
  }, 300);
}

function updateWidgetBoundsInRegistry(routeKey, bounds) {
  popoutsRegistry[routeKey] = bounds;
  savePopoutsRegistry();
}

function removeWidgetFromRegistry(routeKey) {
  if (isQuitting) return; // Do not delete saved popouts during app shutdown
  if (popoutsRegistry[routeKey]) {
    delete popoutsRegistry[routeKey];
    savePopoutsRegistry();
  }
}

// ── Diagnostic coverage: log navigation failures on EVERY window/webview
// (main, popouts, logs, OAuth popups) so a blank/error screen can always be
// traced to the exact URL that failed.
app.on('web-contents-created', (_event, contents) => {
  const tag = `webContents#${contents.id}`;
  contents.on('did-fail-load', (_e, code, desc, url, isMainFrame) => {
    log(`[${tag}] did-fail-load mainFrame=${isMainFrame} ${url}: ${desc} (${code})`);
  });
  contents.on('did-finish-load', () => {
    try {
      log(`[${tag}] did-finish-load ${contents.getURL()}`);
    } catch {}
  });
  contents.on('render-process-gone', (_e, details) => {
    log(`[${tag}] render-process-gone reason=${details?.reason} exitCode=${details?.exitCode}`);
  });
  contents.on('unresponsive', () => log(`[${tag}] unresponsive`));
  contents.on('responsive', () => log(`[${tag}] responsive`));
});

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

  app.on('activate', () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show();
      mainWindow.focus();
    }
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

    // ── License gate (MUST precede all server spawns) ──
    const { runGate, runManifestCheckedUpdate } = require('./license/gate');
    const licConfig = require('./license/config');
    let licenseCfg = null;
    try {
      licenseCfg = licConfig.resolve();
    } catch (e) {
      log(`License config error: ${e.message} — quitting`);
      app.quit();
      return;
    }
    const licKey = await runGate(log);
    if (!licKey) {
      log('License gate denied — quitting (update check remains available from the license window before quit)');
      app.quit();
      return;
    }
    log(`License gate passed (key ${licKey === 'dev-no-key' ? 'not enforced in dev' : 'verified'})`);
    let lastVerifiedUpdate = null;

    // Show splash window immediately while servers boot, so the user never
    // stares at an empty desktop after activating their license.
    let splashWindow = null;
    try {
      splashWindow = new BrowserWindow({
        width: 420,
        height: 300,
        title: "BLM Terminal",
        frame: false,
        alwaysOnTop: true,
        resizable: false,
        show: true,
        icon: path.join(__dirname, process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
        webPreferences: { nodeIntegration: false, contextIsolation: true }
      });
      splashWindow.loadFile(path.join(__dirname, 'splash.html'));
    } catch (e) {
      log(`Splash window creation failed (non-fatal): ${e.message}`);
      splashWindow = null;
    }
    const closeSplash = () => {
      try {
        if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
      } catch {}
      splashWindow = null;
    };
    
    // Dynamic port for Python backend, fixed default port (with fallback) for Next.js
    // IMPORTANT: Next.js frontend origin MUST remain consistent (e.g. http://127.0.0.1:4400)
    // across restarts so that the browser's localStorage (containing layout, watchlists,
    // active widgets, auth, filters) persists across cold boots!
    // ── Per-launch token (A6/§8): children bind ephemeral ports and report
    // back; the token travels over stdin/IPC, never argv/env. Fixed ports are
    // gone so a local squatter can never receive the token or user data. ──
    const crypto = require('crypto');
    const launchToken = crypto.randomBytes(32).toString('base64url');
    log('Per-launch token generated (stdin/IPC only)');
    
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
      // Packaged app path — electron-builder.json places binary at blm-backend/blm-backend(.exe)
      const isWindows = process.platform === 'win32';
      const binName = isWindows ? 'blm-backend.exe' : 'blm-backend';
      pythonCmd = path.join(process.resourcesPath, 'blm-backend', binName);
    }

    log(`Python cmd: ${pythonCmd}  exists=${fs.existsSync(pythonCmd)}`);
    log(`DB path: ${dbPath}`);
    log(`Backend log dir: ${backendLogDir}`);

    // Playwright browsers live in the user's persistent ms-playwright dir
    // (downloaded on demand). The frozen PyInstaller exe resolves its driver
    // package dir to the _MEI temp folder, so without this env var it never
    // finds the installed browsers and every harvest (warm or cold) fails.
    const os = require('os');
    if (!process.env.PLAYWRIGHT_BROWSERS_PATH) {
      const home = os.homedir();
      if (process.platform === 'win32') {
        process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(home, 'AppData', 'Local', 'ms-playwright');
      } else if (process.platform === 'darwin') {
        process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(home, 'Library', 'Caches', 'ms-playwright');
      } else {
        // Linux
        const xdgCache = process.env.XDG_CACHE_HOME || path.join(home, '.cache');
        process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(xdgCache, 'ms-playwright');
      }
    }

    pythonProcess = spawn(pythonCmd, pythonArgs, {
      env: {
        ...process.env,
        // NOTE: no PORT — the backend binds ephemeral and reports BLM_BACKEND_PORT.
        DB_PATH: dbPath,
        LOG_DIR: backendLogDir,
        ENV: isDev ? 'development' : 'production',
        ADMIN_PASSWORD: process.env.ADMIN_PASSWORD || 'admin',
        SECRET_KEY: 'desktop_terminal_local_secret_key_123456789'
      },
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true
    });

    log(`Python process spawned — pid=${pythonProcess.pid}`);

    if (pythonProcess.stderr) {
      pythonProcess.stderr.on('data', (d) => {
        log(`[python stderr]: ${d.toString().trim()}`);
      });
    }

    // Deliver the launch token over stdin (one line), then close stdin.
    try {
      pythonProcess.stdin.write(launchToken + '\n');
      pythonProcess.stdin.end();
    } catch (e) {
      log(`Failed to write launch token to backend stdin: ${e.message}`);
    }

    // Learn the ephemeral backend port from its stdout banner.
    const pythonPort = await new Promise((resolve, reject) => {
      let buf = '';
      const timer = setTimeout(() => reject(new Error('backend did not report BLM_BACKEND_PORT in 120s')), 120000);
      pythonProcess.stdout.on('data', (d) => {
        const text = d.toString();
        log(`[python stdout]: ${text.trim()}`);
        buf += text;
        const m = /BLM_BACKEND_PORT=(\d+)/.exec(buf);
        if (m) {
          clearTimeout(timer);
          resolve(parseInt(m[1], 10));
        }
      });
      pythonProcess.on('exit', (code) => {
        clearTimeout(timer);
        reject(new Error(`backend exited before reporting port (code=${code})`));
      });
    });
    log(`Backend ephemeral port: ${pythonPort}`);

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

    const nextCwd = isDev ? path.join(__dirname, '..') : path.dirname(app.getPath('exe'));
    log(`Forking Next.js process with cwd=${nextCwd} (ephemeral port, token over IPC)...`);
    nextProcess = fork(serverJsPath, [], {
      cwd: nextCwd,
      env: {
        ...process.env,
        // NOTE: no PORT — the Next server binds ephemeral and reports back.
        PYTHON_BACKEND_URL: `http://127.0.0.1:${pythonPort}`,
        NODE_ENV: 'production',
        NEXT_DIR: nextDir
      },
      stdio: 'pipe',
      windowsHide: true
    });

    // Token over IPC (fork channel), then await the reported ephemeral port.
    nextProcess.send({ type: 'license-token', token: launchToken });
    const nextPort = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Next.js did not report server-ready in 30s')), 30000);
      nextProcess.on('message', (m) => {
        if (m && m.type === 'server-ready' && Number.isInteger(m.port)) {
          clearTimeout(timer);
          resolve(m.port);
        }
      });
      nextProcess.on('exit', (code) => {
        clearTimeout(timer);
        reject(new Error(`Next.js exited before reporting port (code=${code})`));
      });
    });
    log(`Next.js ephemeral port: ${nextPort}`);

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

    // Token injection scoped to the EXACT local origins (never wildcard).
    // The renderer never sees the token; fetches/XHR to these origins carry it.
    // WS upgrades use single-use tickets from /api/ws-ticket instead.
    {
      const { session } = require('electron');
      const origins = [`http://127.0.0.1:${nextPort}`, `http://127.0.0.1:${pythonPort}`];
      const filter = { urls: origins.map((o) => `${o}/*`) };
      session.defaultSession.webRequest.onBeforeSendHeaders(filter, (details, cb) => {
        details.requestHeaders['x-blm-token'] = launchToken;
        cb({ requestHeaders: details.requestHeaders });
      });
      log(`Token injection armed for ${origins.join(', ')}`);
    }

    // 4. Create Main Window (hidden until its first paint is ready)
    const savedBounds = loadMainBounds();
    const targetUrl = `http://127.0.0.1:${nextPort}`;
    let loadAttempts = 0;
    const MAX_LOAD_ATTEMPTS = 10;
    mainWindow = new BrowserWindow({
      width: savedBounds.width,
      height: savedBounds.height,
      title: "BLM Terminal",
      autoHideMenuBar: true,
      show: false,
      icon: path.join(__dirname, process.platform === 'win32' ? 'icon.ico' : 'icon.png'),
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        preload: path.join(__dirname, 'preload.js')
      }
    });
    mainWindow.once('ready-to-show', () => {
      log('Main window ready-to-show — closing splash, showing app.');
      closeSplash();
      if (!mainWindow.isDestroyed()) mainWindow.show();
    });

    // Track and persist main window size (only size, not position)
    mainWindow.on('resize', () => {
      if (!mainWindow.isDestroyed() && !mainWindow.isMaximized() && !mainWindow.isMinimized()) {
        const [width, height] = mainWindow.getSize();
        saveMainBounds(width, height);
      }
    });

    mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription, validatedURL) => {
      log(`did-fail-load ${validatedURL}: ${errorDescription} (${errorCode}) — attempt ${loadAttempts + 1}/${MAX_LOAD_ATTEMPTS}`);
      // The Next.js server can hiccup (restart/crash) after the initial
      // readiness probe. Retry the navigation instead of stranding the
      // user on Chromium's raw error page.
      if (loadAttempts < MAX_LOAD_ATTEMPTS && !mainWindow.isDestroyed()) {
        loadAttempts += 1;
        setTimeout(() => {
          if (mainWindow && !mainWindow.isDestroyed()) {
            log(`Retrying main window load (attempt ${loadAttempts})...`);
            mainWindow.loadURL(targetUrl).catch((e) => log(`Reload error: ${e.message}`));
          }
        }, 3000);
      } else {
        // Out of retries — show the window anyway (last-resort error page
        // beats a permanent splash screen).
        closeSplash();
        if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) {
          mainWindow.show();
        }
      }
    });

    // Helper: Create native popped-out widget window with persistent size and position
    function createWidgetWindow(targetUrl, initialBounds = null) {
      // Parse relative route path to use as registry key
      let routeKey;
      try {
        const parsed = new URL(targetUrl);
        routeKey = parsed.pathname + parsed.search;
      } catch {
        routeKey = targetUrl;
      }

      const bounds = initialBounds || { width: 900, height: 650 };
      const winOptions = {
        width: bounds.width || 900,
        height: bounds.height || 650,
        titleBarStyle: 'hidden',
        titleBarOverlay: {
          color: '#121212',
          symbolColor: '#ffb000',
          height: 32
        },
        webPreferences: {
          nodeIntegration: false,
          contextIsolation: true,
          preload: path.join(__dirname, 'preload.js')
        }
      };

      if (
        typeof bounds.x === 'number' &&
        typeof bounds.y === 'number' &&
        isPositionOnAnyDisplay(bounds.x, bounds.y, winOptions.width, winOptions.height)
      ) {
        winOptions.x = bounds.x;
        winOptions.y = bounds.y;
      }

      const widgetWindow = new BrowserWindow(winOptions);

      // Save initial bounds
      updateWidgetBoundsInRegistry(routeKey, widgetWindow.getBounds());

      // Track size and position changes
      const syncBounds = () => {
        if (!widgetWindow.isDestroyed() && !widgetWindow.isMinimized()) {
          updateWidgetBoundsInRegistry(routeKey, widgetWindow.getBounds());
        }
      };

      widgetWindow.on('resize', syncBounds);
      widgetWindow.on('move', syncBounds);

      // When closed by user, remove from registry (only if not closing during app quit)
      widgetWindow.on('closed', () => {
        removeWidgetFromRegistry(routeKey);
      });

      // Add DevTools support for widget windows too
      widgetWindow.webContents.on('before-input-event', (event, input) => {
        if (input.key === 'F12') {
          widgetWindow.webContents.toggleDevTools();
          event.preventDefault();
        }
      });

      widgetWindow.loadURL(targetUrl);
      attachLinkGuards(widgetWindow);
      return widgetWindow;
    }

    // Helper: Create lightweight logs popout window
    function createLogsWindow(targetUrl) {
      const logsWindow = new BrowserWindow({
        width: 900,
        height: 520,
        titleBarStyle: 'hidden',
        titleBarOverlay: {
          color: '#121212',
          symbolColor: '#ffb000',
          height: 32
        },
        webPreferences: {
          nodeIntegration: false,
          contextIsolation: true,
          preload: path.join(__dirname, 'preload.js')
        }
      });

      logsWindow.loadURL(targetUrl);
      attachLinkGuards(logsWindow);
      return logsWindow;
    }

    // ---- External-link policy: everything leaves to the system browser
    // except same-origin app routes and the news/announcement reader below.
    // News rows Ctrl+Click / right-click into the system browser through the
    // same shell.openExternal path.
    function isHttpUrl(url) {
      try {
        const proto = new URL(url).protocol;
        return proto === 'http:' || proto === 'https:';
      } catch {
        return false;
      }
    }

    function isSameOrigin(url) {
      try {
        return new URL(url).origin === new URL(mainWindow.webContents.getURL()).origin;
      } catch {
        return false;
      }
    }

    function openUrlPolicy({ url }) {
      log(`window.open intercepted: ${url}`);
      // If the frontend calls window.open (e.g. for popped out widgets or OAuth)
      if (url.includes('/widget/')) {
        createWidgetWindow(url);
        return { action: 'deny' };
      }

      // Backend logs popout — create a lightweight BrowserWindow
      if (url.includes('/logs')) {
        createLogsWindow(url);
        return { action: 'deny' };
      }

      if (url.includes('accounts.google.com/o/oauth2')) {
        // Open OAuth in default system browser
        shell.openExternal(url);
        return { action: 'deny' };
      }

      if (isSameOrigin(url)) return { action: 'allow' };
      if (isHttpUrl(url)) {
        // YouTube walkthrough, provider/API-key pages, filing originals,
        // publisher sites — all open in the user's own browser.
        void shell.openExternal(url);
        return { action: 'deny' };
      }
      return { action: 'deny' };
    }

    // Same-window navigations can't be trusted to stay internal when the
    // target is data-driven (article URLs): bounce externals out.
    function guardNavigation(win) {
      win.webContents.on('will-navigate', (event, url) => {
        if (!isSameOrigin(url) && isHttpUrl(url)) {
          event.preventDefault();
          void shell.openExternal(url);
        }
      });
    }

    // Right-click on a real <a> offers "Open Link in Browser" (+ copy).
    // Plain divs get no menu — same as today.
    function attachLinkMenu(win) {
      win.webContents.on('context-menu', (_event, params) => {
        const link = params && params.linkURL;
        if (!link || !isHttpUrl(link)) return;
        const menu = Menu.buildFromTemplate([
          { label: 'Open Link in Browser', click: () => { void shell.openExternal(link); } },
          { label: 'Copy Link Address', click: () => { clipboard.writeText(link); } },
        ]);
        menu.popup({ window: win });
      });
    }

    function attachLinkGuards(win) {
      win.webContents.setWindowOpenHandler(openUrlPolicy);
      guardNavigation(win);
      attachLinkMenu(win);
    }

    // Lightweight reader for news/announcement articles (in-app default;
    // Ctrl+Click / right-click from the row goes to the system browser).
    function createReaderWindow(targetUrl) {
      const readerWindow = new BrowserWindow({
        width: 1000,
        height: 700,
        titleBarStyle: 'hidden',
        titleBarOverlay: {
          color: '#121212',
          symbolColor: '#ffb000',
          height: 32
        },
        webPreferences: {
          nodeIntegration: false,
          contextIsolation: true,
          preload: path.join(__dirname, 'preload.js')
        }
      });

      readerWindow.webContents.on('before-input-event', (event, input) => {
        if (input.key === 'F12') {
          readerWindow.webContents.toggleDevTools();
          event.preventDefault();
        }
      });

      attachLinkGuards(readerWindow);
      readerWindow.loadURL(targetUrl);
      return readerWindow;
    }

    // Multi-Window Pop-out Interceptor
    mainWindow.webContents.setWindowOpenHandler(openUrlPolicy);

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
      const iconPath = path.join(__dirname, process.platform === 'win32' ? 'icon.ico' : 'icon.png');
      try {
        icon = nativeImage.createFromPath(iconPath);
        if (icon.isEmpty()) throw new Error('empty icon');
        if (process.platform === 'darwin') {
          icon = icon.resize({ width: 18, height: 18 });
        }
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

    mainWindow.loadURL(targetUrl);

    // Restore previously open popped-out widgets
    popoutsRegistry = loadPopoutsRegistry();
    const savedRoutes = Object.keys(popoutsRegistry);
    if (savedRoutes.length > 0) {
      log(`Restoring ${savedRoutes.length} popped-out widgets from registry...`);
      for (const route of savedRoutes) {
        const bounds = popoutsRegistry[route];
        const fullUrl = `http://127.0.0.1:${nextPort}${route}`;
        log(`Restoring widget pop-out: ${route}`);
        try {
          createWidgetWindow(fullUrl, bounds);
        } catch (err) {
          log(`Failed to restore pop-out widget ${route}: ${err.message}`);
        }
      }
    }

    // Auto Updater Setup
    function sendStatusToWindow(status, data) {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('updater-message', { status, data });
      }
    }

    autoUpdater.on('checking-for-update', () => sendStatusToWindow('checking'));
    autoUpdater.on('update-available', (info) => sendStatusToWindow('available', info));
    autoUpdater.on('update-not-available', (info) => sendStatusToWindow('not-available', info));
    autoUpdater.on('error', (err) => {
      log(`[autoUpdater Event Error]: ${err?.stack || err?.message || err}`);
      sendStatusToWindow('error', err?.message || String(err));
    });
    autoUpdater.on('download-progress', (progressObj) => sendStatusToWindow('progress', progressObj));
    autoUpdater.on('update-downloaded', (info) => sendStatusToWindow('downloaded', info));

    ipcMain.handle('get-app-version', () => app.getVersion());
    ipcMain.handle('storage-get', (_event, key) => terminalStorageData[key] ?? null);
    ipcMain.handle('storage-set', (_event, key, value) => {
      terminalStorageData[key] = value;
      saveTerminalStorage();
      return true;
    });
    ipcMain.handle('storage-remove', (_event, key) => {
      delete terminalStorageData[key];
      saveTerminalStorage();
      return true;
    });
    ipcMain.handle('storage-get-all', () => terminalStorageData);
    ipcMain.on('storage-get-all-sync', (event) => {
      event.returnValue = terminalStorageData;
    });
    // EULA declined: the renderer asks us to close the app. Nothing is
    // recorded, so the next launch prompts again.
    ipcMain.on('eula-decline', () => {
      log('EULA declined — quitting app.');
      isQuitting = true;
      cleanupProcesses();
      app.quit();
    });
    // External links (YouTube walkthrough, provider pages, article
    // Ctrl+Click / right-click): renderer asks, main opens the browser.
    ipcMain.handle('open-external', async (_event, url) => {
      if (typeof url !== 'string' || !isHttpUrl(url)) return { ok: false };
      await shell.openExternal(url);
      return { ok: true };
    });
    ipcMain.handle('open-in-app', async (_event, url) => {
      if (typeof url !== 'string' || !isHttpUrl(url)) return { ok: false };
      createReaderWindow(url);
      return { ok: true };
    });
    ipcMain.handle('check-for-updates', async () => {
      log('IPC check-for-updates triggered');
      try {
        return await autoUpdater.checkForUpdates();
      } catch (err) {
        log(`IPC check-for-updates error: ${err?.message || err}`);
        throw err;
      }
    });
    ipcMain.handle('download-update', async () => {
      log('IPC download-update triggered (manifest-first)');
      try {
        const r = await runManifestCheckedUpdate(licenseCfg, log);
        if (r.ok) {
          lastVerifiedUpdate = { manifest: r.manifest, files: r.files };
          sendStatusToWindow('downloaded', { version: r.manifest.version });
        }
        return r;
      } catch (err) {
        log(`IPC download-update error: ${err?.message || err}`);
        throw err;
      }
    });
    ipcMain.handle('install-update', async () => {
      // Re-verify the cached installer immediately before installing.
      try {
        if (!lastVerifiedUpdate) {
          throw new Error('no verified update pending: download first');
        }
        const ota = require('./license/ota');
        await ota.verifyDownloaded(lastVerifiedUpdate.files, lastVerifiedUpdate.manifest);
        log('Installer re-verified before quitAndInstall');
      } catch (err) {
        log(`Install refused: ${err?.message || err}`);
        autoUpdater.autoInstallOnAppQuit = false;
        throw err;
      }
      isQuitting = true;
      cleanupProcesses();
      autoUpdater.quitAndInstall(true, true);
    });

    if (!isDev) {
      setTimeout(() => {
        log('Running launch auto-check for updates...');
        autoUpdater.checkForUpdates().catch((err) => {
          log(`Launch auto-check failed: ${err?.message || err}`);
        });
      }, 7000);
    }

    // ── License re-validation (6–12h jittered). Definitive negative: warn,
    // allow minutes to save, then quit. Never touches user data. ──
    if (licKey !== 'dev-no-key') {
      const licClient = require('./license/client');
      const licStore = require('./license/store');
      const scheduleReval = () => {
        const delay = (6 + Math.random() * 6) * 3600 * 1000;
        setTimeout(async () => {
          try {
            const st = licStore.load();
            if (!st.key) { scheduleReval(); return; }
            const r = await licClient.validateWithRetry({
              url: licenseCfg.url, boxKid: licenseCfg.boxKid, encPub: licenseCfg.encPub,
              key: st.key, iid: st.iid, timeoutMs: 10000,
            });
            if (r.outcome === 'denied') {
              const { dialog } = require('electron');
              log(`License re-validation denied (${r.status}) — warning user, quitting in 5 min`);
              licStore.clearLease();
              dialog.showMessageBox(mainWindow, {
                type: 'warning', title: 'BLM Terminal license',
                message: r.status === 'revoked'
                  ? 'This license was revoked. The app will quit in 5 minutes — save your work.'
                  : 'This license is no longer valid. The app will quit in 5 minutes — save your work.',
              }).catch(() => {});
              setTimeout(() => { isQuitting = true; cleanupProcesses(); app.quit(); }, 5 * 60 * 1000);
              return;
            }
            if (r.outcome === 'ok' && r.reply && r.reply.lease) {
              licStore.saveLease(r.reply.lease, r.reply.ts, Math.floor(Date.now() / 1000));
            }
          } catch (e) {
            log(`License re-validation error (indeterminate, continuing): ${e.message}`);
          }
          scheduleReval();
        }, delay);
      };
      scheduleReval();
    }

  } catch (error) {
    log(`App failed to start: ${error?.stack || error?.message || error}`);
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