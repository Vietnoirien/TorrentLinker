"use strict";
// Fichiers · Organisation: the board (#223). Provenances on the left, organised libraries on the right,
// linked by connectors. Loaded before view.js, which owns S, say, esc, size, tip and render().
const O = { linking: null, reviewOpen: true, fn: null, folders: null, summary: null, paths: [] };
const COLORS = { films: "#80bdb6", series: "#edbf73", other: "#b9a3f5" };
const KIND = { films: ["Films", "Films"], series: ["Series", "Séries"] };
const oplural = (n, one, many) => `${n} ${n > 1 ? many : one}`;
const oname = (l) => (KIND[l.kind] ? say(...KIND[l.kind]) : oshort(l));
const olib = (path) => S.org?.libraries.find((l) => l.path === path);
const oshort = (f) => (f.disk && f.path.startsWith(`${f.disk}/`) ? f.path.slice(f.disk.length + 1) : f.name || f.path);
const ocol = (l) => COLORS[l.kind] || COLORS.other;
const oitems = (p) => p.films + p.series;
const obytes = (p) => p.bytesFilms + p.bytesSeries;
const ofail = (e) => TLToast.show(e.message, "bad");
const AUTO_WHY = () => say(
  "Automatic: for each item the app picks the library by its kind (film, series), then by the placement rule: the same disk as its other versions or episodes, otherwise the organised library with the most room. You can also pin one library.",
  "Automatique : pour chaque élément, l'application choisit la bibliothèque selon son type (film, série), puis selon la règle de placement : le même disque que ses autres versions ou épisodes, sinon la bibliothèque organisée qui a le plus de place. Vous pouvez aussi imposer une bibliothèque.");

function odisk(root) {
  const d = S.org?.disks.find((x) => x.name === root);
  if (!d) return `<span class="og-disk">${esc(root)}</span>`;
  const pct = d.total ? Math.round((d.used / d.total) * 100) : 0;
  const txt = d.free <= 0 ? say("full", "pleine") : pct < 1 ? size(d.total) : `${pct} %`;
  return `<span class="og-disk" title="${esc(root)}"><i><b style="width:${pct}%" class="${pct >= 90 ? "hot" : ""}"></b></i>${esc(root)} · ${esc(txt)}</span>`;
}
const osw = (on, attrs, label) => `<button type="button" role="switch" aria-checked="${on}" class="og-sw ${on ? "on" : ""}" ${attrs} aria-label="${esc(label)}"><i></i></button>`;
const roleName = (p) => (p.kind === "download" ? say("Downloads", "Téléchargements") : p.kind === "library" ? say("Old library", "Ancienne bibliothèque") : say("Provenance", "Provenance"));
const ochips = (p) => {
  const l = p.to && olib(p.to);
  return l ? `<button type="button" class="og-chip" style="--c:${ocol(l)}" data-o="unlink" data-p="${esc(p.path)}" title="${say("Back to Automatic", "Remettre en Automatique")}"><span class="dot"></span>${esc(oname(l))}<span class="x">✕</span></button>`
    : `<span class="og-chip auto"><span class="dot"></span>→ ${say("Automatic", "Automatique")}</span>`;
};

// Titles to give in one tap: guessed from the name, then from what is typed.
const picks = (found, path) => found.map((t) => `<button type="button" class="small og-pick" data-o="pick" data-i="${esc(path)}" data-t="${esc(t.year ? `${t.title} (${t.year})` : t.title)}">${esc(t.title)}${t.year ? ` <span class="muted">${esc(t.year)}</span>` : ""}${t.kind === "series" ? ` <span class="muted">· ${say("series", "série")}</span>` : ""}</button>`).join("");
function reviewHTML() {
  const rows = S.org.provenances.flatMap((p) => p.review.map((r) => ({ p, r })));
  return `<section class="og-review card" id="og-review"><div class="row"><h3>${say("To check", "À vérifier")}</h3><span class="badge ${rows.length ? "warn" : "ok"}">${rows.length}</span>${tip("These items have no recognisable title (for example IMG_3310.mov). They stay where they are until you fix them. Give them a title so they are tidied, or keep them as they are.", "Ces éléments n'ont pas de titre reconnaissable (par exemple IMG_3310.mov). Ils restent où ils sont tant que vous ne les avez pas corrigés. Donnez-leur un titre pour qu'ils soient rangés, ou gardez-les tel quel.", say("Help on To check", "Aide sur À vérifier"))}<span class="grow"></span>
    ${rows.length ? `<button type="button" class="small quiet" data-o="revtoggle">${O.reviewOpen ? say("Collapse", "Replier") : say("Show", "Afficher")}</button>` : ""}</div>
    ${rows.length ? (O.reviewOpen ? `<div class="og-rv">${rows.map(({ p, r }) => `<div class="og-rrow"><div class="nm"><b title="${esc(r.name)}">${esc(r.name)}</b><small>${esc(oshort(p))} · ${size(r.size)}</small></div>
      <input data-o="title" data-i="${esc(r.path)}" autocomplete="off" placeholder="${say("Title of the film or series", "Titre du film ou de la série")}" aria-label="${say("Title of", "Titre de")} ${esc(r.name)}" />
      <span class="btns"><button type="button" class="small primary" data-o="fix" data-i="${esc(r.path)}">${say("Fix", "Corriger")}</button><button type="button" class="small" data-o="keep" data-i="${esc(r.path)}">${say("Keep as is", "Garder tel quel")}</button></span>
      <div class="og-picks" data-for="${esc(r.path)}">${picks(r.proposals || [], r.path)}</div></div>`).join("")}</div>` : "") : `<p class="muted">${say("Nothing to check.", "Rien à vérifier.")}</p>`}</section>`;
}
function provCard(p) {
  const n = oitems(p), scanning = p.state !== "ready";
  const sub = p.subs.length ? `<small class="muted og-subs">${say("including", "dont")} ${p.subs.map(([a, c]) => `${esc(a)} (${c})`).join(" · ")}</small>` : "";
  const count = scanning ? say("Reading…", "Analyse…") : !n ? (p.swapped.length ? say("All tidied", "Tout est rangé") : say("Nothing to tidy", "Rien à ranger"))
    : `${[p.films ? oplural(p.films, say("film", "film"), say("films", "films")) : "", p.series ? oplural(p.series, say("series", "série"), say("series", "séries")) : ""].filter(Boolean).join(" · ")} · ${size(obytes(p))}`;
  const note = p.swapped.length ? `<div class="og-note">✓ ${say("Empty.", "Vide.")} <span>${say("Replaced by", "Remplacé par")} ${p.swapped.map(esc).join(", ")} ${say("in Settings.", "dans Paramètres.")}</span><button type="button" class="small quiet" data-o="settingsgo">${say("Open Settings", "Ouvrir Paramètres")}</button></div>` : "";
  return `<article class="og-card og-prov ${O.linking === p.path ? "picking" : ""} ${p.to ? "" : "unlinked"}" data-card="${esc(p.path)}" draggable="true" data-drag="${esc(p.path)}">
    <div class="og-top"><span class="og-grip" aria-hidden="true">⠿</span><div class="og-title"><b>${esc(oshort(p))}</b><small class="muted">${esc(p.path)}</small></div><span class="badge">${roleName(p)}</span></div>
    <div class="og-meta">${odisk(p.disk)}</div><div class="og-count ${n ? "" : "muted"}">${count}</div>${sub}
    ${p.review.length ? `<a class="og-warn" href="#og-review" data-o="gorev">⚠ ${p.review.length} ${say("to check", "à vérifier")}</a>` : ""}
    <div class="og-links">${ochips(p)}</div>${note}
    <div class="og-act"><label class="og-auto">${osw(p.auto, `data-o="auto" data-p="${esc(p.path)}"`, say("Tidy new arrivals automatically", "Ranger automatiquement les nouveautés"))}<span>Auto</span></label>${tip("Auto: each new item that arrives in this folder is tidied by itself, and keeps sharing. Off by default for an old library.", "Auto : chaque nouvel élément arrivé dans ce dossier est rangé tout seul, sans cesser de partager. Désactivé par défaut pour une ancienne bibliothèque.", say("Help on Auto", "Aide sur Auto"))}<span class="grow"></span>
      <select data-o="dest" data-p="${esc(p.path)}" aria-label="Destination"><option value="">${say("Automatic", "Automatique")}</option>${S.org.libraries.map((l) => `<option value="${esc(l.path)}" ${p.to === l.path ? "selected" : ""}>${esc(oname(l))}</option>`).join("")}</select>${tip(AUTO_WHY(), say("Help on the destination", "Aide sur la destination"))}<button type="button" class="small" data-o="link" data-p="${esc(p.path)}">${say("Pin", "Fixer")}</button>
      <button type="button" class="small primary" data-o="ranger" data-p="${esc(p.path)}" ${p.ready ? "" : "disabled"}>${say("Tidy", "Ranger")}</button></div></article>`;
}
function libCard(l) {
  const word = l.kind === "series" ? [say("series", "série"), say("series", "séries")] : [say("film", "film"), say("films", "films")];
  return `<article class="og-card og-lib ${O.linking ? "target" : ""}" style="--c:${ocol(l)}" data-lib="${esc(l.path)}" ${O.linking ? `data-o="pick" data-l="${esc(l.path)}" tabindex="0" role="button"` : ""}>
    <div class="og-top"><div class="og-title"><b>${esc(oname(l))}</b><small class="muted">${esc(l.path)}</small></div><span class="badge ok">✓ ${say("organised", "organisée")}</span></div>
    <div class="og-meta">${odisk(l.disk)}</div>
    <div class="og-count">${l.n ? `${oplural(l.n, word[0], word[1])} · ${size(l.bytes)}` : `<span class="muted">0 ${word[0]} · ${say("empty", "vide")}</span>`}</div>
    <small class="muted">${l.pinned ? oplural(l.pinned, say("folder pinned here", "dossier fixé ici"), say("folders pinned here", "dossiers fixés ici")) : say("Also receives the folders set to Automatic", "Reçoit aussi les dossiers en Automatique")}</small>
    <span class="og-drophere">${O.linking ? say("Pin here", "Lier ici") : say("Drop a folder here", "Déposez un dossier ici")}</span></article>`;
}
function orgHTML() {
  const o = S.org;
  if (!o) return `<div class="empty">…</div>`;
  const head = `<div class="og-head"><div class="row"><h2>Organisation</h2>${tip("Here you choose the folders the app organises (your libraries) and where the films and series to tidy come from. Nothing moves without your say; everything keeps sharing.", "Ici, vous choisissez les dossiers que l'application organise (vos bibliothèques) et d'où viennent les films et séries à y ranger. Rien ne bouge sans votre accord ; tout continue de partager.", say("Help on Organisation", "Aide sur Organisation"))}</div><span class="grow"></span>
    ${(() => { const ready = o.provenances.filter((p) => p.ready).map((p) => p.path); return ready.length ? `<button type="button" class="primary" data-o="rangerall" data-ps="${esc(JSON.stringify(ready))}">${say("Tidy everything", "Tout ranger")}</button>` : ""; })()}
    <button type="button" data-o="folders">${say("Choose folders", "Choisir les dossiers")}</button><button type="button" data-o="settings" aria-label="${say("Tidy settings", "Réglages du rangement")}" title="${say("Settings", "Réglages")}">⚙</button></div>`;
  const bar = O.linking ? `<div class="og-linking" role="status"><span>${say("Pin", "Fixer")} <b>${esc(oshort(o.provenances.find((p) => p.path === O.linking) || { path: "", name: "" }))}</b></span><button type="button" class="small" data-o="cancellink">${say("Cancel", "Annuler")}</button></div>` : "";
  const jobs = o.jobs?.length ? `<div class="og-note"><span>${o.jobs.map((j) => `${esc(j.label)} · ${j.ended}/${j.total}`).join(" · ")}</span><button type="button" class="small quiet" data-o="totasks">${say("Follow in Tasks", "Suivre dans Tâches")}</button></div>` : "";
  const empty = !o.libraries.length && !o.provenances.length ? `<div class="empty">${say("No folder has a role yet: choose them.", "Aucun dossier n'a encore de rôle : choisissez-les.")}</div>` : "";
  return `<div class="og">${head}${bar}${jobs}${o.scanning ? `<div class="og-scan">${say("Reading the folders… the counts appear as they are ready.", "Lecture des dossiers… les chiffres s'affichent au fur et à mesure.")}</div>` : ""}${empty}
    <div class="og-board" id="og-board"><svg class="og-wires" id="og-wires" aria-hidden="true"></svg>
      <section class="og-col"><div class="row og-colhead"><h3>${say("Provenances", "Provenances")}</h3>${tip("The folders your films and series come from: old libraries and download folders. Each folder is Automatic by default: the app picks the library of each item. To impose one, drag the folder onto it or tap Pin.", "Les dossiers d'où viennent vos films et séries : anciennes bibliothèques et dossiers de téléchargement. Par défaut chaque dossier est en Automatique : l'application choisit la bibliothèque de chaque élément. Pour en imposer une, glissez le dossier dessus ou touchez Fixer.", say("Help on Provenances", "Aide sur Provenances"))}</div>${o.provenances.map(provCard).join("")}</section>
      <section class="og-col"><div class="row og-colhead"><h3>${say("Organised libraries", "Bibliothèques organisées")}</h3>${tip("The folders the app names and sorts for you (Jellyfin layout). Films go to the films library, series to the series one, then wherever there is room.", "Les dossiers que l'application nomme et classe pour vous (format Jellyfin). Les films vont dans la bibliothèque de films, les séries dans celle des séries, ensuite au mieux selon la place.", say("Help on Organised libraries", "Aide sur Bibliothèques organisées"))}</div>${o.libraries.map(libCard).join("")}</section>
    </div>${reviewHTML()}</div>`;
}
function orgWires() {
  const board = document.getElementById("og-board"), svg = document.getElementById("og-wires");
  if (!board || !svg) return;
  if (matchMedia("(max-width: 800px)").matches) { svg.innerHTML = ""; return; }
  const b = board.getBoundingClientRect();
  svg.setAttribute("width", b.width); svg.setAttribute("height", b.height);
  let out = "";
  for (const p of S.org.provenances) for (const path of p.to ? [p.to] : S.org.libraries.map((l) => l.path)) {
    const a = board.querySelector(`[data-card="${CSS.escape(p.path)}"]`), z = board.querySelector(`[data-lib="${CSS.escape(path)}"]`), l = olib(path), fx = !!p.to;
    if (!a || !z || !l) continue;
    const ra = a.getBoundingClientRect(), rz = z.getBoundingClientRect(), c = fx ? ocol(l) : "#98aab7";
    const x1 = ra.right - b.left, y1 = ra.top - b.top + ra.height / 2, x2 = rz.left - b.left, y2 = rz.top - b.top + rz.height / 2, mx = (x1 + x2) / 2;
    out += `<path d="M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}" fill="none" stroke="${c}" stroke-width="${fx ? 3.5 : 1.6}" stroke-linecap="round" ${fx ? "" : 'stroke-dasharray="5 6"'} opacity="${fx ? 0.95 : 0.55}"/><circle cx="${x2}" cy="${y2}" r="${fx ? 5 : 3}" fill="${c}"/><circle cx="${x1}" cy="${y1}" r="${fx ? 5 : 3}" fill="${c}"/>`;
  }
  svg.innerHTML = out;
}
addEventListener("resize", () => S.tab === "organisation" && orgWires());

// ---- Sheets -------------------------------------------------------------------------------------
function openSheet(fn) {
  const d = $("dialog");
  O.fn = fn; d.className = "sheet"; d.innerHTML = fn(); d.onclick = null;
  if (!d.open) d.showModal();
  d.addEventListener("close", () => { O.fn = null; d.className = ""; render(); }, { once: true });
}
const sheetRedraw = () => { const d = $("dialog"); if (O.fn && d.open) d.innerHTML = O.fn(); };
const sheetHead = (title, text) => `<div class="og-sh"><h2>${title}</h2>${text ? tip(text.en, text.fr) : ""}<span class="grow"></span><button type="button" class="quiet" data-o="close" aria-label="${say("Close", "Fermer")}">✕</button></div>`;
const owait = (s) => (s < 1 ? say("instant", "instantané") : s < 90 ? say("under 2 min", "moins de 2 min") : s < 5400 ? `~${Math.round(s / 60)} min` : `~${Math.round(s / 3600)} h`);

function summarySheet() {
  const s = O.summary, line = (k, label, text, t) => `<div class="og-stat"><span class="k">${k}</span><span class="v"><b>${label}</b>${text ? ` <span class="muted">${text}</span>` : ""}</span>${t ? tip(t[0], t[1]) : ""}</div>`;
  const to = [...new Set(s.dests.map((d) => d.lib))].map(esc).join(say(" and ", " et "));
  const word = (d) => (d.kind === "series" ? [say("series", "série"), say("series", "séries")] : [say("film", "film"), say("films", "films")]);
  const sp = (p) => oshort(S.org.provenances.find((x) => x.path === p) || { path: p, name: p });
  return `${sheetHead(esc(O.paths.length === 1 ? `${say("Tidy", "Ranger")} ${sp(O.paths[0])}` : say("Tidy everything", "Tout ranger")), { en: "A summary of what will happen. Nothing moves before “Start”.", fr: "Un résumé de ce qui va se passer. Rien ne bouge avant « Lancer »." })}
    <div class="og-big"><span class="n">${oplural(s.n, say("item", "élément"), say("items", "éléments"))}</span><span class="arrow">→</span><span class="to">${to || "—"}</span>${tip(AUTO_WHY(), say("Why this library", "Pourquoi cette bibliothèque"))}</div>
    ${s.dests.length > 1 ? `<ul class="og-split">${s.dests.map((d) => `<li><span class="dot" style="--c:${ocol(olib(d.lib) || { kind: "other" })}"></span>${oplural(d.n, ...word(d))} → ${esc(d.lib)}</li>`).join("")}</ul>` : ""}
    ${s.routed.length ? `<div class="og-route">${s.routed.map((r) => `${oplural(r.n, say("series found", "série trouvée"), say("series found", "séries trouvées"))} ${say("in", "dans")} ${esc(sp(r.prov))}: ${say("tidied by kind in", "rangées par type dans")} ${esc(r.lib)}`).join(" · ")}</div>` : ""}
    ${s.unrouted.length ? `<div class="og-route warn">${s.unrouted.map((r) => `${oplural(r.n, ...word(r))} ${say("of", "de")} ${esc(sp(r.prov))}: ${r.why === "no-room" ? say("no room, they stay in place", "pas assez de place, ils restent en place") : say("no library for them, they stay in place", "aucune bibliothèque pour eux, ils restent en place")}`).join(" · ")}</div>` : ""}
    ${s.nblocked ? `<div class="og-route warn">${oplural(s.nblocked, say("item stays in place", "élément reste en place"), say("items stay in place", "éléments restent en place"))} ${reasonHTML(s.blocked[0].reason)}</div>` : ""}
    <div class="og-stats">
      ${line("⏱", `${size(s.bytes)} · ${owait(s.seconds)}`, "", [say("Files copied to another disk take time: this is an estimate. You can close the browser, the rest is in Tasks.", "Les fichiers copiés vers un autre disque prennent du temps : la durée est une estimation. Vous pouvez fermer le navigateur, la suite est dans Tâches."), ""])}
      ${line("▲", say("Everything keeps sharing", "Tout continue de partager"), "", [say("Each torrent keeps its files: it is re-pointed to the new place and rechecked by its client. Sharing stops only for the time of the check.", "Chaque torrent garde ses fichiers : il est re-pointé vers le nouvel emplacement et revérifié par son client. Aucun partage n'est interrompu plus que le temps de la vérification."), ""])}
      ${line("↻", oplural(s.torrents, say("torrent re-pointed", "torrent re-pointé"), say("torrents re-pointed", "torrents re-pointés")), s.cross ? say(`including ${s.cross} films whose torrents share one file: they stay linked`, `dont ${s.cross} films à plusieurs torrents sur un seul fichier : tous restent liés`) : "", [say("Torrents are moved inside their client, not removed and added again: their ratio is kept.", "Les torrents sont déplacés dans leur client, pas supprimés puis recréés : leur ratio est conservé."), ""])}
      ${line("🔗", s.liens ? `${oplural(s.liens, say("link", "lien"), say("links", "liens"))} ${say("via", "via")} ${s.link_root ? esc(s.link_root) : say("the Link Folder", "le Dossier de liens")}` : say("No Link Folder needed", "Aucun Dossier de liens nécessaire"), "", [say("When a client cannot use the new name, it reads the file through a link in the Link Folder. The files themselves are not duplicated.", "Quand un client ne peut pas utiliser le nouveau nom, il lit le fichier par un lien dans le Dossier de liens. Les fichiers eux-mêmes ne sont pas dupliqués."), ""])}
    </div>
    <div class="og-ex"><b>${say("Examples", "Exemples")}</b>${s.examples.map((x) => `<div class="og-rn"><span class="a" title="${esc(x.from)}">${esc(x.from)}</span><span class="b">→ ${esc(x.to)}</span></div>`).join("")}</div>
    ${s.review ? `<p class="muted">${oplural(s.review, say("item to check stays", "élément à vérifier reste"), say("items to check stay", "éléments à vérifier restent"))} ${say("in place.", "en place.")}</p>` : ""}
    <div class="dialog-foot"><button type="button" data-o="close">${say("Cancel", "Annuler")}</button><button type="button" class="primary" data-o="launch" ${s.n ? "" : "disabled"}>${say("Start", "Lancer")}</button></div>`;
}
function foldersSheet() {
  const f = O.folders;
  if (!f) return `${sheetHead(say("Choose folders", "Choisir les dossiers"))}<div class="empty">…</div>`;
  const rows = [];
  for (const d of f.disks) {
    const pct = d.total ? Math.round((d.used / d.total) * 100) : 0;
    rows.push(`<div class="og-fd">${esc(d.name)} <span class="muted">· ${d.free <= 0 ? say("full", "pleine") : pct < 1 ? size(d.total) : `${pct} %`}</span></div>`);
    for (const x of f.folders.filter((y) => y.disk === d.name)) {
      const deep = !!x.parent;
      rows.push(`<div class="og-frow ${deep ? "deep" : ""}"><div class="nm"><b>${esc(x.path.slice(d.name.length + 1))}</b><small class="muted">${esc(x.path)}${x.videos ? ` · ${oplural(x.videos, say("video", "vidéo"), say("videos", "vidéos"))}` : ""}</small></div>
        <div class="og-seg" role="group" aria-label="${say("Role of", "Rôle de")} ${esc(x.path)}">${[["lib", say("Organised", "Organisée")], ["prov", "Provenance"], ["none", say("Ignored", "Ignorée")]].map(([r, t]) => `<button type="button" aria-pressed="${x.role === r}" data-o="role" data-f="${esc(x.path)}" data-r="${r}">${t}</button>`).join("")}</div>
        ${x.role === "lib" ? `<select data-o="kind" data-f="${esc(x.path)}" aria-label="Type"><option value="films" ${x.kind === "films" ? "selected" : ""}>Films</option><option value="series" ${x.kind === "series" ? "selected" : ""}>${say("Series", "Séries")}</option><option value="other" ${x.kind === "other" ? "selected" : ""}>${say("Both", "Les deux")}</option></select>` : ""}</div>`);
    }
  }
  return `${sheetHead(say("Choose folders", "Choisir les dossiers"), { en: "Organised: the app names and sorts everything in it. Provenance: a folder films and series come from, to tidy. Ignored: left alone. You can change your mind at any time.", fr: "Organisée : l'application nomme et classe tout ce qu'il y a dedans. Provenance : un dossier d'où viennent des films et séries à ranger. Ignorée : on n'y touche pas. Vous pourrez changer d'avis à tout moment." })}
    <p class="muted">${say("Your Library and Download Folders (Paramètres). None is set until you choose.", "Vos dossiers de bibliothèque et de téléchargement (Paramètres). Aucun n'est réglé tant que vous ne choisissez pas.")}</p><div class="og-flist">${rows.join("")}</div><div class="dialog-foot"><button type="button" class="primary" data-o="close">${say("Done", "Terminé")}</button></div>`;
}
const SAMPLE_T = { film: { titre: "Dune", année: "2021", tmdbid: "438631" }, series: { titre: "Severance", année: "2022", saison: "01", épisode: "03" } };
const oexample = (tpl, kind) => `${tpl.replace(/\{([^}]*)\}/g, (_, t) => SAMPLE_T[kind][t] ?? "").split("/").join(" / ")}.mkv`;
function settingsSheet() {
  const sets = S.org.libraries.flatMap((l) => l.templates.map((t) => `<div class="og-set"><div class="row"><b>${esc(t.kind === "film" ? "Films" : say("Series", "Séries"))}</b><span class="badge">${esc(oname(l))}</span></div>
    <input data-o="tpl" data-f="${esc(l.path)}" data-kind="${t.kind}" value="${esc(t.template)}" spellcheck="false" aria-label="${say("Template", "Modèle")} ${esc(oname(l))}">
    <div class="tokens">${S.org.tokens.map((x) => `<button type="button" data-o="token" data-f="${esc(l.path)}" data-kind="${t.kind}" data-t="${esc(x)}">${esc(x)}</button>`).join("")}</div>
    <div class="tplout" data-f="${esc(l.path)}" data-kind="${t.kind}">${t.error ? `<div class="err">${esc(t.error)}</div>` : `<div class="example"><small>${say("Example", "Exemple")}</small>${esc(t.example)}</div>`}</div>
    <div class="row"><button type="button" class="small" data-o="tplreset" data-f="${esc(l.path)}" data-kind="${t.kind}" ${t.template === t.default ? "disabled" : ""}>${say("Restore the Jellyfin template", "Rétablir le modèle Jellyfin")}</button></div></div>`));
  return `${sheetHead(say("Tidy settings", "Réglages du rangement"), { en: "A “/” separates one folder from the next; the last level is the file name. The default template follows the Jellyfin layout.", fr: "Un « / » sépare un dossier du suivant ; le dernier niveau est le nom du fichier. Le modèle par défaut suit le format Jellyfin." })}
    ${sets.join("") || `<p class="muted">${say("Choose an organised library first.", "Choisissez d'abord une bibliothèque organisée.")}</p>`}
    <div class="og-set"><div class="row"><b>${say("Link Folder", "Dossier des liens")}</b>${tip("Used only when a client cannot follow the new name: it then reads the file through a link. It is set per client in Settings.", "Utilisé seulement quand un client ne peut pas suivre le nouveau nom : il lit alors le fichier par un lien. Il se règle par client dans Paramètres.")}</div><input value="${esc(S.org.link_root || say("Not set", "Non défini"))}" readonly aria-label="${say("Link Folder", "Dossier des liens")}"></div>
    <div class="dialog-foot"><button type="button" class="primary" data-o="close">${say("Close", "Fermer")}</button></div>`;
}
const pinSheet = (path) => () => `${sheetHead(`${say("Pin", "Fixer")} ${esc(oshort(S.org.provenances.find((p) => p.path === path) || { path, name: path }))}`, { en: AUTO_WHY(), fr: AUTO_WHY() })}
  <div class="og-pick">${S.org.libraries.map((l) => `<button type="button" class="og-pickrow" data-o="dolink" data-p="${esc(path)}" data-l="${esc(l.path)}"><b>${esc(oname(l))}</b><small class="muted">${esc(l.path)}</small></button>`).join("")}</div>
  <div class="dialog-foot"><button type="button" data-o="close">${say("Cancel", "Annuler")}</button></div>`;

// ---- Actions ------------------------------------------------------------------------------------
async function reload() { try { S.org = await api("organisation"); } catch (e) { ofail(e); } sheetRedraw(); if (!$("dialog").open) render(); }
async function post(path, body, done) { try { await api(`organisation/${path}`, body); if (done) TLToast.show(done); } catch (e) { ofail(e); } await reload(); }
const link = (path, to) => post("link", { path, to }, to ? say("Pinned.", "Fixé.") : say("Back to Automatic.", "De nouveau en Automatique."));
async function loadFolders() { try { O.folders = await api("organisation/folders"); } catch (e) { ofail(e); } sheetRedraw(); }

document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-o]");
  if (!el || el.tagName === "INPUT" || el.tagName === "SELECT") return;
  const k = el.dataset.o, p = el.dataset.p;
  if (k === "close") $("dialog").close();
  else if (k === "folders") { O.folders = null; openSheet(foldersSheet); loadFolders(); }
  else if (k === "settings") openSheet(settingsSheet);
  else if (k === "settingsgo") parent.location.hash = "#/setup";
  else if (k === "totasks") { S.tab = "tasks"; render(); load(); }
  else if (k === "auto") post("auto", { path: p, on: el.getAttribute("aria-checked") !== "true" });
  else if (k === "link") { O.linking = O.linking === p ? null : p; render(); if (O.linking) document.querySelector(".og-lib")?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
  else if (k === "cancellink") { O.linking = null; render(); }
  else if (k === "pick") { const from = O.linking; O.linking = null; link(from, el.dataset.l); }
  else if (k === "pick") { await post("review", { path: el.dataset.i, title: el.dataset.t }, say("Title given.", "Titre attribué.")); }
  else if (k === "unlink") link(p, "");
  else if (k === "dolink") { $("dialog").close(); link(p, el.dataset.l); }
  else if (k === "ranger" || k === "rangerall") {
    O.paths = k === "rangerall" ? JSON.parse(el.dataset.ps) : [p];
    try { O.summary = await api("organisation/summary", { paths: O.paths }); openSheet(summarySheet); } catch (x) { ofail(x); }
  } else if (k === "launch") {
    try { const r = await api("organisation/ranger", { paths: O.paths }); $("dialog").close(); TLToast.show(say(`${r.queued} item(s) queued: follow them in Tasks.`, `${r.queued} élément(s) lancé(s) : suivez-les dans Tâches.`)); S.tab = "tasks"; render(); load(); } catch (x) { ofail(x); }
  } else if (k === "revtoggle") { O.reviewOpen = !O.reviewOpen; render(); }
  else if (k === "gorev") { e.preventDefault(); O.reviewOpen = true; render(); document.getElementById("og-review")?.scrollIntoView({ behavior: "smooth", block: "start" }); }
  else if (k === "fix") {
    const input = document.querySelector(`[data-o="title"][data-i="${CSS.escape(el.dataset.i)}"]`), v = input.value.trim();
    if (!v) { input.focus(); return TLToast.show(say("Write a title first.", "Écrivez d'abord un titre."), "bad"); }
    post("review", { path: el.dataset.i, title: v }, say(`“${v}” is ready to tidy.`, `« ${v} » est prêt à ranger.`));
  } else if (k === "keep") post("review", { path: el.dataset.i, keep: true }, say("It stays as it is.", "Il reste tel quel."));
  else if (k === "role") { try { await api("organisation/role", { path: el.dataset.f, role: el.dataset.r, kind: "" }); } catch (x) { ofail(x); } await Promise.all([loadFolders(), reload()]); }
  else if (k === "token") {
    const input = document.querySelector(`input[data-o="tpl"][data-f="${CSS.escape(el.dataset.f)}"][data-kind="${el.dataset.kind}"]`), a = input.selectionStart ?? input.value.length, b = input.selectionEnd ?? a;
    input.value = input.value.slice(0, a) + el.dataset.t + input.value.slice(b);
    input.focus(); input.dispatchEvent(new Event("input", { bubbles: true }));
  } else if (k === "tplreset") { try { await api("organisation/template", { folder: el.dataset.f, kind: el.dataset.kind, template: "" }); } catch (x) { ofail(x); } reload(); }
});
document.addEventListener("change", async (e) => {
  const el = e.target, k = el.dataset?.o;
  if (k === "dest") link(el.dataset.p, el.value);
  else if (k === "kind") { try { await api("organisation/role", { path: el.dataset.f, role: "lib", kind: el.value }); } catch (x) { ofail(x); } await Promise.all([loadFolders(), reload()]); }
  else if (k === "tpl") { try { await api("organisation/template", { folder: el.dataset.f, kind: el.dataset.kind, template: el.value }); TLToast.show(say("Template saved.", "Modèle enregistré.")); } catch (x) { ofail(x); } reload(); }
});
// What is typed asks the indexes again; the picks under the field follow it.
let titleAsk = 0;
document.addEventListener("input", (e) => {
  if (e.target.dataset?.o !== "title") return;
  const field = e.target, value = field.value.trim(), asked = ++titleAsk;
  clearTimeout(field.titleTimer);
  field.titleTimer = setTimeout(async () => {
    const box = [...document.querySelectorAll(".og-picks")].find((b) => b.dataset.for === field.dataset.i);
    if (!box || value.length < 2) return;
    let found = [];
    try { found = (await api(`organisation/suggest?q=${encodeURIComponent(value)}`)).titles; } catch { return; }
    if (asked === titleAsk) box.innerHTML = picks(found, field.dataset.i) || `<span class="muted">${say("No title found: write it and Fix.", "Aucun titre trouvé : écrivez-le puis Corriger.")}</span>`;
  }, 200);
});
document.addEventListener("input", (e) => {
  if (e.target.dataset?.o !== "tpl") return;
  const out = document.querySelector(`.tplout[data-f="${CSS.escape(e.target.dataset.f)}"][data-kind="${e.target.dataset.kind}"]`);
  const bad = (e.target.value.match(/\{[^}]*\}/g) || []).filter((x) => !S.org.tokens.includes(x));
  out.innerHTML = bad.length ? `<div class="err">${say("Unknown token", "Jeton inconnu")} : ${esc(bad.join(", "))}</div>` : !e.target.value.includes("{titre}") ? `<div class="err">${say("The template must contain {titre}.", "Le modèle doit contenir {titre}.")}</div>` : `<div class="example"><small>${say("Example", "Exemple")}</small>${esc(oexample(e.target.value, e.target.dataset.kind))}</div>`;
});
document.addEventListener("keydown", (e) => {
  const sw = e.target.closest?.('[data-o="pick"]');
  if (sw && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); sw.click(); }
});
// Drag a provenance onto a library.
let dragPath = null;
document.addEventListener("dragstart", (e) => { const c = e.target.closest?.("[data-drag]"); if (!c) return; dragPath = c.dataset.drag; e.dataTransfer.setData("text/plain", dragPath); e.dataTransfer.effectAllowed = "link"; document.getElementById("app").classList.add("og-dragging"); });
document.addEventListener("dragend", () => { dragPath = null; document.getElementById("app")?.classList.remove("og-dragging"); document.querySelectorAll(".og-over").forEach((x) => x.classList.remove("og-over")); });
document.addEventListener("dragover", (e) => { const t = e.target.closest?.("[data-lib]"); if (t && dragPath) { e.preventDefault(); document.querySelectorAll(".og-over").forEach((x) => x !== t && x.classList.remove("og-over")); t.classList.add("og-over"); } });
document.addEventListener("drop", (e) => { const t = e.target.closest?.("[data-lib]"); if (!t || !dragPath) return; e.preventDefault(); const from = dragPath; dragPath = null; link(from, t.dataset.lib); });
// True while a person is typing in the board: a redraw would drop what they typed.
const orgBusy = () => !!document.activeElement?.closest?.(".og-rrow, .og-set");
