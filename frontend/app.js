/* sshManager 前端逻辑 —— xshell 风格布局：左侧分组树 + 主区多标签终端 */

const $ = (sel) => document.querySelector(sel);

const state = {
  sessions: [],
  groups: [],
  filter: "",
  expanded: new Set(),
  statuses: {},      // sid -> "on" | "off" | "err"
  bg: {},            // sid -> 后台保活连接 conn_id 数组
  tabs: [],          // [{key, sid, name, connId, mode}] mode: "new"|"restore"
  tabKey: 0,         // tab 唯一 key 递增器
  selectedId: null,  // 列表选中（单击）
  activeKey: null,   // 当前激活 tab 的 key
  term: null,
  fit: null,
  ws: null,
  ctxTarget: null,   // 右键菜单当前目标 {type, id}
};

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: opts.body ? { "Content-Type": "application/json" } : {},
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

// ==========================================================================
// 会话 / 分组数据
// ==========================================================================
async function loadAll() {
  const [sessions, groups] = await Promise.all([api("/api/sessions"), api("/api/groups")]);
  state.sessions = sessions;
  state.groups = groups;
  renderTree();
  refreshStatuses();
}

function sessionById(id) {
  return state.sessions.find((s) => s.id === id);
}

function activeSid() {
  const t = state.tabs.find((x) => x.key === state.activeKey);
  return t ? t.sid : null;
}

function _matches(s) {
  const f = state.filter.trim().toLowerCase();
  if (!f) return true;
  const hay = `${s.name} ${s.host} ${s.port}`.toLowerCase();
  return f.split(/\s+/).every((t) => t && hay.includes(t));
}

function renderTree() {
  const nav = $("#tree");
  nav.innerHTML = "";
  const frag = document.createDocumentFragment();
  let i = 0;
  const anim = () => `animation-delay:${Math.min(i++ * 18, 300)}ms`;

  const groupSessions = (gid) => state.sessions.filter((s) => s.group_id === gid && _matches(s));

  // 分组（过滤时不显示空分组）
  for (const g of state.groups) {
    const items = groupSessions(g.id);
    if (state.filter && !items.length) continue;
    const node = _groupNode(g, items, anim());
    frag.append(node);
  }

  // 无分组会话放在根层级
  for (const s of state.sessions) {
    if (s.group_id || !_matches(s)) continue;
    frag.append(_sessionNode(s, anim()));
  }

  if (!frag.childNodes.length) {
    const empty = document.createElement("div");
    empty.className = "tree-item";
    empty.style.cssText = "color:var(--text-faint);cursor:default";
    empty.textContent = state.filter ? "无匹配会话" : "暂无会话，点右上角「新建会话」";
    frag.append(empty);
  }
  nav.append(frag);
}

function _groupNode(g, items, style) {
  const li = document.createElement("li");
  li.className = "group-item" + (state.expanded.has(g.id) ? "" : " collapsed");

  const row = document.createElement("div");
  row.className = "tree-item group-row";
  row.dataset.groupId = g.id;
  row.style.cssText = style;
  row.innerHTML = `
    <span class="caret">▾</span>
    <span class="gname"></span>
    <span class="gcount">${items.length}</span>`;
  row.querySelector(".gname").textContent = g.name;

  row.addEventListener("click", (e) => {
    e.stopPropagation();
    if (state.expanded.has(g.id)) state.expanded.delete(g.id);
    else state.expanded.add(g.id);
    renderTree();
  });
  row.addEventListener("contextmenu", (e) => {
    e.preventDefault(); e.stopPropagation();
    showCtx(e.clientX, e.clientY, [
      { label: "在此分组新建会话", action: "newInGroup" },
      { label: "重命名分组", action: "renameGroup" },
      { label: "删除分组", action: "deleteGroup", danger: true },
    ]);
    state.ctxTarget = { type: "group", id: g.id, name: g.name };
  });

  const wrap = document.createElement("div");
  wrap.className = "group-children";
  const ul = document.createElement("ul");
  for (const s of items) ul.append(_sessionNode(s, style));
  wrap.append(ul);
  li.append(row, wrap);
  return li;
}

function _sessionNode(s, style) {
  const li = document.createElement("li");
  li.className = "tree-item sess-item"
    + (s.id === activeSid() ? " active" : s.id === state.selectedId ? " selected" : "");
  li.style.cssText = style;
  li.dataset.sid = s.id;
  const st = document.createElement("span");
  st.className = "sess-status off";
  st.dataset.status = s.id;
  st.innerHTML = '<span class="sdot"></span><span class="stext">离线</span>';
  const meta = document.createElement("span");
  meta.className = "sess-meta";
  const name = document.createElement("div");
  name.className = "sess-name";
  name.textContent = s.name;
  const host = document.createElement("div");
  host.className = "sess-host";
  host.textContent = s.transport === "local"
    ? "local · 本地 Shell"
    : `${s.username}@${s.host}:${s.port}`;
  meta.append(name, host);

  li.addEventListener("click", () => selectSession(s.id));           // 单击选中
  li.addEventListener("dblclick", () => openSession(s.id));          // 双击：有后台则恢复，否则新建
  li.addEventListener("contextmenu", (e) => {
    e.preventDefault(); e.stopPropagation();
    const bg = state.bg[s.id] || [];
    const items = [
      { label: "打开", action: "open" },
    ];
    if (bg.length) {
      items.push(
        { label: "恢复到后台连接", action: "restoreBg" },
        { label: "断开后台连接", action: "disconnectBg" },
      );
    }
    items.push(
      { label: "以新连接打开", action: "openNew" },
      { label: "移动到分组…", action: "move" },
      { label: "重命名", action: "renameSession" },
      { label: "删除", action: "deleteSession", danger: true },
    );
    showCtx(e.clientX, e.clientY, items);
    state.ctxTarget = { type: "session", id: s.id, name: s.name };
  });

  li.append(st, meta);
  return li;
}

function selectSession(id) {
  state.selectedId = id;
  renderTree();
}

function setStatus(sid, cls, text) {
  state.statuses[sid] = cls;
  const el = document.querySelector(`[data-status="${sid}"]`);
  if (!el) return;
  el.className = "sess-status " + (cls === "on" ? "on" : cls === "bg" ? "bg" : "off");
  const txt = el.querySelector(".stext");
  if (txt) txt.textContent = text || (cls === "on" ? "运行中" : cls === "bg" ? "后台" : "离线");
}

async function refreshStatuses() {
  for (const s of state.sessions) {
    try {
      const st = await api(`/api/sessions/${s.id}/status`);
      state.bg[s.id] = st.background_conns || [];
      if (state.bg[s.id].length) setStatus(s.id, "bg", `后台 ×${state.bg[s.id].length}`);
      else if (st.connected) setStatus(s.id, "on", "运行中");
      else setStatus(s.id, "off", "离线");
    } catch (_) { setStatus(s.id, "off", "离线"); }
  }
  refreshBgCount();
}

// ==========================================================================
// 多标签终端
// ==========================================================================
function renderTabs() {
  const box = $("#tabs");
  box.innerHTML = "";
  for (const t of state.tabs) {
    const el = document.createElement("div");
    el.className = "tab" + (t.key === state.activeKey ? " active" : "");
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.dataset.tdot = t.sid;
    const _sc = state.statuses[t.sid];
    const dotColor = _sc === "on" ? "var(--ok)" : _sc === "bg" ? "var(--warn)" : "var(--text-faint)";
    dot.style.cssText = `width:6px;height:6px;border-radius:50%;flex-shrink:0;background:${dotColor}`;
    const nm = document.createElement("span");
    nm.className = "tname";
    nm.textContent = t.name;

    // 两个关闭按钮：✕ 仅关闭页面（SSH 保活）；⏻ 断开 SSH 并关闭
    const actions = document.createElement("span");
    actions.className = "t-actions";
    const close = document.createElement("button");
    close.className = "t-btn t-close";
    close.title = "仅关闭页面（SSH 后台保活）";
    close.textContent = "✕";
    close.addEventListener("click", (e) => { e.stopPropagation(); closeTab(t.key); });
    const power = document.createElement("button");
    power.className = "t-btn t-power";
    power.title = "断开 SSH 并关闭";
    power.textContent = "⏻";
    power.addEventListener("click", (e) => { e.stopPropagation(); closeWithDisconnect(t.key); });
    actions.append(close, power);

    el.append(dot, nm, actions);
    el.addEventListener("click", () => activateTab(t.key));
    box.append(el);
  }
}

function openSession(sid) {
  // 双击：有后台保活连接则恢复到它，否则新建独立连接
  const s = sessionById(sid);
  if (!s) return;
  const bg = state.bg[sid] || [];
  if (bg.length) openTab(sid, bg[0], "restore");
  else openTab(sid, null, "new");
}

function openTab(sid, connId, mode) {
  const s = sessionById(sid);
  if (!s) return;
  state.tabKey += 1;
  const key = state.tabKey;
  state.tabs.push({ key, sid, name: s.name, connId, mode });
  activateTab(key);
}

function activateTab(key) {
  teardownTerminal();
  state.activeKey = key;
  renderTabs();
  renderTree();
  $("#empty-state").classList.add("hidden");
  $("#terminal-wrap").classList.remove("hidden");
  setupTerminal(key);
}

function closeTab(key) {
  const idx = state.tabs.findIndex((t) => t.key === key);
  if (idx < 0) return;
  state.tabs.splice(idx, 1);
  if (state.activeKey === key) {
    teardownTerminal();
    state.activeKey = null;
    if (state.tabs.length) {
      activateTab(state.tabs[Math.min(idx, state.tabs.length - 1)].key);
      return;
    }
    $("#terminal-wrap").classList.add("hidden");
    $("#empty-state").classList.remove("hidden");
  }
  renderTabs();
  renderTree();
  refreshStatuses(); // 关闭后刷新后台保活标记
}

function teardownTerminal() {
  if (state.ws) { try { state.ws.close(); } catch (_) {} state.ws = null; }
  if (state.term) {
    try { state.term.dispose(); } catch (_) {}
    if (state.term._ro) { try { state.term._ro.disconnect(); } catch (_) {} }
    state.term = null; state.fit = null;
  }
  $("#terminal").innerHTML = "";
}

function setupTerminal(key) {
  const tab = state.tabs.find((t) => t.key === key);
  if (!tab) return;
  const id = tab.sid;
  const term = new Terminal({
    cursorBlink: true,
    fontFamily: '"JetBrains Mono", "SF Mono", Menlo, Consolas, monospace',
    fontSize: 13,
    lineHeight: 1.25,
    theme: {
      background: "#0c0e13", foreground: "#e8edf5", cursor: "#a5b4fc",
      cursorAccent: "#0c0e13", selectionBackground: "rgba(124,108,240,0.35)",
      black: "#3b4252", red: "#ff7b72", green: "#4ade80", yellow: "#fbbf24",
      blue: "#79c0ff", magenta: "#bc8cff", cyan: "#39c5cf", white: "#e8edf5",
      brightBlack: "#6c7686", brightRed: "#ffa198", brightGreen: "#7ee2a8",
      brightYellow: "#f9d58a", brightBlue: "#a5d6ff", brightMagenta: "#d2a8ff",
      brightCyan: "#56d4dd", brightWhite: "#ffffff",
    },
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open($("#terminal"));
  fit.fit();
  state.term = term;
  state.fit = fit;
  window.__term = term; // E2E 调试钩子

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
  const ro = new ResizeObserver(() => { try { fit.fit(); } catch (_) {} });
  ro.observe($("#terminal-wrap"));
  term._ro = ro;

  connectWs(key);
}

function connectWs(key) {
  const tab = state.tabs.find((t) => t.key === key);
  if (!tab) return;
  const id = tab.sid;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const path = tab.mode === "restore" ? `/ws/connection/${tab.connId}` : `/ws/terminal/${id}`;
  const ws = new WebSocket(`${proto}://${location.host}${path}`);
  state.ws = ws;
  ws.onopen = () => {
    if (state.term && activeSid() === id) {
      ws.send(JSON.stringify({ type: "resize", cols: state.term.cols, rows: state.term.rows }));
    }
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "status" && msg.conn_id) tab.connId = msg.conn_id; // 记住 conn_id（断开/恢复用）
    if (!state.term || activeSid() !== id) return;
    if (msg.type === "output" || msg.type === "buffer") state.term.write(msg.data || "");
    else if (msg.type === "status") {
      const on = msg.state === "connected";
      setStatus(id, on ? "on" : "off", on ? "运行中" : "离线");
      renderTabs();
    }
  };
  ws.onclose = () => {
    if (activeSid() === id) renderTabs();
    refreshStatuses();
  };
  ws.onerror = () => { if (activeSid() === id) setStatus(id, "off", "错误"); };
}

// ==========================================================================
// 右键菜单
// ==========================================================================
const ctxEl = $("#ctxmenu");

function showCtx(x, y, items) {
  ctxEl.innerHTML = "";
  items.forEach((it, idx) => {
    if (it === "sep") {
      const sep = document.createElement("div");
      sep.className = "ctx-sep";
      ctxEl.append(sep);
      return;
    }
    const b = document.createElement("button");
    if (it.danger) b.className = "danger";
    b.textContent = it.label;
    b.addEventListener("click", () => {
      if (it.onSelect) it.onSelect();
      else runCtxAction(it.action);
    });
    ctxEl.append(b);
  });
  ctxEl.classList.remove("hidden");
  const rect = ctxEl.getBoundingClientRect();
  ctxEl.style.left = Math.min(x, window.innerWidth - rect.width - 8) + "px";
  ctxEl.style.top = Math.min(y, window.innerHeight - rect.height - 8) + "px";
}

function hideCtx() { ctxEl.classList.add("hidden"); }

async function closeWithDisconnect(key) {
  const tab = state.tabs.find((t) => t.key === key);
  if (tab && tab.connId) {
    try { await api(`/api/connections/${tab.connId}/disconnect`, { method: "POST" }); } catch (_) {}
  }
  closeTab(key);
  refreshStatuses();
}

async function runCtxAction(action) {
  const t = state.ctxTarget;
  state.ctxTarget = null;
  hideCtx();
  if (!t) return;
  if (action === "open" && t.type === "session") openSession(t.id);
  else if (action === "restoreBg" && t.type === "session") {
    const bg = state.bg[t.id] || [];
    if (bg.length) openTab(t.id, bg[0], "restore");
  }
  else if (action === "openNew" && t.type === "session") openTab(t.id, null, "new");
  else if (action === "disconnectBg" && t.type === "session") {
    const bg = state.bg[t.id] || [];
    for (const conn of bg) {
      try { await api(`/api/connections/${conn}/disconnect`, { method: "POST" }); } catch (_) {}
    }
    state.bg[t.id] = [];
    await loadAll();
    refreshStatuses();
  }
  else if (action === "renameGroup") promptModal("重命名分组", t.name, async (v) => {
    if (v) { await api(`/api/groups/${t.id}`, { method: "PATCH", body: { name: v } }); await loadAll(); }
  });
  else if (action === "renameSession") promptModal("重命名会话", t.name, async (v) => {
    if (v) {
      await api(`/api/sessions/${t.id}`, { method: "PATCH", body: { name: v } });
      state.tabs.forEach((tb) => { if (tb.sid === t.id) tb.name = v; });
      await loadAll(); renderTabs();
    }
  });
  else if (action === "deleteSession" && t.type === "session") {
    if (!confirm(`删除会话「${t.name}」？`)) return;
    await api(`/api/sessions/${t.id}`, { method: "DELETE" });
    const idx = state.tabs.findIndex((x) => x.id === t.id);
    if (idx >= 0) closeTab(t.id);
    await loadAll();
  }
  else if (action === "move" && t.type === "session") {
    state.movingSid = t.id;
    moveModal(t.id, t.name);
  }
  else if (action === "deleteGroup") {
    if (!confirm(`删除分组「${t.name}」？组内会话将回到根层级。`)) return;
    await api(`/api/groups/${t.id}`, { method: "DELETE" });
    await loadAll();
  }
  else if (action === "newInGroup" && t.type === "group") {
    populateGroupSelect();
    $("#n-group").value = t.id;
    toggleNewFields();
    $("#n-name").value = "";
    openModal($("#modal-new"));
  }
}

document.addEventListener("click", (e) => {
  if (!ctxEl.contains(e.target)) hideCtx();
});
document.addEventListener("contextmenu", (e) => {
  if (!e.target.closest(".tree-item")) hideCtx();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { hideCtx(); document.querySelectorAll(".modal").forEach(closeModal); }
});

// ==========================================================================
// 弹窗
// ==========================================================================
function openModal(el) { el.classList.remove("hidden"); }
function closeModal(el) { el.classList.add("hidden"); }
document.querySelectorAll("[data-close]").forEach((b) =>
  b.addEventListener("click", () => closeModal(b.closest(".modal"))));

let promptCb = null;
function promptModal(title, value, cb) {
  $("#mp-title").textContent = title;
  $("#mp-input").value = value || "";
  promptCb = cb;
  openModal($("#modal-prompt"));
  $("#mp-input").focus();
}
$("#mp-ok").addEventListener("click", () => {
  const v = $("#mp-input").value.trim();
  closeModal($("#modal-prompt"));
  if (promptCb) promptCb(v);
  promptCb = null;
});
$("#mp-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); $("#mp-ok").click(); }
});

// 移动分组
function moveModal(sid, sname) {
  const sel = $("#mm-select");
  sel.innerHTML = '<option value="">无分组（根层级）</option>';
  for (const g of state.groups) {
    const o = document.createElement("option");
    o.value = g.id;
    o.textContent = g.name;
    sel.append(o);
  }
  const cur = sessionById(sid);
  if (cur && cur.group_id) sel.value = cur.group_id;
  openModal($("#modal-move"));
}
$("#mm-ok").addEventListener("click", async () => {
  const sid = state.movingSid;
  const gid = $("#mm-select").value;
  closeModal($("#modal-move"));
  if (!sid) return;
  await api(`/api/sessions/${sid}`, { method: "PATCH", body: { group_id: gid || null } });
  state.movingSid = null;
  await loadAll();
});
state.movingSid = null;

// ==========================================================================
// 新建 / 导入 / 导出 / 分组
// ==========================================================================
function populateGroupSelect() {
  const sel = $("#n-group");
  const keep = sel.value;
  sel.innerHTML = '<option value="">无分组</option>';
  for (const g of state.groups) {
    const o = document.createElement("option");
    o.value = g.id; o.textContent = g.name;
    sel.append(o);
  }
  if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
}

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
    group_id: $("#n-group").value || undefined,
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
  await loadAll();
}

function toast(msg) { alert(msg); }

function openNewModal() {
  populateGroupSelect();
  toggleNewFields();
  $("#n-name").value = "";
  openModal($("#modal-new"));
}

// 分组
async function createGroup(name) {
  if (!name) return;
  await api("/api/groups", { method: "POST", body: { name } });
  await loadAll();
}

// 导入导出
async function doExport() {
  const items = await api("/api/sessions/export");
  const json = JSON.stringify(items, null, 2);
  try { await navigator.clipboard.writeText(json); toast("已复制到剪贴板（同时下载 JSON 文件）"); } catch (_) {}
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
  await loadAll();
}

// ==========================================================================
// 后台连接面板
// ==========================================================================
async function refreshBgCount() {
  try {
    const bg = await api("/api/connections/background");
    $("#bg-count").textContent = bg.length;
    if (!$("#bg-panel").classList.contains("hidden")) renderBgPanel();
  } catch (_) {}
}

async function renderBgPanel() {
  const list = $("#bg-list");
  let bg = [];
  try { bg = await api("/api/connections/background"); } catch (_) {}
  $("#bg-count").textContent = bg.length;
  list.innerHTML = "";
  if (!bg.length) {
    list.innerHTML = '<div class="bg-empty">没有后台连接</div>';
    return;
  }
  for (const c of bg) {
    const row = document.createElement("div");
    row.className = "bg-item";
    const info = document.createElement("span");
    info.className = "bg-info";
    const nm = document.createElement("span");
    nm.className = "bg-name"; nm.textContent = c.name;
    const hs = document.createElement("span");
    hs.className = "bg-host"; hs.textContent = c.host || c.transport || "";
    info.append(nm, hs);
    const res = document.createElement("button");
    res.className = "btn small"; res.textContent = "恢复";
    res.addEventListener("click", () => { openTab(c.sid, c.conn_id, "restore"); hideBgPanel(); });
    const disc = document.createElement("button");
    disc.className = "btn small danger"; disc.textContent = "断开";
    disc.addEventListener("click", async () => {
      try { await api(`/api/connections/${c.conn_id}/disconnect`, { method: "POST" }); } catch (_) {}
      await renderBgPanel();
      refreshStatuses();
    });
    row.append(info, res, disc);
    list.append(row);
  }
}

function toggleBgPanel() {
  const p = $("#bg-panel");
  if (p.classList.contains("hidden")) {
    p.classList.remove("hidden");
    const r = $("#btn-bg").getBoundingClientRect();
    p.style.left = Math.min(r.left, Math.max(8, window.innerWidth - 330)) + "px";
    p.style.top = (r.bottom + 6) + "px";
    renderBgPanel();
  } else {
    p.classList.add("hidden");
  }
}

function hideBgPanel() { $("#bg-panel").classList.add("hidden"); }

// ==========================================================================
// 事件绑定
// ==========================================================================
let filterTimer = null;
$("#filter").addEventListener("input", () => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => {
    state.filter = $("#filter").value;
    renderTree();
  }, 180);
});

$("#btn-new").addEventListener("click", openNewModal);
$("#btn-new-tab").addEventListener("click", openNewModal);
$("#empty-new").addEventListener("click", openNewModal);
$("#btn-add-group").addEventListener("click", () => promptModal("新建分组", "", (v) => createGroup(v)));
$("#btn-bg").addEventListener("click", (e) => { e.stopPropagation(); toggleBgPanel(); });
document.addEventListener("click", (e) => {
  if (!e.target.closest("#bg-panel") && !e.target.closest("#btn-bg")) hideBgPanel();
});
$("#n-transport").addEventListener("change", toggleNewFields);
$("#n-auth").addEventListener("change", toggleAuth);
$("#n-submit").addEventListener("click", submitNew);
$("#n-name").addEventListener("keydown", (e) => { if (e.key === "Enter") submitNew(); });

$("#btn-export").addEventListener("click", doExport);
$("#btn-import").addEventListener("click", () => { openModal($("#modal-import")); $("#i-text").focus(); });
$("#i-submit").addEventListener("click", () => importFromText($("#i-text").value));
$("#i-file").addEventListener("click", () => $("#i-file-input").click());
$("#i-file-input").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  await importFromText(await f.text());
  e.target.value = "";
});

// 启动
loadAll();
setInterval(refreshStatuses, 10000);
