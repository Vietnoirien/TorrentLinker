"use strict";
// Fichiers: Corbeille and Tâches (Explorateur, Disques and Organisation arrive with their own tickets).
const $ = (id) => document.getElementById(id);
const fr = () => (parent.document.documentElement.lang || "fr") === "fr";
const say = (en, french) => (fr() ? french : en);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const DAY = 86400;
const S = { tab: "disks", disks: null, trash: null, tasks: [], filter: "all", busy: false, sim: 4.2 };

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
      ${d.items.length ? `<button class="danger" data-k="empty" data-d="${esc(d.id)}">${say("Empty now", "Vider maintenant")}</button>` : ""}</h3>${notice}
      <div class="panel">${d.items.length ? `<table class="list"><thead><tr><th>${say("Name", "Nom")}</th><th>${say("Original location", "Emplacement d'origine")}</th><th>${say("Deleted", "Supprimé")}</th><th class="num">${say("Size", "Taille")}</th><th>${say("Purge", "Purge")}</th><th></th></tr></thead><tbody>
      ${d.items.map((i) => `<tr><td class="name">${esc(i.name)}${i.reason ? `<small>${esc(i.reason)}</small>` : ""}</td><td class="name" style="font-size:12.5px;color:var(--muted)">${esc(i.from)}</td>
        <td>${esc(i.by)}<small>${ago(i.at)}</small></td><td class="num">${size(i.size)}</td><td>${purge(i)}</td>
        <td class="num"><button data-k="restore" data-id="${esc(i.id)}" ${d.writable ? "" : "disabled"}>${say("Restore", "Restaurer")}</button></td></tr>`).join("")}</tbody></table>`
        : `<div class="empty">${say("This disk's trash is empty.", "La corbeille de ce disque est vide.")}</div>`}</div></section>`;
  }).join("");
  return `<p class="muted hint">${say(
    "Deleting, in Files, always means moving to the trash. Each disk has its own: the move is instant.",
    "Supprimer, dans Fichiers, veut toujours dire mettre à la corbeille. Chaque disque a la sienne : le déplacement est instantané.")}</p>
    <section class="card sect"><div class="row"><h3>${say("Retention", "Conservation")}</h3><label class="row">${say("Purge after", "Purger après")} <select data-k="ret">${[1, 3, 7, 14, 30].map((n) => `<option value="${n}" ${t.retention_days === n ? "selected" : ""}>${n} ${say(n > 1 ? "days" : "day", n > 1 ? "jours" : "jour")}</option>`).join("")}</select></label>
      <small style="display:inline">${say("7 days by default.", "7 jours par défaut.")}</small></div></section>${sections || `<div class="empty">${say("No storage folder is configured.", "Aucun dossier de stockage n'est configuré.")}</div>`}`;
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
    <dl class="kv"><dt>Films</dt><dd>${d.films} ${say(d.films === 1 ? "film" : "films", d.films === 1 ? "film" : "films")} ${say("in the Library Folders", "dans les dossiers de bibliothèque")}</dd></dl></article>`;
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
    <div class="disks">${d.disks.map(diskCard).join("")}${d.missing.map(missingCard).join("")}</div>
    ${d.disks.length ? `<div style="height:14px"></div>${placementHTML()}` : `<div class="empty">${say("No storage folder is configured.", "Aucun dossier de stockage n'est configuré.")}</div>`}`;
}
async function place() {
  try { S.placed = await api("disks/placement", { size: Math.round(S.sim * 1e9) }); } catch (e) { fail(e); }
}

const KINDS = {
  trash: ["Moved to the trash", "Mise à la corbeille"], restore: ["Restored", "Restauration"],
  purge: ["Daily purge of the trash", "Purge quotidienne de la corbeille"], empty: ["Trash emptied", "Corbeille vidée"],
};
const STATES = { pending: ["In progress", "En cours"], done: ["Done", "Terminé"], failed: ["Failed", "Échec"] };
function tasksHTML() {
  const rows = S.tasks.filter((o) => S.filter === "all" || (S.filter === "failed" ? o.state === "failed" : S.filter === "running" ? o.state === "pending" : o.state === "done"));
  const f = [["all", "All", "Toutes"], ["running", "Running", "En cours"], ["done", "Done", "Terminées"], ["failed", "Failed", "En échec"]];
  return `<div class="filters">${f.map(([k, en, french]) => `<button data-filter="${k}" class="${S.filter === k ? "on" : ""}">${say(en, french)}</button>`).join("")}</div>
    <div class="tasks">${rows.map((o) => {
      const name = (o.detail.from || "").split("/").pop() || (o.detail.items ? `${o.detail.items}` : "");
      return `<div class="card task ${o.state === "failed" ? "failed" : ""}"><div class="task-head"><b class="grow">${esc(say(...(KINDS[o.kind] || [o.kind, o.kind])))}${name ? ` · ${esc(name)}` : ""}</b>
        <span class="badge ${o.state === "done" ? "ok" : o.state === "failed" ? "bad" : ""}">${esc(say(...(STATES[o.state] || [o.state, o.state])))}</span>
        ${o.undoable ? `<button data-undo="${esc(o.id)}">${say("Undo", "Annuler")}</button>` : ""}</div>
        <small>${esc(o.actor)} · ${when(o.started)}</small>${o.error ? `<div class="reason">${esc(o.error)}</div>` : ""}</div>`;
    }).join("") || `<div class="empty">${say("No task for this filter.", "Aucune tâche pour ce filtre.")}</div>`}</div>`;
}

const TABS = [["disks", "Disks", "Disques"], ["trash", "Trash", "Corbeille"], ["tasks", "Tasks", "Tâches"]];
function render() {
  const tabs = TABS.map(([id, en, french]) => `<button data-tab="${id}" class="${S.tab === id ? "selected" : ""}">${say(en, french)}${id === "trash" && S.trash ? `<span class="badge count">${S.trash.disks.reduce((a, d) => a + d.items.length, 0)}</span>` : ""}</button>`).join("");
  $("app").innerHTML = `<nav class="tabs" role="tablist">${tabs}</nav>${S.tab === "trash" ? trashHTML() : S.tab === "disks" ? disksHTML() : tasksHTML()}`;
}
async function load() {
  try {
    if (S.tab === "disks") { S.disks = await api("disks"); await place(); }
    else if (S.tab === "trash") S.trash = await api("trash");
    else S.tasks = (await api("journal")).operations;
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
  const t = e.target.closest("[data-tab],[data-k],[data-filter],[data-undo]");
  if (!t) return;
  if (t.dataset.tab) { S.tab = t.dataset.tab; render(); load(); }
  else if (t.dataset.filter) { S.filter = t.dataset.filter; render(); }
  else if (t.dataset.undo) {
    try { await api(`journal/${t.dataset.undo}/undo`, {}); TLToast.show(say("Undone.", "Annulé.")); } catch (x) { fail(x); }
    load();
  } else if (t.dataset.k === "restore") {
    try { const r = await api(`trash/${t.dataset.id}/restore`, {}); TLToast.show(say(`Restored to ${r.restored}.`, `Restauré dans ${r.restored}.`)); } catch (x) { fail(x); }
    load();
  } else if (t.dataset.k === "empty") confirmEmpty(t.dataset.d);
});
document.addEventListener("change", async (e) => {
  if (e.target.dataset.k === "sim") { S.sim = Math.max(0.1, Number(e.target.value) || 4.2); await place(); render(); return; }
  if (e.target.dataset.k !== "ret") return;
  try { await api("trash/retention", { days: Number(e.target.value) }); TLToast.show(say("Retention saved.", "Conservation enregistrée.")); } catch (x) { fail(x); }
  load();
});

function theme() {
  document.documentElement.dataset.theme = parent.document.documentElement.dataset.theme || "dark";
  document.documentElement.lang = parent.document.documentElement.lang || "fr";
}
theme();
new MutationObserver(() => { theme(); render(); }).observe(parent.document.documentElement, { attributes: true, attributeFilter: ["data-theme", "lang"] });
render();
load();
window.addEventListener("files-environment", () => load());
if (window.filesReady) window.filesReady();
else bridge.then(() => window.filesReady?.());
setInterval(() => { if (!document.hidden) load(); }, 15000);
