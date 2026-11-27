"use strict";
// Fichiers: Corbeille and Tâches (Explorateur, Disques and Organisation arrive with their own tickets).
const $ = (id) => document.getElementById(id);
const fr = () => (parent.document.documentElement.lang || "fr") === "fr";
const say = (en, french) => (fr() ? french : en);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const DAY = 86400;
const S = { tab: "trash", trash: null, tasks: [], filter: "all", busy: false };

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

const TABS = [["trash", "Trash", "Corbeille"], ["tasks", "Tasks", "Tâches"]];
function render() {
  const tabs = TABS.map(([id, en, french]) => `<button data-tab="${id}" class="${S.tab === id ? "selected" : ""}">${say(en, french)}${id === "trash" && S.trash ? `<span class="badge count">${S.trash.disks.reduce((a, d) => a + d.items.length, 0)}</span>` : ""}</button>`).join("");
  $("app").innerHTML = `<nav class="tabs" role="tablist">${tabs}</nav>${S.tab === "trash" ? trashHTML() : tasksHTML()}`;
}
async function load() {
  try {
    if (S.tab === "trash") S.trash = await api("trash");
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
