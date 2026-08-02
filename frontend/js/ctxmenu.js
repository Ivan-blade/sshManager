/* sshManager — 右键菜单（从 app.js 拆分） */

const ctxEl = $("#ctxmenu");

let subMenus = [];

function removeSubMenus() {
  for (const s of subMenus) s.remove();
  subMenus = [];
}

function buildCtxItem(container, it) {
  if (it === "sep") {
    const sep = document.createElement("div");
    sep.className = "ctx-sep";
    container.append(sep);
    return;
  }
  const b = document.createElement("button");
  if (it.danger) b.className = "danger";

  if (it.submenu) {
    // 二级子菜单：hover 显示右侧飞出
    const txt = document.createElement("span");
    txt.textContent = it.label;
    const caret = document.createElement("span");
    caret.className = "ctx-caret"; caret.textContent = "▸";
    b.append(txt, caret);
    const sub = document.createElement("div");
    sub.className = "ctxmenu ctx-sub";
    sub.style.display = "none";
    for (const si of it.submenu) buildCtxItem(sub, si);
    document.body.append(sub);
    subMenus.push(sub);

    const show = () => {
      sub.style.display = "block";
      const br = b.getBoundingClientRect();
      const sw = sub.offsetWidth || 170;
      const left = (br.right + 4 + sw > window.innerWidth) ? br.left - sw - 4 : br.right + 4;
      sub.style.left = left + "px";
      sub.style.top = br.top + "px";
    };
    const maybeHide = () => {
      setTimeout(() => {
        if (!sub.matches(":hover") && !b.matches(":hover")) sub.style.display = "none";
      }, 120);
    };
    b.addEventListener("mouseenter", show);
    b.addEventListener("mouseleave", maybeHide);
    sub.addEventListener("mouseleave", maybeHide);
  } else {
    b.textContent = it.label;
    b.addEventListener("click", () => {
      hideCtx();
      if (it.onSelect) it.onSelect();
      else runCtxAction(it.action);
    });
  }
  container.append(b);
}

function showCtx(x, y, items) {
  removeSubMenus();
  ctxEl.innerHTML = "";
  for (const it of items) buildCtxItem(ctxEl, it);
  ctxEl.classList.remove("hidden");
  const rect = ctxEl.getBoundingClientRect();
  ctxEl.style.left = Math.min(x, window.innerWidth - rect.width - 8) + "px";
  ctxEl.style.top = Math.min(y, window.innerHeight - rect.height - 8) + "px";
}

function hideCtx() {
  ctxEl.classList.add("hidden");
  removeSubMenus();
}

async function closeWithDisconnect(key) {
  const tab = state.tabs.find((t) => t.key === key);
  if (tab && tab.connId) {
    delete state.connLabels[tab.connId];
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
  else if (action === "renameTab" && t.type === "tab") {
    const tab = state.tabs.find((x) => x.key === t.key);
    if (!tab) return;
    promptModal("Rename Tab", tab.name, (v) => {
      if (!v) return;
      tab.name = v;
      tab.custom = true;
      if (tab.connId) {
        state.connLabels[tab.connId] = v;
        // 持久化到服务端 ts.label（与 AI connect 的 label 共用同一字段）
        api(`/api/connections/${tab.connId}/label`, { method: "PATCH", body: { label: v } }).catch(() => {});
      }
      renderTabs();
    });
  }
  else if (action === "restoreBg" && t.type === "session") {
    const bg = state.bg[t.id] || [];
    if (bg.length) openTab(t.id, bg[0], "restore");
  }
  else if (action === "openNew" && t.type === "session") openTab(t.id, null, "new");
  else if (action === "disconnectBg" && t.type === "session") {
    const bg = state.bg[t.id] || [];
    for (const conn of bg) {
      delete state.connLabels[conn];
      try { await api(`/api/connections/${conn}/disconnect`, { method: "POST" }); } catch (_) {}
    }
    state.bg[t.id] = [];
    await loadAll();
    refreshStatuses();
  }
  else if (action === "renameGroup") promptModal("Rename group", t.name, async (v) => {
    if (v) { await api(`/api/groups/${t.id}`, { method: "PATCH", body: { name: v } }); await loadAll(); }
  });
  else if (action === "renameSession") promptModal("Rename session", t.name, async (v) => {
    if (v) {
      await api(`/api/sessions/${t.id}`, { method: "PATCH", body: { name: v } });
      state.tabs.forEach((tb) => { if (tb.sid === t.id) tb.name = v; });
      await loadAll(); renderTabs();
    }
  });
  else if (action === "deleteSession" && t.type === "session") {
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
    if (!confirm(`Delete group "${t.name}"? Sessions will return to root.`)) return;
    await api(`/api/groups/${t.id}`, { method: "DELETE" });
    await loadAll();
  }
  else if (action === "quickRenameGroup" && t.type === "quickGroup") promptModal("Rename group", t.name, async (v) => {
    if (v) { await api(`/api/quick/groups/${t.id}`, { method: "PATCH", body: { name: v } }); await loadQuick(); }
  });
  else if (action === "quickDeleteGroup" && t.type === "quickGroup") {
    await api(`/api/quick/groups/${t.id}`, { method: "DELETE" });
    if (state.quickActiveGroup === t.id) state.quickActiveGroup = null;
    await loadQuick();
  }
  else if (action === "quickEditCmd" && t.type === "quickCmd") {
    const cmd = state.quickCommands.find((x) => x.id === t.id);
    if (cmd) openQuickCmdModal(cmd);
  }
  else if (action === "quickDeleteCmd" && t.type === "quickCmd") {
    await api(`/api/quick/commands/${t.id}`, { method: "DELETE" });
    await loadQuick();
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
