"use strict";
// Preview "Fichiers · Organisation": rename diff (Jellyfin), template editor per Library Folder, "Ranger automatiquement" per Download Folder.
LSNav.screen({ id: "organisation", label: "Fichiers · Organisation", tab: "organisation", build({ add, sep, call }) {
  add("Dossier : Téléchargements", () => call("scope", "Téléchargements"));
  add("Dossier : Films", () => call("scope", "Films"));
  sep();
  add("Réinitialiser", () => call("reset").then(() => call("show", "organisation")));
} });
