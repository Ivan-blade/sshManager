/* sshManager — 会话/分组树（从 app.js 拆分） */

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
    empty.textContent = state.filter ? "No matching sessions" : "No sessions yet, click + Session";
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
      { label: "New session here", action: "newInGroup" },
      { label: "Rename group", action: "renameGroup" },
      { label: "Delete group", action: "deleteGroup", danger: true },
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
  st.innerHTML = '<span class="sdot"></span><span class="stext">Offline</span>';
  // 重建列表时从已知状态初始化，避免单击选中触发 renderTree 后闪成「离线」
  const _bgN = (state.bg[s.id] || []).length;
  if (_bgN > 0) { st.className = "sess-status bg"; st.querySelector(".stext").textContent = `Background ×${_bgN}`; }
  else if (state.statuses[s.id] === "on") { st.className = "sess-status on"; st.querySelector(".stext").textContent = "Running"; }
  const meta = document.createElement("span");
  meta.className = "sess-meta";
  const name = document.createElement("div");
  name.className = "sess-name";
  name.textContent = s.name;
  const host = document.createElement("div");
  host.className = "sess-host";
  host.textContent = s.transport === "local"
    ? "local · Local Shell"
    : `${s.username}@${s.host}:${s.port}`;
  meta.append(name, host);

  li.addEventListener("click", () => selectSession(s.id));           // 单击选中
  li.addEventListener("dblclick", () => openSession(s.id));          // 双击：有后台则恢复，否则新建
  li.addEventListener("contextmenu", (e) => {
    e.preventDefault(); e.stopPropagation();
    const bg = state.bg[s.id] || [];
    const items = [
      { label: "Open", action: "open" },
    ];
    if (bg.length) {
      items.push(
        { label: "Restore background", action: "restoreBg" },
        { label: "Disconnect background", action: "disconnectBg" },
      );
    }
    items.push(
      { label: "Open new connection", action: "openNew" },
      { label: "Move to group…", action: "move" },
      { label: "Rename", action: "renameSession" },
      { label: "Delete", action: "deleteSession", danger: true },
    );
    showCtx(e.clientX, e.clientY, items);
    state.ctxTarget = { type: "session", id: s.id, name: s.name };
  });

  // hover 操作按钮：编辑 / 删除
  const act = document.createElement("span");
  act.className = "sess-actions";
  const editBtn = document.createElement("button");
  editBtn.className = "icon-btn small icon-edit"; editBtn.title = "Edit session";
  editBtn.textContent = "✎";
  editBtn.addEventListener("click", (e) => { e.stopPropagation(); openEditModal(s.id); });
  const delBtn = document.createElement("button");
  delBtn.className = "icon-btn small danger"; delBtn.title = "Delete session";
  delBtn.textContent = "✕";
  delBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    await api(`/api/sessions/${s.id}`, { method: "DELETE" });
    const tab = state.tabs.find((x) => x.sid === s.id);
    if (tab) closeTab(tab.key);
    await loadAll();
    refreshStatuses();
  });
  act.append(editBtn, delBtn);

  li.append(st, meta, act);
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
  if (txt) txt.textContent = text || (cls === "on" ? "Running" : cls === "bg" ? "Background" : "Offline");
}

async function refreshStatuses() {
  for (const s of state.sessions) {
    try {
      const st = await api(`/api/sessions/${s.id}/status`);
      state.bg[s.id] = st.background_conns || [];
      if (state.bg[s.id].length) setStatus(s.id, "bg", `Background ×${state.bg[s.id].length}`);
      else if (st.connected) setStatus(s.id, "on", "Running");
      else setStatus(s.id, "off", "Offline");
    } catch (_) { setStatus(s.id, "off", "Offline"); }
  }
  refreshBgCount();
}
