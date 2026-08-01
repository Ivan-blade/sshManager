// sshManager Electron 壳：启动时拉起 Python 后端，等待就绪后加载前端。
const { app, BrowserWindow, dialog, session } = require('electron');
const { spawn } = require('child_process');
const path = require('path');

const PORT = process.env.SSHMANAGER_PORT || '8747';
const BACKEND_URL = `http://127.0.0.1:${PORT}`;
const REPO_ROOT = path.resolve(__dirname, '../..');
const PYTHON = process.env.SSHMANAGER_PYTHON
  || path.join(REPO_ROOT, 'backend', '.venv', 'bin', 'python');

let backendProc = null;

function startBackend() {
  const args = [path.join(REPO_ROOT, 'backend', 'run.py')];
  backendProc = spawn(PYTHON, args, {
    env: { ...process.env, SSHMANAGER_RELOAD: '0' },
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
      const r = await fetch(`${BACKEND_URL}/api/sessions`);
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
  win.loadURL(BACKEND_URL);
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
