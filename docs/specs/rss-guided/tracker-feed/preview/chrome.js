"use strict";
// Preview toolbar: Show changes, language, theme, simulated missing passkey, reset.
(() => {
  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const labels = {
    fr: { changes: "Afficher les changements", passkey: "Passkey tr4ker absente", reset: "Réinitialiser" },
    en: { changes: "Show changes", passkey: "tr4ker passkey missing", reset: "Reset" },
  };
  const apply = () => root.classList.toggle("show-180", $("pv-changes").checked);
  $("pv-changes").onchange = apply;
  apply();
  $("pv-lang").onchange = (e) => {
    const t = labels[e.target.value];
    $("pv-changes-label").textContent = t.changes;
    $("pv-passkey-label").textContent = t.passkey;
    $("pv-reset").textContent = t.reset;
    previewBackend.set("language", e.target.value);
  };
  $("pv-theme").onchange = (e) => previewBackend.set("theme", e.target.value);
  $("pv-passkey").onchange = (e) => (previewBackend.state.passkeyMissing = e.target.checked);
  $("pv-reset").onclick = async () => {
    previewBackend.reset();
    if ($("dialog").open) $("dialog").close();
    feedState.id = "";
    feedState.selected.clear();
    await loadFeeds();
  };
})();
