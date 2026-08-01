/* sshManager 前端逻辑（原生 JS，Electron 友好） */

// ---------- 基础 ----------
const $ = (sel) => document.querySelector(sel);
const state = {
  sessions: [],
  activeId: null,
  term: null,
  fit: null,
  ws: null,
};

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!resp.ok) {
    let detail = "";
    try { detail = (await resp.json()).detail || ""; } catch (_) {}
    throw new Error(`HTTP ${resp.status} ${detail}`);
  }
  return resp.json();
}

function toast(msg) { alert(msg); }

// ---------- 会话列表 ----------
let filterTimer = null;
async function loadSessions() {
  const q = encodeURIComponent($("#filter").value.trim());
  const list = await api(`/api/sessions?q=${q}`);
  state.sessions = list;
  renderList();
  refreshStatuses();
}

function renderList() {
  const ul = $("#session-list");
  ul.innerHTML = "";
  if (!state.sessions.length) {
    ul.innerHTML = '<li class="session-item"><span class="meta"><span class="host">（无会话，点击「新建」）</span></span></li>';
    return;
  }
  for (const s of state.sessions) {
    const li = document.createElement("li");
    li.className = "session-item" + (s.id === state.activeId ? " active" : "");
    li.dataset.id = s.id;

    const dot = document.createElement("span");
    dot.className = "dot";
    dot.dataset.dot = s.id;
    dot.title = "连接状态";

    const meta = document.createElement("span");
    meta.className = "meta";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = s.name;
    const host = document.createElement("div");
    host.className = "host";
    host.textContent = s.transport === "local"
      ? "local · 本地 Shell"
      : `${s.username}@${s.host}:${s.port}`;
    meta.append(name, host);

    const del = document.createElement("button");
    del.className = "del";
    del.title = "删除会话";
    del.textContent = "✕";
    del.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`删除会话「${s.name}」？`)) return;
      await api(`/api/sessions/${s.id}`, { method: "DELETE" });
      if (state.activeId === s.id) closeTerminal();
      await loadSessions();
    });

    li.addEventListener("click", () => openSession(s.id));
    li.append(dot, meta, del);
    ul.append(li);
  }
}

async function refreshStatuses() {
  for (const s of state.sessions) {
    const dot = document.querySelector(`[data-dot="${s.id}"]`);
    if (!dot) continue;
    try {
      const st = await api(`/api/sessions/${s.id}/status`);
      dot.className = "dot " + (st.connected ? "on" : "off");
    } catch (_) { dot.className = "dot err"; }
  }
}

// ---------- 新建会话 ----------
function toggleNewFields() {
  const isSsh = $("#n-transport").value === "ssh";
  document.querySelector(".n-ssh").classList.toggle("hidden", !isSsh);
  toggleAuth();
}
function toggleAuth() {
  const key = $("#n-auth").value === "key";
  $("#n-key-wrap").classList.toggle("hidden", !key);
  $("#n-password-wrap").classList.toggle("hidden", key);
}

async function submitNew() {
  const name = $("#n-name").value.trim();
  if (!name) return toast("名称不能为空");
  const isSsh = $("#n-transport").value === "ssh";
  const body = {
    name,
    transport: $("#n-transport").value,
    description: $("#n-desc").value.trim() || undefined,
  };
  if (isSsh) {
    Object.assign(body, {
      host: $("#n-host").value.trim() || "localhost",
      port: parseInt($("#n-port").value, 10) || 22,
      username: $("#n-user").value.trim() || "root",
      auth_type: $("#n-auth").value,
      password: $("#n-auth").value === "password" ? $("#n-password").value : undefined,
      key_path: $("#n-auth").value === "key" ? $("#n-key").value.trim() : undefined,
    });
  }
  await api("/api/sessions", { method: "POST", body });
  closeModal($("#modal-new"));
  $("#n-name").value = "";
  await loadSessions();
}

// ---------- 导入 / 导出 ----------
async function doExport() {
  const items = await api("/api/sessions/export");
  const json = JSON.stringify(items, null, 2);
  // 剪贴板
  try {
    await navigator.clipboard.writeText(json);
    toast("已复制到剪贴板（同时开始下载 JSON 文件）");
  } catch (_) { /* 剪贴板不可用时仅下载 */ }
  // JSON 文件
  const blob = new Blob([json], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `sshmanager-sessions-${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function importFromText(text) {
  let items;
  try {
    items = JSON.parse(text);
    if (!Array.isArray(items)) items = [items];
  } catch (_) { return toast("JSON 解析失败"); }
  const res = await api("/api/sessions/import", { method: "POST", body: { sessions: items } });
  toast(`导入完成：新增 ${res.added}，跳过 ${res.skipped}，共 ${res.total}`);
  closeModal($("#modal-import"));
  await loadSessions();
}

// ---------- 终端 ----------
function closeTerminal() {
  if (state.ws) { try { state.ws.close(); } catch (_) {} state.ws = null; }
  if (state.term) {
    try { state.term.dispose(); } catch (_) {}
    state.term = null; state.fit = null;
  }
  state.activeId = null;
  $("#terminal-wrap").classList.add("hidden");
  $("#terminal-tabbar").classList.add("hidden");
  $("#empty-state").classList.remove("hidden");
}

async function openSession(id) {
  const s = state.sessions.find((x) => x.id === id);
  if (!s) return;
  closeTerminal();
  state.activeId = id;
  $("#empty-state").classList.add("hidden");
  $("#terminal-wrap").classList.remove("hidden");
  $("#terminal-tabbar").classList.remove("hidden");
  $("#tab-name").textContent = s.name;
  setStatus("off", "连接中…");

  const term = new Terminal({
    cursorBlink: true,
    fontFamily: '"SF Mono", Menlo, Consolas, monospace',
    fontSize: 13,
    theme: {
      background: "#1e1e2e", foreground: "#cdd6f4",
      cursor: "#f5e0dc", selectionBackground: "#45475a",
      black: "#45475a", red: "#f38ba8", green: "#a6e3a1",
      yellow: "#f9e2af", blue: "#89b4fa", magenta: "#cba6f7",
      cyan: "#94e2d5", white: "#bac2de",
    },
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open($("#terminal"));
  fit.fit();
  state.term = term; state.fit = fit;
  window.__term = term; // 调试钩子（E2E 测试用）

  term.onData((data) => {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ type: "input", data }));
    }
  });
  term.onResize(({ cols, rows }) => {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ type: "resize", cols, rows }));
    }
  });

  // 容器尺寸变化时适配
  const ro = new ResizeObserver(() => { try { fit.fit(); } catch (_) {} });
  ro.observe($("#terminal-wrap"));
  term._ro = ro;

  connectWs(id);
}

function connectWs(id) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/terminal/${id}`);
  state.ws = ws;
  ws.onopen = () => {
    if (state.term) {
      state.ws.send(JSON.stringify({ type: "resize", cols: state.term.cols, rows: state.term.rows }));
    }
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (!state.term || state.activeId !== id) return;
    if (msg.type === "output" || msg.type === "buffer") state.term.write(msg.data || "");
    else if (msg.type === "status") {
      const label = { connected: "已连接", closed: "已断开" }[msg.state] || msg.message || "连接状态";
      const cls = msg.state === "connected" ? "on" : (msg.state === "closed" ? "off" : "err");
      setStatus(cls, label);
    }
  };
  ws.onclose = () => {
    if (state.activeId === id) setStatus("err", "连接已断开");
    refreshStatuses();
  };
  ws.onerror = () => { if (state.activeId === id) setStatus("err", "WebSocket 错误"); };
}

function setStatus(cls, text) {
  const el = $("#tab-status");
  el.className = "status " + cls;
  el.textContent = text;
}

// ---------- AI 面板 ----------
function aiModeChanged() {
  const mode = $("#ai-mode").value;
  $("#ai-path").classList.toggle("hidden", mode !== "find");
  $("#ai-pattern").classList.toggle("hidden", mode !== "find");
  $("#ai-input").placeholder =
    mode === "write" ? "写入共享终端的内容…" :
    mode === "exec" ? "非交互式 shell 命令…" : "";
  $("#ai-output").classList.add("hidden");
}

async function aiRun() {
  if (!state.activeId) return toast("请先打开一个终端会话");
  const id = state.activeId;
  const mode = $("#ai-mode").value;
  const out = $("#ai-output");
  const show = (text) => { out.textContent = text; out.classList.remove("hidden"); };

  if (mode === "write") {
    const data = $("#ai-input").value;
    if (!data) return;
    await api(`/api/sessions/${id}/write`, { method: "POST", body: { data } });
    // 内容已注入共享终端，界面通过 ws 回显；清空输入便于连续执行
    $("#ai-input").value = "";
    out.classList.add("hidden");
    return;
  }

  if (mode === "exec") {
    const cmd = $("#ai-input").value;
    if (!cmd) return;
    try {
      const r = await api(`/api/sessions/${id}/exec`, { method: "POST", body: { command: cmd } });
      const tail = r.stderr ? `\n[stderr]\n${r.stderr}` : "";
      show(`$ ${cmd}\n${r.stdout}${tail}\n→ exit ${r.exit_code} (${r.duration_ms}ms)` +
           (r.timed_out ? " ⚠ 超时" : ""));
    } catch (e) { show(`错误：${e.message}`); }
    return;
  }

  // find
  const path = $("#ai-path").value.trim() || ".";
  const pattern = $("#ai-pattern").value.trim() || "*";
  try {
    const r = await api(`/api/sessions/${id}/find`, { method: "POST", body: { path, pattern } });
    const head = r.results.slice(0, 200).join("\n");
    show(`find ${path} -name "${pattern}"\n${head || "(无匹配)"}\n→ ${r.count} 个结果`);
  } catch (e) { show(`错误：${e.message}`); }
}

// ---------- 弹窗 ----------
function openModal(el) { el.classList.remove("hidden"); }
function closeModal(el) { el.classList.add("hidden"); }
document.querySelectorAll("[data-close]").forEach((b) =>
  b.addEventListener("click", () => closeModal(b.closest(".modal"))));

// ---------- 事件绑定 ----------
$("#filter").addEventListener("input", () => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(loadSessions, 200);
});
$("#btn-new").addEventListener("click", () => { toggleNewFields(); openModal($("#modal-new")); });
$("#n-transport").addEventListener("change", toggleNewFields);
$("#n-auth").addEventListener("change", toggleAuth);
$("#n-submit").addEventListener("click", submitNew);

$("#btn-export").addEventListener("click", doExport);
$("#btn-import").addEventListener("click", () => { openModal($("#modal-import")); $("#i-text").focus(); });
$("#i-submit").addEventListener("click", () => importFromText($("#i-text").value));
$("#i-file").addEventListener("click", () => $("#i-file-input").click());
$("#i-file-input").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const text = await f.text();
  await importFromText(text);
  e.target.value = "";
});

$("#btn-disconnect").addEventListener("click", async () => {
  if (!state.activeId) return;
  await api(`/api/sessions/${state.activeId}/disconnect`, { method: "POST" });
  setStatus("off", "已断开");
  refreshStatuses();
});

$("#ai-mode").addEventListener("change", aiModeChanged);
$("#ai-run").addEventListener("click", aiRun);
$("#ai-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); aiRun(); }
});

// 回车新建、Esc 关弹窗
$("#n-name").addEventListener("keydown", (e) => { if (e.key === "Enter") submitNew(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") document.querySelectorAll(".modal").forEach(closeModal);
});

// 启动
loadSessions();
setInterval(refreshStatuses, 10000);
