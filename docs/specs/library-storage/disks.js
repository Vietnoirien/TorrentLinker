"use strict";
// Preview "Fichiers · Disques": /saves, /windocs (full), the new 14 To disk; scenarios for smartctl and for a disk the container does not see yet.
LSNav.screen({ id: "disks", label: "Fichiers · Disques", tab: "disks", build({ add, sep, call }) {
  add("smartctl non autorisé", b => call("smartctl", !b.classList.toggle("on")));
  add("Disque absent du conteneur", async b => { const on = b.classList.toggle("on"); await call("setMounted", !on); });
  sep();
  add("Réinitialiser", () => call("reset"));
} });
