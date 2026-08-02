/* sshManager — 基础层（从 app.js 拆分）：DOM/api/state/主题/modal 助手 */

const $ = (sel) => document.querySelector(sel);

const state = {
  sessions: [],
  groups: [],
  filter: "",
  expanded: new Set(),
  statuses: {},      // sid -> "on" | "off" | "err"
  bg: {},            // sid -> 后台保活连接 conn_id 数组
  bgNames: {},       // conn_id -> 服务端返回的显示名（label 或会话名，恢复用）
  connLabels: {},    // conn_id -> 自定义 tab 标签（后台面板/恢复用）
  tabs: [],          // [{key, sid, name, connId, mode, custom}] mode: "new"|"restore"
  tabKey: 0,         // tab 唯一 key 递增器
  selectedId: null,  // 列表选中（单击）
  activeKey: null,   // 当前激活 tab 的 key
  editingSid: null,  // 正在编辑的会话 id（null=新建）
  quickGroups: [],
  quickCommands: [],
  quickActiveGroup: null,
  sftpSid: null,   // 当前 SFTP 面板所属会话
  sftpPath: ".",
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

function toast(msg) { alert(msg); }

// ==========================================================================
// 主题（暗/亮）：xterm 双主题 + 切换
// ==========================================================================
const XTERM_THEMES = {
  dark: {
    background: "#0c0e13", foreground: "#e8edf5", cursor: "#a5b4fc",
    cursorAccent: "#0c0e13", selectionBackground: "rgba(124,108,240,0.35)",
    black: "#3b4252", red: "#ff7b72", green: "#4ade80", yellow: "#fbbf24",
    blue: "#79c0ff", magenta: "#bc8cff", cyan: "#39c5cf", white: "#e8edf5",
    brightBlack: "#6c7686", brightRed: "#ffa198", brightGreen: "#7ee2a8",
    brightYellow: "#f9d58a", brightBlue: "#a5d6ff", brightMagenta: "#d2a8ff",
    brightCyan: "#56d4dd", brightWhite: "#ffffff",
  },
  light: {
    background: "#eff1f5", foreground: "#4c4f69", cursor: "#8839ef",
    cursorAccent: "#eff1f5", selectionBackground: "rgba(136,57,239,0.20)",
    black: "#5c5f77", red: "#d20f39", green: "#40a02b", yellow: "#df8e1d",
    blue: "#1e66f5", magenta: "#8839ef", cyan: "#179299", white: "#eff1f5",
    brightBlack: "#6c6f85", brightRed: "#e64553", brightGreen: "#40a02b",
    brightYellow: "#df8e1d", brightBlue: "#1e66f5", brightMagenta: "#8839ef",
    brightCyan: "#179299", brightWhite: "#4c4f69",
  },
};
function currentXtermTheme() {
  return XTERM_THEMES[document.documentElement.dataset.theme === "light" ? "light" : "dark"];
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("sshmgr-theme", theme);
  const btn = $("#btn-theme");
  if (btn) btn.textContent = theme === "dark" ? "🌙" : "☀️";
  // 已打开的终端立即换色
  if (state.term) {
    state.term.options.theme = XTERM_THEMES[theme];
    try { state.term.refresh(0, state.term.rows - 1); } catch (_) {}
  }
}

// ==========================================================================
// 弹窗基础
// ==========================================================================
function openModal(el) {
  el.classList.remove("hidden");
  // 每个弹窗统一加右上角 ✕ 关闭按钮
  const box = el.querySelector(".modal-box");
  if (box && !box.querySelector(".modal-x")) {
    const x = document.createElement("button");
    x.className = "modal-x";
    x.textContent = "✕";
    x.title = "Close";
    x.addEventListener("click", () => closeModal(el));
    box.appendChild(x);
  }
}
function closeModal(el) { el.classList.add("hidden"); }
// 点击弹窗非弹框区域（backdrop）收起
document.addEventListener("click", (e) => {
  if (e.target.classList && e.target.classList.contains("modal")) closeModal(e.target);
});
document.querySelectorAll("[data-close]").forEach((b) =>
  b.addEventListener("click", () => closeModal(b.closest(".modal"))));

// 通用命名弹窗（重命名/新建分组等）
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
  sel.innerHTML = '<option value="">No group (root)</option>';
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
