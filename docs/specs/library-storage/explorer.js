"use strict";
// Preview "Fichiers · Explorateur": dual pane, right-click menu, conflicts, seeded moves; "Vue membre" is the Gérer les fichiers scenario.
LSNav.screen({ id: "explorer", label: "Fichiers · Explorateur", tab: "explorer", build({ add, sep, call, files }) {
  const member = add("Vue membre (Gérer les fichiers)", async b => { const on = !(files()?.api.member); await call("setMember", on); b.classList.toggle("on", on); });
  member.classList.toggle("on", !!files()?.api.member);
  sep();
  add("Réinitialiser", async () => { await call("reset"); member.classList.remove("on"); });
  add("Explorateur ↔ Recherche", () => LSNav.openSearchQueue());
} });
