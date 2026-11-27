"use strict";
// Preview "Organisation B" (libraries first): one large card per organised library, its provenance folders under it.
LSNav.screen({ id: "org-b", label: "Organisation B", tab: "orgB", build({ add, sep, call }) {
  add("Réinitialiser", () => call("orgReset", "orgB"));
} });
