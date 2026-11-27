"use strict";
// Fichiers: one page for what the app does to files under the storage roots (ADR-0029).
// The panel has no network access; it asks this host, which forwards only /api/files/.
const filesFrame = document.createElement("iframe");
filesFrame.id = "files-frame";
filesFrame.title = "Fichiers";
lazyFrame(filesFrame, "static/files/view.html");
filesFrame.style.cssText = "width:100%;border:0;display:block";
$("view-files").append(filesFrame);
function filesEnvironment() {
  filesFrame.contentWindow?.postMessage({ type: "files-environment", value: { active: !$("view-files").hidden } }, location.origin);
}
window.addEventListener("message", async (e) => {
  if (e.source !== filesFrame.contentWindow || e.origin !== location.origin) return;
  const m = e.data;
  if (m?.type === "files-ready") { filesEnvironment(); return; }
  if (m?.type !== "files-request") return;
  const allowed = /^(disks|disks\/placement|trash|trash\/empty|trash\/retention|trash\/[0-9a-f]{12}\/restore|journal|journal\/[0-9a-f]{32}\/undo)$/;
  try {
    if ($("workspace").hidden) throw Error("Sign in first.");
    if (!allowed.test(m.path)) throw Error("Unknown file action.");
    const value = await api(`files/${m.path}`, m.body);
    filesFrame.contentWindow.postMessage({ type: "files-response", id: m.id, value }, location.origin);
  } catch (error) {
    filesFrame.contentWindow.postMessage({ type: "files-response", id: m.id, error: error.message }, location.origin);
  }
});
new MutationObserver(filesEnvironment).observe($("view-files"), { attributes: true, attributeFilter: ["hidden"] });
