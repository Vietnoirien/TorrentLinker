"use strict";
// Preview "Fichiers · Corbeille": per disk, restore, "Vider maintenant" (owner only), retention.
LSNav.screen({ id: "trash", label: "Fichiers · Corbeille", tab: "trash", build({ add, sep, call, files }) {
  const m = add("Vue membre", async b => { const on = !(files()?.api.member); await call("setMember", on); await call("show", "trash"); b.classList.toggle("on", on); });
  m.classList.toggle("on", !!files()?.api.member);
  sep();
  add("Réinitialiser", () => call("reset").then(() => call("show", "trash")));
} });
