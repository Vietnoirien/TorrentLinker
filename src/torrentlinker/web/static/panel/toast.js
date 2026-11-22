"use strict";
// One toast for every panel: bottom-right, stacked. A success fades after about 4 s; an error
// stays with a close button until dismissed. Colours come from base.css.
const TLToast = (() => {
  let stack;
  function container() {
    if (!stack) {
      stack = document.createElement("div");
      stack.className = "tl-toasts";
      document.body.append(stack);
    }
    return stack;
  }
  function show(message, kind = "ok") {
    if (!message) return null;
    const failed = kind === "bad";
    const node = document.createElement("div");
    node.className = `tl-toast ${failed ? "bad" : "ok"}`;
    node.setAttribute("role", failed ? "alert" : "status");
    const text = document.createElement("span");
    text.textContent = message;
    node.append(text);
    const close = () => node.remove();
    if (failed) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tl-toast-close";
      button.textContent = "×";
      button.setAttribute("aria-label", document.documentElement.lang === "fr" ? "Fermer" : "Close");
      button.onclick = close;
      node.append(button);
    } else setTimeout(close, 4000);
    container().append(node);
    return node;
  }
  return { show };
})();
