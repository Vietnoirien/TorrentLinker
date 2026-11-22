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
  // The server's fixed sentences about a refused or banned client login, in French.
  const french = {
    "The client refused the login. Check the username and password (or API key) in Settings, then press Test. No automatic login is tried until then.":
      "Le client a refusé la connexion. Vérifiez l’identifiant et le mot de passe (ou la clé API) dans les paramètres, puis appuyez sur Tester. Aucune connexion automatique n’est tentée d’ici là.",
    "qBittorrent has banned this IP address after too many failed logins. Restart qBittorrent (or wait for the ban to end), check the username and password in Settings, then press Test.":
      "qBittorrent a banni cette adresse IP après trop d’échecs de connexion. Redémarrez qBittorrent (ou attendez la fin du bannissement), vérifiez l’identifiant et le mot de passe dans les paramètres, puis appuyez sur Tester.",
  };
  function show(message, kind = "ok") {
    if (!message) return null;
    if (document.documentElement.lang === "fr")
      message = String(message)
        .split(" · ")
        .map((part) => {
          // A client's error may come as "Client name: sentence".
          const at = part.indexOf(": ");
          const name = at < 0 ? "" : part.slice(0, at + 2);
          return french[part] || (french[part.slice(name.length)] ? name + french[part.slice(name.length)] : part);
        })
        .join(" · ");
    const failed = kind === "bad";
    // The same error, such as a client refusing its login on every refresh, shows once.
    if (failed) {
      const same = [...container().querySelectorAll(".tl-toast.bad > span")].find(
        (node) => node.textContent === message,
      );
      if (same) return same.parentNode;
    }
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
