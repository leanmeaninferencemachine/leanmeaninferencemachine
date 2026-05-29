const {
  app,
  BrowserWindow,
  shell,
  Menu,
  session,
  dialog,
  ipcMain,
} = require('electron');
const path    = require('path');
const { spawn, execSync } = require('child_process');
const http    = require('http');
const fs      = require('fs');
const net     = require('net');

const APP_URL   = 'http://127.0.0.1:5000/dev';
const APP_TITLE = 'Lean Mean Inference Machine';
const DEV_TOOLS = false; // ← set true to enable DevTools for debugging

let mainWindow     = null;
let flaskProcess   = null;
let baileysProcess = null;

// ─────────────────────────────────────────────────────────────────────────────
// Port helpers
// ─────────────────────────────────────────────────────────────────────────────
function killPort(port) {
  try { execSync(`fuser -k ${port}/tcp 2>/dev/null || true`, { timeout: 3000 }); } catch (_) {}
  try {
    const m = execSync(`ss -tlnp sport = :${port} 2>/dev/null || true`).toString().match(/pid=(\d+)/);
    if (m) process.kill(parseInt(m[1]), 'SIGTERM');
  } catch (_) {}
}

function waitPortFree(port, retries = 10) {
  return new Promise(resolve => {
    let tries = 0;
    const check = () => {
      const sock = net.createConnection(port, '127.0.0.1');
      sock.on('connect', () => { sock.destroy(); ++tries < retries ? setTimeout(check, 300) : resolve(); });
      sock.on('error',   () => resolve());
    };
    check();
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Backend resolution (dev script vs AppImage binary)
// ─────────────────────────────────────────────────────────────────────────────
function resolveBackend() {
  if (process.env.APPIMAGE) {
    const bin = path.join(process.resourcesPath, 'backend', 'lmim_backend');
    console.log(`[LMIM] AppImage mode — backend: ${bin}`);
    if (!fs.existsSync(bin)) {
      console.error(`[LMIM] ❌ Backend binary not found: ${bin}`);
      return null;
    }
    return { cmd: bin, args: [], cwd: path.join(process.resourcesPath, 'backend') };
  }

  const script = path.join(__dirname, '..', 'run_app_backend.py');
  console.log(`[LMIM] Dev mode — script: ${script}`);
  if (!fs.existsSync(script)) {
    console.error(`[LMIM] ❌ Dev script not found: ${script}`);
    return null;
  }

  const root = path.join(__dirname, '..');
  const venvCandidates = [
    path.join(root, 'venv_build', 'bin', 'python3'),
    path.join(root, 'venv_311',   'bin', 'python3'),
    path.join(root, 'venv',       'bin', 'python3'),
    path.join(root, '.venv',      'bin', 'python3'),
  ];
  let python = 'python3';
  for (const p of venvCandidates) {
    if (fs.existsSync(p)) { python = p; console.log(`[LMIM] Using venv python: ${p}`); break; }
  }
  return { cmd: python, args: [script], cwd: root };
}

// ─────────────────────────────────────────────────────────────────────────────
// Wait for Flask to be ready
// ─────────────────────────────────────────────────────────────────────────────
function waitForFlask(maxTries = 90) {
  return new Promise((resolve, reject) => {
    let tries = 0;
    const attempt = () => {
      const req = http.get(APP_URL, res => {
        if (res.statusCode < 500) {
          resolve();
        } else if (++tries < maxTries) {
          setTimeout(attempt, 1000);
        } else {
          reject(new Error(`HTTP ${res.statusCode}`));
        }
      });
      req.on('error', () => { ++tries < maxTries ? setTimeout(attempt, 1000) : reject(new Error('Flask timeout')); });
      req.setTimeout(2000, () => req.destroy());
    };
    attempt();
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Start Python/Flask backend
// ─────────────────────────────────────────────────────────────────────────────
function startBackend() {
  const backend = resolveBackend();
  if (!backend) { app.quit(); return; }

  const dataDir = path.join(process.env.HOME || '/tmp', '.lmim_os');
  const env = {
    ...process.env,
    LMIM_DATA_DIR:    dataDir,
    DISPLAY:          process.env.DISPLAY          || ':0',
    XDG_SESSION_TYPE: process.env.XDG_SESSION_TYPE || 'x11',
    WAYLAND_DISPLAY:  process.env.WAYLAND_DISPLAY  || '',
    XDG_RUNTIME_DIR:  process.env.XDG_RUNTIME_DIR  || `/run/user/${process.getuid ? process.getuid() : 1000}`,
    LMIM_WA_IPC_PORT: '5002',
  };

  if (process.env.APPIMAGE) {
    const backendDir = path.join(process.resourcesPath, 'backend');
    // PyInstaller 5 = flat layout (files in backend/), 6 = _internal/ subdir
    const internalDir = path.join(backendDir, '_internal');
    const bundleRoot  = fs.existsSync(internalDir) ? internalDir : backendDir;
    env.PYTHONPATH = bundleRoot;
    const libDir    = path.join(bundleRoot, 'lib');
    const llamaDir  = path.join(bundleRoot, 'llama.cpp', 'build', 'bin');
    const torchLib  = path.join(bundleRoot, 'torch', 'lib');
    const voiceBin  = path.join(bundleRoot, 'voice', 'bin');
    env.LD_LIBRARY_PATH = [
      process.env.LD_LIBRARY_PATH || '',
      libDir, llamaDir, torchLib, voiceBin,
    ].filter(Boolean).join(':');
    env.PLAYWRIGHT_BROWSERS_PATH = path.join(backendDir, 'playwright_driver', 'browser_packages');
  }

  console.log(`[LMIM] Starting backend: ${backend.cmd} ${backend.args.join(' ')}`);
  flaskProcess = spawn(backend.cmd, backend.args, { cwd: backend.cwd, env, stdio: 'inherit' });
  flaskProcess.on('exit',  (code, sig) => {
    console.log(`[LMIM] Backend exited code=${code} sig=${sig}`);
    if (mainWindow) mainWindow.close();
  });
  flaskProcess.on('error', err => console.error(`[LMIM] Backend spawn error: ${err.message}`));
}

// ─────────────────────────────────────────────────────────────────────────────
// Baileys WhatsApp daemon
// ─────────────────────────────────────────────────────────────────────────────
function startBaileysDaemon() {
  const isAppImage = !!process.env.APPIMAGE;
  const root   = isAppImage ? path.join(process.resourcesPath, 'backend') : path.join(__dirname, '..');
  const script = path.join(root, 'daemons', 'whatsapp-baileys.js');

  if (!fs.existsSync(script)) {
    console.error(`[LMIM] ❌ Baileys daemon not found: ${script}`);
    return;
  }

  let nodeBin = 'node';
  if (isAppImage) {
    const bundled = path.join(process.resourcesPath, 'backend', 'node_runtime');
    if (fs.existsSync(bundled)) nodeBin = bundled;
  } else {
    for (const p of ['/usr/bin/node', '/usr/local/bin/node']) {
      if (fs.existsSync(p)) { nodeBin = p; break; }
    }
  }

  const nodeModules = isAppImage
    ? path.join(process.resourcesPath, 'node_modules')
    : path.join(__dirname, '..', 'node_modules');

  const env = {
    ...process.env,
    LMIM_DATA_DIR:    path.join(process.env.HOME || '/tmp', '.lmim_os'),
    LMIM_WA_IPC_PORT: '5002',
    NODE_PATH:        nodeModules,
  };

  console.log(`[LMIM] Starting Baileys daemon: ${nodeBin} ${script}`);
  baileysProcess = spawn(nodeBin, [script], { cwd: root, env, stdio: 'inherit' });
  baileysProcess.on('exit',  code => console.log(`[LMIM] Baileys exited code=${code}`));
  baileysProcess.on('error', err  => console.error(`[LMIM] Baileys spawn error: ${err.message}`));
}

// ─────────────────────────────────────────────────────────────────────────────
// Mic / media permissions — must be called BEFORE createWindow
// ─────────────────────────────────────────────────────────────────────────────
function setupPermissions() {
  const ses = session.defaultSession;

  // Grant all media/mic permission requests automatically
  ses.setPermissionRequestHandler((webContents, permission, callback) => {
    console.log(`[LMIM] Permission requested: ${permission}`);
    const granted = ['media', 'audioCapture', 'microphone', 'mediaKeySystem'].includes(permission)
      || permission.startsWith('media');
    console.log(`[LMIM] Permission ${permission}: ${granted ? 'GRANTED' : 'denied'}`);
    callback(granted);
  });

  // Satisfy synchronous permission checks (getUserMedia goes through this too)
  ses.setPermissionCheckHandler((webContents, permission) => {
    return ['media', 'audioCapture', 'microphone', 'mediaKeySystem'].includes(permission)
      || permission.startsWith('media');
  });

  console.log('[LMIM] ✅ Media permissions configured');
}

// ─────────────────────────────────────────────────────────────────────────────
// IPC Handlers
// ─────────────────────────────────────────────────────────────────────────────
ipcMain.handle('select-directory', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openDirectory'],
    title: 'Select LMIM Workspace',
  });
  return result.canceled ? null : result.filePaths[0];
});

// ─────────────────────────────────────────────────────────────────────────────
// Main window
// ─────────────────────────────────────────────────────────────────────────────
function createWindow() {
  Menu.setApplicationMenu(null);

  mainWindow = new BrowserWindow({
    width:           1280,
    height:          800,
    minWidth:        800,
    minHeight:       600,
    backgroundColor: '#050505',
    title:           APP_TITLE,
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration:  false,
      contextIsolation: true,
      preload:          path.join(__dirname, 'preload.js'), // ✅ critical
      sandbox:          false,  // must be false for getUserMedia / mic access
    },
  });

  mainWindow.setMenuBarVisibility(false);
  mainWindow.loadURL(APP_URL);

  if (DEV_TOOLS) {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }

  mainWindow.webContents.on('page-title-updated', e => {
    e.preventDefault();
    mainWindow.setTitle(APP_TITLE);
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ─────────────────────────────────────────────────────────────────────────────
// App lifecycle
// ─────────────────────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  console.log('[LMIM] Clearing ports 5000, 5002, 8080...');
  killPort(5000); killPort(5002); killPort(8080);
  await waitPortFree(5000);
  await waitPortFree(8080);

  console.log('[LMIM] Ports clear — starting services...');
  startBackend();

  console.log('[LMIM] Waiting for Flask (up to 90s)...');
  try {
    await waitForFlask(90);
    console.log('[LMIM] Flask ready — setting up permissions and opening window');
    setupPermissions();
    createWindow();
  } catch (err) {
    console.error(`[LMIM] Flask failed: ${err.message}`);
    shell.openExternal(APP_URL);
    setTimeout(() => app.quit(), 3000);
  }
});

app.on('window-all-closed', () => {
  if (baileysProcess) try { baileysProcess.kill('SIGTERM'); } catch (_) {}
  if (flaskProcess)   try { flaskProcess.kill('SIGTERM');   } catch (_) {}
  killPort(8080); killPort(5000); killPort(5002);
  app.quit();
});

app.on('activate', () => { if (!mainWindow) createWindow(); });
