/* sshManager — 事件绑定 + 启动（从 app.js 拆分；最后一个加载，勿在它之前引用） */

let filterTimer = null;
$("#filter").addEventListener("input", () => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => {
    state.filter = $("#filter").value;
    renderTree();
  }, 180);
});

$("#btn-new").addEventListener("click", openNewModal);
$("#empty-new").addEventListener("click", openNewModal);
$("#btn-add-group").addEventListener("click", () => promptModal("New group", "", (v) => createGroup(v)));
$("#quick-group-btn").addEventListener("click", toggleQuickGroupMenu);
document.addEventListener("click", (e) => {
  if (!e.target.closest("#quick-group-menu") && !e.target.closest("#quick-group-btn")) hideQuickMenu();
});
$("#qexp-groups-all").addEventListener("click", () => toggleAllExport("#qexp-groups"));
$("#qexp-commands-all").addEventListener("click", () => toggleAllExport("#qexp-commands"));
$("#qexp-clipboard").addEventListener("click", () => doQuickExport("clipboard"));
$("#qexp-file").addEventListener("click", () => doQuickExport("file"));
$("#qimp-clipboard").addEventListener("click", async () => {
  let text;
  try { text = await navigator.clipboard.readText(); } catch (_) { return toast("Clipboard unavailable"); }
  loadQuickImportText(text);
});
$("#qimp-file").addEventListener("click", () => $("#qimp-file-input").click());
$("#qimp-file-input").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (f) { const rd = new FileReader(); rd.onload = () => loadQuickImportText(rd.result); rd.readAsText(f); }
  e.target.value = "";
});
$("#qimp-drop").addEventListener("dragover", (e) => { e.preventDefault(); $("#qimp-drop").classList.add("dragging"); });
$("#qimp-drop").addEventListener("dragleave", () => $("#qimp-drop").classList.remove("dragging"));
$("#qimp-drop").addEventListener("drop", (e) => {
  e.preventDefault();
  $("#qimp-drop").classList.remove("dragging");
  const f = e.dataTransfer.files[0];
  if (f) { const rd = new FileReader(); rd.onload = () => loadQuickImportText(rd.result); rd.readAsText(f); }
});
$("#qimp-confirm").addEventListener("click", confirmQuickImport);
$("#qimp-cancel").addEventListener("click", () => closeModal($("#modal-q-import")));
$("#qc-ok").addEventListener("click", submitQuickCmd);
$("#qc-command").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submitQuickCmd(); });
$("#tab-sftp").addEventListener("click", () => {
  const sid = activeSid();
  if (!sid) return toast("Open a terminal first");
  // 重复点击切换 SFTP 侧栏开关
  if ($("#sftp-panel").classList.contains("hidden")) openSftp(sid);
  else closeSftp();
});
$("#sftp-close").addEventListener("click", closeSftp);
$("#sftp-up").addEventListener("click", () => { state.sftpPath = parentPath(state.sftpPath); loadSftp(); });
$("#sftp-go").addEventListener("click", () => { state.sftpPath = $("#sftp-path").value || "."; loadSftp(); });
$("#sftp-path").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#sftp-go").click(); });
$("#sftp-search-btn").addEventListener("click", sftpSearch);
$("#sftp-search").addEventListener("keydown", (e) => { if (e.key === "Enter") sftpSearch(); });
$("#fe-save").addEventListener("click", saveSftpFile);
$("#sftp-upload").addEventListener("click", () => $("#sftp-file-input").click());
$("#sftp-file-input").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (f) uploadSftp(f);
  e.target.value = "";
});
// 拖拽上传到当前目录
const _sftpList = $("#sftp-list");
_sftpList.addEventListener("dragover", (e) => { e.preventDefault(); _sftpList.classList.add("dragging"); });
_sftpList.addEventListener("dragleave", () => _sftpList.classList.remove("dragging"));
_sftpList.addEventListener("drop", (e) => {
  e.preventDefault();
  _sftpList.classList.remove("dragging");
  for (const f of e.dataTransfer.files) uploadSftp(f);
});
$("#btn-bg").addEventListener("click", (e) => { e.stopPropagation(); toggleBgPanel(); });
document.addEventListener("click", (e) => {
  if (!e.target.closest("#bg-panel") && !e.target.closest("#btn-bg")) hideBgPanel();
});
$("#n-transport").addEventListener("change", toggleNewFields);
$("#n-auth").addEventListener("change", toggleAuth);
$("#n-submit").addEventListener("click", submitNew);
$("#n-name").addEventListener("keydown", (e) => { if (e.key === "Enter") submitNew(); });

$("#btn-export").addEventListener("click", openExportModal);
$("#btn-q-export").addEventListener("click", openQuickExportModal);
$("#btn-q-import").addEventListener("click", openQuickImportModal);
$("#exp-clipboard").addEventListener("click", () => doExport("clipboard"));
$("#exp-file").addEventListener("click", () => doExport("file"));
$("#exp-groups-all").addEventListener("click", () => toggleAllExport("#exp-groups"));
$("#exp-sessions-all").addEventListener("click", () => toggleAllExport("#exp-sessions"));
$("#btn-import").addEventListener("click", openImportModal);
$("#i-clipboard").addEventListener("click", async () => {
  let text;
  try { text = await navigator.clipboard.readText(); } catch (_) { return toast("Cannot read clipboard (browser permission)"); }
  loadImportText(text);
});
$("#i-file").addEventListener("click", () => $("#i-file-input").click());
$("#i-file-input").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (f) { const rd = new FileReader(); rd.onload = () => loadImportText(rd.result); rd.readAsText(f); }
  e.target.value = "";
});
$("#i-drop").addEventListener("dragover", (e) => { e.preventDefault(); $("#i-drop").classList.add("dragging"); });
$("#i-drop").addEventListener("dragleave", () => $("#i-drop").classList.remove("dragging"));
$("#i-drop").addEventListener("drop", (e) => {
  e.preventDefault();
  $("#i-drop").classList.remove("dragging");
  const f = e.dataTransfer.files[0];
  if (f) { const rd = new FileReader(); rd.onload = () => loadImportText(rd.result); rd.readAsText(f); }
});
$("#i-confirm").addEventListener("click", confirmImport);
$("#i-cancel").addEventListener("click", () => closeModal($("#modal-import")));

// ---- 主题切换（暗/亮）----
$("#btn-theme").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  applyTheme(cur === "dark" ? "light" : "dark");
});

// 启动（默认白天；用户切过才记住）
applyTheme(localStorage.getItem("sshmgr-theme") === "dark" ? "dark" : "light");
loadAll();
loadQuick();
setInterval(refreshStatuses, 10000);
