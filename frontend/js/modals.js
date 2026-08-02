/* sshManager — 新建/编辑会话、导入/导出、分组（从 app.js 拆分） */

function populateGroupSelect() {
  const sel = $("#n-group");
  const keep = sel.value;
  sel.innerHTML = '<option value="">No Group</option>';
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
  if (!name) return toast("Name is required");
  const isSsh = $("#n-transport").value === "ssh";
  const body = {
    name,
    transport: $("#n-transport").value,
    group_id: $("#n-group").value || null,
    description: $("#n-desc").value.trim() || undefined,
  };
  if (isSsh) {
    Object.assign(body, {
      host: $("#n-host").value.trim() || "localhost",
      port: parseInt($("#n-port").value, 10) || 22,
      username: $("#n-user").value.trim() || "root",
      auth_type: $("#n-auth").value,
    });
    if (state.editingSid) {
      // 编辑：密码/密钥留空表示不修改
      if ($("#n-auth").value === "password") { if ($("#n-password").value) body.password = $("#n-password").value; }
      else { if ($("#n-key").value.trim()) body.key_path = $("#n-key").value.trim(); }
    } else {
      body.password = $("#n-auth").value === "password" ? $("#n-password").value : undefined;
      body.key_path = $("#n-auth").value === "key" ? $("#n-key").value.trim() : undefined;
    }
  }
  if (state.editingSid) {
    await api(`/api/sessions/${state.editingSid}`, { method: "PATCH", body });
    state.tabs.forEach((tb) => { if (tb.sid === state.editingSid) tb.name = name; });
  } else {
    await api("/api/sessions", { method: "POST", body });
  }
  state.editingSid = null;
  closeModal($("#modal-new"));
  await loadAll();
  renderTabs();
}

function openNewModal() {
  state.editingSid = null;
  $("#n-title").textContent = "New Session";
  $("#n-submit").textContent = "Create";
  populateGroupSelect();
  toggleNewFields();
  ["#n-name", "#n-desc", "#n-password", "#n-key"].forEach((s) => $(s).value = "");
  $("#n-host").value = "localhost";
  $("#n-port").value = "22";
  $("#n-user").value = "root";
  $("#n-auth").value = "password";
  $("#n-group").value = "";
  openModal($("#modal-new"));
  $("#n-name").focus();
}

function openEditModal(sid) {
  const s = sessionById(sid);
  if (!s) return;
  state.editingSid = sid;
  $("#n-title").textContent = "Edit Session";
  $("#n-submit").textContent = "Save";
  populateGroupSelect();
  $("#n-name").value = s.name || "";
  $("#n-desc").value = s.description || "";
  $("#n-group").value = s.group_id || "";
  $("#n-transport").value = s.transport || "ssh";
  if (s.transport === "ssh") {
    $("#n-host").value = s.host || "localhost";
    $("#n-port").value = s.port || 22;
    $("#n-user").value = s.username || "root";
    $("#n-auth").value = s.auth_type || "password";
    $("#n-password").value = "";
    $("#n-key").value = s.key_path || "";
  }
  toggleNewFields();
  openModal($("#modal-new"));
  $("#n-name").focus();
}

// 分组
async function createGroup(name) {
  if (!name) return;
  await api("/api/groups", { method: "POST", body: { name } });
  await loadAll();
}

// 导出弹窗（选分组/会话 → 剪贴板或文件）
function openExportModal() {
  renderExportList("#exp-groups", state.groups, "group_ids");
  renderExportList("#exp-sessions", state.sessions, "session_ids");
  openModal($("#modal-export"));
}

function renderExportList(sel, items, type) {
  const box = $(sel);
  box.innerHTML = "";
  if (!items.length) {
    box.innerHTML = '<div class="exp-empty">(none)</div>';
    return;
  }
  for (const it of items) {
    const label = document.createElement("label");
    label.className = "exp-item";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = it.id;
    cb.checked = true;
    label.append(cb);
    const nm = document.createElement("span");
    nm.textContent = it.name;
    label.append(nm);
    if (type === "session_ids") {
      const hs = document.createElement("span");
      hs.className = "exp-host";
      hs.textContent = it.host || it.transport;
      label.append(hs);
    }
    box.append(label);
  }
}

function toggleAllExport(sel) {
  const cbs = document.querySelectorAll(`${sel} input[type=checkbox]`);
  const allOn = [...cbs].every((c) => c.checked);
  cbs.forEach((c) => { c.checked = !allOn; });
}

async function doExport(mode) {
  const body = {
    group_ids: [...document.querySelectorAll("#exp-groups input:checked")].map((e) => e.value),
    session_ids: [...document.querySelectorAll("#exp-sessions input:checked")].map((e) => e.value),
  };
  const data = await api("/api/export", { method: "POST", body });
  const json = JSON.stringify(data, null, 2);
  if (mode === "clipboard") {
    try { await navigator.clipboard.writeText(json); }
    catch (_) { return toast("Clipboard unavailable, use Download File"); }
  } else {
    const blob = new Blob([json], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `sshmanager-export-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
  closeModal($("#modal-export"));
}

// ---- 导入：拖拽/选择/剪贴板 → 预览列表 → 确定导入（不弹提示）----
let importData = null;

function openImportModal() {
  importData = null;
  $("#i-preview").classList.add("hidden");
  $("#i-groups").innerHTML = "";
  $("#i-sessions").innerHTML = "";
  openModal($("#modal-import"));
}

function parseImport(text) {
  if (!text || !text.trim()) return { error: "Empty content" };
  let data;
  try { data = JSON.parse(text); } catch (_) { return { error: "Invalid JSON" }; }
  if (!data || !Array.isArray(data.sessions)) return { error: "Invalid format: expected {groups, sessions}" };
  return { data: { groups: data.groups || [], sessions: data.sessions } };
}

function showImportPreview(data) {
  importData = data;
  const gbox = $("#i-groups");
  gbox.innerHTML = "";
  data.groups.forEach((g, i) => {
    if (!g || !g.name) return;
    const label = document.createElement("label");
    label.className = "exp-item";
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = true; cb.dataset.idx = i;
    const nm = document.createElement("span"); nm.textContent = g.name;
    label.append(cb, nm);
    gbox.append(label);
  });
  const sbox = $("#i-sessions");
  sbox.innerHTML = "";
  data.sessions.forEach((s, i) => {
    if (!s || !s.name) return;
    const label = document.createElement("label");
    label.className = "exp-item";
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = true; cb.dataset.idx = i;
    const nm = document.createElement("span"); nm.textContent = s.name;
    const hs = document.createElement("span"); hs.className = "exp-host"; hs.textContent = s.host || s.transport || "";
    label.append(cb, nm, hs);
    sbox.append(label);
  });
  $("#i-preview").classList.remove("hidden");
}

function loadImportText(text) {
  const r = parseImport(text);
  if (r.error) { toast(r.error); return; }
  showImportPreview(r.data);
}

async function confirmImport() {
  if (!importData) return;
  const groups = importData.groups.filter((_, i) =>
    document.querySelector(`#i-groups input[data-idx="${i}"]`)?.checked !== false);
  const sessions = importData.sessions.filter((_, i) =>
    document.querySelector(`#i-sessions input[data-idx="${i}"]`)?.checked !== false);
  await api("/api/import", { method: "POST", body: { groups, sessions } });
  closeModal($("#modal-import"));
  await loadAll();
  // 不弹提示
}
