/* sshManager — SFTP 文件面板（从 app.js 拆分） */

async function openSftp(sid) {
  if (state.sftpSid !== sid) { state.sftpSid = sid; state.sftpPath = "."; }
  $("#sftp-panel").classList.remove("hidden");
  const s = sessionById(sid);
  $("#sftp-name").textContent = s ? s.name : "";
  await loadSftp();
}

function closeSftp() {
  $("#sftp-panel").classList.add("hidden");
  state.sftpSid = null;
}

function parentPath(p) {
  if (!p || p === ".") return ".";
  if (p === "/") return "/";
  const parts = p.split("/").filter(Boolean);
  parts.pop();
  return parts.length ? "/" + parts.join("/") : "/";
}

function fmtSize(n) {
  if (n == null) return "";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

async function loadSftp() {
  if (!state.sftpSid) return;
  const list = $("#sftp-list");
  list.innerHTML = '<div class="sftp-loading">Loading…</div>';
  $("#sftp-path").value = state.sftpPath;
  let entries = [];
  try {
    entries = await api(`/api/sessions/${state.sftpSid}/sftp/ls?path=${encodeURIComponent(state.sftpPath)}`);
  } catch (e) { list.innerHTML = `<div class="sftp-empty">Load failed: ${e.message}</div>`; return; }
  list.innerHTML = "";
  if (!entries.length) { list.innerHTML = '<div class="sftp-empty">(empty)</div>'; return; }
  for (const e of entries) {
    const row = document.createElement("div");
    row.className = "sftp-item" + (e.is_dir ? " dir" : "");
    const icon = document.createElement("span");
    icon.className = "sftp-icon"; icon.textContent = e.is_dir ? "▸" : "·";
    const nm = document.createElement("span");
    nm.className = "sftp-name"; nm.textContent = e.name;
    const sz = document.createElement("span");
    sz.className = "sftp-size"; sz.textContent = e.is_dir ? "" : fmtSize(e.size);
    row.append(icon, nm, sz);
    if (e.is_dir) {
      row.addEventListener("dblclick", () => { state.sftpPath = e.path; loadSftp(); });
    } else {
      row.addEventListener("dblclick", () => downloadSftp(e.path)); // 双击文件下载
    }
    row.addEventListener("contextmenu", (ev) => {
      ev.preventDefault();
      ev.stopPropagation(); // 关键：阻止全局 contextmenu 处理器关掉刚弹出的菜单
      if (e.is_dir) {
        showCtx(ev.clientX, ev.clientY, [
          { label: "Open", onSelect: () => { state.sftpPath = e.path; loadSftp(); } },
          { label: "Delete", onSelect: () => deleteSftp(e.path), danger: true },
        ]);
      } else {
        showFileMenu(ev, e.path);
      }
    });
    list.append(row);
  }
}

function downloadSftp(path) {
  // 用隐藏 <a download> 触发下载，避免 window.open 在 Electron 里开空白窗口
  const a = document.createElement("a");
  a.href = `/api/sessions/${state.sftpSid}/sftp/download?path=${encodeURIComponent(path)}`;
  a.download = path.split("/").pop() || "download";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

async function uploadSftp(file) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("target_dir", state.sftpPath);
  const resp = await fetch(`/api/sessions/${state.sftpSid}/sftp/upload`, { method: "POST", body: fd });
  if (!resp.ok) { const d = await resp.json().catch(() => ({})); toast("Upload failed: " + (d.detail || resp.status)); return; }
  await loadSftp();
}

function showFileMenu(e, path) {
  const name = path.split("/").pop();
  showCtx(e.clientX, e.clientY, [
    { label: "Download", onSelect: () => downloadSftp(path) },
    { label: "Edit", onSelect: () => editSftpFile(path, name) },
    { label: "Delete", onSelect: () => deleteSftp(path), danger: true },
  ]);
}

async function deleteSftp(path) {
  try {
    await api(`/api/sessions/${state.sftpSid}/sftp/delete`, { method: "POST", body: { path } });
  } catch (e) { return toast("Delete failed: " + e.message); }
  await loadSftp();
}

async function editSftpFile(path, name) {
  try {
    const resp = await fetch(`/api/sessions/${state.sftpSid}/sftp/download?path=${encodeURIComponent(path)}`);
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const text = await resp.text();
    $("#fe-name").textContent = name;
    $("#fe-path").textContent = path;
    $("#fe-text").value = text;
    openModal($("#modal-file-edit"));
  } catch (err) { toast("Read failed: " + err.message); }
}

async function saveSftpFile() {
  const path = $("#fe-path").textContent;
  const content = $("#fe-text").value;
  const name = path.split("/").pop();
  const dir = path.slice(0, path.lastIndexOf("/")) || ".";
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const fd = new FormData();
  fd.append("file", blob, name);
  fd.append("target_dir", dir);
  const resp = await fetch(`/api/sessions/${state.sftpSid}/sftp/upload`, { method: "POST", body: fd });
  if (!resp.ok) { const d = await resp.json().catch(() => ({})); toast("Save failed: " + (d.detail || resp.status)); return; }
  closeModal($("#modal-file-edit"));
  await loadSftp();
}

async function sftpSearch() {
  const q = $("#sftp-search").value.trim();
  if (!state.sftpSid) return;
  if (!q) { loadSftp(); return; }
  const list = $("#sftp-list");
  list.innerHTML = '<div class="sftp-loading">Searching…</div>';
  let r;
  try {
    // ftype=all：文件和目录都搜；条目带 is_dir
    r = await api(`/api/sessions/${state.sftpSid}/find`, { method: "POST", body: { path: state.sftpPath, pattern: q, ftype: "all" } });
  } catch (err) { list.innerHTML = `<div class="sftp-empty">Search failed: ${err.message}</div>`; return; }
  list.innerHTML = "";
  const entries = (r.entries && r.entries.length)
    ? r.entries
    : (r.results || []).map((p) => ({ path: p, is_dir: false }));
  if (!entries.length) { list.innerHTML = '<div class="sftp-empty">(no match)</div>'; return; }
  for (const en of entries) {
    const p = en.path;
    const row = document.createElement("div");
    row.className = "sftp-item" + (en.is_dir ? " dir" : "");
    const icon = document.createElement("span"); icon.className = "sftp-icon"; icon.textContent = en.is_dir ? "▸" : "·";
    const nm = document.createElement("span"); nm.className = "sftp-name"; nm.textContent = p;
    row.append(icon, nm);
    row.addEventListener("click", () => {
      $("#sftp-search").value = "";
      if (en.is_dir) state.sftpPath = p; // 文件夹 → 进入
      else state.sftpPath = p.lastIndexOf("/") > 0 ? p.slice(0, p.lastIndexOf("/")) : "."; // 文件 → 父目录
      loadSftp();
    });
    row.addEventListener("contextmenu", (ev) => { ev.preventDefault(); ev.stopPropagation(); showFileMenu(ev, p); });
    list.append(row);
  }
}
