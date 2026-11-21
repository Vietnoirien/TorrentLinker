"use strict";
function offerCrashReport(draft) {
  if (signedInMember() || !draft?.url?.startsWith("https://github.com/Vietnoirien/TorrentLinker/issues/new?")) return;
  document.getElementById("crash-report-preview")?.remove();
  const dialog = document.createElement("dialog"); dialog.id = "crash-report-preview";
  const title = element("h2", say("Report the problem", "Signaler le problème"));
  const help = element("p", say("Review this sanitized draft. Nothing is sent automatically; you can edit it on GitHub before submitting.", "Relisez ce brouillon nettoyé. Rien n’est envoyé automatiquement ; vous pourrez le modifier sur GitHub avant de le publier."));
  const preview = element("textarea"); preview.value = draft.body; preview.readOnly = true; preview.rows = 16; preview.style.width = "100%";
  preview.setAttribute("aria-label", say("Sanitized report", "Rapport nettoyé"));
  const open = element("a", say("Open GitHub draft", "Ouvrir le brouillon GitHub")); open.href = draft.url; open.target = "_blank"; open.rel = "noopener noreferrer";
  const close = button(say("Close", "Fermer"), () => dialog.close());
  dialog.append(title, help, preview, open, close); document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove()); dialog.showModal();
}
let crashReporting = false;
async function reportBrowserCrash(error) {
  if (crashReporting || $("workspace").hidden || signedInMember() || !error?.stack) return;
  crashReporting = true;
  try { offerCrashReport(await api("crash-report", {stack: String(error.stack).slice(0, 20000)})); }
  catch (_) { /* Reporting must never cause another report. */ }
  finally { crashReporting = false; }
}
window.addEventListener("error", event => reportBrowserCrash(event.error));
window.addEventListener("unhandledrejection", event => reportBrowserCrash(event.reason));
