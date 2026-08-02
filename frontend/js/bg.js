/* sshManager — 后台连接面板（从 app.js 拆分） */

async function refreshBgCount() {
  try {
    const bg = await api("/api/connections/background");
    $("#bg-count").textContent = bg.length;
    state.bgNames = {};
    for (const c of bg) state.bgNames[c.conn_id] = c.name; // 记住服务端显示名，供双击恢复
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
    list.innerHTML = '<div class="bg-empty">No background connections</div>';
    return;
  }
  for (const c of bg) {
    const row = document.createElement("div");
    row.className = "bg-item";
    const info = document.createElement("span");
    info.className = "bg-info";
    const nm = document.createElement("span");
    nm.className = "bg-name"; nm.textContent = state.connLabels[c.conn_id] || c.name;
    const hs = document.createElement("span");
    hs.className = "bg-host"; hs.textContent = c.host || c.transport || "";
    info.append(nm, hs);
    const res = document.createElement("button");
    res.className = "btn small"; res.textContent = "Restore";
    res.addEventListener("click", (e) => { e.stopPropagation(); openTab(c.sid, c.conn_id, "restore", c.name); hideBgPanel(); });
    const disc = document.createElement("button");
    disc.className = "btn small danger"; disc.textContent = "Disconnect";
    disc.addEventListener("click", async (e) => {
      e.stopPropagation();
      try { await api(`/api/connections/${c.conn_id}/disconnect`, { method: "POST" }); } catch (_) {}
      await renderBgPanel();
      refreshStatuses();
    });
    row.append(info, res, disc);
    row.title = "Click to restore";
    row.addEventListener("click", () => { openTab(c.sid, c.conn_id, "restore"); hideBgPanel(); }); // 整行可点恢复
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
