"use strict";
// Preview "Fichiers · Tâches": the queue the moves feed; "Exemple" starts three transfers (native client, other disk, a failure).
LSNav.screen({ id: "tasks", label: "Fichiers · Tâches", tab: "tasks", build({ add, sep, call }) {
  add("Lancer 3 exemples", () => call("demo"));
  add("Échec de vérification au prochain transfert", b => call("failNext", b.classList.toggle("on")));
  sep();
  add("Réinitialiser", () => call("reset"));
} });
