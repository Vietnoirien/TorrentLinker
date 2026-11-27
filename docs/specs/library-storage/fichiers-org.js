"use strict";
// Preview "Organisation A" (board) and "Organisation B" (libraries first). Needs fichiers.js and fichiers-storage.js.
// Self-contained fixture: the owner's real folders. Nothing is read from a disk; "Lancer" feeds the real task queue of the preview.
(() => {
  const { S, esc, size, num } = FX;
  const tip = (t, l) => FX.tipBtn(t, l || "Plus d'informations");
  const SPEED = 0.1; // GB/s, a copy to the other disk
  const COLORS = { films: "#80bdb6", series: "#edbf73", other: "#b9a3f5" };
  const DISKS = { "/windocs": { pct: 100, txt: "pleine" }, "/saves": { pct: 92, txt: "92 %" }, "/library": { pct: 0, txt: "14 To" } };
  const KIND = { films: "Films", series: "Séries" };
  const O = (FX.O = { variant: null, linking: null, dlg: null, dlgFn: null, reviewOpen: true, tpl: {} });

  // ------------------------------------------------------------------------------------------ fixture
  const prov = o => ({ role: "prov", films: 0, series: 0, gbF: 0, gbS: 0, review: [], auto: false, links: [], cross: 0, torrents: 0, liens: 0, subs: [], ex: [], ...o });
  const lib = (id, path, kind, poster0) => ({ id, path, disk: "/library", role: "lib", kind, n: 0, gb: 0, shown: [], poster0 });
  function fixture() {
    O.f = [
      lib("lf", "/library/Films", "films", 0),
      lib("ls", "/library/Séries", "series", 6),
      prov({ id: "wf", path: "/windocs/Film", disk: "/windocs", was: true, films: 412, series: 3, gbF: 1840, gbS: 60, cross: 2, torrents: 231, liens: 18,
        review: [["VID_20190812_221534.mp4", 1.2], ["New folder (3)", 3.4], ["movie.mkv", 1.6], ["1080p.x265-GRP.mkv", 2.1], ["DSC_0042.avi", 0.4]],
        ex: [["Gourou.2026.FRENCH.AD.720p.WEB.H265-TyHD.mkv", "Gourou (2026)/Gourou (2026).mkv"],
          ["Le.Daim.2019.FRENCH.1080p.HDLight.x264.AC3-TOXIC.mkv", "Le Daim (2019)/Le Daim (2019).mkv"],
          ["Annihilation.2018.MULTi.1080p.BluRay.x264-FuN.mkv", "Annihilation (2018)/Annihilation (2018).mkv"]],
        exS: [["Dark.Matter.2024.S01E03.MULTi.1080p.WEB.mkv", "Dark Matter (2024)/Saison 01/Dark Matter S01E03.mkv"]] }),
      prov({ id: "vf", path: "/saves/Vidéos/Films", disk: "/saves", was: true, films: 96, gbF: 400, links: ["lf"], torrents: 40, liens: 3, subs: [["Science Fiction", 41], ["film sonia", 28]],
        review: [["film sonia/Sans titre 2.mp4", 0.9], ["film sonia/IMG_3310.mov", 0.5], ["Science Fiction/untitled.mkv", 1.4]],
        ex: [["Blade.Runner.2049.2017.MULTi.2160p.UHD.x265-PRiME.mkv", "Blade Runner 2049 (2017)/Blade Runner 2049 (2017).mkv"],
          ["Moon.2009.FRENCH.720p.BluRay.x264.mkv", "Moon (2009)/Moon (2009).mkv"]] }),
      prov({ id: "ws", path: "/windocs/Séries", disk: "/windocs", was: true, series: 38, gbS: 1100, torrents: 22, liens: 2,
        ex: [["Black.Mirror.S01E01.The.National.Anthem.1080p.mkv", "Black Mirror (2011)/Saison 01/Black Mirror S01E01.mkv"]] }),
      prov({ id: "td", path: "/library/Téléchargements", disk: "/library", dl: true, auto: true, review: [["a8f3k2.mkv", 0.7]],
        ex: [["Dune.Part.Two.2024.MULTi.1080p.BluRay.x265-FRATERNiTY.mkv", "Dune Part Two (2024)/Dune Part Two (2024).mkv"]] }),
      { id: "ph", path: "/windocs/Documents", disk: "/windocs", role: "none", items: "aucune vidéo" },
      { id: "pp", path: "/windocs/Photos", disk: "/windocs", role: "none", items: "aucune vidéo" },
      { id: "sv", path: "/saves/Sauvegardes", disk: "/saves", role: "none", items: "aucune vidéo" },
      prov({ id: "vp", path: "/saves/Vidéos/Perso", disk: "/saves", role: "none", films: 4, gbF: 26, review: [["Noël 2021.mp4", 2], ["Vacances.mov", 2]], torrents: 0, liens: 0 }),
    ];
    O.f.find(f => f.id === "td").cross = 0;
    O.linking = null;
    O.tpl = { Films: S.templates?.Films || "{titre} ({année})/{titre} ({année})", "Séries": S.templates?.["Séries"] || "{titre} ({année})/Saison {saison}/{titre} S{saison}E{épisode}" };
    O.tpl.Films = "{titre} ({année})/{titre} ({année})";
  }
  fixture();
  const get = id => O.f.find(f => f.id === id);
  const libs = () => O.f.filter(f => f.role === "lib");
  const provs = () => O.f.filter(f => f.role === "prov");
  const items = p => p.films + p.series;
  const gbOf = p => p.gbF + p.gbS;
  const dpath = f => f.path.split("/").filter(Boolean);
  const short = f => dpath(f).slice(1).join("/") || f.path;
  const wait = gb => { const s = gb / SPEED; return s < 90 ? "moins de 2 min" : s < 5400 ? `~${Math.round(s / 60)} min` : `~${num(Math.round(s / 360) / 10)} h`.replace(",0", ""); };
  const hours = gb => { const s = gb / SPEED; return s < 5400 ? `~${Math.max(2, Math.round(s / 60))} min` : `~${Math.round(s / 3600)} h`; };
  const col = l => COLORS[l.kind] || COLORS.other;

  // Where a provenance's content goes: films to its linked films library, series to the series library (linked or not).
  const AUTO_WHY = "Automatique : pour chaque élément, l'application choisit la bibliothèque selon son type (film, série, anime), puis selon la règle de placement : le même disque que ses autres versions ou épisodes, sinon la bibliothèque organisée qui a le plus de place. Vous pouvez aussi imposer une bibliothèque.";
  const fixedLib = p => (p.links[0] ? get(p.links[0]) : null);
  const byKind = kind => libs().filter(l => l.kind === kind).sort((a, b) => (14000 - a.gb) < (14000 - b.gb) ? 1 : -1)[0] || null;
  function dest(p) {
    const fx = fixedLib(p), out = [];
    const pick = kind => fx && fx.kind === kind ? { lib: fx, routed: false } : { lib: byKind(kind), routed: !!fx };
    if (p.films) out.push({ kind: "films", n: p.films, gb: p.gbF, ...pick("films") });
    if (p.series) out.push({ kind: "series", n: p.series, gb: p.gbS, ...pick("series") });
    return out;
  }
  const ready = p => items(p) > 0 && dest(p).some(d => d.lib);
  function summary(list) {
    const parts = list.filter(ready);
    const s = { n: 0, gb: 0, torrents: 0, liens: 0, cross: 0, review: 0, ex: [], exS: [], dests: new Map(), routed: [], unrouted: [], names: parts.map(short) };
    for (const p of parts) {
      for (const d of dest(p)) {
        if (!d.lib) { s.unrouted.push({ p, d }); continue; }
        s.n += d.n; s.gb += d.gb;
        const k = d.lib.id, cur = s.dests.get(k) || { lib: d.lib, n: 0, gb: 0 };
        cur.n += d.n; cur.gb += d.gb; s.dests.set(k, cur);
        if (d.routed) s.routed.push({ p, d });
      }
      const done = dest(p).filter(d => d.lib), share = items(p) ? done.reduce((a, d) => a + d.n, 0) / items(p) : 0;
      s.torrents += Math.round(p.torrents * share); s.liens += Math.round(p.liens * share); s.cross += p.cross; s.review += p.review.length;
      s.ex.push(...p.ex); s.exS.push(...(p.exS || []));
    }
    s.parts = parts;
    return s;
  }
  const plural = (n, a, b) => `${num(n)} ${n > 1 ? b : a}`;

  // ------------------------------------------------------------------------------------------ pieces
  const disk = d => { const x = DISKS[d] || { pct: 0, txt: "" }; return `<span class="og-disk" title="${esc(d)}"><i><b style="width:${x.pct}%" class="${x.pct >= 90 ? "hot" : ""}"></b></i>${esc(d)} · ${esc(x.txt)}</span>`; };
  const sw = (on, attrs, label) => `<button type="button" role="switch" aria-checked="${on}" class="og-sw ${on ? "on" : ""}" ${attrs} aria-label="${esc(label)}"><i></i></button>`;
  const roleName = p => p.dl ? "Téléchargements" : p.was ? "Ancienne bibliothèque" : "Provenance";
  const emptied = p => p.was && items(p) === 0 && !p.review.length && p.done;
  const emptiedNote = p => {
    const l = fixedLib(p) || byKind("films");
    return `<div class="og-note">✓ Vide. <span>Remplacé par ${esc(l.path)} dans Paramètres.</span><button type="button" class="small quiet" data-o="settingsgo">Ouvrir Paramètres</button></div>`;
  };
  const chips = p => !p.links.length ? `<span class="og-chip auto"><span class="dot"></span>→ Automatique</span>` : p.links.map(get).map(l => `<button type="button" class="og-chip" style="--c:${col(l)}" data-o="unlink" data-p="${p.id}" data-l="${l.id}" title="Remettre en Automatique"><span class="dot"></span>${esc(KIND[l.kind] || short(l))}<span class="x">✕</span></button>`).join("");
  const reviewHTML = () => {
    const rows = provs().flatMap(p => p.review.map((r, i) => ({ p, r, i })));
    return `<section class="og-review card" id="og-review">
      <div class="row"><h3>À vérifier</h3><span class="badge ${rows.length ? "warn" : "ok"}">${rows.length}</span>${tip("Ces éléments n'ont pas de titre reconnaissable (par exemple IMG_3310.mov). Ils restent où ils sont tant que vous ne les avez pas corrigés. Donnez-leur un titre pour qu'ils soient rangés, ou gardez-les tel quel.", "Aide sur À vérifier")}<span class="grow"></span>
        ${rows.length ? `<button type="button" class="small quiet" data-o="revtoggle">${O.reviewOpen ? "Replier" : "Afficher"}</button>` : ""}</div>
      ${rows.length ? (O.reviewOpen ? `<div class="og-rv">${rows.map(({ p, r, i }) => `<div class="og-rrow"><div class="nm"><b title="${esc(r[0])}">${esc(r[0])}</b><small>${esc(short(p))} · ${size(r[1])}</small></div>
          <input data-o="title" data-p="${p.id}" data-i="${i}" placeholder="Titre du film ou de la série" aria-label="Titre de ${esc(r[0])}" />
          <span class="btns"><button type="button" class="small primary" data-o="fix" data-p="${p.id}" data-i="${i}">Corriger</button><button type="button" class="small" data-o="keep" data-p="${p.id}" data-i="${i}">Garder tel quel</button></span></div>`).join("")}</div>` : "") : `<p class="muted">Rien à vérifier.</p>`}
    </section>`;
  };
  const linkingBar = () => { const p = O.linking && get(O.linking); return p ? `<div class="og-linking" role="status"><span>Fixer <b>${esc(short(p))}</b></span><button type="button" class="small" data-o="cancellink">Annuler</button></div>` : ""; };
  const head = (variant) => `<div class="og-head">
      <div class="row"><h2>Organisation</h2>${tip("Ici, vous choisissez les dossiers que l'application organise (vos bibliothèques) et d'où viennent les films et séries à y ranger. Rien ne bouge sans votre accord ; tout continue de partager.", "Aide sur Organisation")}</div>
      <span class="grow"></span>
      <button type="button" data-o="folders">${variant === "A" ? "Choisir les dossiers" : "Gérer les dossiers"}</button>
      <button type="button" data-o="settings" aria-label="Réglages du rangement" title="Réglages">⚙</button></div>`;

  // ------------------------------------------------------------------------------------------ Design A
  function provCardA(p) {
    const n = items(p), dragging = !p.dl || true;
    const sub = p.subs.length ? `<small class="muted og-subs">dont ${p.subs.map(([a, c]) => `${esc(a)} (${c})`).join(" · ")}</small>` : "";
    const count = n ? `${plural(p.films, "film", "films")}${p.series ? ` · ${plural(p.series, "série", "séries")}` : ""} · ${size(gbOf(p))}` : p.done ? "Tout est rangé" : "Rien à ranger";
    const seriesOnly = !p.films && p.series ? `${plural(p.series, "série", "séries")} · ${size(gbOf(p))}` : count;
    return `<article class="og-card og-prov ${O.linking === p.id ? "picking" : ""} ${p.links.length ? "" : "unlinked"}" data-card="${p.id}" ${dragging ? `draggable="true" data-drag="${p.id}"` : ""}>
      <div class="og-top"><span class="og-grip" aria-hidden="true">⠿</span><div class="og-title"><b>${esc(short(p))}</b><small class="muted">${esc(p.path)}</small></div><span class="badge">${roleName(p)}</span></div>
      <div class="og-meta">${disk(p.disk)}</div>
      <div class="og-count ${n ? "" : "muted"}">${seriesOnly}${n ? "" : ""}</div>${sub}
      ${p.review.length ? `<a class="og-warn" href="#og-review" data-o="gorev">⚠ ${plural(p.review.length, "à vérifier", "à vérifier")}</a>` : ""}
      <div class="og-links">${chips(p)}</div>
      ${emptied(p) ? emptiedNote(p) : ""}
      <div class="og-act"><label class="og-auto">${sw(p.auto, `data-o="auto" data-p="${p.id}"`, "Ranger automatiquement les nouveautés")}<span>Auto</span></label>${tip("Auto : chaque nouvel élément arrivé dans ce dossier est rangé tout seul, sans cesser de partager. Désactivé par défaut pour une ancienne bibliothèque.", "Aide sur Auto")}
        <span class="grow"></span>
        <select data-o="dest" data-p="${p.id}" aria-label="Destination"><option value="">Automatique</option>${libs().map(l => `<option value="${l.id}" ${p.links[0] === l.id ? "selected" : ""}>${esc(KIND[l.kind] || short(l))}</option>`).join("")}</select>${tip(AUTO_WHY, "Aide sur la destination")}<button type="button" class="small" data-o="link" data-p="${p.id}">Fixer</button>
        <button type="button" class="small primary" data-o="ranger" data-p="${p.id}" ${ready(p) ? "" : "disabled"}>Ranger</button></div>
    </article>`;
  }
  function libCardA(l) {
    const linked = provs().filter(p => p.links.includes(l.id));
    return `<article class="og-card og-lib ${O.linking ? "target" : ""}" style="--c:${col(l)}" data-lib="${l.id}" ${O.linking ? `data-o="pick" data-l="${l.id}" tabindex="0" role="button"` : ""}>
      <div class="og-top"><div class="og-title"><b>${esc(KIND[l.kind] || short(l))}</b><small class="muted">${esc(l.path)}</small></div><span class="badge ok">✓ organisée</span></div>
      <div class="og-meta">${disk(l.disk)}</div>
      <div class="og-count">${l.n ? `${plural(l.n, l.kind === "series" ? "série" : "film", l.kind === "series" ? "séries" : "films")} · ${size(l.gb)}` : `<span class="muted">${l.kind === "series" ? "0 série" : "0 film"} · vide</span>`}</div>
      <small class="muted">${linked.length ? `${plural(linked.length, "dossier fixé ici", "dossiers fixés ici")}` : "Reçoit aussi les dossiers en Automatique"}</small>
      ${O.linking ? `<span class="og-drophere">Lier ici</span>` : `<span class="og-drophere">Déposez un dossier ici</span>`}
    </article>`;
  }
  FX.orgAHTML = () => `<div class="og og-a">${head("A")}${linkingBar()}
    <div class="og-board" id="og-board">
      <svg class="og-wires" id="og-wires" aria-hidden="true"></svg>
      <section class="og-col"><div class="row og-colhead"><h3>Provenances</h3>${tip("Les dossiers d'où viennent vos films et séries : anciennes bibliothèques et dossiers de téléchargement. Par défaut chaque dossier est en Automatique : l'application choisit la bibliothèque de chaque élément. Pour en imposer une, glissez le dossier dessus ou touchez Fixer.", "Aide sur Provenances")}</div>
        ${provs().filter(p => p.role === "prov").map(provCardA).join("")}</section>
      <section class="og-col"><div class="row og-colhead"><h3>Bibliothèques organisées</h3>${tip("Les dossiers que l'application nomme et classe pour vous (format Jellyfin). Les films vont dans la bibliothèque de films, les séries dans celle des séries, ensuite au mieux selon la place.", "Aide sur Bibliothèques organisées")}</div>
        ${libs().map(libCardA).join("")}</section>
    </div>${reviewHTML()}</div>`;

  function wires() {
    const board = document.getElementById("og-board"), svg = document.getElementById("og-wires");
    if (!board || !svg) return;
    if (matchMedia("(max-width: 800px)").matches) { svg.innerHTML = ""; return; }
    const b = board.getBoundingClientRect();
    svg.setAttribute("width", b.width); svg.setAttribute("height", b.height);
    let out = "";
    for (const p of provs().filter(x => x.role === "prov")) for (const id of (p.links.length ? p.links : libs().map(l => l.id))) {
      const a = board.querySelector(`[data-card="${p.id}"]`), z = board.querySelector(`[data-lib="${id}"]`), l = get(id), fx = p.links.length > 0;
      if (!a || !z || !l) continue;
      const ra = a.getBoundingClientRect(), rz = z.getBoundingClientRect();
      const x1 = ra.right - b.left, y1 = ra.top - b.top + ra.height / 2, x2 = rz.left - b.left, y2 = rz.top - b.top + rz.height / 2, mx = (x1 + x2) / 2, c = fx ? col(l) : "#98aab7";
      out += `<path d="M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}" fill="none" stroke="${c}" stroke-width="${fx ? 3.5 : 1.6}" stroke-linecap="round" ${fx ? "" : 'stroke-dasharray="5 6"'} opacity="${fx ? 0.95 : 0.55}"/><circle cx="${x2}" cy="${y2}" r="${fx ? 5 : 3}" fill="${c}"/>`;
      if (!out.includes(`data-s${p.id}`)) out += `<circle data-s${p.id} cx="${x1}" cy="${y1}" r="5" fill="${fx ? col(l) : "#98aab7"}"/>`;
    }
    svg.innerHTML = out;
  }
  addEventListener("resize", () => wires());

  // ------------------------------------------------------------------------------------------ Design B
  function mosaic(l) {
    const cells = [];
    for (let i = 0; i < 6; i++) cells.push(i < l.shown.length ? `<img src="/library-storage-preview/poster-${l.shown[i]}.png" alt="" loading="lazy" />` : `<span class="ghost"></span>`);
    return `<div class="og-mosaic ${l.n ? "" : "empty"}">${cells.join("")}${l.n ? "" : `<span class="og-emptylbl">Bibliothèque vide pour l'instant</span>`}</div>`;
  }
  function chipRow(p, l) {
    const n = items(p), c = l ? col(l) : "var(--muted)";
    const status = emptied(p) ? "Vide" : n ? `${num(n)} à ranger` : p.done ? "Tout est rangé" : "Rien à ranger";
    return `<div class="og-prow" style="--c:${c}"><span class="dot"></span>
      <div class="nm"><b>${esc(short(p))}</b><small class="muted">${esc(p.disk)} · ${esc(status)}${p.review.length ? ` · ⚠ ${p.review.length} à vérifier` : ""}</small>${emptied(p) ? emptiedNote(p) : ""}</div>
      <label class="og-auto" title="Ranger automatiquement les nouveautés">${sw(p.auto, `data-o="auto" data-p="${p.id}"`, "Auto")}<span>Auto${p.auto ? " ●" : ""}</span></label>
      <button type="button" class="small primary" data-o="ranger" data-p="${p.id}" ${ready(p) ? "" : "disabled"}>Ranger</button>
      ${l ? `<button type="button" class="small quiet" data-o="unlink" data-p="${p.id}" data-l="${l.id}" aria-label="Remettre ${esc(short(p))} en Automatique" title="Remettre en Automatique">✕</button>` : `<button type="button" class="small" data-o="addfix" data-p="${p.id}">Fixer…</button>`}</div>`;
  }
  function autoGroup() {
    const list = provs().filter(p => p.role === "prov" && !p.links.length);
    return `<article class="og-bigcard og-autogrp"><div class="og-bigbody"><div class="og-top"><div class="og-title"><b>Automatique</b><small class="muted">Chaque élément va dans la bonne bibliothèque</small></div>${tip(AUTO_WHY, "Aide sur Automatique")}<span class="badge">${plural(list.length, "dossier", "dossiers")}</span></div>
      <div class="og-rows">${list.map(p => chipRow(p, null)).join("") || `<p class="muted og-none">Aucun dossier en Automatique.</p>`}</div></div></article>`;
  }
  function libCardB(l) {
    const linked = provs().filter(p => p.links.includes(l.id));
    const free = provs().filter(p => p.role === "prov" && !p.links.includes(l.id));
    return `<article class="og-bigcard" style="--c:${col(l)}">${mosaic(l)}
      <div class="og-bigbody"><div class="og-top"><div class="og-title"><b>${esc(KIND[l.kind] || short(l))}</b><small class="muted">${esc(l.path)}</small></div><span class="badge ok">✓ organisée</span></div>
        <div class="og-meta"><span class="og-count">${l.n ? `${plural(l.n, l.kind === "series" ? "série" : "film", l.kind === "series" ? "séries" : "films")} · ${size(l.gb)}` : `<span class="muted">0 ${l.kind === "series" ? "série" : "film"} · 0 Go</span>`}</span>${disk(l.disk)}</div>
        <div class="og-rows">${linked.map(p => chipRow(p, l)).join("") || `<p class="muted og-none">Aucun dossier fixé ici. Reçoit aussi les dossiers en Automatique.</p>`}</div>
        <button type="button" class="og-add" data-o="addlink" data-l="${l.id}" ${free.length ? "" : "disabled"}>+ Lier un dossier</button></div></article>`;
  }
  FX.orgBHTML = () => {
    const s = summary(provs().filter(p => p.role === "prov"));
    const films = s.parts.reduce((a, p) => a + p.films, 0), series = s.parts.reduce((a, p) => a + p.series, 0);
    const txt = s.n ? `${plural(films, "film", "films")}${series ? ` et ${plural(series, "série", "séries")}` : ""} à ranger · ${size(s.gb)} · ${hours(s.gb)}` : "Tout est rangé";
    return `<div class="og og-b">${head("B")}
      <div class="og-strip ${s.n ? "" : "calm"}"><div class="txt"><b>${txt}</b>${s.review ? `<a href="#og-review" data-o="gorev" class="og-warn">⚠ ${s.review} à vérifier</a>` : ""}</div>
        <button type="button" class="primary" data-o="rangerall" ${s.n ? "" : "disabled"}>Tout ranger</button></div>
      <div class="og-biggrid">${autoGroup()}${libs().map(libCardB).join("")}</div>${reviewHTML()}</div>`;
  };

  // ------------------------------------------------------------------------------------------ sheets
  function openSheet(fn) {
    O.dlgFn = fn; O.dlg = FX.modal(fn()); O.dlg.classList.add("sheet");
    O.dlg.addEventListener("close", () => { O.dlg = null; O.dlgFn = null; });
  }
  const sheetHead = (title, tipText) => `<div class="og-sh"><h2>${title}</h2>${tipText ? tip(tipText) : ""}<span class="grow"></span><button type="button" class="quiet" data-o="close" aria-label="Fermer">✕</button></div>`;
  const redraw = () => { FX.render(); if (O.dlg?.open && O.dlgFn) O.dlg.innerHTML = O.dlgFn(); };

  function rangerSheet(list, title) {
    const s = summary(list);
    const dests = [...s.dests.values()];
    const to = dests.map(d => `${esc(d.lib.path)}`).join(" et ");
    const line = (k, label, text, t) => `<div class="og-stat"><span class="k">${k}</span><span class="v"><b>${label}</b>${text ? ` <span class="muted">${text}</span>` : ""}</span>${t ? tip(t) : ""}</div>`;
    return () => `${sheetHead(esc(title), "Un résumé de ce qui va se passer. Rien ne bouge avant « Lancer ».")}
      <div class="og-big"><span class="n">${plural(s.n, "élément", "éléments")}</span><span class="arrow">→</span><span class="to">${to}</span>${tip(AUTO_WHY, "Pourquoi cette bibliothèque")}</div>
      ${dests.length > 1 ? `<ul class="og-split">${dests.map(d => `<li><span class="dot" style="--c:${col(d.lib)}"></span>${plural(d.n, d.lib.kind === "series" ? "série" : "film", d.lib.kind === "series" ? "séries" : "films")} → ${esc(d.lib.path)}</li>`).join("")}</ul>` : ""}
      ${s.routed.length ? `<div class="og-route">${s.routed.map(r => `${plural(r.d.n, "série trouvée", "séries trouvées")} dans ${esc(short(r.p))} : ${r.d.n > 1 ? "rangées" : "rangée"} par type dans ${esc(r.d.lib.path)}`).join(" · ")}</div>` : ""}
      ${s.unrouted.length ? `<div class="og-route warn">${s.unrouted.map(r => `${plural(r.d.n, r.d.kind === "series" ? "série" : "film", r.d.kind === "series" ? "séries" : "films")} de ${esc(short(r.p))} : aucune bibliothèque ${r.d.kind === "series" ? "de séries" : "de films"} : ${r.d.n > 1 ? "restent" : "reste"} en place`).join(" · ")}</div>` : ""}
      <div class="og-stats">
        ${line("⏱", `${size(s.gb)} · ${wait(s.gb)}`, "", "Les fichiers sont copiés vers /library, un autre disque : la durée est une estimation. Vous pouvez fermer le navigateur, la suite est dans Tâches.")}
        ${line("▲", "Tout continue de partager", "", "Chaque torrent garde ses fichiers : il est re-pointé vers le nouvel emplacement et revérifié par son client. Aucun partage n'est interrompu plus que le temps de la vérification.")}
        ${line("↻", plural(s.torrents, "torrent re-pointé", "torrents re-pointés"), s.cross ? `dont ${s.cross} films à deux torrents sur un seul fichier : les deux restent liés` : "", "Les torrents sont déplacés dans leur client, pas supprimés puis recréés : leur ratio est conservé.")}
        ${line("🔗", plural(s.liens, "lien via /library/.liens", "liens via /library/.liens"), "", "Quand un client ne peut pas utiliser le nouveau nom, il lit le fichier par un lien dans /library/.liens. Les fichiers eux-mêmes ne sont pas dupliqués.")}
      </div>
      <div class="og-ex"><b>Exemples</b>${[...s.ex.slice(0, 3), ...s.exS.slice(0, 1)].map(([a, b]) => `<div class="og-rn"><span class="a" title="${esc(a)}">${esc(a)}</span><span class="b">→ ${esc(b)}</span></div>`).join("")}</div>
      ${s.review ? `<p class="muted">${plural(s.review, "élément à vérifier reste", "éléments à vérifier restent")} en place.</p>` : ""}
      <div class="dialog-foot"><button type="button" data-o="close">Annuler</button><button type="button" class="primary" data-o="launch" ${s.n ? "" : "disabled"}>Lancer</button></div>`;
  }

  function foldersSheet() {
    const rows = [];
    const seen = new Set();
    for (const d of ["/windocs", "/saves", "/library"]) {
      rows.push(`<div class="og-fd">${esc(d)} <span class="muted">· ${esc(DISKS[d].txt)}</span></div>`);
      for (const f of O.f.filter(x => x.disk === d)) {
        const role = f.role;
        const parentOf = f.path.split("/").length > 3;
        rows.push(`<div class="og-frow ${parentOf ? "deep" : ""}"><div class="nm"><b>${esc(short(f))}</b><small class="muted">${esc(f.path)}${f.role === "lib" ? "" : items(f) ? ` · ${plural(items(f), "vidéo", "vidéos")}` : f.items ? ` · ${f.items}` : ""}</small></div>
          <div class="og-seg" role="group" aria-label="Rôle de ${esc(f.path)}">${[["lib", "Organisée"], ["prov", "Provenance"], ["none", "Ignorée"]].map(([r, t]) => `<button type="button" aria-pressed="${role === r}" data-o="role" data-f="${f.id}" data-r="${r}">${t}</button>`).join("")}</div>
          ${role === "lib" ? `<select data-o="kind" data-f="${f.id}" aria-label="Type"><option value="films" ${f.kind === "films" ? "selected" : ""}>Films</option><option value="series" ${f.kind === "series" ? "selected" : ""}>Séries</option></select>` : ""}</div>`);
        if (f.subs?.length) for (const [a, c] of f.subs) rows.push(`<div class="og-frow deep sub"><div class="nm"><b>${esc(a)}</b><small class="muted">${esc(f.path)}/${esc(a)} · ${plural(c, "film", "films")}</small></div><span class="muted og-in">fait partie de ${esc(short(f))}</span></div>`);
      }
    }
    return () => `${sheetHead("Choisir les dossiers", "Organisée : l'application nomme et classe tout ce qu'il y a dedans. Provenance : un dossier d'où viennent des films et séries à ranger. Ignorée : on n'y touche pas. Vous pourrez changer d'avis à tout moment.")}
      <p class="muted">Tous les dossiers de vos disques.</p><div class="og-flist">${rows.join("")}</div><div class="dialog-foot"><button type="button" class="primary" data-o="close">Terminé</button></div>`;
  }
  const settingsSheet = () => `${sheetHead("Réglages du rangement", "Un « / » sépare un dossier du suivant ; le dernier niveau est le nom du fichier. Le modèle par défaut suit le format Jellyfin.")}
    ${["Films", "Séries"].map(k => `<div class="og-set"><b>${k}</b><input data-o="tpl" data-k="${k}" value="${esc(O.tpl[k])}" aria-label="Modèle ${k}" /><small class="muted">Exemple : ${esc(k === "Films" ? O.tpl[k].replace(/\{titre\}/g, "Gourou").replace(/\{année\}/g, "2026") : O.tpl[k].replace(/\{titre\}/g, "Black Mirror").replace(/\{année\}/g, "2011").replace(/\{saison\}/g, "01").replace(/\{épisode\}/g, "01"))}.mkv</small></div>`).join("")}
    <div class="og-set"><div class="row"><b>Dossier des liens</b>${tip("Utilisé seulement quand un client ne peut pas suivre le nouveau nom : il lit alors le fichier par un lien. Il se trouve sur le disque des bibliothèques.")}</div><input value="/library/.liens" readonly aria-label="Dossier des liens" /></div>
    <div class="dialog-foot"><button type="button" class="primary" data-o="close">Fermer</button></div>`;
  const fixSheet = pid => () => { const p = get(pid); return `${sheetHead(`Fixer ${esc(short(p))}`, AUTO_WHY)}
    <div class="og-pick">${libs().map(l => `<button type="button" class="og-pickrow" data-o="dolink" data-p="${p.id}" data-l="${l.id}"><b>${esc(KIND[l.kind] || short(l))}</b><small class="muted">${esc(l.path)}</small></button>`).join("")}</div>
    <div class="dialog-foot"><button type="button" data-o="close">Annuler</button></div>`; };
  const chooseSheet = lid => () => {
    const l = get(lid), free = provs().filter(p => p.role === "prov" && !p.links.includes(lid));
    return `${sheetHead(`Fixer sur ${esc(KIND[l.kind] || short(l))}`)}
      <div class="og-pick">${free.map(p => `<button type="button" class="og-pickrow" data-o="dolink" data-p="${p.id}" data-l="${lid}"><b>${esc(short(p))}</b><small class="muted">${esc(p.disk)} · ${items(p) ? `${plural(items(p), "élément", "éléments")} · ${size(gbOf(p))}` : "rien à ranger"}</small></button>`).join("") || `<p class="muted">Tous les dossiers sont déjà fixés ici.</p>`}</div>
      <div class="dialog-foot"><button type="button" data-o="folders">Gérer les dossiers</button><button type="button" data-o="close">Fermer</button></div>`;
  };

  // ------------------------------------------------------------------------------------------ actions
  function link(pid, lid) {
    const p = get(pid), l = get(lid);
    if (!p || !l || p.links[0] === lid) return;
    p.links = [lid];
    FX.toast(`${short(p)} est fixée sur ${l.path}.`, "ok");
  }
  function launch(list) {
    const parts = list.filter(ready);
    const tasks = [];
    for (const p of parts) for (const d of dest(p)) if (d.lib) {
      const fake = { n: `${short(p)} → ${KIND[d.lib.kind] || short(d.lib)} (${plural(d.n, d.kind === "series" ? "série" : "film", d.kind === "series" ? "séries" : "films")})`, s: d.gb };
      const it = FX.makeItem("organise", fake, { disk: p.disk === "/windocs" ? "d2" : p.disk === "/saves" ? "d1" : "d3", path: [short(p)] }, { disk: "d3", path: [KIND[d.lib.kind]] }, {});
      Object.assign(it, { fake: { pid: p.id, kind: d.kind, lid: d.lib.id, n: d.n, gb: d.gb }, mappings: [], instant: false, total: Math.max(3, Math.min(10, d.gb / 120)),
        mode: `Copie vers ${d.lib.disk} · torrents re-pointés dans leurs clients · tout continue de partager` });
      tasks.push(it);
    }
    if (!tasks.length) return;
    const names = parts.map(short).join(", ");
    FX.enqueue({ kind: "organise", label: `Ranger ${plural(summary(parts).n, "élément", "éléments")} (${names})`, undo: false, items: tasks });
    O.dlg?.close();
    FX.show("tasks");
  }
  const baseApply = FX.applyOrganise;
  FX.applyOrganise = it => {
    if (!it.fake) return baseApply(it);
    const { pid, kind, lid, n, gb } = it.fake, p = get(pid), l = get(lid);
    if (!p || !l) return true;
    const take = Math.min(n, kind === "series" ? p.series : p.films);
    if (kind === "series") { p.series -= take; p.gbS = Math.max(0, p.gbS - gb); } else { p.films -= take; p.gbF = Math.max(0, p.gbF - gb); }
    if (!items(p)) { p.torrents = 0; p.liens = 0; p.done = true; p.cross = 0; }
    l.n += take; l.gb += gb;
    l.shown = Array.from({ length: Math.min(6, l.n) }, (_, i) => (l.poster0 + i * 3 + 1) % 14);
    if (!items(p) && !p.review.length && p.was) FX.toast(`${p.path} est vide : remplacé par ${(p.links.map(get).find(x => x.kind === "films") || l).path} dans Paramètres.`, "ok");
    S.dirty = true;
    return true;
  };

  document.addEventListener("click", e => {
    const el = e.target.closest("[data-o]");
    if (!el || el.tagName === "INPUT" || el.tagName === "SELECT") return;
    const k = el.dataset.o, p = get(el.dataset.p);
    if (k === "close") el.closest("dialog")?.close();
    else if (k === "folders") { if (O.dlg?.open) O.dlg.close(); openSheet(foldersSheet()); }
    else if (k === "settings") openSheet(() => settingsSheet());
    else if (k === "settingsgo") { parent.location.hash = "#/setup"; FX.toast("Paramètres : ouvrez Dossiers de bibliothèque."); }
    else if (k === "auto") { p.auto = !p.auto; FX.toast(p.auto ? `Auto activé : les nouveautés de ${short(p)} seront rangées seules.` : `Auto désactivé pour ${short(p)}.`); redraw(); }
    else if (k === "link") { O.linking = O.linking === p.id ? null : p.id; redraw(); if (O.linking) document.querySelector(".og-lib")?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
    else if (k === "cancellink") { O.linking = null; redraw(); }
    else if (k === "pick") { const pid = O.linking; O.linking = null; link(pid, el.dataset.l); redraw(); }
    else if (k === "unlink") { p.links = []; FX.toast(`${short(p)} est de nouveau en Automatique.`); redraw(); }
    else if (k === "addfix") openSheet(fixSheet(p.id));
    else if (k === "addlink") openSheet(chooseSheet(el.dataset.l));
    else if (k === "dolink") { link(el.dataset.p, el.dataset.l); el.closest("dialog")?.close(); redraw(); }
    else if (k === "ranger") { O.sumList = [p]; openSheet(rangerSheet([p], `Ranger ${short(p)}`)); }
    else if (k === "rangerall") { O.sumList = provs().filter(x => x.role === "prov"); openSheet(rangerSheet(O.sumList, "Tout ranger")); }
    else if (k === "launch") launch(O.sumList || []);
    else if (k === "revtoggle") { O.reviewOpen = !O.reviewOpen; redraw(); }
    else if (k === "gorev") { e.preventDefault(); O.reviewOpen = true; redraw(); document.getElementById("og-review")?.scrollIntoView({ behavior: "smooth", block: "start" }); }
    else if (k === "fix") {
      const input = document.querySelector(`[data-o="title"][data-p="${p.id}"][data-i="${el.dataset.i}"]`), v = input.value.trim();
      if (!v) { input.focus(); FX.toast("Écrivez d'abord un titre.", "bad"); return; }
      const [, gb] = p.review.splice(+el.dataset.i, 1)[0];
      p.films += 1; p.gbF += gb; p.done = false;
      FX.toast(`« ${v} » est prêt à ranger (${short(p)}).`, "ok"); redraw();
    } else if (k === "keep") { const [name] = p.review.splice(+el.dataset.i, 1)[0]; FX.toast(`« ${name} » reste tel quel.`); redraw(); }
    else if (k === "role") {
      const f = get(el.dataset.f), r = el.dataset.r;
      if (f.role === r) return;
      for (const q of provs()) q.links = q.links.filter(x => x !== f.id);
      if (r === "lib") { Object.assign(f, { role: "lib", kind: f.kind || (f.series && !f.films ? "series" : "films"), n: f.n || 0, gb: f.gb || 0, shown: f.shown || [], poster0: 3 }); f.links = []; }
      else if (r === "prov") Object.assign(f, { role: "prov", links: [], films: f.films || 0, series: f.series || 0, gbF: f.gbF || 0, gbS: f.gbS || 0, review: f.review || [], auto: false, ex: f.ex || [], torrents: f.torrents || 0, liens: f.liens || 0, subs: f.subs || [] });
      else f.role = "none";
      redraw();
    }
  });
  document.addEventListener("change", e => { const el = e.target; if (el.dataset?.o === "dest") { const p = get(el.dataset.p); if (el.value) link(p.id, el.value); else { p.links = []; FX.toast(`${short(p)} est en Automatique.`); } redraw(); return; } if (el.dataset?.o === "kind") { get(el.dataset.f).kind = el.value; redraw(); } });
  document.addEventListener("input", e => {
    const el = e.target;
    if (el.dataset?.o === "tpl") { O.tpl[el.dataset.k] = el.value; const sm = el.parentElement.querySelector("small"); sm.textContent = `Exemple : ${(el.dataset.k === "Films" ? el.value.replace(/\{titre\}/g, "Gourou").replace(/\{année\}/g, "2026") : el.value.replace(/\{titre\}/g, "Black Mirror").replace(/\{année\}/g, "2011").replace(/\{saison\}/g, "01").replace(/\{épisode\}/g, "01"))}.mkv`; }
  });
  document.addEventListener("keydown", e => { const el = e.target.closest?.('[data-o="pick"]'); if (el && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); el.click(); } });
  // Drag a provenance onto a library.
  let dragId = null;
  document.addEventListener("dragstart", e => { const c = e.target.closest?.("[data-drag]"); if (!c) return; dragId = c.dataset.drag; e.dataTransfer.setData("text/plain", dragId); e.dataTransfer.effectAllowed = "link"; document.getElementById("app").classList.add("og-dragging"); });
  document.addEventListener("dragend", () => { dragId = null; document.getElementById("app")?.classList.remove("og-dragging"); document.querySelectorAll(".og-over").forEach(x => x.classList.remove("og-over")); });
  document.addEventListener("dragover", e => { const t = e.target.closest?.("[data-lib]"); if (t && dragId) { e.preventDefault(); document.querySelectorAll(".og-over").forEach(x => x !== t && x.classList.remove("og-over")); t.classList.add("og-over"); } });
  document.addEventListener("drop", e => { const t = e.target.closest?.("[data-lib]"); if (!t || !dragId) return; e.preventDefault(); const id = dragId; dragId = null; link(id, t.dataset.lib); redraw(); });

  // ------------------------------------------------------------------------------------------ plumbing
  const baseAfter = FX.afterRender;
  FX.afterRender = () => { baseAfter?.(); requestAnimationFrame(wires); };
  const setVariant = tab => { S.orgVariant = tab === "orgA" || tab === "orgB" ? tab : null; };
  const baseShow = FX.show;
  FX.show = tab => { if (tab === "orgA" || tab === "orgB") setVariant(tab); else if (tab === "organisation") S.orgVariant = null; baseShow(tab); };
  FX.api.show = FX.show;
  FX.api.orgReset = tab => { fixture(); O.dlg?.close(); FX.show(tab); };
  // The tabs of the page click through S.tab; keep the variant when one is picked there.
  document.addEventListener("click", e => { const t = e.target.closest("[data-tab]"); if (t && (t.dataset.tab === "orgA" || t.dataset.tab === "orgB")) setVariant(t.dataset.tab); }, true);
  // Series and film names for the library mosaic stay empty until something is ranged.
})();
