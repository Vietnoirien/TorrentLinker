"use strict";
/* The one change of the Settings page: the Permission "Films" is now "Films et séries" (serve.py renames it in
   members.js). This marks it with the "Aperçu" badge wherever the label is drawn. */
(() => {
  const mark = () => {
    for (const node of document.querySelectorAll("label, .member-tag")) {
      const own = [...node.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join("").trim();
      if (!/^Films et séries$|^Films and series$/.test(own) || node.querySelector(".ts-preview")) continue;
      const badge = document.createElement("span"); badge.className = "ts-preview"; badge.textContent = "Aperçu";
      node.append(badge);
    }
  };
  new MutationObserver(mark).observe(document.documentElement, {childList: true, subtree: true});
  addEventListener("DOMContentLoaded", mark);
})();
