// sshManager Electron 壳：启动时拉起 Python 后端，等待就绪后加载前端。
const { app, BrowserWindow, dialog, session } = require('electron');
const { spawn } = require('child_process');
const net = require('net');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '../..');
// 端口策略：显式 SSHMANAGER_PORT 优先；打包态自动选空闲端口（避免和 dev 8747 冲突）；dev 默认 8747。
let PORT = process.env.SSHMANAGER_PORT || '8747';
const BACKEND_URL = () => `http://127.0.0.1:${PORT}`;

let backendProc = null;

async function resolvePort() {
  if (process.env.SSHMANAGER_PORT) return process.env.SSHMANAGER_PORT; // 显式覆盖优先
  if (app.isPackaged) {
    // 找一个空闲端口，避免残留的 dev 后端占用 8747 导致连错服务
    const srv = net.createServer();
    await new Promise((res, rej) => { srv.once('error', rej); srv.listen(0, '127.0.0.1', res); });
    const p = srv.address().port;
    await new Promise((res) => srv.close(res));
    return String(p);
  }
  return '8747';
}

function startBackend() {
  const env = { ...process.env, SSHMANAGER_RELOAD: '0', SSHMANAGER_PORT: PORT };
  let command, args;
  if (app.isPackaged) {
    // 打包态：直接跑随包内置的 PyInstaller 二进制（内含前端静态资源）
    command = path.join(process.resourcesPath, 'backend', 'sshmgr-backend', 'sshmgr-backend');
    args = [];
  } else {
    // 开发态：venv python + run.py
    command = process.env.SSHMANAGER_PYTHON
      || path.join(REPO_ROOT, 'backend', '.venv', 'bin', 'python');
    args = [path.join(REPO_ROOT, 'backend', 'run.py')];
  }
  backendProc = spawn(command, args, {
    env,
    detached: true, // 便于通过进程组整树终止
    stdio: 'inherit',
  });
  backendProc.on('error', (err) => console.error('[backend] spawn error:', err));
  backendProc.on('exit', (code, sig) => {
    console.log(`[backend] exited code=${code} sig=${sig}`);
  });
}

async function waitForBackend(timeoutMs = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`${BACKEND_URL()}/api/health`);
      if (r.ok) return true;
    } catch (_) { /* 后端尚未就绪 */ }
    await new Promise((r) => setTimeout(r, 300));
  }
  return false;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 840,
    title: 'sshManager',
    backgroundColor: '#1e1e2e',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  win.loadURL(BACKEND_URL());
}

app.whenReady().then(async () => {
  // 下载：弹出原生 macOS 保存对话框（默认下载目录）
  session.defaultSession.on('will-download', (event, item) => {
    event.preventDefault();
    dialog.showSaveDialog({ defaultPath: item.getFilename() }).then((r) => {
      if (!r.canceled && r.filePath) item.setSavePath(r.filePath);
      item.resume();
    });
  });
  PORT = await resolvePort();
  startBackend();
  const ok = await waitForBackend();
  if (!ok) {
    console.error('[backend] failed to start within timeout');
    app.quit();
    return;
  }
  createWindow();
});

app.on('window-all-closed', () => app.quit());

app.on('before-quit', () => { app.isQuitting = true; });
app.on('will-quit', () => {
  if (backendProc && backendProc.pid) {
    try { process.kill(-backendProc.pid, 'SIGTERM'); } catch (_) { /* 已退出 */ }
  }
});
