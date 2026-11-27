"use strict";
// Fichiers: Corbeille and Tâches (Explorateur, Disques and Organisation arrive with their own tickets).
const $ = (id) => document.getElementById(id);
const fr = () => (parent.document.documentElement.lang || "fr") === "fr";
const say = (en, french) => (fr() ? french : en);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const DAY = 86400;
const S = { owner: true, tab: "explorer", panes: [{ path: "", entries: [], sel: new Set() }, { path: "", entries: [], sel: new Set() }], active: 0, roots: [], queue: [], tab0: "", disks: null, trash: null, tasks: [], filter: "all", busy: false, sim: 4.2 };

// The panel has no network of its own: the host forwards each request to /api/files/.
const bridge = window.TLPanel.connect("files", { asynchronous: true });
const api = async (path, body) => (await bridge)(path, body);
const size = (n) => {
  const units = fr() ? ["o", "Ko", "Mo", "Go", "To"] : ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1000 && i < 4) { n /= 1000; i++; }
  return `${i ? n.toFixed(n < 10 ? 1 : 0) : n} ${units[i]}`.replace(".", fr() ? "," : ".");
};
const when = (t) => new Date(t * 1000).toLocaleString(fr() ? "fr-FR" : "en-GB", { dateStyle: "short", timeStyle: "short" });
const ago = (t) => {
  const s = Date.now() / 1000 - t;
  if (s < 90) return say("just now", "à l’instant");
  if (s < 5400) return say(`${Math.round(s / 60)} min ago`, `il y a ${Math.round(s / 60)} min`);
  if (s < 2 * DAY) return say(`${Math.round(s / 3600)} h ago`, `il y a ${Math.round(s / 3600)} h`);
  return say(`${Math.round(s / DAY)} d ago`, `il y a ${Math.round(s / DAY)} j`);
};
const fail = (e) => TLToast.show(e.message, "bad");

function purge(item) {
  const n = item.days_left;
  if (n <= 1) return `<span class="badge warn">${n === 0 ? say("tonight", "ce soir") : say("in 1 d", "dans 1 j")}</span>`;
  return `<span class="badge">${say(`purged in ${n} d`, `purgée dans ${n} j`)}</span>`;
}

function trashHTML() {
  const t = S.trash;
  if (!t) return `<div class="empty">…</div>`;
  const sections = t.disks.map((d) => {
    const total = d.items.reduce((a, i) => a + i.size, 0);
    const notice = d.writable ? "" : `<div class="note warn">${say(
      `${esc(d.name)} is mounted read-only, so nothing can be trashed or restored there yet. ${esc(d.reason)} Make the folder writable (remove “:ro” from its volume in your compose file), then reload this page.`,
      `${esc(d.name)} est monté en lecture seule : rien ne peut y être mis à la corbeille ni restauré pour l’instant. ${esc(d.reason)} Rendez le dossier modifiable (retirez « :ro » de son volume dans votre fichier compose), puis rechargez cette page.`)}</div>`;
    return `<section class="sect"><h3>${say("Trash of", "Corbeille de")} ${esc(d.name)} <span class="badge">${size(total)}</span>
      ${S.owner && d.items.length ? `<button class="danger" data-k="empty" data-d="${esc(d.id)}">${say("Empty now", "Vider maintenant")}</button>` : ""}</h3>${notice}
      <div class="panel">${d.items.length ? `<table class="list"><thead><tr><th>${say("Name", "Nom")}</th><th>${say("Original location", "Emplacement d'origine")}</th><th>${say("Deleted", "Supprimé")}</th><th class="num">${say("Size", "Taille")}</th><th>${say("Purge", "Purge")}</th><th></th></tr></thead><tbody>
      ${d.items.map((i) => `<tr><td class="name">${esc(i.name)}${i.reason ? `<small>${esc(i.reason)}</small>` : ""}</td><td class="name" style="font-size:12.5px;color:var(--muted)">${esc(i.from)}</td>
        <td>${esc(i.by)}<small>${ago(i.at)}</small></td><td class="num">${size(i.size)}</td><td>${purge(i)}</td>
        <td class="num"><button data-k="restore" data-id="${esc(i.id)}" ${d.writable ? "" : "disabled"}>${say("Restore", "Restaurer")}</button></td></tr>`).join("")}</tbody></table>`
        : `<div class="empty">${say("This disk's trash is empty.", "La corbeille de ce disque est vide.")}</div>`}</div></section>`;
  }).join("");
  return `<p class="muted hint">${say(
    "Deleting, in Files, always means moving to the trash. Each disk has its own: the move is instant.",
    "Supprimer, dans Fichiers, veut toujours dire mettre à la corbeille. Chaque disque a la sienne : le déplacement est instantané.")}</p>
    ${S.owner ? `<section class="card sect"><div class="row"><h3>${say("Retention", "Conservation")}</h3><label class="row">${say("Purge after", "Purger après")} <select data-k="ret">${[1, 3, 7, 14, 30].map((n) => `<option value="${n}" ${t.retention_days === n ? "selected" : ""}>${n} ${say(n > 1 ? "days" : "day", n > 1 ? "jours" : "jour")}</option>`).join("")}</select></label>
      <small style="display:inline">${say("7 days by default.", "7 jours par défaut.")}</small></div></section>` : ""}${sections || `<div class="empty">${say("No storage folder is configured.", "Aucun dossier de stockage n'est configuré.")}</div>`}`;
}

// ---- Disques --------------------------------------------------------------------------------
const pct = (n) => `${Math.round(n)} %`;
function diskCard(d) {
  if (d.error) return `<article class="card disk"><h3>${esc(d.name)}</h3><div class="note warn">${esc(d.error)}</div></article>`;
  const seg = (v, c) => `<i class="${c}" style="width:${Math.max(0, v) / d.total * 100}%" title="${size(v)}"></i>`;
  const used = d.used / d.total * 100;
  const ro = d.writable ? "" : `<div class="note warn">${say(
    `This disk is mounted read-only (${esc(d.reason)}): the Corbeille, Fichiers and Organisation cannot work there until it is writable. Remove “:ro” from its volume in your compose file, then restart the container. TorrentLinker never formats or mounts a disk.`,
    `Ce disque est monté en lecture seule (${esc(d.reason)}) : la corbeille, Fichiers et Organisation n'y fonctionneront pas tant qu'il ne sera pas modifiable. Retirez « :ro » de son volume dans votre fichier compose, puis redémarrez le conteneur. TorrentLinker ne formate ni ne monte jamais un disque.`)}</div>`;
  return `<article class="card disk"><div class="row between"><h3>${esc(d.name)}</h3><span class="row"><span class="badge">${size(d.total)}</span></span></div>
    <small>${d.roots.map(esc).join(", ")}</small>
    <div><div class="bar stack" title="${say("10 % margin marked", "Marge de 10 % marquée")}">${seg(d.library, "c-lib")}${seg(d.downloads, "c-dl")}${seg(d.trash, "c-tr")}${seg(d.other, "c-ot")}</div>
      <div class="bar" style="margin-top:6px;height:6px"><i class="${used > 99.5 ? "bad" : used > 90 ? "warn" : ""}" style="width:${Math.min(100, used)}%"></i><u style="left:90%"></u></div></div>
    <div class="legend"><span><b class="c-lib"></b>${say("Library", "Médiathèque")} ${size(d.library)}</span><span><b class="c-dl"></b>${say("Downloads", "Téléchargements")} ${size(d.downloads)}</span><span><b class="c-tr"></b>${say("Trash", "Corbeille")} ${size(d.trash)}</span><span><b class="c-ot"></b>${say("Other data", "Autres données")} ${size(d.other)}</span></div>
    <div class="row"><b>${size(d.used)} ${say("used", "utilisés")}</b><span>·</span><b>${size(d.free)} ${say("free", "libres")} (${pct(d.free / d.total * 100)})</b>
      ${d.free <= 0 ? `<span class="badge bad">${say("full", "plein")}</span>` : ""}${d.below_margin ? `<span class="badge ${d.free <= 0 ? "bad" : "warn"}">${say("below the 10 % margin", "sous la marge de 10 %")} (${size(d.margin)})</span>` : `<span class="badge ok">${say("10 % margin kept", "marge de 10 % respectée")}</span>`}</div>
    ${d.below_margin ? `<div class="note warn">${d.free <= 0 ? say("This disk is full: no download will be placed on it.", "Ce disque est plein : plus aucun téléchargement n'y sera placé.") : say("This disk is below the margin: the placement rule avoids it.", "Ce disque est sous la marge : la règle de placement l'évite.")} ${size(Math.max(0, d.margin - d.free))} ${say("to free to get the margin back.", "à libérer pour retrouver la marge.")}</div>` : ""}${ro}
    <dl class="kv"><dt>Films</dt><dd>${d.films} ${say(d.films === 1 ? "film" : "films", d.films === 1 ? "film" : "films")} ${say("in the Library Folders", "dans les dossiers de bibliothèque")}</dd>${smartHTML(d.health)}</dl></article>`;
}
function smartHTML(h) {
  if (!h || h.unavailable) return `<dt>${say("Health", "Santé")}</dt><dd><span class="badge warn">${say("unknown", "inconnue")}</span> <small style="display:inline">${say("smartctl is not allowed and Scrutiny is not set (see above)", "smartctl n'est pas autorisé et Scrutiny n'est pas configuré (voir plus haut)")}</small></dd>`;
  const status = h.status === "ok" ? `<span class="badge ok">SMART : OK</span>` : `<span class="badge bad">${say("Alert", "Alerte")} : ${h.reallocated ? `${h.reallocated} ${say("reallocated sectors", "secteurs réalloués")}` : say("SMART status failing", "état SMART en échec")}${h.pending ? `, ${h.pending} ${say("pending", "en attente")}` : ""}</span>`;
  return `<dt>${say("Health", "Santé")}</dt><dd>${status}</dd><dt>${say("Temperature", "Température")}</dt><dd>${h.temperature ?? "—"} °C</dd><dt>${say("Hours", "Heures")}</dt><dd>${h.hours ?? "—"} h</dd><dt>Source</dt><dd>${h.source === "scrutiny" ? "Scrutiny" : "smartctl"}</dd>`;
}
const copyBtn = (text) => `<button data-k="copy" data-v="${esc(text)}">${say("Copy", "Copier")}</button>`;
const code = (text) => `<div class="row" style="align-items:flex-start"><pre class="code grow">${esc(text)}</pre>${copyBtn(text)}</div>`;
function healthHTML() {
  const d = S.disks, any = d.disks.some((c) => c.health && !c.health.unavailable);
  const hint = d.disks.length && !any && !d.scrutiny_url ? `<div class="note warn"><b>${say("smartctl is not allowed", "smartctl n'est pas autorisé")}</b> ${say("for this server: disk health is unknown. To allow it (read-only):", "pour ce serveur : la santé des disques est inconnue. Pour l'autoriser (lecture seule) :")}
    ${code("# docker compose\nservices:\n  torrentlinker:\n    cap_add:\n      - SYS_RAWIO\n    devices:\n      - /dev/sda:/dev/sda\n      - /dev/sdb:/dev/sdb")}</div>` : "";
  return `<section class="card sect"><div class="row between"><h3>${say("Disk health", "Santé des disques")}</h3></div>
    <div class="row"><span>smartctl : <b>${any ? say("allowed", "autorisé") : say("not allowed", "non autorisé")}</b></span><span class="grow"></span>
    <label class="row">Scrutiny (API) <input data-k="scr" value="${esc(d.scrutiny_url)}" placeholder="http://scrutiny:8080" style="width:260px"></label><button data-k="scrsave">${say("Save", "Enregistrer")}</button><button data-k="scrtest">${say("Test", "Tester")}</button></div>${hint}</section>`;
}
function missingCard(path) {
  return `<article class="card disk" style="border:1px dashed var(--warning);grid-column:1/-1"><div class="row between"><h3>${esc(path)}</h3><span class="badge warn">${say("missing from the container", "absent du conteneur")}</span></div>
    <div class="note warn">${say(
      `This folder is set in Settings but TorrentLinker cannot see it. If the disk is mounted on the machine, one step is left, which you do yourself: add the volume to the container and restart it. TorrentLinker never partitions or formats a disk.`,
      `Ce dossier est défini dans les paramètres mais TorrentLinker ne le voit pas. Si le disque est monté sur la machine, il reste une seule étape, à faire vous-même : ajouter le volume au conteneur, puis le redémarrer. TorrentLinker ne partitionne ni ne formate jamais un disque.`)}</div>
    <div><b>${say("In the compose file", "Dans le fichier compose")}</b>, <code>volumes</code> :<pre class="code">services:\n  torrentlinker:\n    volumes:\n      - ${esc(path)}:${esc(path)}</pre></div>
    <div><b>${say("Then restart", "Puis redémarrer")}</b> :<pre class="code">docker compose up -d</pre></div></article>`;
}
const WHY = {
  "most-free": ["the disk with the most free space above the margin", "le disque qui a le plus de place libre au-dessus de la marge"],
  together: ["it stays on the disk the film already shares", "il reste sur le disque que ce film partage déjà"],
  "together-full": ["its disk lacks room, so the most free space wins", "son disque manque de place : le plus libre l'emporte"],
  none: ["no disk has room above the margin", "aucun disque n'a de place au-dessus de la marge"],
};
function placementHTML() {
  const d = S.disks;
  const answer = S.placed ? `<div class="note ${S.placed.disk ? "" : "warn"}">${say(`This ${S.sim} GB download would go to`, `Ce téléchargement de ${S.sim} Go irait sur`)} <b>${esc(S.placed.name || "—")}</b> : ${esc(say(...WHY[S.placed.why]))}.
    ${d.disks.filter((c) => !c.error).map((c) => `<div><small>${esc(c.name)} : ${size(c.usable)} ${say("usable above the margin", "utilisables au-dessus de la marge")}</small></div>`).join("")}</div>` : "";
  return `<section class="card sect"><div class="row between"><h3>${say("Placement rule", "Règle de placement")}</h3></div>
    <p><b>${say("“Keep together, otherwise the freest disk.”", "« Garder ensemble, sinon le disque le plus libre. »")}</b> ${say(
      "A film's versions and a series' episodes stay on the disk they already share. Otherwise the download goes to the disk with the most free space above the 10 % margin. Replace and the downloads use it.",
      "Les versions d'un film et les épisodes d'une série restent sur le disque qu'ils partagent déjà. Sinon, le téléchargement va sur le disque qui a le plus de place libre au-dessus de la marge de 10 %. Remplacer et les téléchargements l'utilisent.")}</p>
    <div class="sim"><div class="row"><label>${say("Next download size (GB)", "Taille du prochain téléchargement (Go)")}<input type="number" min="0.1" step="0.1" value="${S.sim}" data-k="sim" style="width:100px"></label></div>${answer}</div></section>`;
}
function disksHTML() {
  const d = S.disks;
  if (!d) return `<div class="empty">…</div>`;
  return `<p class="muted hint">${say(
    "Each disk is mounted separately and identified by its device (st_dev). The Corbeille is counted apart.",
    "Chaque disque est monté séparément et identifié par son périphérique (st_dev). La corbeille est comptée à part.")}</p>
    ${healthHTML()}<div class="disks">${d.disks.map(diskCard).join("")}${d.missing.map(missingCard).join("")}</div>
    ${d.disks.length ? `<div style="height:14px"></div>${placementHTML()}` : `<div class="empty">${say("No storage folder is configured.", "Aucun dossier de stockage n'est configuré.")}</div>`}`;
}
async function place() {
  try { S.placed = await api("disks/placement", { size: Math.round(S.sim * 1e9) }); } catch (e) { fail(e); }
}

// ---- Explorateur ----------------------------------------------------------------------------
// A film Médias knows shows its poster, through the app's own artwork route.
function icon(e) {
  if (e.film) {
    const url = new URL(`api/media/items/${encodeURIComponent(e.film.id)}/artwork?size=grid`, parent.document.baseURI);
    return `<span class="ico"><img src="${esc(url.href)}" alt="" width="28" height="42" loading="lazy" onerror="this.parentNode.textContent='🎞'"></span>`;
  }
  return `<span class="ico small">${e.dir ? "📁" : "🎞"}</span>`;
}
const seedBadge = (e) => e.seed ? `<span class="badge ok seed" title="${say("A torrent uses these files", "Un torrent utilise ces fichiers")}">▲ ${esc(e.seed.client)} · ratio ${String(e.seed.ratio).replace(".", fr() ? "," : ".")}</span>` : "";
const name = (p) => p.split("/").filter(Boolean).pop() || p;
const parentOf = (p) => p.replace(/\/[^/]+\/?$/, "") || "/";
const rootOf = (p) => S.roots.filter((r) => p === r || p.startsWith(r + "/")).sort((a, b) => b.length - a.length)[0] || "";
const date = (t) => new Date(t * 1000).toLocaleDateString(fr() ? "fr-FR" : "en-GB");
async function openPane(i, path) {
  const pane = S.panes[i];
  try {
    const r = await api(`browse?path=${encodeURIComponent(path)}`);
    Object.assign(pane, { path: r.path, entries: r.entries, sel: new Set() });
  } catch (e) { fail(e); }
  render();
}
function crumbs(pane) {
  const root = rootOf(pane.path);
  if (!root) return "";
  const parts = pane.path.slice(root.length).split("/").filter(Boolean);
  let at = root;
  return `<button data-k="go" data-p="${esc(root)}">${esc(name(root))}</button>${parts.map((x) => { at += "/" + x; return `<span>/</span><button data-k="go" data-p="${esc(at)}">${esc(x)}</button>`; }).join("")}`;
}
function paneHTML(i) {
  const pane = S.panes[i];
  const options = S.roots.map((r) => `<option value="${esc(r)}" ${rootOf(pane.path) === r ? "selected" : ""}>${esc(r)}</option>`).join("");
  const rows = pane.entries.map((e) => `<tr draggable="true" data-k="row" data-pane="${i}" data-n="${esc(e.name)}" class="${pane.sel.has(e.name) ? "sel" : ""}"><td class="name"><span class="who">${icon(e)}<b>${esc(e.name)}</b></span>${e.film && e.film.title !== e.name ? `<small>${esc(e.film.title)}</small>` : ""}</td><td class="num">${e.dir ? "" : size(e.size)}</td><td class="date">${date(e.modified)}</td><td>${seedBadge(e)}</td></tr>`).join("");
  return `<section class="pane ${S.active === i ? "active" : ""}" data-pane="${i}"><div class="pane-head"><div class="row"><select data-k="root" data-pane="${i}"><option value="">${say("Choose a disk or folder…", "Choisir un disque ou un dossier…")}</option>${options}</select>
    <button data-k="up" data-pane="${i}" ${pane.path && pane.path !== rootOf(pane.path) ? "" : "disabled"}>↑</button></div><div class="crumbs">${crumbs(pane)}</div></div>
    <div class="files">${pane.path ? `<table class="list"><thead><tr><th>${say("Name", "Nom")}</th><th class="num">${say("Size", "Taille")}</th><th class="date">${say("Modified", "Modifié")}</th><th></th></tr></thead><tbody>${rows || `<tr><td colspan="4" class="empty">${say("This folder is empty.", "Ce dossier est vide.")}</td></tr>`}</tbody></table>` : `<div class="empty">${say("Choose a disk or folder above.", "Choisissez un disque ou un dossier ci-dessus.")}</div>`}</div>
    <div class="pane-foot"><span>${pane.entries.length} ${say("items", "éléments")}</span><span>${pane.sel.size ? `${pane.sel.size} ${say("selected", "sélectionné(s)")}` : ""}</span></div></section>`;
}
function explorerHTML() {
  const none = !S.panes[S.active].sel.size ? "disabled" : "";
  return `<p class="muted hint">${say("Move, copy, rename and trash files no torrent uses. Moves run in the background in Tasks; each item is verified.", "Déplacez, copiez, renommez et mettez à la corbeille les fichiers qu'aucun torrent n'utilise. Les opérations s'exécutent en arrière-plan dans Tâches ; chaque élément est vérifié.")}</p>
    <div class="panes">${paneHTML(0)}${paneHTML(1)}</div>
    <div class="fkeys"><button data-f="rename" ${none}><kbd>F2</kbd>${say("Rename", "Renommer")}</button><button data-f="copy" ${none}><kbd>F5</kbd>${say("Copy", "Copier")}</button><button data-f="move" ${none}><kbd>F6</kbd>${say("Move", "Déplacer")}</button>
      <button data-f="mkdir"><kbd>F7</kbd>${say("New folder", "Nouveau dossier")}</button><button data-f="trash" class="danger" ${none}><kbd>Suppr</kbd>${say("Move to the trash", "Mettre à la corbeille")}</button></div>`;
}
const picked = () => { const p = S.panes[S.active]; return p.entries.filter((e) => p.sel.has(e.name)).map((e) => `${p.path}/${e.name}`); };
function ask(html, onOk) {
  const d = $("dialog");
  d.innerHTML = html + `<div class="dialog-foot"><button id="no">${say("Cancel", "Annuler")}</button><button id="yes" class="primary">OK</button></div>`;
  d.showModal();
  d.onclick = (e) => { if (e.target.id === "no") d.close(); if (e.target.id === "yes") { const values = { conflict: (d.querySelector("input[name=c]:checked") || {}).value, text: (d.querySelector("input[type=text]") || {}).value }; d.close(); onOk(values); } };
}
// What a torrent that seeds the chosen files changes about each operation (ADR-0029): the client
// moves, renames and unseeds them, and the confirmation says how long it takes.
const entryOf = (path) => S.panes.map((p) => p.entries.find((e) => `${p.path}/${e.name}` === path)).find(Boolean);
function seedNotes(f, paths, crossing) {
  const seeded = paths.map((p) => entryOf(p)).filter((e) => e?.seed);
  if (!seeded.length) return "";
  const clients = [...new Set(seeded.map((e) => e.seed.client))].join(", ");
  const bytes = seeded.reduce((a, e) => a + (e.size || 0), 0);
  const speed = 150e6;
  if (f === "trash") return `<div class="note warn">${say(`${seeded.length} item(s) are shared (${clients}): the torrent leaves the client <b>without its data</b>, as with Replace.`, `${seeded.length} élément(s) sont en partage (${clients}) : le torrent est retiré du client <b>sans ses données</b>, comme pour « Remplacer ».`)}</div>`;
  if (f === "rename") return `<div class="note">${say(`Shared in <b>${esc(clients)}</b>: the name is changed <b>in the client</b> (the torrent's path), not only on the disk.`, `En partage dans <b>${esc(clients)}</b> : le nom est changé <b>dans le client</b> (chemin du torrent), pas seulement sur le disque.`)}</div>`;
  if (f === "copy") return `<div class="note">${say("The torrent stays in place and keeps sharing the original; the copy is not shared.", "Le torrent reste en place et continue de partager l'original ; la copie n'est pas partagée.")}</div>`;
  return `<div class="note">${say(`Shared in <b>${esc(clients)}</b>: the move goes through the client, which keeps sharing. `, `En partage dans <b>${esc(clients)}</b> : le déplacement passe par le client, qui continue de partager. `)}${crossing
    ? say(`<b>Copy</b> of ${size(bytes)}, about ${duration(bytes / speed)}, checked before the original leaves.`, `<b>Copie</b> de ${size(bytes)}, environ ${duration(bytes / speed)}, vérifiée avant que l'original parte.`)
    : say("<b>Instant move</b> (same disk).", "<b>Déplacement instantané</b> (même disque).")}</div>`;
}
function operate(f, drop) {
  // A drop names its own items and destination; otherwise the other pane is the destination.
  const from = drop ? drop.from : picked(), here = S.panes[S.active], there = drop ? { path: drop.to } : S.panes[1 - S.active];
  const list = from.map((p) => `<div class="dlg-item"><span>${esc(name(p))}</span></div>`).join("");
  if (f === "mkdir") return ask(`<h2>${say("New folder", "Nouveau dossier")}</h2><input type="text" placeholder="${say("Name", "Nom")}" style="width:100%">`, ({ text }) => text && submit("mkdir", [{ from: `${here.path}/${text}` }]));
  if (f === "rename") return ask(`<h2>${say("Rename", "Renommer")}</h2><input type="text" value="${esc(name(from[0]))}" style="width:100%">${seedNotes("rename", from)}`, ({ text }) => text && submit("rename", [{ from: from[0], to: `${here.path}/${text}` }]));
  if (f === "trash") return ask(`<h2>${say("Move to the trash", "Mettre à la corbeille")} ?</h2><p>${say("Nothing is deleted: each disk's trash keeps it for the retention delay and you can restore it.", "Rien n'est supprimé : la corbeille de chaque disque le garde pendant le délai de conservation et vous pouvez le restaurer.")}</p><div class="dlg-list">${list}</div>${seedNotes("trash", from)}`, () => submit("trash", from.map((x) => ({ from: x }))));
  if (!there.path) return TLToast.show(say("Open a destination in the other pane first.", "Ouvrez d'abord une destination dans l'autre panneau."), "bad");
  const crossing = rootOf(here.path) !== rootOf(there.path);
  const note = f === "move" && crossing ? say("Between disks this is a copy: the source goes to the trash only after the copy is verified.", "Entre deux disques, c'est une copie : la source n'est mise à la corbeille qu'une fois la copie vérifiée.") : f === "move" ? say("On the same disk this is instant.", "Sur le même disque, c'est instantané.") : say("The copy is verified.", "La copie est vérifiée.");
  const choices = [["skip", "Ignorer", "Skip"], ["replace", "Remplacer (l'ancien va à la corbeille)", "Replace (the old one goes to the trash)"], ["rename", "Renommer", "Rename"], ["keep-one", "Garder un seul (fichiers identiques)", "Keep one (identical files)"]];
  ask(`<h2>${f === "move" ? say("Move", "Déplacer") : say("Copy", "Copier")} ${from.length} ${say("item(s) to", "élément(s) vers")} ${esc(there.path)}</h2><div class="dlg-list">${list}</div><div class="note">${note}</div>${seedNotes(f, from, crossing)}
    <p class="muted">${say("If a name is already taken:", "Si un nom existe déjà :")}</p>${choices.map(([v, french, en], n) => `<label class="row"><input type="radio" name="c" value="${v}" ${n === 0 ? "checked" : ""}> ${say(en, french)}</label>`).join("")}`, ({ conflict }) => submit(f, from.map((x) => ({ from: x, to: there.path })), conflict));
}
async function submit(kind, items, conflict = "skip") {
  try { await api("tasks", { kind, items, conflict }); TLToast.show(say("Started: follow it in Tasks.", "Lancé : suivez-le dans Tâches.")); } catch (e) { fail(e); }
  setTimeout(async () => { await Promise.all([0, 1].map((i) => S.panes[i].path && openPane(i, S.panes[i].path))); }, 800);
}

const duration = (s) => (s < 90 ? `${Math.max(1, Math.round(s))} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1).replace(".", fr() ? "," : ".")} h`);
const KINDS = {
  trash: ["Moved to the trash", "Mise à la corbeille"], restore: ["Restored", "Restauration"],
  purge: ["Daily purge of the trash", "Purge quotidienne de la corbeille"], empty: ["Trash emptied", "Corbeille vidée"],
};
const STATES = { pending: ["In progress", "En cours"], done: ["Done", "Terminé"], failed: ["Failed", "Échec"] };
function tasksHTML() {
  const rows = S.tasks.filter((o) => S.filter === "all" || (S.filter === "failed" ? o.state === "failed" : S.filter === "running" ? o.state === "pending" : o.state === "done"));
  const f = [["all", "All", "Toutes"], ["running", "Running", "En cours"], ["done", "Done", "Terminées"], ["failed", "Failed", "En échec"]];
  const queue = S.queue.map((t) => `<div class="card task ${t.state === "failed" ? "failed" : ""}"><div class="task-head"><b class="grow">${esc(t.kind)} · ${t.items.length}</b><span class="badge ${t.state === "done" ? "ok" : t.state === "failed" ? "bad" : ""}">${esc(t.state)}</span>${t.state === "running" || t.state === "queued" ? `<button data-cancel="${esc(t.id)}">${say("Cancel", "Annuler")}</button>` : ""}</div>
    ${t.items.map((x, n) => `<div class="titem"><span class="nm">${esc(name(x.from))}${x.note ? `<small>${esc(x.note)}</small>` : ""}</span><div class="prog"><i style="width:${Math.round(x.progress * 100)}%"></i></div>${x.eta > 0 && x.state === "running" ? `<small>${say("about", "reste ~")} ${duration(x.eta)}</small>` : ""}<span>${x.verified ? `<span class="ver">✓ ${say("verified", "vérifié")}</span>` : ""}${x.undo && x.state === "done" ? `<button data-undoitem="${esc(t.id)}" data-n="${n}">${say("Undo", "Annuler")}</button>` : ""}${x.state === "undone" ? say("undone", "annulé") : ""}</span>${x.reason ? `<div class="reason">${esc(x.reason)}</div>` : ""}</div>`).join("")}
    <small>${esc(t.actor)} · ${when(t.created)}</small></div>`).join("");
  return `${queue ? `<div class="tasks" style="margin-bottom:16px">${queue}</div><h3>${say("Log", "Journal")}</h3>` : ""}<div class="filters">${f.map(([k, en, french]) => `<button data-filter="${k}" class="${S.filter === k ? "on" : ""}">${say(en, french)}</button>`).join("")}</div>
    <div class="tasks">${rows.map((o) => {
      const name = (o.detail.from || "").split("/").pop() || (o.detail.items ? `${o.detail.items}` : "");
      return `<div class="card task ${o.state === "failed" ? "failed" : ""}"><div class="task-head"><b class="grow">${esc(say(...(KINDS[o.kind] || [o.kind, o.kind])))}${name ? ` · ${esc(name)}` : ""}</b>
        <span class="badge ${o.state === "done" ? "ok" : o.state === "failed" ? "bad" : ""}">${esc(say(...(STATES[o.state] || [o.state, o.state])))}</span>
        ${o.undoable ? `<button data-undo="${esc(o.id)}">${say("Undo", "Annuler")}</button>` : ""}</div>
        <small>${esc(o.actor)} · ${when(o.started)}</small>${o.error ? `<div class="reason">${esc(o.error)}</div>` : ""}</div>`;
    }).join("") || `<div class="empty">${say("No task for this filter.", "Aucune tâche pour ce filtre.")}</div>`}</div>`;
}

const TABS = [["explorer", "Explorer", "Explorateur"], ["disks", "Disks", "Disques"], ["trash", "Trash", "Corbeille"], ["tasks", "Tasks", "Tâches"]];
// A Member with "Gérer les fichiers" gets Explorateur, Corbeille and Tâches, never Disques.
const tabsFor = () => TABS.filter(([id]) => S.owner || id !== "disks");
function render() {
  const tabs = tabsFor().map(([id, en, french]) => `<button data-tab="${id}" class="${S.tab === id ? "selected" : ""}">${say(en, french)}${id === "trash" && S.trash ? `<span class="badge count">${S.trash.disks.reduce((a, d) => a + d.items.length, 0)}</span>` : ""}</button>`).join("");
  $("app").innerHTML = `<nav class="tabs" role="tablist">${tabs}</nav>${S.tab === "trash" ? trashHTML() : S.tab === "disks" ? disksHTML() : S.tab === "explorer" ? explorerHTML() : tasksHTML()}`;
}
async function load() {
  try {
    if (S.tab === "explorer") {
      const r = await api("browse");
      S.roots = r.roots;
      for (const [i, pane] of S.panes.entries()) if (!pane.path && r.roots[i] && !pane.chosen) { pane.chosen = true; await openPane(i, r.roots[i]); }
    } else if (S.tab === "disks") { S.disks = await api("disks"); await place(); }
    else if (S.tab === "trash") { S.trash = await api("trash"); S.owner = S.trash.owner !== false; }
    else { S.tasks = (await api("journal")).operations; S.queue = (await api("tasks")).tasks; }
  } catch (e) { fail(e); }
  if (!document.querySelector("dialog[open]")) render();
}

function confirmEmpty(disk) {
  const d = $("dialog"), item = S.trash.disks.find((x) => x.id === disk);
  const n = item.items.length, total = item.items.reduce((a, i) => a + i.size, 0);
  d.innerHTML = `<h2>${say("Empty the trash of", "Vider la corbeille de")} ${esc(item.name)} ?</h2>
    <p>${say(`${n} item(s), ${size(total)}, will be deleted for good. This cannot be undone.`, `${n} élément(s), ${size(total)}, seront supprimés définitivement. Cette action est irréversible.`)}</p>
    <div class="dialog-foot"><button id="no" autofocus>${say("Cancel", "Annuler")}</button><button id="yes" class="primary danger">${say("Empty now", "Vider maintenant")}</button></div>`;
  d.showModal();
  d.onclick = async (e) => {
    if (e.target.id === "no") d.close();
    if (e.target.id === "yes") {
      d.close();
      try { const r = await api("trash/empty", { confirm: true, disk }); TLToast.show(say(`${r.deleted} item(s) deleted.`, `${r.deleted} élément(s) supprimé(s).`)); } catch (x) { fail(x); }
      load();
    }
  };
}

document.addEventListener("click", async (e) => {
  const t = e.target.closest("[data-tab],[data-k],[data-filter],[data-undo],[data-f],[data-cancel],[data-undoitem]");
  if (!t) return;
  if (t.dataset.f) return operate(t.dataset.f);
  if (t.dataset.cancel) { try { await api(`tasks/${t.dataset.cancel}/cancel`, {}); } catch (x) { fail(x); } return load(); }
  if (t.dataset.undoitem) { try { await api(`tasks/${t.dataset.undoitem}/undo/${t.dataset.n}`, {}); TLToast.show(say("Undone.", "Annulé.")); } catch (x) { fail(x); } return load(); }
  if (t.dataset.k === "go") return openPane(S.active, t.dataset.p);
  if (t.dataset.k === "up") { S.active = Number(t.dataset.pane); return openPane(S.active, parentOf(S.panes[S.active].path)); }
  if (t.dataset.k === "row") {
    const i = Number(t.dataset.pane), pane = S.panes[i], n = t.dataset.n;
    S.active = i;
    const entry = pane.entries.find((x) => x.name === n);
    if (e.detail >= 2 && entry?.dir) return openPane(i, `${pane.path}/${n}`);
    if (!(e.ctrlKey || e.metaKey)) pane.sel.clear();
    pane.sel.has(n) && (e.ctrlKey || e.metaKey) ? pane.sel.delete(n) : pane.sel.add(n);
    return render();
  }
  if (t.dataset.tab) { S.tab = t.dataset.tab; render(); load(); }
  else if (t.dataset.filter) { S.filter = t.dataset.filter; render(); }
  else if (t.dataset.undo) {
    try { await api(`journal/${t.dataset.undo}/undo`, {}); TLToast.show(say("Undone.", "Annulé.")); } catch (x) { fail(x); }
    load();
  } else if (t.dataset.k === "restore") {
    try { const r = await api(`trash/${t.dataset.id}/restore`, {}); TLToast.show(say(`Restored to ${r.restored}.`, `Restauré dans ${r.restored}.`)); } catch (x) { fail(x); }
    load();
  } else if (t.dataset.k === "empty") confirmEmpty(t.dataset.d);
  else if (t.dataset.k === "copy") { try { await navigator.clipboard.writeText(t.dataset.v); TLToast.show(say("Copied.", "Copié.")); } catch { TLToast.show(say("Copy is not allowed here.", "Copie impossible ici."), "bad"); } }
  else if (t.dataset.k === "scrsave" || t.dataset.k === "scrtest") {
    const url = document.querySelector('[data-k="scr"]').value;
    try {
      if (t.dataset.k === "scrsave") { await api("disks/scrutiny", { url }); TLToast.show(say("Scrutiny address saved.", "Adresse de Scrutiny enregistrée.")); load(); }
      else { const r = await api("disks/scrutiny/test", { url }); TLToast.show(say(`Scrutiny answers: ${r.disks.length} disk(s).`, `Scrutiny répond : ${r.disks.length} disque(s).`)); }
    } catch (x) { fail(x); }
  }
});
document.addEventListener("keydown", (e) => {
  if (S.tab !== "explorer" || e.target.closest("input,select,textarea") || $("dialog").open) return;
  const f = { F2: "rename", F5: "copy", F6: "move", F7: "mkdir", Delete: "trash" }[e.key];
  if (f && (f === "mkdir" || S.panes[S.active].sel.size)) { e.preventDefault(); operate(f); }
});
document.addEventListener("change", async (e) => {
  if (e.target.dataset.k === "root") { S.active = Number(e.target.dataset.pane); if (e.target.value) await openPane(S.active, e.target.value); return; }
  if (e.target.dataset.k === "sim") { S.sim = Math.max(0.1, Number(e.target.value) || 4.2); await place(); render(); return; }
  if (e.target.dataset.k !== "ret") return;
  try { await api("trash/retention", { days: Number(e.target.value) }); TLToast.show(say("Retention saved.", "Conservation enregistrée.")); } catch (x) { fail(x); }
  load();
});

// ---- Right-click menu and drag between the panes ---------------------------------------------
function menu() {
  let box = $("menu");
  if (!box) { box = document.createElement("div"); box.id = "menu"; box.className = "context"; box.hidden = true; document.body.append(box); }
  return box;
}
function showMenu(x, y, items) {
  const box = menu();
  box.innerHTML = items.map((it) => (it === "-" ? "<hr>" : `<button data-act="${it.act}" ${it.off ? "disabled" : ""}><span>${esc(it.label)}</span><span class="kbd">${esc(it.key || "")}</span></button>`)).join("");
  box.hidden = false;
  box.style.left = Math.max(4, Math.min(x, innerWidth - box.offsetWidth - 6)) + "px";
  box.style.top = Math.max(4, Math.min(y, innerHeight - box.offsetHeight - 6)) + "px";
  box._items = items;
}
const hideMenu = () => { menu().hidden = true; };
addEventListener("click", (e) => { if (!e.target.closest("#menu")) hideMenu(); });
addEventListener("blur", hideMenu);
addEventListener("scroll", hideMenu, true);
menu().addEventListener("click", (e) => {
  const b = e.target.closest("button[data-act]");
  if (!b) return;
  const found = menu()._items.find((x) => x.act === b.dataset.act);
  hideMenu();
  found?.run?.();
});
function properties(path, e) {
  ask(`<h2>${say("Properties", "Propriétés")}</h2><dl class="kv"><dt>${say("Name", "Nom")}</dt><dd>${esc(e.name)}</dd><dt>${say("Location", "Emplacement")}</dt><dd>${esc(path)}</dd>
    <dt>${say("Size", "Taille")}</dt><dd>${size(e.size)}</dd><dt>${say("Modified", "Modifié")}</dt><dd>${when(e.modified)}</dd>
    ${e.film ? `<dt>${say("Film", "Film")}</dt><dd>${esc(e.film.title)}</dd>` : ""}${e.seed ? `<dt>${say("Seeded by", "Partagé par")}</dt><dd>${esc(e.seed.client)} · ratio ${e.seed.ratio}</dd>` : ""}</dl>`, () => {});
}
function contextMenu(ev, i, n) {
  ev.preventDefault();
  const pane = S.panes[i];
  S.active = i;
  if (n && !pane.sel.has(n)) { pane.sel.clear(); pane.sel.add(n); render(); }
  const chosen = pane.entries.filter((x) => pane.sel.has(x.name)), one = chosen.length === 1 ? chosen[0] : null, none = !chosen.length;
  showMenu(ev.clientX, ev.clientY, [
    { act: "open", label: say("Open", "Ouvrir"), key: "↵", off: !one?.dir, run: () => openPane(i, `${pane.path}/${one.name}`) },
    { act: "play", label: say("Play in Media", "Lire dans Médias"), off: !one?.film, run: () => { parent.location.hash = "#/media"; } },
    "-",
    { act: "rename", label: say("Rename", "Renommer"), key: "F2", off: !one, run: () => operate("rename") },
    { act: "moveto", label: say("Move to…", "Déplacer vers…"), key: "F6", off: none, run: () => operate("move") },
    { act: "copyto", label: say("Copy to…", "Copier vers…"), key: "F5", off: none, run: () => operate("copy") },
    { act: "mkdir", label: say("New folder", "Nouveau dossier"), key: "F7", run: () => operate("mkdir") },
    "-",
    { act: "trash", label: say("Move to the trash", "Mettre à la corbeille"), key: "Suppr", off: none, run: () => operate("trash") },
    "-",
    { act: "torrent", label: say("See the torrent", "Voir le torrent"), off: !one?.seed, run: () => { parent.location.hash = "#/torrents"; } },
    { act: "props", label: say("Properties", "Propriétés"), off: !one, run: () => properties(`${pane.path}/${one.name}`, one) },
  ]);
}
document.addEventListener("contextmenu", (e) => {
  const row = e.target.closest("tr[data-n]"), box = e.target.closest(".files");
  if (S.tab !== "explorer") return;
  if (row) contextMenu(e, Number(row.dataset.pane), row.dataset.n);
  else if (box) contextMenu(e, Number(box.closest("[data-pane]").dataset.pane), null);
});
let drag = null;
document.addEventListener("dragstart", (e) => {
  const row = e.target.closest("tr[data-n]");
  if (!row) return;
  const i = Number(row.dataset.pane), pane = S.panes[i];
  if (!pane.sel.has(row.dataset.n)) { pane.sel.clear(); pane.sel.add(row.dataset.n); }
  S.active = i;
  drag = { i, from: picked() };
  e.dataTransfer.setData("text/plain", drag.from.map(name).join("\n"));
  e.dataTransfer.effectAllowed = "copyMove";
});
const dropTarget = (e) => {
  const pane = e.target.closest("section.pane[data-pane]");
  if (!pane || !drag) return null;
  const j = Number(pane.dataset.pane), row = e.target.closest("tr[data-n]"), entry = row && S.panes[j].entries.find((x) => x.name === row.dataset.n);
  const folder = entry?.dir && !drag.from.includes(`${S.panes[j].path}/${entry.name}`) ? `${S.panes[j].path}/${entry.name}` : S.panes[j].path;
  return { j, row: entry?.dir ? row : null, to: folder };
};
document.addEventListener("dragover", (e) => {
  const hit = dropTarget(e);
  if (!hit) return;
  e.preventDefault();
  document.querySelectorAll("tr.drop").forEach((x) => x.classList.remove("drop"));
  hit.row?.classList.add("drop");
});
document.addEventListener("dragend", () => { drag = null; document.querySelectorAll("tr.drop").forEach((x) => x.classList.remove("drop")); });
document.addEventListener("drop", (e) => {
  const hit = dropTarget(e);
  if (!hit) return;
  e.preventDefault();
  const from = drag.from;
  drag = null;
  document.querySelectorAll("tr.drop").forEach((x) => x.classList.remove("drop"));
  if (from.every((p) => parentOf(p) === hit.to)) return TLToast.show(say("Drop on the other pane or on a folder.", "Déposez sur l'autre panneau ou sur un dossier."), "bad");
  showMenu(e.clientX, e.clientY, [
    { act: "dm", label: `${say("Move here", "Déplacer ici")} (${from.length})`, key: "F6", run: () => operate("move", { from, to: hit.to }) },
    { act: "dc", label: `${say("Copy here", "Copier ici")} (${from.length})`, key: "F5", run: () => operate("copy", { from, to: hit.to }) },
  ]);
});

function theme() {
  document.documentElement.dataset.theme = parent.document.documentElement.dataset.theme || "dark";
  document.documentElement.lang = parent.document.documentElement.lang || "fr";
}
theme();
new MutationObserver(() => { theme(); render(); }).observe(parent.document.documentElement, { attributes: true, attributeFilter: ["data-theme", "lang"] });
api("trash").then((t) => { S.owner = t.owner !== false; if (!S.owner && S.tab === "disks") S.tab = "explorer"; render(); }).catch(() => {});
render();
load();
window.addEventListener("files-environment", () => load());
if (window.filesReady) window.filesReady();
else bridge.then(() => window.filesReady?.());
setInterval(() => { if (!document.hidden) load(); }, 15000);
