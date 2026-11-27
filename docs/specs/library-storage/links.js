"use strict";
// Preview "Liens": in the real Paramètres page (client tab), next to the real "Dossier des liens" field, a card explains
// what the Link Folder is used for with this client and whether the client requires it. The real page is untouched otherwise.
(() => {
  const CLIENTS = {
    qbittorrent: { name: "qBittorrent", need: false, native: "setLocation et le renommage des chemins du torrent" },
    deluge: { name: "Deluge", need: false, native: "move_storage et le renommage des chemins du torrent" },
    transmission: { name: "Transmission", need: false, native: "torrent-set-location et le renommage des chemins du torrent" },
    utorrent: { name: "µTorrent", need: true },
    bittorrent: { name: "BitTorrent", need: true },
    rtorrent: { name: "rTorrent", need: true },
  };
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  function html(c, root) {
    const need = c.need;
    const uses = [
      ["Remise en seed d'un torrent dont les noms de fichiers ou de sous-dossiers diffèrent de la médiathèque",
        need ? "Toujours par liens : ce client ne sait pas renommer les chemins d'un torrent, renommer changerait vos fichiers d'origine. Les liens reproduisent la disposition du torrent sans toucher aux originaux."
          : "Par défaut le client renomme les chemins dans le torrent : aucun lien. Choisissez « Liens » seulement pour garder la disposition d'origine du torrent (cross-seed)."],
      ["Organisation (Fichiers › Organisation) des fichiers déjà en partage",
        need ? "Le client ne peut pas renommer : le fichier est renommé sur le disque, puis le torrent est re-pointé et revérifié via le Dossier de liens. Sans lui, ces lignes affichent « nécessite un Dossier de liens »."
          : `Le client renomme et déplace lui-même (${c.native}) : pas de Dossier de liens. Il ne sert que pour un torrent dont la disposition diffère de la bibliothèque (dossier Subs/, fichiers en plus à la racine).`],
      ["Déplacement d'un fichier en partage (Fichiers › Explorateur)",
        need ? "Pause, déplacement, re-pointage, revérification, reprise : fait par TorrentLinker, sans Dossier de liens, mais le client doit être arrêté pendant l'opération." : "Natif : le client déplace lui-même, le Dossier de liens n'intervient pas."],
    ];
    const text = uses.map(([t, d]) => `${t} : ${d}`).join("\n\n") + "\n\nGardez le Dossier de liens hors de la bibliothèque tant que ses torrents partagent : les liens sont permanents.";
    const todo = need && !root;
    return `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span class="ls-mini" style="margin:0">Aperçu</span><b>Dossier de liens · ${esc(c.name)}</b>${LSPreview.tipHTML(text, "À quoi sert le Dossier de liens")}
      <span style="margin-left:auto;padding:2px 9px;border-radius:6px;font-size:12px;font-weight:650;${need ? "background:#edbf7326;color:var(--warning)" : "background:#4ad39426;color:var(--success)"}">${need ? "Requis par ce client" : "Facultatif pour ce client"}</span></div>
      ${todo ? `<div style="margin-top:8px;color:var(--warning)"><b>À configurer</b> ${LSPreview.tipHTML(`Indiquez le dossier ci-dessus, hors de la bibliothèque, pour que Remise en seed et Organisation puissent fonctionner avec ${c.name}.`, "Pourquoi")}</div>` : ""}`;
  }
  function enhance() {
    const doc = document.getElementById("settings-frame")?.contentDocument;
    if (!doc?.body) return;
    const kind = doc.querySelector('select[aria-label="Type de client"], select[aria-label="Client type"]');
    const link = doc.querySelector('input[aria-label="Dossier des liens de remise en seed"], input[aria-label="Reseed link folder"]');
    const old = doc.getElementById("ls-links-card");
    if (!kind || !link) {
      old?.remove();
      // The client form is on the "Clients" tab of Connexions: open it once for the viewer.
      const tab = opening && [...doc.querySelectorAll('[role=tab],button')].find(x => /^Clients/.test(x.textContent.trim()));
      if (tab) { opening = false; tab.click(); }
      return;
    }
    opening = false;
    const c = CLIENTS[kind.value] || CLIENTS.qbittorrent, key = kind.value + "|" + link.value;
    if (old?.dataset.key === key) return;
    old?.remove();
    const card = doc.createElement("div");
    card.id = "ls-links-card"; card.dataset.key = key;
    card.style.cssText = "grid-column:1/-1;margin:12px 0;padding:10px 14px;border:1px dashed #edbf73aa;border-radius:10px;background:var(--raised);font-size:13.5px;max-width:760px";
    LSPreview.tipInstall(doc);
    card.innerHTML = html(c, link.value.trim());
    const note = link.closest("label")?.nextElementSibling;
    (note?.classList.contains("file-access-note") ? note : link.closest("label")).after(card);
    if (!doc.getElementById("ls-css")) { const l = doc.createElement("link"); l.id = "ls-css"; l.rel = "stylesheet"; l.href = LSPreview.BASE + "preview.css"; doc.head.append(l); }
  }
  let timer = 0, opening = false;
  LSPreview.register({
    id: "links", label: "Liens",
    controls(box) {
      const add = (t, on) => { const b = document.createElement("button"); b.type = "button"; b.textContent = t; b.onclick = on; box.append(b); };
      add("Ouvrir le client (Paramètres)", () => { opening = true; location.hash = "#/setup/connections"; });
      const s = document.createElement("span"); s.className = "ls-state"; s.textContent = "Changez « Type de client » : la carte suit."; box.append(s);
    },
    activate() { opening = true; LSNav.ensure(); location.hash = "#/setup/connections"; timer = setInterval(() => { try { enhance(); } catch (e) { console.error(e); } }, 400); },
    deactivate() { clearInterval(timer); document.getElementById("settings-frame")?.contentDocument?.getElementById("ls-links-card")?.remove(); },
  });
})();
