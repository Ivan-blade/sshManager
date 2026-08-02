/* sshManager — 多标签终端 + WebSocket 流（从 app.js 拆分） */

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
    close.title = "Close tab only (SSH keeps running)";
    close.textContent = "✕";
    close.addEventListener("click", (e) => { e.stopPropagation(); closeTab(t.key); });
    const power = document.createElement("button");
    power.className = "t-btn t-power";
    power.title = "Disconnect SSH & close";
    power.textContent = "⏻";
    power.addEventListener("click", (e) => { e.stopPropagation(); closeWithDisconnect(t.key); });
    actions.append(close, power);

    el.append(dot, nm, actions);
    el.addEventListener("click", () => activateTab(t.key));
    el.addEventListener("contextmenu", (e) => {
      e.preventDefault(); e.stopPropagation();
      showCtx(e.clientX, e.clientY, [
        { label: "Rename Tab", action: "renameTab" },
        { label: "Disconnect & Close", onSelect: () => closeWithDisconnect(t.key) },
        { label: "Close tab only (SSH keeps running)", onSelect: () => { closeTab(t.key); refreshStatuses(); } },
      ]);
      state.ctxTarget = { type: "tab", key: t.key };
    });
    box.append(el);
  }
}

function openSession(sid) {
  // 双击：始终新建独立连接（恢复后台连接走 ◔ Background 面板 / 右键 Restore background）。
  // 注意：非激活 tab 的连接无 ws reader，会被 status 当成后台连接——若双击去"恢复"会造成
  // 同一个 SSH 出现在两个窗口。所以双击一律新建，不恢复。
  const s = sessionById(sid);
  if (!s) return;
  openTab(sid, null, "new");
}

function openTab(sid, connId, mode, labelOverride) {
  const s = sessionById(sid);
  if (!s) return;
  state.tabKey += 1;
  const key = state.tabKey;
  // labelOverride：恢复时带上服务端 label（可能跨启动）；与会话名相同则不视为自定义
  if (labelOverride && labelOverride !== s.name) state.connLabels[connId] = labelOverride;
  const label = (connId && state.connLabels[connId]) || s.name;
  const custom = !!(labelOverride && labelOverride !== s.name) || !!(connId && state.connLabels[connId]);
  state.tabs.push({ key, sid, name: label, connId, mode, custom });
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
  // SFTP 面板跟随活动 tab 的会话
  if (!$("#sftp-panel").classList.contains("hidden")) {
    const sid = activeSid();
    if (sid && sid !== state.sftpSid) openSftp(sid);
  }
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
    theme: currentXtermTheme(),
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
  // 已有 connId 就复用（切回 tab 不新建连接，避免后台数量堆积）；没有才新建
  const path = tab.connId ? `/ws/connection/${tab.connId}` : `/ws/terminal/${id}`;
  const ws = new WebSocket(`${proto}://${location.host}${path}`);
  state.ws = ws;
  ws.onopen = () => {
    if (state.term && activeSid() === id) {
      ws.send(JSON.stringify({ type: "resize", cols: state.term.cols, rows: state.term.rows }));
    }
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "status" && msg.conn_id) {
      tab.connId = msg.conn_id; // 记住 conn_id（断开/恢复用）
      if (tab.custom && tab.name) state.connLabels[tab.connId] = tab.name; // 自定义标签关联到连接
    }
    if (msg.type === "status" && msg.state === "error" && tab.connId) {
      // 连接已失效（如曾被断开）→ 退回新建连接
      tab.connId = null;
      try { ws.close(); } catch (_) {}
      connectWs(key);
      return;
    }
    if (!state.term || activeSid() !== id) return;
    if (msg.type === "output" || msg.type === "buffer") state.term.write(msg.data || "");
    else if (msg.type === "status") {
      const on = msg.state === "connected";
      setStatus(id, on ? "on" : "off", on ? "Running" : "Offline");
      renderTabs();
    }
  };
  ws.onclose = () => {
    if (activeSid() === id) renderTabs();
    refreshStatuses();
  };
  ws.onerror = () => { if (activeSid() === id) setStatus(id, "off", "Error"); };
}
