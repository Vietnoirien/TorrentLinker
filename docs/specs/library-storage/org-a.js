"use strict";
// Preview "Organisation A" (board): provenances on the left, organised libraries on the right, linked by connectors.
LSNav.screen({ id: "org-a", label: "Organisation A", tab: "orgA", build({ add, sep, call }) {
  add("Réinitialiser", () => call("orgReset", "orgA"));
} });
