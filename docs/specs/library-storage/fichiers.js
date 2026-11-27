"use strict";
// Preview "Fichiers": the page, the Explorateur and Tâches. Disques, Corbeille and Organisation are in fichiers-storage.js.
// No backend: the tree, the disks and the clients are in storage.json; operations change the in-memory tree through a task queue.
const BASE = "/library-storage-preview/";
const FX = (window.FX = {});
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const DAY = 86400000;
const S = FX.S = {
  hddMounted: true,
  data: null, roots: {}, disks: {}, tab: "explorer", member: false, active: 0, tasks: [], trash: [], retention: 7,
  panes: [], smartctl: true, scrutinyUrl: "", failNext: false, nid: 100, mobile: false, org: null,
  autoTidy: { d1: false, d2: false },
};
FX.GRANTED = "Films"; // the member's granted Library Folder

// ---- formatting ----------------------------------------------------------------------------------------
const nf = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
const size = gb => gb <= 0 ? "0 Go" : gb >= 1000 ? nf.format(gb / 1000) + " To" : gb >= 1 ? nf.format(gb) + " Go" : gb >= 0.001 ? Math.round(gb * 1000) + " Mo" : Math.max(1, Math.round(gb * 1e6)) + " Ko";
const num = n => nf.format(n);
const dateOf = age => new Date(Date.now() - age * DAY).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
const ago = ms => {
  const m = Math.max(0, Math.round((Date.now() - ms) / 60000));
  return m < 1 ? "à l'instant" : m < 60 ? `il y a ${m} min` : m < 1440 ? `il y a ${Math.round(m / 60)} h` : `il y a ${Math.round(m / 1440)} j`;
};
const dur = sec => sec < 5 ? "quelques secondes" : sec < 90 ? `${Math.round(sec)} s` : sec < 5400 ? `${Math.round(sec / 60)} min` : `${num(sec / 3600)} h`;
const SPEED = 0.15; // GB/s of a disk-to-disk copy, for the estimates
Object.assign(FX, { esc, size, num, dateOf, ago, dur, $ });
const toast = (text, kind) => typeof TLToast !== "undefined" ? TLToast.show(text, kind) : console.log(text);
FX.toast = toast;

// ---- tree ----------------------------------------------------------------------------------------------
const clone = o => JSON.parse(JSON.stringify(o));
const mount = d => S.disks[d].mount;
const fullPath = (disk, path) => [mount(disk), ...path].join("/");
const rootList = disk => S.roots[disk];
const liveIds = () => Object.keys(S.disks).filter(id => id !== "d3" || S.hddMounted);
FX.liveIds = liveIds;
function nodeAt(disk, path) {
  let list = rootList(disk), node = { d: 1, c: list, n: "", root: 1 };
  for (const part of path) {
    node = (node.c || []).find(c => c.n === part);
    if (!node) return null;
  }
  return node;
}
function ensureDir(disk, path) {
  let node = { d: 1, c: rootList(disk) };
  for (const part of path) {
    let next = node.c.find(c => c.n === part);
    if (!next) { next = { n: part, d: 1, age: 0, c: [] }; node.c.push(next); }
    node = next;
  }
  return node;
}
const sizeOf = n => (n.s || 0) + (n.c || []).reduce((a, c) => a + sizeOf(c), 0);
const countFiles = n => n.d ? (n.c || []).reduce((a, c) => a + countFiles(c), 0) : 1;
const keyOf = n => n.d ? "D[" + (n.c || []).map(c => c.n + ":" + keyOf(c)).sort().join(",") + "]" : n.hash || "";
function seedOf(n) { return n.seed || (n.c || []).map(seedOf).find(Boolean) || null; }
function filmOf(n) { return n.film ? n : (n.c || []).map(filmOf).find(Boolean) || null; }
Object.assign(FX, { nodeAt, ensureDir, sizeOf, seedOf, filmOf, fullPath, clone, keyOf, countFiles });

function discUsage(id) {
  const d = S.disks[id], sum = (list, test) => list.filter(test).reduce((a, n) => a + sizeOf(n), 0);
  const lib = sum(rootList(id), n => n.lib), dl = sum(rootList(id), n => n.dl);
  const tr = S.trash.filter(t => t.disk === id).reduce((a, t) => a + t.size, 0);
  const used = d.other + lib + dl + tr;
  let films = 0;
  const walk = n => { if (n.film && n.d && n.poster !== undefined) films++; else (n.c || []).forEach(walk); };
  rootList(id).filter(n => n.lib === "Films").forEach(n => (n.c || []).forEach(walk));
  return { lib, dl, tr, used, free: Math.max(0, d.total - used), films, margin: d.total * 0.1, usable: Math.max(0, d.total - used - d.total * 0.1) };
}
Object.assign(FX, { discUsage });
FX.place = (gb, together) => {
  const ids = liveIds(), u = id => discUsage(id).usable;
  if (together && u(together) >= gb) return { disk: together, why: `garde les versions ou les épisodes ensemble sur ${S.disks[together].name}` };
  const best = ids.slice().sort((a, b) => u(b) - u(a))[0];
  return { disk: best, why: together ? `${S.disks[together].name} n'a plus assez de place au-dessus de la marge : le disque le plus libre` : "pas de version ou d'épisode déjà présent : le disque le plus libre au-dessus de la marge de 10 %" };
};

// ---- who / permissions ---------------------------------------------------------------------------------
const who = () => S.member ? "Camille (membre)" : "Vous";
const allowed = (disk, path) => !S.member || (rootList(disk).find(r => r.n === path[0])?.lib === FX.GRANTED);
function places() {
  const out = [];
  for (const id of liveIds()) {
    if (S.member) {
      for (const r of rootList(id)) if (r.lib === FX.GRANTED) out.push({ disk: id, path: [r.n], label: `${S.disks[id].name} › ${r.n} · dossier de bibliothèque` });
      continue;
    }
    out.push({ disk: id, path: [], label: `${S.disks[id].name} · ${size(discUsage(id).free)} libres` });
    for (const r of rootList(id)) out.push({ disk: id, path: [r.n], label: `    ${r.n} · ${r.lib ? "dossier de bibliothèque" : r.dl ? "dossier de téléchargement" : "dossier"}` });
  }
  return out;
}
FX.places = places;

// ---- panes ---------------------------------------------------------------------------------------------
function newPane(disk, path) { return { disk, path, sel: new Set(), cursor: null, anchor: null, sort: { key: "name", dir: 1 } }; }
function resetPanes() {
  S.panes = S.member ? [newPane("d1", [FX.GRANTED]), newPane("d2", [FX.GRANTED])] : [newPane("d1", ["Films"]), newPane("d1", ["Téléchargements"])];
  S.active = 0;
}
const pane = i => S.panes[i];
const listOf = p => {
  const dir = nodeAt(p.disk, p.path);
  if (!dir) return [];
  const { key, dir: sd } = p.sort;
  const val = n => key === "size" ? sizeOf(n) : key === "date" ? -(n.age || 0) : n.n.toLowerCase();
  return (dir.c || []).slice().sort((a, b) => (b.d ? 1 : 0) - (a.d ? 1 : 0) || (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * sd);
};
const minDepth = () => S.member ? 1 : 0;

function icon(n) {
  if (n.poster !== undefined && n.film) return `<span class="ico"><img src="${BASE}poster-${n.poster}.png" alt="" width="28" height="42" loading="lazy"></span>`;
  const e = n.d ? "📁" : /\.(mkv|mp4|avi)$/i.test(n.n) ? "🎞️" : /\.(srt|nfo|txt)$/i.test(n.n) ? "📄" : "▫️";
  return `<span class="ico small">${e}</span>`;
}
const seedBadge = n => {
  const s = seedOf(n);
  return s ? `<span class="badge ok seed" title="Un torrent utilise ces fichiers">▲ ${esc(s.client)} · ratio ${num(s.ratio)}</span>` : "";
};

const tip = (text, label) => (FX.tipBtn ? FX.tipBtn(text, label) : "");
const TAB_TIPS = {
  explorer: () => "Cliquez pour sélectionner (Ctrl ou Maj pour plusieurs), double-clic pour ouvrir, glissez d'un panneau à l'autre, clic droit pour le menu." + (S.member ? " Vue membre : vous ne gérez que vos dossiers de bibliothèque accordés." : ""),
  tasks: () => "Les opérations de Fichiers s'exécutent ici, en arrière-plan : vous pouvez fermer le navigateur. Chaque élément est vérifié, rien n'échoue en silence. Le journal garde qui, quoi et quand ; chaque déplacement ou renommage terminé peut être annulé. Dans l'aperçu, les durées sont accélérées.",
  disks: () => "Chaque disque est monté séparément. La corbeille est comptée à part. Les alertes de santé viennent de smartctl ou de Scrutiny (réglages ⚙).",
  trash: () => "Supprimer, dans Fichiers, veut toujours dire mettre à la corbeille. Chaque disque a la sienne : le déplacement est instantané." + (S.member ? " Vous ne voyez que ce qui vient de vos dossiers de bibliothèque accordés." : ""),
};
function explorerHTML() {
  const narrow = innerWidth < 800;
  const panesHTML = S.panes.map((p, i) => {
    if (narrow && i !== S.active) return "";
    const u = discUsage(p.disk), d = S.disks[p.disk], dir = nodeAt(p.disk, p.path), rows = listOf(p);
    const crumbs = [`<button data-go="${i}:-1" ${S.member ? "disabled" : ""}>${esc(d.name)}</button>`]
      .concat(p.path.map((n, k) => `<span>›</span><button data-go="${i}:${k}" ${S.member && k < 0 ? "disabled" : ""}>${esc(n)}</button>`)).join("");
    const pct = Math.min(100, (u.used / d.total) * 100);
    const cls = pct > 99 ? "bad" : pct > 90 ? "warn" : "";
    const place = places().findIndex(x => x.disk === p.disk && (p.path.length ? x.path[0] === p.path[0] && x.path.length === 1 : x.path.length === 0));
    const th = (k, label, c = "") => `<th class="${c}"><button class="quiet" data-sort="${i}:${k}" style="padding:0;border:0">${label}${p.sort.key === k ? (p.sort.dir > 0 ? " ▲" : " ▼") : ""}</button></th>`;
    return `<section class="pane ${i === S.active ? "active" : ""}" data-pane="${i}">
      <div class="pane-head">
        <div class="row"><select data-place="${i}" aria-label="Disque ou dossier">${places().map((x, k) => `<option value="${k}" ${k === place ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select>
          <button data-up="${i}" title="Dossier parent (Retour arrière)" ${p.path.length <= minDepth() ? "disabled" : ""}>↑</button></div>
        <div class="crumbs">${crumbs}</div>
        ${S.member ? `<div class="space"><span>Accès limité au dossier de bibliothèque « ${FX.GRANTED} » (Gérer les fichiers)</span></div>` :
          `<div class="space"><div class="bar" title="La marge de 10 % est marquée"><i class="${cls}" style="width:${pct}%"></i><u style="left:90%"></u></div>
          <span>${size(u.free)} libres sur ${size(d.total)} · ${size(u.usable)} utilisables avant la marge de 10 %</span></div>`}
      </div>
      <div class="files" tabindex="0" data-files="${i}">
        <table class="list"><thead><tr><th></th>${th("name", "Nom")}${th("size", "Taille", "num")}${th("date", "Modifié", "date")}<th>Partage</th></tr></thead>
        <tbody>${rows.map(n => {
          const film = n.film && n.poster !== undefined ? `<small>${esc(n.film)}</small>` : "";
          return `<tr draggable="true" data-i="${i}" data-name="${esc(n.n)}" class="${p.sel.has(n.n) ? "sel" : ""} ${p.cursor === n.n ? "cursor" : ""}">
            <td style="width:40px">${icon(n)}</td><td class="name">${esc(n.n)}${film}</td><td class="num">${size(sizeOf(n))}</td><td class="date">${dateOf(n.age || 0)}</td><td>${seedBadge(n)}</td></tr>`;
        }).join("") || `<tr><td colspan="5" class="empty">${p.disk === "d3" ? "Dossier vide, sur le disque neuf. Glissez-y des fichiers depuis l'autre panneau." : "Dossier vide"}</td></tr>`}</tbody></table>
      </div>
      <div class="pane-foot"><span>${rows.length} élément${rows.length > 1 ? "s" : ""} · ${p.sel.size} sélectionné${p.sel.size > 1 ? "s" : ""}</span><span>${esc(fullPath(p.disk, p.path))}</span></div>
    </section>`;
  }).join("");
  const sw = narrow ? `<div class="row hint"><button data-switch="0" class="${S.active === 0 ? "on" : ""}">Panneau 1</button><button data-switch="1" class="${S.active === 1 ? "on" : ""}">Panneau 2</button></div>` : "";
  return `${sw}
    <div class="panes">${panesHTML}</div>
    <div class="fkeys"><button data-f="rename"><kbd>F2</kbd>Renommer</button><button data-f="copy"><kbd>F5</kbd>Copier</button><button data-f="move"><kbd>F6</kbd>Déplacer</button>
      <button data-f="mkdir"><kbd>F7</kbd>Nouveau dossier</button><button data-f="trash" class="danger"><kbd>Suppr</kbd>Mettre à la corbeille</button></div>`;
}

// ---- selection -----------------------------------------------------------------------------------------
function paintSel(i) {
  const p = pane(i), box = document.querySelector(`[data-pane="${i}"]`);
  if (!box) return;
  for (const tr of box.querySelectorAll("tbody tr[data-name]")) {
    tr.classList.toggle("sel", p.sel.has(tr.dataset.name));
    tr.classList.toggle("cursor", p.cursor === tr.dataset.name);
  }
  box.querySelector(".pane-foot span").textContent = `${listOf(p).length} élément${listOf(p).length > 1 ? "s" : ""} · ${p.sel.size} sélectionné${p.sel.size > 1 ? "s" : ""}`;
  document.querySelectorAll(".pane").forEach(el => el.classList.toggle("active", +el.dataset.pane === S.active));
}
function select(i, name, ev = {}) {
  const p = pane(i), names = listOf(p).map(n => n.n);
  S.active = i;
  if (ev.shiftKey && p.anchor) {
    const a = names.indexOf(p.anchor), b = names.indexOf(name);
    p.sel = new Set(names.slice(Math.min(a, b), Math.max(a, b) + 1));
  } else if (ev.ctrlKey || ev.metaKey) {
    p.sel.has(name) ? p.sel.delete(name) : p.sel.add(name);
    p.anchor = name;
  } else { p.sel = new Set([name]); p.anchor = name; }
  p.cursor = name;
  paintSel(i); paintSel(1 - i);
}
function selected(i) { const p = pane(i); return listOf(p).filter(n => p.sel.has(n.n)); }
function go(i, path) {
  const p = pane(i);
  if (S.member && !allowed(p.disk, path)) return;
  p.path = path; p.sel = new Set(); p.cursor = null; p.anchor = null; S.active = i;
  render();
}
const openNode = (i, n) => {
  if (n.d) return go(i, [...pane(i).path, n.n]);
  toast(`Ouverture de « ${n.n} » : le navigateur télécharge ou affiche le fichier.`);
};

// ---- menu ----------------------------------------------------------------------------------------------
const menu = () => $("menu");
function showMenu(x, y, items) {
  const m = menu();
  m.innerHTML = items.map(it => it === "-" ? "<hr>" : `<button data-act="${it.act}" ${it.off ? "disabled" : ""}><span>${esc(it.label)}</span><span class="kbd">${esc(it.key || "")}</span></button>`).join("");
  m.hidden = false;
  const w = m.offsetWidth, h = m.offsetHeight;
  m.style.left = Math.max(4, Math.min(x, innerWidth - w - 6)) + "px";
  m.style.top = Math.max(4, Math.min(y, innerHeight - h - 6)) + "px";
  m._items = items;
}
const hideMenu = () => { menu().hidden = true; };
addEventListener("click", e => { if (!e.target.closest("#menu")) hideMenu(); });
addEventListener("blur", hideMenu);
addEventListener("scroll", hideMenu, true);
menu().addEventListener("click", e => {
  const b = e.target.closest("button[data-act]");
  if (!b) return;
  const it = menu()._items.find(x => x.act === b.dataset.act);
  hideMenu();
  it?.run?.();
});

function contextMenu(ev, i, name) {
  ev.preventDefault();
  const p = pane(i);
  S.active = i;
  if (name) { if (!p.sel.has(name)) select(i, name, {}); }
  const items = selected(i), one = items.length === 1 ? items[0] : null, other = 1 - i;
  const film = one && filmOf(one), seed = one && seedOf(one);
  const none = !items.length;
  const menuItems = [
    { act: "open", label: "Ouvrir", key: "Entrée", off: !one, run: () => openNode(i, one) },
    { act: "play", label: "Lire dans Médias", off: !film, run: () => { toast(`« ${film.film} » s'ouvre dans Médias.`); parent.location.hash = "#/media"; } },
    "-",
    { act: "rename", label: "Renommer", key: "F2", off: !one, run: () => renameDialog(i) },
    { act: "moveto", label: "Déplacer vers…", key: "F6", off: none, run: () => transfer("move", i, true) },
    { act: "copyto", label: "Copier vers…", key: "F5", off: none, run: () => transfer("copy", i, true) },
    { act: "mkdir", label: "Nouveau dossier", key: "F7", run: () => mkdirDialog(i) },
    "-",
    { act: "trash", label: "Mettre à la corbeille", key: "Suppr", off: none, run: () => trashDialog(i) },
    "-",
    { act: "torrent", label: "Voir le torrent", off: !seed, run: () => { toast(`Torrent de « ${one.n} » dans ${seed.client}.`); parent.location.hash = "#/torrents"; } },
    { act: "props", label: "Propriétés", off: !one, run: () => propsDialog(one, i) },
  ];
  showMenu(ev.clientX, ev.clientY, menuItems);
}

// ---- dialogs -------------------------------------------------------------------------------------------
function modal(html) {
  const d = document.createElement("dialog");
  d.innerHTML = html;
  document.body.append(d);
  d.addEventListener("close", () => d.remove());
  d.showModal();
  return d;
}
FX.modal = modal;
function propsDialog(n, i) {
  const p = pane(i), s = seedOf(n), f = filmOf(n);
  const d = modal(`<h2>Propriétés</h2><dl class="props">
    <dt>Nom</dt><dd>${esc(n.n)}</dd><dt>Emplacement</dt><dd>${esc(fullPath(p.disk, p.path))}</dd>
    <dt>Type</dt><dd>${n.d ? `Dossier · ${countFiles(n)} fichier${countFiles(n) > 1 ? "s" : ""}` : "Fichier"}</dd>
    <dt>Taille</dt><dd>${size(sizeOf(n))}</dd><dt>Modifié</dt><dd>${dateOf(n.age || 0)}</dd><dt>Disque</dt><dd>${esc(S.disks[p.disk].name)} (${esc(S.disks[p.disk].model)})</dd>
    ${f ? `<dt>Film</dt><dd>${esc(f.film)} · connu de Médias</dd>` : ""}
    ${!n.d && n.hash ? `<dt>Somme SHA-1</dt><dd>${esc(n.hash)}</dd>` : ""}
    ${s ? `<dt>Partage</dt><dd>${esc(s.client)} · ratio ${num(s.ratio)} · ${s.hours} h<br><small>${esc(s.hash)}</small></dd>` : "<dt>Partage</dt><dd>Aucun torrent n'utilise ce fichier</dd>"}</dl>
    <div class="dialog-foot"><button class="primary" data-close>Fermer</button></div>`);
  d.onclick = e => { if (e.target.closest("[data-close]")) d.close(); };
}
function mkdirDialog(i) {
  const p = pane(i), dir = nodeAt(p.disk, p.path);
  const d = modal(`<h2>Nouveau dossier</h2><p class="muted">Dans ${esc(fullPath(p.disk, p.path))}</p>
    <input id="mk" value="Nouveau dossier" style="width:100%"><p class="reason" id="mkerr" style="color:var(--danger)"></p>
    <div class="dialog-foot"><button data-close>Annuler</button><button class="primary" id="mkok">Créer</button></div>`);
  const input = d.querySelector("#mk");
  input.select();
  const ok = () => {
    const v = input.value.trim();
    if (!v || /[\\/]/.test(v)) return (d.querySelector("#mkerr").textContent = "Nom invalide : il ne doit pas être vide ni contenir de barre.");
    if (dir.c.some(c => c.n === v)) return (d.querySelector("#mkerr").textContent = "Ce nom existe déjà ici.");
    dir.c.push({ n: v, d: 1, age: 0, c: [] });
    logDone("mkdir", `Créer le dossier « ${v} »`, [{ name: v, from: fullPath(p.disk, p.path), to: fullPath(p.disk, p.path), size: 0, mode: "Création d'un dossier" }]);
    d.close(); render();
  };
  d.onclick = e => { if (e.target.closest("[data-close]")) d.close(); if (e.target.id === "mkok") ok(); };
  input.onkeydown = e => { if (e.key === "Enter") ok(); };
}
function renameDialog(i) {
  const [n] = selected(i);
  if (!n) return;
  const p = pane(i), dir = nodeAt(p.disk, p.path), s = seedOf(n);
  const d = modal(`<h2>Renommer</h2><p class="muted">${esc(fullPath(p.disk, p.path))}</p><input id="rn" style="width:100%" value="${esc(n.n)}">
    ${s ? `<div class="note row">En partage dans <b>${esc(s.client)}</b> : renommé aussi dans le client ${tip("Le nom est changé dans le client (chemin du torrent), pas seulement sur le disque. " + (FX.clientOf(s.client)?.native ? "Aucune revérification nécessaire." : "Ce client ne sait pas renommer : le nom est changé sur le disque puis le torrent est re-pointé et revérifié, comme pour Remise en seed."), "Détails")}</div>` : ""}
    <p id="rnerr" style="color:var(--danger)"></p><div class="dialog-foot"><button data-close>Annuler</button><button class="primary" id="rnok">Renommer</button></div>`);
  const input = d.querySelector("#rn");
  input.focus(); input.setSelectionRange(0, n.d ? n.n.length : n.n.lastIndexOf(".") > 0 ? n.n.lastIndexOf(".") : n.n.length);
  const ok = () => {
    const v = input.value.trim();
    if (!v || /[\\/]/.test(v)) return (d.querySelector("#rnerr").textContent = "Nom invalide.");
    if (v === n.n) return d.close();
    if (dir.c.some(c => c.n === v)) return (d.querySelector("#rnerr").textContent = "Ce nom existe déjà ici.");
    d.close();
    enqueue({ kind: "rename", label: `Renommer « ${n.n} »`, items: [makeItem("rename", n, p, p, { newName: v })] });
  };
  d.onclick = e => { if (e.target.closest("[data-close]")) d.close(); if (e.target.id === "rnok") ok(); };
  input.onkeydown = e => { if (e.key === "Enter") ok(); };
}
function trashDialog(i) {
  const items = selected(i);
  if (!items.length) return;
  const p = pane(i), seeded = items.filter(seedOf);
  const total = items.reduce((a, n) => a + sizeOf(n), 0);
  const d = modal(`<h2>Mettre à la corbeille</h2><p class="row">${items.length} élément${items.length > 1 ? "s" : ""} · ${size(total)} → corbeille de ${esc(S.disks[p.disk].name)} ${tip(`Rien n'est effacé : ${items.length > 1 ? "ils vont" : "il va"} dans la corbeille du disque (déplacement instantané) et ${items.length > 1 ? "restent restaurables" : "reste restaurable"} ${S.retention} jours.`, "Détails")}</p>
    <div class="dlg-list">${items.map(n => `<div class="dlg-item"><span>${esc(n.n)}</span><small>${size(sizeOf(n))}</small></div>`).join("")}</div>
    ${seeded.length ? `<div class="note warn row">${seeded.length} en partage (${[...new Set(seeded.map(n => seedOf(n).client))].join(", ")}) : retiré du client ${tip("Le torrent est retiré du client sans ses données, comme pour « Remplacer ». Pour le garder, restaurez-le depuis la corbeille puis re-pointez-le.", "Détails")}</div>` : ""}
    <div class="dialog-foot"><button data-close>Annuler</button><button class="primary danger" id="ok">Mettre à la corbeille</button></div>`);
  d.onclick = e => {
    if (e.target.closest("[data-close]")) d.close();
    if (e.target.id === "ok") { d.close(); enqueue({ kind: "trash", label: `Mettre ${items.length} élément${items.length > 1 ? "s" : ""} à la corbeille`, items: items.map(n => makeItem("trash", n, p, p)) }); }
  };
}
FX.clientOf = name => S.data.clients.find(c => c.name === name);

// A folder picker (for "Déplacer vers…" and "Choisir…"); resolves {disk, path} or null.
function pickFolder(start, title = "Choisir la destination") {
  return new Promise(resolve => {
    let cur = { disk: start.disk, path: start.path.slice() };
    const walk = (disk, list, path, depth, out) => {
      for (const n of list.filter(c => c.d).sort((a, b) => a.n.localeCompare(b.n, "fr"))) {
        const p = [...path, n.n];
        if ((S.member && !allowed(disk, p)) || n.film) continue;
        out.push(`<button data-d="${disk}" data-p="${esc(JSON.stringify(p))}" class="${cur.disk === disk && cur.path.join("/") === p.join("/") ? "on" : ""}" style="padding-left:${8 + depth * 18}px">📁 ${esc(n.n)}</button>`);
        if (depth < 2) walk(disk, n.c || [], p, depth + 1, out);
      }
    };
    const d = modal(`<h2>${title}</h2><div class="tree" id="tree"></div><p class="muted" id="where"></p>
      <div class="dialog-foot"><button data-close>Annuler</button><button class="primary" id="pk">Choisir ce dossier</button></div>`);
    const paint = () => {
      const out = [];
      for (const id of liveIds()) {
        if (S.member) { walk(id, rootList(id).filter(r => r.lib === FX.GRANTED), [], 0, out); continue; }
        out.push(`<button data-d="${id}" data-p="[]" class="${cur.disk === id && !cur.path.length ? "on" : ""}">💽 <b>${esc(S.disks[id].name)}</b> <small>${size(discUsage(id).free)} libres</small></button>`);
        walk(id, rootList(id), [], 1, out);
      }
      d.querySelector("#tree").innerHTML = out.join("");
      d.querySelector("#where").textContent = fullPath(cur.disk, cur.path);
    };
    paint();
    d.onclick = e => {
      const b = e.target.closest("#tree button");
      if (b) { cur = { disk: b.dataset.d, path: JSON.parse(b.dataset.p) }; paint(); }
      if (e.target.closest("[data-close]")) d.close();
      if (e.target.id === "pk") { resolve(cur); d.close(); }
    };
    d.addEventListener("close", () => resolve(null));
  });
}
FX.pickFolder = pickFolder;

// ---- transfer: confirmation (instant or copy, seeded or not), conflicts, then a task -------------------
function describeItem(n, from, to, mode) {
  const sz = sizeOf(n), seed = seedOf(n), same = from.disk === to.disk;
  const info = { n, sz, seed, same };
  const dest = S.disks[to.disk].name;
  const copyBit = `Copie vers ${dest} · ${size(sz)} · ~${dur(sz / SPEED)}`;
  if (seed) {
    const client = FX.clientOf(seed.client), native = client?.native;
    info.client = seed.client; info.native = native;
    const how = { qBittorrent: "setLocation", Transmission: "torrent-set-location", Deluge: "move_storage" }[seed.client];
    if (mode === "copy") { info.short = same ? `Copie sur le même disque · ${size(sz)}` : copyBit; info.tip = "Le torrent reste en place et continue de partager l'original ; la copie n'est pas partagée."; }
    else if (native) { info.short = same ? `Instantané · ${seed.client} déplace` : `${copyBit} · ${seed.client} déplace`; info.tip = `En partage dans ${seed.client} (ratio ${num(seed.ratio)}). Le client déplace lui-même les fichiers (${how}) et continue de partager.${same ? "" : " Il supprime l'original après la copie."}`; }
    else { info.short = same ? `Instantané · géré par TorrentLinker` : `${copyBit} · géré par TorrentLinker`; info.tip = `En partage dans ${seed.client} (ratio ${num(seed.ratio)}). Ce client ne déplace pas ses fichiers : TorrentLinker le fait à sa place. Pause → Déplacement → Re-pointage → Revérification (~${dur(sz / (SPEED * 1.4))}) → Reprise. La reprise est toujours tentée, même après une erreur.`; }
  } else {
    info.short = same && mode === "move" ? "Instantané (même disque)" : same ? `Copie sur le même disque · ${size(sz)} · ~${dur(sz / SPEED)}` : copyBit;
    info.tip = same && mode === "move" ? "Seul le chemin change." : mode === "move" ? "L'original est supprimé après vérification de la copie." : "";
  }
  info.instant = same && mode === "move";
  return info;
}
async function transfer(mode, i, choose, drop) {
  const items = drop ? drop.items : selected(i);
  if (!items.length) return toast("Sélectionnez d'abord des éléments.");
  const from = { disk: pane(i).disk, path: pane(i).path.slice() };
  let to = drop ? drop.to : { disk: pane(1 - i).disk, path: pane(1 - i).path.slice() };
  if (choose) {
    const picked = await pickFolder(to, mode === "move" ? "Déplacer vers…" : "Copier vers…");
    if (!picked) return;
    to = picked;
  }
  confirmTransfer(mode, items, from, to, i);
}
function confirmTransfer(mode, items, from, to, i) {
  const verb = mode === "move" ? "Déplacer" : "Copier";
  const draw = () => {
    const infos = items.map(n => describeItem(n, from, to, mode));
    const total = infos.reduce((a, x) => a + (x.instant ? 0 : x.sz), 0);
    const u = discUsage(to.disk), cross = infos.filter(x => !x.same).reduce((a, x) => a + x.sz, 0) + (mode === "copy" ? infos.filter(x => x.same).reduce((a, x) => a + x.sz, 0) : 0);
    const sameFolder = from.disk === to.disk && from.path.join("/") === to.path.join("/");
    const inside = items.some(n => n.d && from.disk === to.disk && to.path.join("/").startsWith([...from.path, n.n].join("/")));
    const lowFree = cross > u.free, lowMargin = !lowFree && cross > u.usable;
    const eta = infos.reduce((a, x) => a + (x.instant ? 0 : x.sz / SPEED), 0);
    return { infos, total, u, cross, sameFolder, inside, lowFree, lowMargin, eta };
  };
  let st = draw();
  const d = modal(`<h2></h2><p class="muted" id="sum"></p>
    <div class="row"><b>Destination</b><span id="dest" class="grow" style="word-break:break-all"></span><button id="change">Choisir…</button></div>
    <div class="dlg-list" id="list"></div><div id="warn"></div>
    <div class="dialog-foot"><button data-close>Annuler</button><button class="primary" id="go"></button></div>`);
  const paint = () => {
    st = draw();
    d.querySelector("h2").textContent = `${verb} ${items.length} élément${items.length > 1 ? "s" : ""}`;
    d.querySelector("#sum").textContent = `${size(items.reduce((a, n) => a + sizeOf(n), 0))} · de ${fullPath(from.disk, from.path)}`;
    d.querySelector("#dest").textContent = fullPath(to.disk, to.path);
    d.querySelector("#list").innerHTML = st.infos.map(x => `<div class="dlg-item"><b style="word-break:break-all">${esc(x.n.n)}</b><div class="mode row ${x.instant ? "instant" : "copy"}">${esc(x.short)}${x.tip ? " " + tip(x.tip, "Détails") : ""}</div></div>`).join("");
    const w = [];
    if (st.sameFolder) w.push(`<div class="note warn">Même dossier que l'origine.</div>`);
    if (st.inside) w.push(`<div class="note warn">Un dossier ne peut pas entrer dans lui-même.</div>`);
    if (st.lowFree) w.push(`<div class="note warn row">Place insuffisante sur ${esc(S.disks[to.disk].name)} : ${size(st.u.free)} libres, ${size(st.cross)} nécessaires ${tip("L'élément sera marqué en échec dans Tâches, sans rien perdre.", "Détails")}</div>`);
    else if (st.lowMargin) w.push(`<div class="note warn row">${esc(S.disks[to.disk].name)} passerait sous la marge de 10 % ${tip(`Il reste ${size(st.u.usable)} utilisables avant la marge de 10 % d'espace libre.`, "Détails")}</div>`);
    if (st.eta > 0) w.push(`<div class="note row">Durée : ~${dur(st.eta)} ${tip(`Copie à ${Math.round(SPEED * 1000)} Mo/s. L'opération continue en arrière-plan dans l'onglet Tâches ; chaque élément est vérifié.`, "Détails")}</div>`);
    d.querySelector("#warn").innerHTML = w.join("");
    const go = d.querySelector("#go");
    go.textContent = verb;
    go.disabled = st.sameFolder || st.inside;
  };
  paint();
  d.onclick = async e => {
    if (e.target.closest("[data-close]")) d.close();
    if (e.target.id === "change") { const p = await pickFolder(to); if (p) { to = p; paint(); } }
    if (e.target.id === "go") { d.close(); const plan = await resolveConflicts(mode, items, from, to); if (plan) startTransfer(mode, plan, from, to, i); }
  };
}

// Conflict dialog: Ignorer / Remplacer (old to the trash) / Renommer, "appliquer à tous"; identical files offer "Garder un seul".
async function resolveConflicts(mode, items, from, to) {
  const dest = nodeAt(to.disk, to.path), plan = [];
  let all = null;
  for (const n of items) {
    const old = dest.c.find(c => c.n === n.n);
    if (!old) { plan.push({ n, choice: "go" }); continue; }
    const same = keyOf(old) === keyOf(n) && keyOf(n) !== "";
    let choice = all && (all !== "keepone" || same) ? all : null;
    if (!choice) {
      const r = await conflictDialog(n, old, same, items.filter(x => dest.c.some(c => c.n === x.n)).length > 1);
      if (!r) return null;
      choice = r.choice;
      if (r.all) all = choice;
    }
    plan.push({ n, choice, old });
  }
  return plan;
}
function conflictDialog(n, old, same, many) {
  return new Promise(resolve => {
    const row = (label, x) => `<div class="dlg-item"><b>${label}</b><span style="word-break:break-all">${esc(x.n)}</span><small>${size(sizeOf(x))} · ${dateOf(x.age || 0)}${x.hash ? " · " + esc(x.hash.slice(0, 10)) + "…" : ""}</small></div>`;
    const d = modal(`<h2>« ${esc(n.n)} » existe déjà</h2>
      <div class="dlg-list">${row("Déjà dans la destination", old)}${row("À déplacer ou copier", n)}</div>
      ${same ? `<div class="note row">Les deux sont <b>identiques</b> ${tip("Même somme SHA-1 : inutile d'en garder deux.", "Détails")}</div>` : `<div class="note warn">Les contenus sont <b>différents</b>.</div>`}
      <label class="row"><input type="checkbox" id="all"> Appliquer à tous les conflits suivants</label>
      <div class="dialog-foot">${tip("Remplacer envoie l'ancien fichier à la corbeille. Renommer garde les deux, le nouveau devient « " + n.n + " (2) ». Ignorer ne touche à rien.", "Aide")}<span class="grow"></span><button data-c="skip">Ignorer</button><button data-c="replace" class="danger">Remplacer</button><button data-c="rename">Renommer</button>
        ${same ? `<button data-c="keepone" class="primary">Garder un seul</button>` : ""}<button data-close>Annuler tout</button></div>`);
    if (!many) d.querySelector("#all").closest("label").hidden = true;
    let done = false;
    d.onclick = e => {
      const b = e.target.closest("[data-c]");
      if (b) { done = true; resolve({ choice: b.dataset.c, all: d.querySelector("#all").checked }); d.close(); }
      if (e.target.closest("[data-close]")) d.close();
    };
    d.addEventListener("close", () => { if (!done) resolve(null); });
  });
}
function startTransfer(mode, plan, from, to, i) {
  const items = [], skipped = [];
  for (const { n, choice, old } of plan) {
    if (choice === "skip") { skipped.push(n.n); continue; }
    if (choice === "keepone") {
      // The destination copy stays; for a move the duplicate source goes to the trash, for a copy nothing happens.
      if (mode === "move") items.push(makeItem("trash", n, from, from, { note: "Doublon identique : une seule copie gardée" }));
      else skipped.push(n.n);
      continue;
    }
    items.push(makeItem(mode, n, from, to, { conflict: choice, old }));
  }
  if (!items.length) { toast(skipped.length ? "Rien à faire : tous les éléments ont été ignorés." : "Rien à faire."); return; }
  const verb = mode === "move" ? "Déplacer" : "Copier";
  enqueue({ kind: mode, label: items.length === 1 ? `${verb} « ${items[0].name} »` : `${verb} ${items.length} éléments`, items });
  if (skipped.length) toast(`${skipped.length} ignoré${skipped.length > 1 ? "s" : ""}.`);
  S.panes[i].sel = new Set();
}

// ---- tasks: queue, progress, verification, log, undo ---------------------------------------------------
function makeItem(op, n, from, to, extra = {}) {
  const sz = sizeOf(n), seed = seedOf(n), same = from.disk === to.disk;
  const it = {
    id: ++S.nid, op, name: n.n, size: sz, from: { disk: from.disk, path: from.path.slice() }, to: { disk: to.disk, path: to.path.slice() },
    seed, state: "queued", stage: "", progress: 0, verified: false, reason: "", ...extra,
  };
  it.newName = extra.newName || n.n;
  if (extra.conflict === "rename") it.newName = n.d ? n.n + " (2)" : n.n.replace(/(\.[^.]+)?$/, " (2)$1");
  const client = seed ? FX.clientOf(seed.client) : null;
  if (op === "trash") it.mode = `Corbeille de ${S.disks[from.disk].name} : déplacement instantané${seed ? ` · torrent retiré de ${seed.client} sans ses données` : ""}`;
  else if (op === "rename") it.mode = seed ? `Renommé dans le client (${seed.client})${client?.native ? "" : " : disque, re-pointage, revérification"}` : "Renommage sur disque";
  else if (op === "restore") it.mode = "Retour à l'emplacement d'origine";
  else {
    const instant = same && op === "move";
    it.mode = `${instant ? "Même disque : déplacement instantané" : `Autre disque : copie (${size(sz)})`}${seed && op === "move" ? ` · client : ${seed.client} (${client?.native ? "natif" : "pause, déplacement, re-pointage, revérification, reprise"})` : ""}`;
  }
  it.instant = op === "trash" || op === "rename" || op === "restore" || op === "organise" || (same && op === "move");
  // Seconds in the preview (accelerated): a copy takes longer than a path change, a client that cannot move adds a recheck.
  it.total = it.instant ? 0.7 : Math.max(2.5, Math.min(10, sz * 1.6));
  if (seed && op === "move" && client && !client.native) it.total += Math.max(2.5, Math.min(7, sz * 1.2));
  if (seed && op === "rename" && client && !client.native) it.total = 3.5;
  return it;
}
function enqueue(task) {
  const t = { id: "k" + ++S.nid, state: "queued", who: who(), at: Date.now(), undo: ["move", "rename", "trash", "organise"].includes(task.kind), ...task };
  S.tasks.unshift(t);
  toast(`${t.label} : ajouté aux tâches.`);
  if (S.tab === "tasks") render(); else refreshTabs();
  return t;
}
FX.enqueue = enqueue; FX.makeItem = makeItem;
function logDone(kind, label, items) {
  S.tasks.unshift({ id: "l" + ++S.nid, kind, label, who: who(), at: Date.now(), state: "done", undo: false,
    items: items.map(x => ({ state: "done", verified: true, progress: 1, ...x })) });
  refreshTabs();
}
FX.logDone = logDone;

// What one finished item does to the tree.
function applyItem(it) {
  if (it.op === "restore") return FX.restoreRecord(it.rec);
  if (it.op === "organise") return FX.applyOrganise(it);
  const src = nodeAt(it.from.disk, it.from.path);
  const node = src?.c.find(c => c.n === it.name);
  if (!node) return false;
  const destDir = () => ensureDir(it.to.disk, it.to.path);
  if (it.op === "trash") {
    src.c.splice(src.c.indexOf(node), 1);
    S.trash.push({ id: "t" + ++S.nid, disk: it.from.disk, name: node.n, from: fullPath(it.from.disk, [...it.from.path, node.n]), node, by: it.by || who(), ts: Date.now(), size: sizeOf(node), dir: !!node.d, reason: it.note || "" });
    return true;
  }
  if (it.op === "rename") { node.n = it.newName; return true; }
  const dest = destDir();
  const existing = dest.c.find(c => c.n === it.newName);
  if (existing && it.conflict === "replace") {
    dest.c.splice(dest.c.indexOf(existing), 1);
    S.trash.push({ id: "t" + ++S.nid, disk: it.to.disk, name: existing.n, from: fullPath(it.to.disk, [...it.to.path, existing.n]), node: existing, by: it.by || who(), ts: Date.now(), size: sizeOf(existing), dir: !!existing.d, reason: "Remplacé par un autre fichier" });
  }
  if (it.op === "move") {
    src.c.splice(src.c.indexOf(node), 1);
    node.n = it.newName; node.age = 0;
    dest.c.push(node);
  } else {
    const copy = clone(node);
    const strip = x => { delete x.seed; (x.c || []).forEach(strip); };
    strip(copy); copy.n = it.newName; copy.age = 0;
    dest.c.push(copy);
  }
  return true;
}
FX.applyItem = (it) => { const ok = applyItem(it); S.dirty = true; return ok; };

function failReason(it) {
  if (it.op === "move" || it.op === "copy" || it.op === "organise") {
    const need = it.size, u = discUsage(it.to.disk);
    if (it.from.disk !== it.to.disk || it.op === "copy") if (need > u.free) return `Pas assez de place sur ${S.disks[it.to.disk].name} : ${size(u.free)} libres, ${size(need)} nécessaires. Rien n'a été modifié.`;
  }
  if (S.failNext && !it.instant) {
    S.failNext = false;
    return it.seed ? `Vérification échouée : le client ne retrouve que 97,9 % des pièces à la destination. La copie est supprimée, l'original est intact et ${it.seed.client} partage de nouveau depuis l'emplacement d'origine.`
      : "Vérification échouée : la somme de contrôle de la copie diffère de l'original. La copie est supprimée, l'original est intact.";
  }
  return "";
}
function stagesOf(it) {
  if (it.op === "trash" || it.op === "restore") return [["Déplacement", 1]];
  if (it.op === "organise") return it.seed ? [[`${it.seed.client} : ${it.instant ? "renommage" : "déplacement"}`, .8], ["Vérification", .2]] : [[it.instant ? "Renommage" : "Copie", .8], ["Vérification de la somme de contrôle", .2]];
  if (it.op === "rename") return it.seed && !FX.clientOf(it.seed.client)?.native ? [["Renommage sur disque", .4], ["Re-pointage", .3], ["Revérification", .3]] : [[it.seed ? `Renommage dans ${it.seed.client}` : "Renommage", 1]];
  if (it.seed && it.op === "move") {
    const c = FX.clientOf(it.seed.client);
    return c?.native ? [[`Déplacement par ${it.seed.client}`, .85], ["Vérification", .15]]
      : [["Pause", .05], [it.instant ? "Déplacement" : "Copie", .4], ["Re-pointage", .05], ["Revérification", .4], ["Reprise", .1]];
  }
  return it.instant ? [["Déplacement", 1]] : [[it.op === "copy" ? "Copie" : "Déplacement (copie)", .8], ["Vérification de la somme de contrôle", .2]];
}
FX.stagesOf = stagesOf;
let last = Date.now();
function tick() {
  const now = Date.now(), dt = (now - last) / 1000;
  last = now;
  let busy = false, changed = false;
  for (const t of S.tasks.slice().reverse()) {
    if (t.state === "done" || t.state === "failed" || t.state === "cancelled" || t.state === "partial") continue;
    if (busy) break;
    busy = true;
    if (t.state === "queued") { t.state = "running"; changed = true; }
    const it = t.items.find(x => x.state === "queued" || x.state === "running");
    if (!it) { finish(t); changed = true; continue; }
    if (it.state === "queued") {
      it.state = "running";
      const why = failReason(it);
      if (why) { it.fail = why; it.failAt = 0.5 + Math.random() * .3; }
    }
    it.progress = Math.min(1, it.progress + dt / it.total);
    const stages = stagesOf(it);
    let acc = 0;
    it.stage = stages[stages.length - 1][0];
    for (const [name, share] of stages) { acc += share; if (it.progress <= acc) { it.stage = name; break; } }
    it.eta = Math.max(0, Math.round(it.total * (1 - it.progress)));
    if (it.fail && it.progress >= (it.failAt || 0.5)) { it.state = "failed"; it.reason = it.fail; it.verified = false; }
    else if (it.progress >= 1) {
      it.by = t.who;
      if (FX.applyItem(it)) { it.state = "done"; it.verified = true; } else { it.state = "failed"; it.reason = "Le fichier a changé ou n'existe plus à l'emplacement d'origine."; }
    }
    changed = true;
    if (!t.items.some(x => x.state === "queued" || x.state === "running")) finish(t);
  }
  if (changed) {
    if (S.tab === "tasks") paintTasks();
    else if (S.dirty && !document.querySelector("dialog[open]") && !drag && ["explorer", "trash", "disks", "organisation"].includes(S.tab)) { S.dirty = false; render(); }
    refreshTabs();
  }
}
function finish(t) {
  const fails = t.items.filter(x => x.state === "failed").length, done = t.items.filter(x => x.state === "done").length;
  t.state = fails && done ? "partial" : fails ? "failed" : "done";
  t.endedAt = Date.now();
  toast(t.state === "done" ? `${t.label} : terminé et vérifié.` : `${t.label} : ${fails} échec${fails > 1 ? "s" : ""}, voir Tâches.`, t.state === "done" ? "ok" : "bad");
  if (t.state === "failed") t.undo = false;
}
setInterval(tick, 300);

function cancel(t, itemId) {
  for (const it of t.items) if ((!itemId || it.id === itemId) && (it.state === "queued" || it.state === "running")) {
    it.reason = it.progress > 0 && !it.instant ? "Annulé : copie partielle supprimée, original intact." : "Annulé avant le début : rien n'a changé.";
    it.state = "cancelled";
  }
  if (!t.items.some(x => x.state === "queued" || x.state === "running")) {
    const done = t.items.some(x => x.state === "done");
    t.state = done ? "partial" : "cancelled"; t.endedAt = Date.now(); if (!done) t.undo = false;
  }
  paintTasks(); refreshTabs();
}
function undo(t) {
  const items = t.items.filter(x => x.state === "done").map(x => {
    const r = { ...x, id: ++S.nid, state: "queued", progress: 0, verified: false, reason: "", stage: "", fail: "", conflict: "", old: null };
    if (x.op === "move") Object.assign(r, { from: x.to, to: x.from, name: x.newName, newName: x.name });
    else if (x.op === "rename") Object.assign(r, { name: x.newName, newName: x.name });
    else if (x.op === "trash") {
      const rec = S.trash.find(q => q.name === x.name && q.disk === x.from.disk);
      if (!rec) return null;
      Object.assign(r, { op: "restore", rec, from: { disk: x.from.disk, path: [".corbeille"] }, to: x.from });
    } else if (x.op === "organise") Object.assign(r, { mappings: x.mappings.map(m => ({ from: m.to, to: m.from })), meta: x.undoMeta, undoMeta: null });
    else return null;
    r.instant = true; r.total = 0.7; r.mode = "Retour en arrière : la même opération en sens inverse";
    return r;
  }).filter(Boolean);
  t.undone = true; t.undo = false;
  if (!items.length) { toast("Rien à annuler : une copie ne change pas l'original."); paintTasks(); return; }
  enqueue({ kind: "undo", label: `Annuler : ${t.label}`, undo: false, items });
  paintTasks();
}
FX.undo = undo;

const STATE = { queued: ["En attente", ""], running: ["En cours", ""], done: ["Terminé", "ok"], failed: ["Échec", "bad"], partial: ["Partiel", "warn"], cancelled: ["Annulé", "warn"] };
function taskHTML(t) {
  const [label, cls] = STATE[t.state] || [t.state, ""];
  const active = t.state === "queued" || t.state === "running";
  const total = t.items.reduce((a, x) => a + (x.state === "done" ? 1 : x.progress || 0), 0) / Math.max(1, t.items.length);
  const eta = active ? t.items.filter(x => x.state === "running" || x.state === "queued").reduce((a, x) => a + (x.total || 1) * (1 - (x.progress || 0)), 0) : 0;
  return `<article class="card task ${t.state}" data-task="${t.id}">
    <div class="task-head"><div class="grow"><b>${esc(t.label)}</b> <small style="display:inline">· ${esc(t.who)} · ${ago(t.at)}</small></div>
      <span class="badge ${cls}">${label}${t.undone ? " · annulé après coup" : ""}</span>
      ${active ? `<small>${t.items.length > 1 ? `${t.items.filter(x => x.state === "done").length}/${t.items.length} · ` : ""}reste ~${dur(eta)}</small><button data-cancel="${t.id}">Annuler</button>` : ""}
      ${t.undo && !t.undone && !active ? `<button data-undo="${t.id}" title="Remet les éléments comme avant (journalisé)">Annuler l'opération</button>` : ""}</div>
    ${active ? `<div class="prog"><i style="width:${Math.round(total * 100)}%"></i></div>` : ""}
    ${t.items.map(it => `<div class="titem"><div class="nm"><b>${esc(it.name)}${it.newName && it.newName !== it.name && it.op !== "move" || it.op === "rename" ? " → " + esc(it.newName) : ""}</b><small>${esc(it.mode || "")}</small>
        <small>${esc(typeof it.from === "string" ? it.from : fullPath(it.from.disk, it.from.path))}${it.to ? " → " + esc(typeof it.to === "string" ? it.to : fullPath(it.to.disk, it.to.path)) : ""}</small></div>
      <div>${it.state === "running" ? `<div class="prog"><i style="width:${Math.round(it.progress * 100)}%"></i></div><small>${esc(it.stage)} · ${Math.round(it.progress * 100)} % · ~${dur(it.eta || 0)}</small>`
        : it.state === "queued" ? `<small>En attente</small>` : `<small>${size(it.size)}</small>`}</div>
      <div>${it.state === "done" ? `<span class="ver" title="Somme de contrôle ou revérification du client">✓ vérifié</span>` : it.state === "failed" ? `<span class="badge bad">échec</span>` : it.state === "cancelled" ? `<span class="badge warn">annulé</span>` : active && (it.state === "queued" || it.state === "running") ? `<button data-cancel="${t.id}:${it.id}" class="quiet">Annuler</button>` : ""}</div>
      ${it.reason ? `<div class="reason">${esc(it.reason)}</div>` : ""}</div>`).join("")}</article>`;
}
let taskFilter = "all";
function tasksHTML() {
  const f = { all: () => true, active: t => t.state === "running" || t.state === "queued", done: t => t.state === "done", failed: t => t.state === "failed" || t.state === "partial" || t.state === "cancelled" };
  const filters = [["all", "Toutes"], ["active", "En cours"], ["done", "Terminées"], ["failed", "Échecs et annulations"]];
  return `<div class="filters">${filters.map(([k, l]) => `<button class="chip ${taskFilter === k ? "on" : ""}" data-filter="${k}">${l}</button>`).join("")}
      <span class="grow"></span><label class="row" title="Aperçu : fait échouer la vérification du prochain élément copié"><input type="checkbox" id="failnext" ${S.failNext ? "checked" : ""}> Simuler un échec</label></div>
    <div class="tasks" id="tasklist">${S.tasks.filter(f[taskFilter]).map(taskHTML).join("") || `<div class="empty">Aucune tâche pour ce filtre.</div>`}</div>`;
}
function paintTasks() {
  const el = $("tasklist");
  if (!el || S.tab !== "tasks") return;
  const f = { all: () => true, active: t => t.state === "running" || t.state === "queued", done: t => t.state === "done", failed: t => t.state === "failed" || t.state === "partial" || t.state === "cancelled" };
  el.innerHTML = S.tasks.filter(f[taskFilter]).map(taskHTML).join("") || `<div class="empty">Aucune tâche pour ce filtre.</div>`;
}

// ---- page ----------------------------------------------------------------------------------------------
const TABS = [["explorer", "Explorateur", false], ["disks", "Disques", true], ["organisation", "Organisation", true], ["trash", "Corbeille", false], ["tasks", "Tâches", false]];
function tabsHTML() {
  const active = S.tasks.filter(t => t.state === "running" || t.state === "queued").length;
  return TABS.filter(([, , owner]) => !(S.member && owner)).map(([id, label]) =>
    `<button data-tab="${id}" class="${S.tab === id ? "selected" : ""}">${label}${id === "tasks" && active ? `<span class="badge count">${active}</span>` : ""}${id === "trash" ? `<span class="badge count">${S.trash.filter(t => !S.member || t.from.includes("/Films/")).length}</span>` : ""}</button>${S.tab === id && TAB_TIPS[id] && FX.tipBtn ? `<span class="tabtip">${FX.tipBtn(TAB_TIPS[id](), "Aide sur cet onglet")}</span>` : ""}`).join("");
}
function refreshTabs() { const t = $("tabs"); if (t) t.innerHTML = tabsHTML(); }
function render() {
  const app = $("app");
  if (S.member && ["disks", "organisation"].includes(S.tab)) S.tab = "explorer";
  const scroll = document.querySelector(".files")?.scrollTop || 0;
  const view = { explorer: explorerHTML, tasks: tasksHTML, disks: () => FX.disksHTML(), trash: () => FX.trashHTML(), organisation: () => FX.orgHTML() }[S.tab]();
  app.innerHTML = `<div class="row between"><nav class="tabs" id="tabs">${tabsHTML()}</nav>
      <span class="row"><span class="badge-preview">Aperçu</span>${S.member ? `<span class="badge warn">Vue membre · Gérer les fichiers</span>` : ""}</span></div>
    <div id="view">${view}</div>`;
  const f = document.querySelector(".files");
  if (f) f.scrollTop = scroll;
  FX.afterRender?.();
}
FX.render = render;
FX.show = tab => { S.tab = tab; render(); };
FX.setMounted = on => { S.hddMounted = !!on; if (!on) S.panes.forEach(p => { if (p.disk === "d3") { p.disk = "d1"; p.path = ["Films"]; p.sel = new Set(); } }); render(); };
FX.setMember = on => { S.member = !!on; resetPanes(); S.tab = "explorer"; render(); };
FX.api = { show: FX.show, setMember: FX.setMember, setMounted: FX.setMounted, get member() { return S.member; } };
FX.refreshTabs = refreshTabs;

// ---- events --------------------------------------------------------------------------------------------
document.addEventListener("click", e => {
  const t = e.target;
  const tab = t.closest("[data-tab]");
  if (tab) { S.tab = tab.dataset.tab; render(); return; }
  const g = t.closest("[data-go]");
  if (g) { const [i, k] = g.dataset.go.split(":").map(Number); go(i, pane(i).path.slice(0, k + 1)); return; }
  const up = t.closest("[data-up]");
  if (up) { const i = +up.dataset.up; go(i, pane(i).path.slice(0, -1)); return; }
  const sw = t.closest("[data-switch]");
  if (sw) { S.active = +sw.dataset.switch; render(); return; }
  const so = t.closest("[data-sort]");
  if (so) { const [i, k] = so.dataset.sort.split(":"); const s = pane(+i).sort; s.dir = s.key === k ? -s.dir : 1; s.key = k; render(); return; }
  const f = t.closest("[data-f]");
  if (f) { fkey(f.dataset.f); return; }
  const tr = t.closest("tr[data-name]");
  if (tr) { select(+tr.dataset.i, tr.dataset.name, e); return; }
  const pn = t.closest("[data-pane]");
  if (pn && !t.closest("button,select")) { S.active = +pn.dataset.pane; paintSel(0); paintSel(1); }
  if (t.closest("[data-cancel]")) {
    const [tid, iid] = t.closest("[data-cancel]").dataset.cancel.split(":");
    const task = S.tasks.find(x => x.id === tid);
    if (task) cancel(task, iid ? +iid : 0);
    return;
  }
  if (t.closest("[data-undo]")) { undo(S.tasks.find(x => x.id === t.closest("[data-undo]").dataset.undo)); return; }
  if (t.closest("[data-filter]")) { taskFilter = t.closest("[data-filter]").dataset.filter; render(); return; }
});
document.addEventListener("change", e => {
  if (e.target.dataset.place !== undefined) {
    const i = +e.target.dataset.place, x = places()[+e.target.value];
    pane(i).disk = x.disk;
    go(i, x.path);
  }
  if (e.target.id === "failnext") S.failNext = e.target.checked;
});
document.addEventListener("dblclick", e => {
  const tr = e.target.closest("tr[data-name]");
  if (!tr) return;
  const i = +tr.dataset.i, n = nodeAt(pane(i).disk, pane(i).path)?.c.find(c => c.n === tr.dataset.name);
  if (n) openNode(i, n);
});
document.addEventListener("contextmenu", e => {
  const tr = e.target.closest("tr[data-name]"), fl = e.target.closest("[data-files]");
  if (tr) contextMenu(e, +tr.dataset.i, tr.dataset.name);
  else if (fl) contextMenu(e, +fl.dataset.files, null);
});
// Drag between panes, or onto a folder row.
let drag = null;
document.addEventListener("dragstart", e => {
  const tr = e.target.closest("tr[data-name]");
  if (!tr) return;
  const i = +tr.dataset.i;
  if (!pane(i).sel.has(tr.dataset.name)) select(i, tr.dataset.name, {});
  drag = { i, items: selected(i) };
  e.dataTransfer.setData("text/plain", drag.items.map(n => n.n).join("\n"));
  e.dataTransfer.effectAllowed = "copyMove";
});
document.addEventListener("dragover", e => {
  if (!drag) return;
  const tr = e.target.closest("tr[data-name]"), box = e.target.closest("[data-pane]");
  if (!box) return;
  e.preventDefault();
  document.querySelectorAll("tr.drop").forEach(x => x.classList.remove("drop"));
  const node = tr && nodeAt(pane(+tr.dataset.i).disk, pane(+tr.dataset.i).path)?.c.find(c => c.n === tr.dataset.name);
  if (node?.d && !drag.items.includes(node)) tr.classList.add("drop");
});
document.addEventListener("dragend", () => { drag = null; document.querySelectorAll("tr.drop").forEach(x => x.classList.remove("drop")); });
document.addEventListener("drop", e => {
  if (!drag) return;
  const box = e.target.closest("[data-pane]");
  if (!box) return;
  e.preventDefault();
  const j = +box.dataset.pane, p = pane(j), tr = e.target.closest("tr[data-name]");
  const node = tr && nodeAt(p.disk, p.path)?.c.find(c => c.n === tr.dataset.name);
  const to = { disk: p.disk, path: node?.d && !drag.items.includes(node) ? [...p.path, node.n] : p.path.slice() };
  const d = drag; drag = null;
  document.querySelectorAll("tr.drop").forEach(x => x.classList.remove("drop"));
  if (S.member && !allowed(to.disk, to.path)) return;
  if (d.i === j && to.path.join("/") === p.path.join("/")) return toast("Déposez sur l'autre panneau ou sur un dossier.");
  showMenu(e.clientX, e.clientY, [
    { act: "dm", label: `Déplacer ici (${d.items.length})`, key: "F6", run: () => transfer("move", d.i, false, { items: d.items, to }) },
    { act: "dc", label: `Copier ici (${d.items.length})`, key: "F5", run: () => transfer("copy", d.i, false, { items: d.items, to }) },
    "-", { act: "dx", label: "Annuler", run: () => {} }]);
});
function fkey(k) {
  const i = S.active;
  if (k === "rename") renameDialog(i);
  else if (k === "copy") transfer("copy", i, false);
  else if (k === "move") transfer("move", i, false);
  else if (k === "mkdir") mkdirDialog(i);
  else if (k === "trash") trashDialog(i);
}
document.addEventListener("keydown", e => {
  if (S.tab !== "explorer" || document.querySelector("dialog[open]") || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
  const i = S.active, p = pane(i), rows = listOf(p).map(n => n.n);
  const map = { F2: "rename", F5: "copy", F6: "move", F7: "mkdir", Delete: "trash" };
  if (map[e.key]) { e.preventDefault(); fkey(map[e.key]); return; }
  if (e.key === "Tab") { e.preventDefault(); S.active = 1 - i; render(); return; }
  if (e.key === "a" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); p.sel = new Set(rows); paintSel(i); return; }
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const at = rows.indexOf(p.cursor), next = rows[Math.max(0, Math.min(rows.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))];
    if (next) select(i, next, e);
  }
  if (e.key === "Enter" && p.cursor) { const n = listOf(p).find(x => x.n === p.cursor); if (n) openNode(i, n); }
  if (e.key === "Backspace" && p.path.length > minDepth()) go(i, p.path.slice(0, -1));
  if (e.key === "Escape") { p.sel = new Set(); paintSel(i); }
});
addEventListener("resize", () => { const n = innerWidth < 800; if (n !== S.mobile) { S.mobile = n; if (S.tab === "explorer") render(); } });

// ---- start ---------------------------------------------------------------------------------------------
function init(data) {
  S.data = data;
  S.roots = {}; S.disks = {};
  for (const d of data.disks) {
    S.disks[d.id] = d;
    S.roots[d.id] = clone(data.roots[d.id]);
  }
  S.trash = data.trash.map(t => ({ ...t, ts: Date.now() - t.ago * DAY - 3600e3, node: null }));
  for (const d of data.disks) {
    const trash0 = S.trash.filter(t => t.disk === d.id).reduce((a, t) => a + t.size, 0);
    d.other = d.used - d.library - d.downloads - trash0;
  }
  const where = str => { const d = data.disks.find(k => str.startsWith(k.mount)); return { disk: d.id, path: str.slice(d.mount.length).split("/").filter(Boolean) }; };
  S.tasks = data.tasks.map(t => ({ ...t, at: Date.now() - t.ago_min * 60000, items: t.items.map(x => ({ ...x, id: ++S.nid, progress: 1, op: t.kind, from: where(x.from), to: where(x.to),
    name: x.name.split(" → ")[0], newName: x.name.split(" → ")[1] || x.name })) }));
  S.mobile = innerWidth < 800;
  resetPanes();
  render();
}
addEventListener("DOMContentLoaded", () => {
  S.theme = () => { try { document.documentElement.dataset.theme = parent.document.documentElement.dataset.theme || "dark"; } catch {} };
  S.theme();
  fetch(BASE + "storage.json").then(r => r.json()).then(init);
});
FX.reset = () => { S.hddMounted = true; S.member = false; S.tab = "explorer"; init(S.data); };
