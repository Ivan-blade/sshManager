/* sshManager — 快捷命令（终端底部栏）+ 快捷命令导入导出（从 app.js 拆分） */

async function loadQuick() {
  const [groups, commands] = await Promise.all([
    api("/api/quick/groups"), api("/api/quick/commands"),
  ]);
  state.quickGroups = groups;
  state.quickCommands = commands;
  renderQuick();
}

const QUICK_ALL = "__all__"; // 快捷命令「全部」视图哨兵值

function renderQuick() {
  const active = state.quickGroups.find((g) => g.id === state.quickActiveGroup);
  const label = state.quickActiveGroup === QUICK_ALL ? "All Commands"
    : (active ? active.name : "Default Group");
  $("#quick-group-btn").textContent = label + " ▾";

  // 移除旧的 +（动态放置）
  document.querySelectorAll("#quickbar .quick-add-cmd").forEach((b) => b.remove());

  const cbox = $("#quick-cmds");
  cbox.innerHTML = "";
  // All Commands = 全部分组；Default Group = 仅未分组；否则 = 指定分组
  const cmds = state.quickCommands.filter((c) => {
    if (state.quickActiveGroup === QUICK_ALL) return true;
    if (state.quickActiveGroup === null) return !c.group_id;
    return c.group_id === state.quickActiveGroup;
  });

  const addBtn = document.createElement("button");
  addBtn.className = "icon-btn quick-add-cmd";
  addBtn.title = "New command";
  addBtn.textContent = "＋";
  addBtn.addEventListener("click", () => openQuickCmdModal(null));

  if (cmds.length) {
    for (const c of cmds) {
      const btn = document.createElement("button");
      btn.className = "quick-cmd";
      btn.textContent = c.name;
      btn.title = c.command;
      btn.addEventListener("click", () => runQuickCommand(c));
      btn.addEventListener("contextmenu", (e) => {
        e.preventDefault(); e.stopPropagation();
        showCtx(e.clientX, e.clientY, [
          { label: "Edit", action: "quickEditCmd" },
          { label: "Move to group", submenu: [
            { label: "Default Group", onSelect: () => moveQuickCmd(c.id, null) },
            ...state.quickGroups.map((g) => ({ label: g.name, onSelect: () => moveQuickCmd(c.id, g.id) })),
          ]},
          { label: "Delete", action: "quickDeleteCmd", danger: true },
        ]);
        state.ctxTarget = { type: "quickCmd", id: c.id, name: c.name };
      });
      cbox.append(btn);
    }
    cbox.append(addBtn); // 有命令：+ 放在命令最右
  } else {
    $("#quick-group-btn").after(addBtn); // 无命令：+ 放在分组按钮右边
  }
}

function hideQuickMenu() { $("#quick-group-menu").classList.add("hidden"); }

function buildInlineGroupInput() {
  const row = document.createElement("div");
  row.className = "qgm-item qgm-input";
  const input = document.createElement("input");
  input.placeholder = "Group name";
  const ok = document.createElement("button");
  ok.className = "icon-btn small"; ok.textContent = "✓"; ok.title = "OK";
  const commit = async () => {
    const v = input.value.trim();
    if (!v) return;
    await api("/api/quick/groups", { method: "POST", body: { name: v } });
    await loadQuick();
    renderQuickMenu();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") commit();
    else if (e.key === "Escape") renderQuickMenu();
  });
  ok.addEventListener("click", (e) => { e.stopPropagation(); commit(); });
  row.append(input, ok);
  setTimeout(() => input.focus(), 0);
  return row;
}

function buildInlineGroupEdit(gid, currentName) {
  const row = document.createElement("div");
  row.className = "qgm-item qgm-input";
  const input = document.createElement("input");
  input.value = currentName;
  const ok = document.createElement("button");
  ok.className = "icon-btn small"; ok.textContent = "✓"; ok.title = "OK";
  const commit = async () => {
    const v = input.value.trim();
    if (!v) return;
    await api(`/api/quick/groups/${gid}`, { method: "PATCH", body: { name: v } });
    await loadQuick();
    renderQuickMenu();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") commit();
    else if (e.key === "Escape") renderQuickMenu();
  });
  ok.addEventListener("click", (e) => { e.stopPropagation(); commit(); });
  row.append(input, ok);
  setTimeout(() => input.focus(), 0);
  return row;
}

function renderQuickMenu() {
  const menu = $("#quick-group-menu");
  menu.innerHTML = "";
  const head = document.createElement("div");
  head.className = "qgm-head"; head.textContent = "Groups";
  menu.append(head);

  const addRow = (gid, label, isAll) => {
    const row = document.createElement("div");
    row.className = "qgm-item" + (state.quickActiveGroup === gid ? " active" : "");
    const nm = document.createElement("span");
    nm.className = "qgm-name"; nm.textContent = label;
    row.append(nm);
    row.addEventListener("click", () => { state.quickActiveGroup = gid; renderQuick(); hideQuickMenu(); });
    if (!isAll) {
      const rn = document.createElement("button");
      rn.className = "icon-btn small icon-edit"; rn.textContent = "✎"; rn.title = "Rename group";
      rn.addEventListener("click", (e) => {
        e.stopPropagation();
        row.replaceWith(buildInlineGroupEdit(gid, label)); // 行内重命名，不弹窗
      });
      const del = document.createElement("button");
      del.className = "icon-btn small danger"; del.textContent = "✕"; del.title = "Delete group";
      del.addEventListener("click", async (e) => {
        e.stopPropagation();
        await api(`/api/quick/groups/${gid}`, { method: "DELETE" });
        if (state.quickActiveGroup === gid) state.quickActiveGroup = null;
        await loadQuick();
        renderQuickMenu();
      });
      row.append(rn, del);
    }
    menu.append(row);
  };

  addRow(QUICK_ALL, "All Commands", true);
  addRow(null, "Default Group", true);
  for (const g of state.quickGroups) addRow(g.id, g.name, false);

  const foot = document.createElement("div");
  foot.className = "qgm-foot";
  const newBtn = document.createElement("button");
  newBtn.className = "qgm-new"; newBtn.textContent = "＋ New Group";
  newBtn.addEventListener("click", (e) => {
    // 关键：replaceWith 会把按钮从 DOM 移除，导致后续冒泡到 document 的
    // 「点外部关闭」处理器把 e.target.closest 判断成 null（parentNode 已空）→ 误关菜单
    e.stopPropagation();
    newBtn.replaceWith(buildInlineGroupInput()); // 行内新增，不弹窗
  });
  foot.append(newBtn);
  menu.append(foot);
}

function toggleQuickGroupMenu() {
  const menu = $("#quick-group-menu");
  if (!menu.classList.contains("hidden")) { hideQuickMenu(); return; }
  renderQuickMenu();
  const qb = $("#quickbar").getBoundingClientRect();
  menu.style.left = qb.left + "px";
  menu.style.bottom = (window.innerHeight - qb.top + 4) + "px";
  menu.classList.remove("hidden");
}

function runQuickCommand(cmd) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return toast("No active terminal");
  // 只回显到终端：命令本身带换行符才执行；否则用户可编辑后回车
  state.ws.send(JSON.stringify({ type: "input", data: (cmd.command || "") }));
  // 焦点还给终端：否则回车会再次触发快捷命令按钮（重复输入）
  if (state.term) state.term.focus();
}

async function moveQuickCmd(cid, newGroupId) {
  await api(`/api/quick/commands/${cid}`, { method: "PATCH", body: { group_id: newGroupId } });
  await loadQuick();
}

let editingQuickCmdId = null;
function openQuickCmdModal(cmd) {
  editingQuickCmdId = cmd ? cmd.id : null;
  $("#qc-title").textContent = cmd ? "Edit Command" : "New Command";
  const sel = $("#qc-group");
  sel.innerHTML = '<option value="">Default Group</option>';
  for (const g of state.quickGroups) {
    const o = document.createElement("option");
    o.value = g.id; o.textContent = g.name;
    sel.append(o);
  }
  $("#qc-name").value = cmd ? cmd.name : "";
  $("#qc-command").value = cmd ? cmd.command : "";
  sel.value = cmd ? (cmd.group_id || "")
    : (state.quickActiveGroup && state.quickActiveGroup !== QUICK_ALL ? state.quickActiveGroup : "");
  openModal($("#modal-quick"));
}

async function submitQuickCmd() {
  const name = $("#qc-name").value.trim();
  const command = $("#qc-command").value.trim();
  if (!name || !command) return toast("Name and command required");
  const body = { name, command, group_id: $("#qc-group").value || null };
  if (editingQuickCmdId) await api(`/api/quick/commands/${editingQuickCmdId}`, { method: "PATCH", body });
  else await api("/api/quick/commands", { method: "POST", body });
  editingQuickCmdId = null;
  closeModal($("#modal-quick"));
  await loadQuick();
}

// ==========================================================================
// 快捷命令导入 / 导出
// ==========================================================================
function renderQuickExportList(sel, items, type) {
  const box = $(sel);
  box.innerHTML = "";
  if (!items.length) { box.innerHTML = '<div class="exp-empty">(none)</div>'; return; }
  for (const it of items) {
    const label = document.createElement("label");
    label.className = "exp-item";
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.value = it.id; cb.checked = true;
    label.append(cb);
    const nm = document.createElement("span"); nm.textContent = it.name;
    label.append(nm);
    if (type === "command_ids") {
      const hs = document.createElement("span"); hs.className = "exp-host"; hs.textContent = it.command || "";
      label.append(hs);
    }
    box.append(label);
  }
}

function openQuickExportModal() {
  renderQuickExportList("#qexp-groups", state.quickGroups, "group_ids");
  renderQuickExportList("#qexp-commands", state.quickCommands, "command_ids");
  openModal($("#modal-q-export"));
}

async function doQuickExport(mode) {
  const body = {
    group_ids: [...document.querySelectorAll("#qexp-groups input:checked")].map((e) => e.value),
    command_ids: [...document.querySelectorAll("#qexp-commands input:checked")].map((e) => e.value),
  };
  const data = await api("/api/quick/export", { method: "POST", body });
  const json = JSON.stringify(data, null, 2);
  if (mode === "clipboard") {
    try { await navigator.clipboard.writeText(json); }
    catch (_) { return toast("Clipboard unavailable, use Download File"); }
  } else {
    const blob = new Blob([json], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `quick-commands-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
  closeModal($("#modal-q-export"));
}

let qImportData = null;
function openQuickImportModal() {
  qImportData = null;
  $("#qimp-preview").classList.add("hidden");
  $("#qimp-groups").innerHTML = "";
  $("#qimp-commands").innerHTML = "";
  openModal($("#modal-q-import"));
}

function loadQuickImportText(text) {
  let data;
  try { data = JSON.parse(text); } catch (_) { return toast("Invalid JSON"); }
  if (!data || !Array.isArray(data.commands)) return toast("Format: {groups, commands}");
  qImportData = data;
  renderQuickImportPreview(data);
}

function renderQuickImportPreview(data) {
  const gb = $("#qimp-groups"); gb.innerHTML = "";
  (data.groups || []).forEach((g, i) => {
    if (!g || !g.name) return;
    const l = document.createElement("label"); l.className = "exp-item";
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = true; cb.dataset.idx = i;
    const nm = document.createElement("span"); nm.textContent = g.name;
    l.append(cb, nm); gb.append(l);
  });
  const cbox = $("#qimp-commands"); cbox.innerHTML = "";
  (data.commands || []).forEach((c, i) => {
    if (!c || !c.name) return;
    const l = document.createElement("label"); l.className = "exp-item";
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = true; cb.dataset.idx = i;
    const nm = document.createElement("span"); nm.textContent = c.name;
    l.append(cb, nm); cbox.append(l);
  });
  $("#qimp-preview").classList.remove("hidden");
}

async function confirmQuickImport() {
  if (!qImportData) return;
  const groups = (qImportData.groups || []).filter((_, i) =>
    document.querySelector(`#qimp-groups input[data-idx="${i}"]`)?.checked !== false);
  const commands = (qImportData.commands || []).filter((_, i) =>
    document.querySelector(`#qimp-commands input[data-idx="${i}"]`)?.checked !== false);
  await api("/api/quick/import", { method: "POST", body: { groups, commands } });
  closeModal($("#modal-q-import"));
  await loadQuick();
}
