"use strict";
// Preview "Fichiers": Disques, Corbeille and Organisation (needs fichiers.js: FX, its state and its task queue).
(() => {
  const { S, esc, size, num, dateOf, ago, dur, nodeAt, ensureDir, sizeOf, seedOf, discUsage, clone } = FX;
  const DAY = 86400000;
  const pct = n => nf1.format(n);
  const nf1 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
  const owner = () => !S.member;
  const live = () => FX.liveIds();
  const diskName = id => S.disks[id].name;
  const SPEED = 0.15;
  const copyBtn = (text, label = "Copier") => `<button data-k="copy" data-v="${esc(text)}">${label}</button>`;
  const code = text => `<div class="row" style="align-items:flex-start"><pre class="code grow">${esc(text)}</pre>${copyBtn(text)}</div>`;

  // ======================================================== Disques ========================================
  S.scrutinyUrl = "http://scrutiny:8080";
  S.sim = { kind: "new", gb: 4.2 };
  S.rebal = null; S.rebalOpen = new Set();
  const tip = (text, label = "Plus d'informations") => FX.tipBtn(text, label);
  const srcOf = d => {
    if (d.source === "scrutiny") return S.scrutinyUrl ? "Scrutiny" : S.smartctl ? "smartctl" : null;
    return S.smartctl ? "smartctl" : S.scrutinyUrl ? "Scrutiny" : null;
  };
  function smartHTML(d) {
    const src = srcOf(d);
    if (!src) return `<dt>Santé</dt><dd><span class="badge warn">Inconnue</span> ${tip("smartctl n'est pas autorisé et Scrutiny n'est pas configuré. Voir les réglages ⚙ de cet onglet.")}</dd>`;
    const m = d.smart;
    const status = m.status === "ok" ? `<span class="badge ok">Bon état</span>` : `<span class="badge bad">Alerte</span> ${tip(`${m.realloc} secteurs réalloués${m.pending ? `, ${m.pending} en attente` : ""} : le disque s'use. Pensez à le remplacer.`)}`;
    return `<dt>Santé</dt><dd>${status}</dd><dt>Température</dt><dd>${m.temp} °C</dd><dt>Âge</dt><dd>${num(m.hours)} h d'utilisation</dd>`;
  }
  function diskCard(id) {
    const d = S.disks[id], u = discUsage(id);
    const used = u.used / d.total * 100, below = u.free < u.margin;
    const other = Math.max(0, u.used - u.lib - u.dl - u.tr);
    const seg = (v, c) => `<i class="${c}" style="width:${Math.max(0, v) / d.total * 100}%" title="${size(v)}"></i>`;
    const chip = u.free <= 0 ? `<span class="badge bad">Plein</span>` : below ? `<span class="badge warn">Presque plein</span>` : `<span class="badge ok">Place suffisante</span>`;
    const chipTip = u.free <= 0 ? `Ce disque est plein : plus aucun téléchargement n'y est placé. ${size(u.margin)} à libérer pour retrouver la marge de 10 %. Voir la proposition plus bas.`
      : below ? `Ce disque est sous la marge de 10 % (${size(u.margin)}) : la règle de placement l'évite. ${size(Math.max(0, u.margin - u.free))} à libérer pour la retrouver. Voir la proposition plus bas.`
      : `La marge de 10 % d'espace libre (${size(u.margin)}) est respectée.`;
    return `<article class="card disk" data-disk="${id}">
      <div class="row between"><h3>${esc(d.name)}</h3><span class="row"><span class="badge">${d.capacity || size(d.total)}</span>${chip} ${tip(chipTip)}</span></div>
      <small>${esc(d.model)} · ${d.fs}${d.note ? " " : ""}${d.note ? tip(d.note) : ""}</small>
      <div><div class="bar stack" title="Marge de 10 % marquée">${seg(u.lib, "c-lib")}${seg(u.dl, "c-dl")}${seg(u.tr, "c-tr")}${seg(other, "c-ot")}</div>
        <div class="bar" style="margin-top:6px;height:6px"><i class="${used > 99.5 ? "bad" : used > 90 ? "warn" : ""}" style="width:${Math.min(100, used)}%"></i><u style="left:90%"></u></div></div>
      <div class="legend"><span><b class="c-lib"></b>Médiathèque ${size(u.lib)}</span><span><b class="c-dl"></b>Téléchargements ${size(u.dl)}</span><span><b class="c-tr"></b>Corbeille ${size(u.tr)}</span><span><b class="c-ot"></b>Autres ${size(other)}</span></div>
      <div class="row"><b>${size(u.used)} utilisés</b><span>·</span><b>${size(u.free)} libres (${pct(100 - used)} %)</b></div>
      <dl class="kv"><dt>Films</dt><dd>${u.films}</dd>${smartHTML(d)}</dl></article>`;
  }
  const unmountedCard = () => {
    const d = S.disks.d3;
    return `<article class="card disk" style="border:1px dashed #edbf73aa;grid-column:1/-1"><div class="row between"><h3>${esc(d.model)}</h3><span class="row"><span class="badge-preview">Aperçu</span><span class="badge">${d.capacity}</span><span class="badge warn">Absent du conteneur</span> ${tip("Le disque est prêt sur la machine (ext4, étiquette « library », monté sur /library) mais TorrentLinker ne le voit pas encore. Il reste une seule étape, à faire vous-même : ajouter le volume au conteneur, puis le redémarrer. TorrentLinker ne partitionne ni ne formate jamais un disque.")}</span></div>
      <div><b>Fichier compose</b>${code("services:\n  torrentlinker:\n    volumes:\n      - /library:/library")}</div>
      <div><b>Redémarrer</b>${code("docker compose up -d")}</div>
      <div class="row"><button data-k="remount" class="primary">C'est fait (aperçu)</button>${tip("Dans l'application, le disque apparaît ensuite ici et dans l'Explorateur, et reçoit les prochains téléchargements.")}</div></article>`;
  };
  function placement() {
    const films = [];
    for (const id of live()) for (const r of FX.S.roots[id]) if (r.lib === "Films") for (const f of r.c) if (f.film && f.poster !== undefined) films.push({ id, f });
    const together = S.sim.kind === "new" ? null : S.sim.kind === "series" ? "d1" : films.find(x => x.f.film === S.sim.kind)?.id;
    const r = FX.place(S.sim.gb, together);
    return `<section class="card sect"><div class="row"><h3>Règle de placement</h3>${tip("Garder ensemble, sinon le disque le plus libre. Les versions d'un film et les épisodes d'une série restent sur le disque qu'ils partagent déjà. Sinon, le téléchargement va sur le disque qui a le plus de place libre au-dessus de la marge de 10 %.")}<span class="grow"></span><span class="badge-preview">Aperçu</span></div>
      <div class="row"><b>Prochain téléchargement → ${esc(diskName(r.disk))}</b>${tip(`${r.why}. ` + live().map(id => `${diskName(id)} : ${size(discUsage(id).usable)} utilisables au-dessus de la marge.`).join(" "))}</div>
      <div class="sim"><div class="row"><label>Essayer avec<select data-k="simkind"><option value="new" ${S.sim.kind === "new" ? "selected" : ""}>Un nouveau film</option><option value="series" ${S.sim.kind === "series" ? "selected" : ""}>Un épisode de The Office</option>
        ${films.map(x => `<option value="${esc(x.f.film)}" ${S.sim.kind === x.f.film ? "selected" : ""}>Autre version de ${esc(x.f.film)}</option>`).join("")}</select></label>
        <label>Taille (Go)<input type="number" min="0.1" step="0.1" value="${S.sim.gb}" data-k="simgb" style="width:100px"></label></div></div></section>`;
  }
  function rebalanceCandidates() {
    const out = [];
    for (const id of live()) {
      if (id === "d3") continue;
      const u = discUsage(id);
      if (u.free >= u.margin) continue;
      const films = [];
      for (const r of FX.S.roots[id]) if (r.lib === "Films") for (const f of r.c) if (f.film && f.poster !== undefined) films.push(f);
      films.sort((a, b) => sizeOf(b) - sizeOf(a));
      out.push({ id, u, films });
    }
    return out;
  }
  function rebalance() {
    const head = `<div class="row"><h3>Rééquilibrer</h3>`;
    if (!S.hddMounted) return `<section class="card sect">${head}<span class="muted">En attente de ${esc(S.disks.d3.model)}</span>${tip(`Dès que le conteneur voit le disque ${S.disks.d3.model} (/library), TorrentLinker propose d'y déplacer des films depuis les disques sous la marge.`)}</div></section>`;
    const blocks = rebalanceCandidates();
    if (!blocks.length) return `<section class="card sect">${head}<span class="muted">Rien à faire</span>${tip("Aucun disque n'est sous la marge de 10 %.")}</div></section>`;
    if (!S.rebal) S.rebal = new Set(blocks.flatMap(b => b.films.slice(0, 3).map(f => f.n)));
    let total = 0;
    const html = blocks.map(b => {
      const picked = b.films.filter(f => S.rebal.has(f.n)), gb = picked.reduce((a, f) => a + sizeOf(f), 0);
      total += gb;
      const open = S.rebalOpen.has(b.id), need = b.u.margin - b.u.free;
      const detail = `${diskName(b.id)} ${b.u.free <= 0 ? "est plein" : "est presque plein"} (${size(b.u.free)} libres, marge de 10 % = ${size(b.u.margin)}). Chaque film en partage est déplacé par son client (qBittorrent : déplacement natif, le partage continue), puis l'original est supprimé après vérification. Copie entre disques d'environ ${dur(gb / SPEED)}.${gb < need ? ` La marge demanderait ${size(need)} : le reste est hors des dossiers de bibliothèque, TorrentLinker n'y touche pas.` : ""}`;
      return `<div class="sect" style="margin:0 0 8px"><div class="row"><b>Libérer ${esc(diskName(b.id))} : ${picked.length ? `${picked.length} film${picked.length > 1 ? "s" : ""}, ${size(gb)} → ${esc(diskName("d3"))}` : "aucun film choisi"}</b>${tip(detail)}<span class="grow"></span>
        <button data-k="rebview" data-d="${b.id}" aria-expanded="${open}">${open ? "Masquer" : "Voir"}</button><button class="primary" data-k="rebgo" data-d="${b.id}" ${picked.length ? "" : "disabled"}>Lancer</button></div>
        ${open ? `<div class="panel" style="margin-top:8px"><table class="list"><tbody>${b.films.map(f => { const s = seedOf(f); return `<tr data-k="film" data-n="${esc(f.n)}" style="cursor:pointer"><td style="width:30px"><input type="checkbox" data-k="reb" data-n="${esc(f.n)}" ${S.rebal.has(f.n) ? "checked" : ""}></td>
          <td style="width:40px"><span class="ico"><img src="${FX.base || "/library-storage-preview/"}poster-${f.poster}.png" alt="" width="28" height="42"></span></td><td class="name">${esc(f.film)}</td><td class="num">${size(sizeOf(f))}</td>
          <td>${s ? `<span class="badge ok">▲ ${esc(s.client)}</span>` : ""}</td></tr>`; }).join("")}</tbody></table></div>` : ""}</div>`;
    }).join("");
    return `<section class="card sect"><div class="row"><h3>Rééquilibrer</h3>${tip("Déplace des films des disques presque pleins vers le disque neuf. Les déplacements s'ouvrent dans Tâches, vous pouvez les annuler.")}<span class="grow"></span><span class="badge-preview">Aperçu</span></div>${html}</section>`;
  }
  const scrutinyUrlOk = v => /^https?:\/\/.+/.test(v);
  FX.diskSettingsHTML = () => `<div class="row between"><h2>Réglages des disques</h2><button class="quiet" data-close aria-label="Fermer">✕</button></div>
    <section class="sect"><div class="row"><h3>Scrutiny</h3>${tip("Adresse de l'API de Scrutiny, qui fournit la santé des disques qu'il connaît. Laissez vide pour ne pas l'utiliser.")}</div>
      <div class="row"><input data-k="scr" value="${esc(S.scrutinyUrl)}" placeholder="http://scrutiny:8080" style="width:260px" aria-label="Adresse de Scrutiny"><button data-k="scrsave">Enregistrer</button><button data-k="scrtest">Tester</button></div></section>
    <section class="sect"><div class="row"><h3>smartctl</h3><span class="badge ${S.smartctl ? "ok" : "warn"}">${S.smartctl ? "Autorisé" : "Non autorisé"}</span>${tip(S.smartctl ? "smartctl lit la santé des disques en lecture seule." : "smartctl n'est pas autorisé pour ce serveur : la santé des disques est inconnue" + (S.scrutinyUrl ? ", Scrutiny la fournit pour les disques qu'il connaît" : "") + ". Pour l'autoriser (lecture seule), ajoutez ceci au fichier compose.")}</div>
      ${S.smartctl ? "" : code("# docker compose\nservices:\n  torrentlinker:\n    cap_add:\n      - SYS_RAWIO\n    devices:\n      - /dev/sda:/dev/sda\n      - /dev/sdb:/dev/sdb")}</section>
    <div class="dialog-foot"><button class="primary" data-close>Fermer</button></div>`;
  FX.disksHTML = () => `<div class="row"><h3>Disques</h3><span class="grow"></span><button data-k="disksettings" aria-label="Réglages des disques" title="Réglages">⚙</button></div>
      <div style="height:10px"></div>
      <div class="disks">${live().map(diskCard).join("")}${S.hddMounted ? "" : unmountedCard()}</div>
      <div style="height:14px"></div>${placement()}${rebalance()}`;

  // ======================================================== Corbeille ======================================
  const parseFrom = str => { const d = Object.values(S.disks).find(k => str === k.mount || str.startsWith(k.mount + "/")); return d ? { disk: d.id, path: str.slice(d.mount.length).split("/").filter(Boolean) } : null; };
  const left = t => Math.max(0, S.retention - Math.floor((Date.now() - t.ts) / DAY));
  const visible = t => !S.member || t.from.includes("/Films/");
  FX.restoreRecord = rec => {
    const at = parseFrom(rec.from);
    if (!at) return false;
    const parent = ensureDir(at.disk, at.path.slice(0, -1));
    let name = at.path[at.path.length - 1];
    if (parent.c.some(c => c.n === name)) name += " (restauré)";
    const node = rec.node ? rec.node : rec.dir ? { n: name, d: 1, age: 0, c: [{ n: "contenu", s: rec.size, age: 0, hash: "x" + rec.id }] } : { n: name, s: rec.size, age: 0, hash: "x" + rec.id };
    node.n = name;
    parent.c.push(node);
    S.trash.splice(S.trash.indexOf(rec), 1);
    return true;
  };
  const whereOf = t => { const at = parseFrom(t.from); return at ? `${diskName(at.disk)}${at.path.length > 1 ? " · " + at.path[0] : ""}` : t.from; };
  FX.trashHTML = () => {
    const sections = live().map(id => {
      const items = S.trash.filter(t => t.disk === id && visible(t));
      const total = items.reduce((a, t) => a + t.size, 0);
      return `<section class="sect"><h3>Corbeille de ${esc(diskName(id))} <span class="badge">${size(total)}</span>
        ${owner() && items.length ? `<button class="danger" data-k="empty" data-d="${id}">Vider maintenant</button>` : ""}</h3>
        <div class="panel">${items.length ? `<table class="list"><thead><tr><th>Nom</th><th>D'où</th><th>Supprimé</th><th class="num">Taille</th><th>Purge</th><th></th></tr></thead><tbody>
        ${items.map(t => `<tr><td class="name">${esc(t.name)}${t.reason ? `<small>${esc(t.reason)}</small>` : ""}</td><td class="name" style="font-size:12.5px;color:var(--muted)" title="${esc(t.from)}">${esc(whereOf(t))}</td>
          <td>${esc(t.by)}<small>${ago(t.ts)}</small></td><td class="num">${size(t.size)}</td>
          <td>${left(t) <= 1 ? `<span class="badge warn">${left(t) === 0 ? "ce soir" : "dans 1 j"}</span>` : `<span class="badge">dans ${left(t)} j</span>`}</td>
          <td class="num"><button data-k="restore" data-id="${t.id}">Restaurer</button></td></tr>`).join("")}</tbody></table>` : `<div class="empty">Corbeille vide.</div>`}</div></section>`;
    }).join("");
    return `${owner() ? `<div class="row"><span class="grow"></span><button data-k="trashsettings" aria-label="Réglages de la corbeille" title="Réglages">⚙</button></div>` : ""}${sections}`;
  };
  FX.trashSettingsHTML = () => `<div class="row between"><h2>Réglages de la corbeille</h2><button class="quiet" data-close aria-label="Fermer">✕</button></div>
    <section class="sect"><div class="row"><h3>Conservation</h3>${tip("7 jours par défaut. Passé ce délai, la corbeille est purgée. L'espace qu'elle occupe est compté à part dans Disques.")}</div>
      <label class="row">Purger après <select data-k="ret">${[1, 3, 7, 14, 30].map(n => `<option value="${n}" ${S.retention === n ? "selected" : ""}>${n} jour${n > 1 ? "s" : ""}</option>`).join("")}</select></label></section>
    <div class="dialog-foot"><button class="primary" data-close>Fermer</button></div>`;

  // ======================================================== Organisation ===================================
  const TOKENS = ["{titre}", "{année}", "{tmdbid}", "{résolution}", "{codec}", "{source}", "{langue}", "{saison}", "{épisode}", "{groupe}"];
  S.templates = { Films: "{titre} ({année}) [tmdbid-{tmdbid}]/{titre} ({année}) [tmdbid-{tmdbid}]", "Séries": "{titre} ({année})/Saison {saison}/{titre} S{saison}E{épisode}" };
  const DEFAULTS = clone(S.templates);
  S.orgScope = "Films"; S.orgOff = new Set(); S.orgExtra = [];
  const clean = s => s.replace(/\s*:\s*/g, " - ").replace(/[<>"\\|?*]/g, "").replace(/\s+/g, " ").trim();
  const pad = n => String(n).padStart(2, "0");
  function fill(tpl, r, ep) {
    const v = { "{titre}": r.title, "{année}": r.year, "{tmdbid}": r.tmdb, "{résolution}": r.res, "{codec}": r.codec, "{source}": r.src, "{langue}": r.lang, "{saison}": pad(r.season || 1), "{épisode}": pad(ep ?? r.episode ?? 1), "{groupe}": r.group || "GRP" };
    return tpl.replace(/\{[^}]*\}/g, t => (t in v ? v[t] : t));
  }
  const tplError = tpl => {
    const bad = (tpl.match(/\{[^}]*\}/g) || []).filter(t => !TOKENS.includes(t));
    if (bad.length) return `Jeton inconnu : ${bad.join(", ")}`;
    if (!tpl.includes("{titre}")) return "Le modèle doit contenir {titre}.";
    if (/\.\./.test(tpl) || tpl.startsWith("/") || tpl.endsWith("/")) return "Chemin invalide (pas de « .. », ni de barre au début ou à la fin).";
    return tpl.split("/").length > 3 ? "Trois niveaux au plus." : "";
  };
  const isVideo = n => /\.(mkv|mp4|avi)$/i.test(n.n);
  function filesOf(node, rel = []) { return node.d ? (node.c || []).flatMap(c => filesOf(c, [...rel, c.n])) : [{ node, rel }]; }
  function locate(r) {
    const [folder, name] = r.path.split("/");
    for (const id of live()) { const root = S.roots[id].find(n => n.n === folder); const node = root?.c.find(c => c.n === name); if (node) return { node, disk: id, folder, name }; }
    return null;
  }
  // The proposal for one release: where it goes, its new tree, whether the client or the Link Folder is involved.
  function propose(r, loc) {
    const lib = r.kind === "film" ? "Films" : "Séries";
    const tpl = S.templates[lib], error = tplError(tpl);
    const videos = filesOf(loc.node).filter(f => isVideo(f.node)).sort((a, b) => a.rel.join("/").localeCompare(b.rel.join("/")));
    const others = filesOf(loc.node).filter(f => !isVideo(f.node));
    const maps = [];
    const sz = sizeOf(loc.node);
    let destDisk = loc.disk, why = "";
    if (loc.folder !== lib) {
      if (r.kind === "film") { const p = FX.place(sz, null); destDisk = p.disk; why = p.why; }
      else {
        const top = fill(tpl, r).split("/")[0];
        const together = live().find(id => S.roots[id].find(n => n.n === lib)?.c.some(c => c.n === clean(top)));
        const p = FX.place(sz, together); destDisk = p.disk; why = p.why;
      }
    }
    let first = "";
    videos.forEach((f, i) => {
      const segs = fill(tpl, r, (r.episode || 1) + i).split("/").map(clean);
      const ext = f.node.n.match(/\.[^.]+$/)?.[0] || ".mkv";
      segs[segs.length - 1] += ext;
      if (!first) first = segs.join("/");
      maps.push({ from: { disk: loc.disk, path: [loc.folder, loc.name, ...f.rel].slice(loc.node.d ? 0 : 0, loc.node.d ? undefined : 2) }, to: { disk: destDisk, path: [lib, ...segs] } });
    });
    if (r.kind === "film" && videos.length === 1) {
      const base = maps[0].to.path.slice(0, -1), file = maps[0].to.path.at(-1).replace(/\.[^.]+$/, "");
      for (const f of others) maps.push({ from: { disk: loc.disk, path: [loc.folder, loc.name, ...f.rel] }, to: { disk: destDisk, path: [...base, f.rel.length > 1 ? f.rel.join("/") : file + (f.node.n.match(/\.[^.]+$/)?.[0] || "")].flatMap(x => x.split("/")) } });
    }
    const more = videos.length > 1 ? ` … (${videos.length} épisodes)` : "";
    const top = maps[0]?.to.path[1] ?? "";
    const same = loc.folder === lib && loc.disk === destDisk && loc.name === top && videos.every((f, i) => maps[i].to.path.slice(1).join("/") === [loc.name, ...f.rel].join("/"));
    const native = r.seed ? FX.clientOf(r.seed)?.native : true;
    const link = !!r.seed && (!native || !!r.layout);
    return { r, loc, lib, destDisk, why, maps, first, more, same, link, error, top, sz,
      moving: destDisk !== loc.disk || loc.folder !== lib };
  }
  function orgRows() {
    const out = [];
    for (const r of [...S.data.org, ...S.orgExtra]) {
      const loc = locate(r);
      if (loc && loc.folder === S.orgScope) out.push(propose(r, loc));
    }
    return out;
  }
  const applicable = p => !p.same && !p.link && !p.error;
  const checked = p => applicable(p) && !S.orgOff.has(p.r.path);
  const curTop = p => `${p.loc.folder}/${p.loc.name}`;
  FX.applyOrganise = it => {
    const tops = new Set(it.mappings.map(m => m.from.path.slice(0, 2).join("/")));
    const first = it.mappings[0];
    const srcTop = nodeAt(first.from.disk, first.from.path.slice(0, 2));
    if (srcTop && !it.undoMeta) it.undoMeta = { film: srcTop.film, poster: srcTop.poster };
    const topDst = first.to.path.slice(0, 2);
    const existed = !!nodeAt(first.to.disk, topDst);
    for (const m of it.mappings) {
      const parent = nodeAt(m.from.disk, m.from.path.slice(0, -1));
      const file = parent?.c.find(c => c.n === m.from.path.at(-1));
      if (!file) return false;
      parent.c.splice(parent.c.indexOf(file), 1);
      const dst = ensureDir(m.to.disk, m.to.path.slice(0, -1));
      file.n = m.to.path.at(-1); file.age = 0;
      dst.c.push(file);
    }
    const newTop = nodeAt(first.to.disk, topDst);
    if (!existed && newTop?.d && it.meta) for (const [k, v] of Object.entries(it.meta)) if (v !== undefined) newTop[k] = v;
    for (const t of tops) {
      const path = t.split("/"), node = nodeAt(first.from.disk, path);
      if (node?.d && FX.countFiles(node) === 0) { const par = nodeAt(first.from.disk, path.slice(0, -1)); par.c.splice(par.c.indexOf(node), 1); }
    }
    return true;
  };
  function orgItem(p) {
    const r = p.r, lib = p.lib;
    const it = FX.makeItem("organise", p.loc.node, { disk: p.loc.disk, path: [p.loc.folder] }, { disk: p.destDisk, path: [lib] }, {
      newName: p.top, mappings: p.maps, meta: r.kind === "film" ? { film: r.title, poster: r.poster ?? undefined } : {},
    });
    it.instant = !p.moving || p.destDisk === p.loc.disk;
    it.total = it.instant ? 0.9 : Math.max(2.5, Math.min(10, p.sz * 1.6));
    it.mode = (p.moving ? (p.destDisk === p.loc.disk ? `Même disque : déplacement instantané vers ${lib}` : `Autre disque : copie vers ${diskName(p.destDisk)} (${size(p.sz)})`) : "Renommage sur place")
      + (r.seed ? ` · renommé dans le client (${r.seed})` : "");
    it.seed = r.seed ? { client: r.seed } : null;
    return it;
  }
  function exampleRow(lib) {
    const r = S.data.org.find(x => (x.kind === "film") === (lib === "Films"));
    return r;
  }
  // ⓘ info box: one shared popover (click, hover with a mouse, Enter/Space, Esc; works on a phone).
  const tipBtn = (text, label = "Plus d'informations", action = "") => `<button type="button" class="info" data-k="info" data-tip="${esc(text)}" ${action ? `data-act="${esc(action)}"` : ""} aria-label="${esc(label)}" aria-expanded="false">i</button>`;
  FX.tipBtn = tipBtn;
  let tipEl = null, tipFor = null;
  function tipHide() { if (tipEl) tipEl.hidden = true; tipFor?.setAttribute("aria-expanded", "false"); tipFor = null; }
  function tipShow(btn) {
    if (!tipEl) { tipEl = document.createElement("div"); tipEl.id = "tip"; tipEl.className = "tip"; tipEl.setAttribute("role", "tooltip"); tipEl.hidden = true; document.body.append(tipEl); }
    tipFor?.setAttribute("aria-expanded", "false");
    (btn.closest("dialog") || document.body).append(tipEl);
    tipFor = btn; btn.setAttribute("aria-expanded", "true");
    tipEl.innerHTML = `<span></span>${btn.dataset.act ? `<button type="button" data-k="${esc(btn.dataset.act)}">Ouvrir Paramètres</button>` : ""}`;
    tipEl.firstChild.textContent = btn.dataset.tip;
    tipEl.hidden = false;
    const r = btn.getBoundingClientRect(), w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    const left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2));
    const top = r.bottom + 6 + h > innerHeight - 8 && r.top - h - 6 > 8 ? r.top - h - 6 : r.bottom + 6;
    tipEl.style.left = left + "px"; tipEl.style.top = top + "px";
  }
  document.addEventListener("click", e => {
    const b = e.target.closest(".info");
    if (b) { e.preventDefault(); e.stopPropagation(); tipFor === b ? tipHide() : tipShow(b); }
    else if (!e.target.closest("#tip") || e.target.closest("#tip button")) tipHide();
  }, true);
  document.addEventListener("keydown", e => { if (e.key === "Escape") tipHide(); });
  // Hover closes after a short delay, so the pointer can cross the gap into the box and click its button.
  let tipTimer = 0;
  const hover = () => matchMedia("(hover:hover)").matches;
  document.addEventListener("mouseover", e => {
    if (!hover()) return;
    const b = e.target.closest?.(".info");
    if (b || e.target.closest?.("#tip")) clearTimeout(tipTimer);
    if (b && tipFor !== b) tipShow(b);
  });
  document.addEventListener("mouseout", e => {
    if (!hover() || !(e.target.closest?.(".info") || e.target.closest?.("#tip"))) return;
    const to = e.relatedTarget;
    if (to?.closest?.("#tip") || (tipFor && to?.closest?.(".info") === tipFor)) return;
    clearTimeout(tipTimer);
    tipTimer = setTimeout(tipHide, 300);
  });
  window.addEventListener("scroll", tipHide, true);

  const shortName = s => s.replace(/\s*\[tmdbid-\d+\]/g, "");
  const tplLabel = lib => {
    const last = S.templates[lib].split("/").at(-1).replace(/\s*\[tmdbid-\{tmdbid\}\]/g, "");
    return last.replace(/\{([^}]*)\}/g, (_, t) => t.charAt(0).toUpperCase() + t.slice(1));
  };
  S.orgTpl = false;
  FX.orgHTML = () => {
    const rows = orgRows(), sel = rows.filter(checked);
    const scopes = ["Films", "Séries", "Téléchargements"];
    const tplLib = S.orgScope === "Séries" ? "Séries" : "Films";
    const state = !rows.some(applicable) ? "" : sel.length === rows.filter(applicable).length ? "all" : sel.length ? "some" : "none";
    const rowHTML = p => {
      const r = p.r, bad = p.link || p.error;
      const seedTip = r.seed ? `En partage dans ${r.seed} : le nom est aussi changé dans le client, le partage continue.` : "";
      const moveTip = p.moving && !bad && !p.same ? `Sera déplacé vers ${diskName(p.destDisk)} / ${p.lib}.${p.why ? " " + p.why : ""}` : "";
      const blockTip = p.error ? p.error : p.link ? (r.layout || "Ce client ne sait pas renommer les fichiers d'un torrent.") + " Un Dossier de liens est nécessaire (Paramètres, onglet du client)." : "";
      const tip = bad ? tipBtn(blockTip, "Pourquoi ce n'est pas rangeable", p.link ? "links" : "") : (seedTip || moveTip) ? tipBtn([seedTip, moveTip].filter(Boolean).join(" "), "Détails") : "";
      return `<div class="orow ${p.same ? "unchanged" : ""} ${bad ? "blocked" : ""}">
        <span class="oc">${bad ? `<span class="warnmark" aria-hidden="true">⚠</span>` : `<input type="checkbox" data-k="orgrow" data-p="${esc(r.path)}" ${checked(p) ? "checked" : ""} ${applicable(p) ? "" : "disabled"} aria-label="Ranger ${esc(r.title)}">`}</span>
        <span class="cur" title="${esc(p.loc.name)}">${r.seed && !bad ? `<i class="dot" title="En partage dans ${esc(r.seed)}"></i>` : ""}<span class="t">${esc(p.loc.name)}</span></span>
        <span class="new">${bad ? `<span class="no">ne peut pas être rangé</span>` : p.same ? `<span class="muted">Déjà rangé</span>` : `<span class="arrow" aria-hidden="true">→</span><b class="t" title="${esc(p.first)}">${esc(shortName(p.top))}</b>`}</span>
        <span class="oi">${tip}</span></div>`;
    };
    return `<section class="sect"><div class="row orghead"><select data-k="scope" aria-label="Dossier">${scopes.map(s => `<option ${s === S.orgScope ? "selected" : ""}>${s}</option>`).join("")}</select>
        ${tipBtn("Ranger renomme chaque élément coché avec le modèle de sa bibliothèque (format Jellyfin) et le déplace si besoin. Rien n'est appliqué avant que vous cliquiez ; le résultat est dans Tâches et annulable. Un torrent en partage est aussi renommé dans son client.", "Aide sur Ranger")}
        <button data-k="orgsettings" aria-label="Réglages du rangement" title="Réglages">⚙</button><span class="grow"></span><button class="primary" data-k="orgapply" ${sel.length ? "" : "disabled"}>Ranger la sélection (${sel.length})</button></div>
      <div class="panel orows"><div class="orow ohead"><span class="oc"><input type="checkbox" data-k="orgtoggle" data-state="${state}" ${state === "all" ? "checked" : ""} ${state ? "" : "disabled"} aria-label="Tout cocher ou décocher"></span><span class="muted">Tout cocher</span><span></span><span></span></div>
        ${rows.map(rowHTML).join("") || `<div class="empty">Rien à ranger.</div>`}</div>
      </section>`;
  };
  FX.orgSettingsHTML = () => {
    const tplCard = lib => {
      const r = exampleRow(lib), err = tplError(S.templates[lib]);
      const ex = err ? "" : fill(S.templates[lib], r, 1).split("/").map(clean).join(" / ") + ".mkv";
      return `<div class="card tpl"><div class="row"><h3>${lib}</h3>${tipBtn("Un « / » sépare un dossier du suivant. Le dernier niveau est le nom du fichier ; l'extension est ajoutée. Le modèle par défaut suit le format Jellyfin.", "Aide sur le modèle")}</div>
        <input data-k="tpl" data-lib="${lib}" value="${esc(S.templates[lib])}" spellcheck="false" aria-label="Modèle ${lib}">
        <div class="tokens">${TOKENS.map(t => `<button data-k="token" data-lib="${lib}" data-t="${esc(t)}">${esc(t)}</button>`).join("")}</div>
        ${err ? `<div class="err">${esc(err)}</div>` : `<div class="example">${esc(ex)}</div>`}
        <div class="row"><button data-k="tplreset" data-lib="${lib}" ${S.templates[lib] === DEFAULTS[lib] ? "disabled" : ""}>Rétablir le modèle Jellyfin</button></div></div>`;
    };
    const folders = [["d1", "/saves/Téléchargements"], ...(S.hddMounted ? [["d3", "/library/Téléchargements"]] : [])];
    const dlCard = `<section class="sect"><div class="row"><h3>Vos dossiers de téléchargement</h3>${tipBtn("Désactivé par défaut : rien n'est rangé sans votre accord. Activé pour un dossier, chaque téléchargement terminé est renommé avec le modèle de sa bibliothèque puis déplacé là où la règle de placement l'envoie, sans cesser de partager. Tout est dans Tâches et annulable.", "Aide sur le rangement automatique")}<span class="grow"></span>${folders.length ? `<button class="quiet small" data-k="dlfolders">Modifier dans Paramètres</button>` : ""}</div>
      ${folders.length ? "" : `<div class="row autorow"><span class="muted">Aucun dossier de téléchargement</span><button class="quiet small" data-k="dlfolders">Ajouter</button></div>`}
      ${folders.map(([id, path]) => {
        const on = !!S.autoTidy[id];
        return `<div class="row autorow"><div class="switch" role="switch" tabindex="0" data-k="auto" data-d="${id}" aria-checked="${on}" aria-label="Ranger automatiquement ${esc(path)}"><span class="sw"></span><span>${esc(path)}</span></div>
          ${on ? `<button class="quiet small" data-k="simdl" data-d="${id}">Simuler un téléchargement terminé</button>` : ""}</div>`;
      }).join("")}</section>`;
    return `<div class="row between"><h2>Réglages du rangement</h2><button class="quiet" data-close aria-label="Fermer">✕</button></div>
      <section class="sect"><div class="row"><h3>Modèle de nom</h3></div><div class="grid2 one">${tplCard("Films")}${tplCard("Séries")}</div></section>${dlCard}
      <div class="dialog-foot"><button class="primary" data-close>Fermer</button></div>`;
  };
  function openOrgSettings() {
    const d = FX.modal(FX.orgSettingsHTML());
    S.orgDlg = d;
    d.addEventListener("close", () => { S.orgDlg = null; });
    d.onclick = e => { if (e.target.closest("[data-close]")) d.close(); };
  }
  // A settings modal (⚙) like Organisation's: header with ✕, sections, a Fermer button; redrawn with the page.
  function openSettings(key, html) {
    const d = FX.modal(html());
    S[key] = d; d.dataset.settings = key;
    d.addEventListener("close", () => { S[key] = null; });
    d.onclick = e => { if (e.target.closest("[data-close]")) d.close(); };
  }
  const baseRender = FX.render;
  FX.render = () => {
    baseRender();
    if (S.orgDlg?.open) S.orgDlg.innerHTML = FX.orgSettingsHTML();
    if (S.diskDlg?.open) { const v = S.diskDlg.querySelector('[data-k="scr"]')?.value; S.diskDlg.innerHTML = FX.diskSettingsHTML(); if (v !== undefined) S.diskDlg.querySelector('[data-k="scr"]').value = v; }
    if (S.trashDlg?.open) S.trashDlg.innerHTML = FX.trashSettingsHTML();
  };
  const prevAfter = FX.afterRender;
  FX.afterRender = () => { prevAfter?.(); const t = document.querySelector('[data-k="orgtoggle"]'); if (t) t.indeterminate = t.dataset.state === "some"; };

  // ======================================================== events =========================================
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); } catch {
      const t = document.createElement("textarea"); t.value = text; document.body.append(t); t.select();
      try { document.execCommand("copy"); } catch {} t.remove();
    }
    FX.toast("Commande copiée.");
  }
  document.addEventListener("click", async e => {
    const el = e.target.closest("[data-k]");
    if (!el) return;
    const k = el.dataset.k;
    if (k === "copy") copyText(el.dataset.v);
    else if (k === "remount") { S.hddMounted = true; FX.toast(`${S.disks.d3.model} est maintenant visible dans le conteneur (/library).`); FX.render(); }
    else if (k === "disksettings") openSettings("diskDlg", FX.diskSettingsHTML);
    else if (k === "trashsettings") openSettings("trashDlg", FX.trashSettingsHTML);
    else if (k === "rebview") { const id = el.dataset.d; S.rebalOpen.has(id) ? S.rebalOpen.delete(id) : S.rebalOpen.add(id); FX.render(); }
    else if (k === "scrsave") { S.scrutinyUrl = S.diskDlg.querySelector('[data-k="scr"]').value.trim(); FX.toast(S.scrutinyUrl ? "Adresse de Scrutiny enregistrée." : "Scrutiny retiré."); FX.render(); }
    else if (k === "scrtest") {
      const v = S.diskDlg.querySelector('[data-k="scr"]').value.trim();
      FX.toast(/^https?:\/\/.+/.test(v) ? `Scrutiny répond (${S.data.disks.length} disques connus).` : "Adresse invalide : commencez par http:// ou https://.", /^https?:\/\/.+/.test(v) ? "ok" : "bad");
    } else if (k === "reb" || k === "film") {
      const n = el.dataset.n;
      if (k === "film" && e.target.closest("input")) return;
      S.rebal.has(n) ? S.rebal.delete(n) : S.rebal.add(n);
      FX.render();
    } else if (k === "rebgo") {
      const items = [];
      for (const b of rebalanceCandidates()) if (!el.dataset.d || el.dataset.d === b.id) for (const f of b.films.filter(x => S.rebal.has(x.n)))
        items.push(FX.makeItem("move", f, { disk: b.id, path: ["Films"] }, { disk: "d3", path: ["Films"] }));
      if (!items.length) return;
      for (const it of items) S.rebal?.delete(it.name);
      if (S.rebal && !S.rebal.size) S.rebal = null;
      FX.enqueue({ kind: "move", label: `Rééquilibrer : déplacer ${items.length} film${items.length > 1 ? "s" : ""} vers ${diskName("d3")}`, items });
      FX.show("tasks");
    } else if (k === "restore") {
      const rec = S.trash.find(t => t.id === el.dataset.id);
      if (!rec) return;
      const at = parseFrom(rec.from);
      const it = FX.makeItem("restore", { n: rec.name, s: rec.size }, { disk: rec.disk, path: [".corbeille"] }, at, { rec });
      it.to = { disk: at.disk, path: at.path.slice(0, -1) };
      FX.enqueue({ kind: "restore", label: `Restaurer « ${rec.name} »`, items: [it] });
      FX.toast("Restauration en cours : voir Tâches.");
    } else if (k === "empty") {
      const id = el.dataset.d, items = S.trash.filter(t => t.disk === id);
      const d = FX.modal(`<h2>Vider la corbeille de ${esc(diskName(id))} ?</h2><p><b>Suppression définitive, impossible à annuler.</b></p><p class="row">${items.length} élément${items.length > 1 ? "s" : ""} · ${size(items.reduce((a, t) => a + t.size, 0))}</p>
        <div class="dialog-foot"><button data-close>Annuler</button><button class="primary danger" id="ok">Vider maintenant</button></div>`);
      d.onclick = ev => {
        if (ev.target.closest("[data-close]")) d.close();
        if (ev.target.id === "ok") {
          S.trash = S.trash.filter(t => t.disk !== id);
          FX.logDone("empty", `Vider la corbeille de ${diskName(id)}`, items.map(t => ({ name: t.name, from: t.from, to: "supprimé définitivement", size: t.size, mode: "Suppression définitive" })));
          d.close(); FX.render();
        }
      };
    } else if (k === "token") {
      const input = document.querySelector(`input[data-k="tpl"][data-lib="${el.dataset.lib}"]`);
      const a = input.selectionStart ?? input.value.length, b = input.selectionEnd ?? a;
      S.templates[el.dataset.lib] = input.value.slice(0, a) + el.dataset.t + input.value.slice(b);
      FX.render();
      const again = document.querySelector(`input[data-k="tpl"][data-lib="${el.dataset.lib}"]`); again.focus(); again.setSelectionRange(a + el.dataset.t.length, a + el.dataset.t.length);
    } else if (k === "tplreset") { S.templates[el.dataset.lib] = DEFAULTS[el.dataset.lib]; FX.render(); }
    else if (k === "auto") { S.autoTidy[el.dataset.d] = !S.autoTidy[el.dataset.d]; FX.render(); }
    else if (k === "simdl") { S.orgDlg?.close(); simulateDownload(el.dataset.d); }
    else if (k === "orgsettings") openOrgSettings();
    else if (k === "orgapply") {
      const sel = orgRows().filter(checked);
      if (!sel.length) return;
      FX.enqueue({ kind: "organise", label: `Ranger ${sel.length} élément${sel.length > 1 ? "s" : ""} (format Jellyfin)`, items: sel.map(orgItem) });
      FX.show("tasks");
    } else if (k === "dlfolders") { S.orgDlg?.close(); parent.location.hash = "#/setup"; FX.toast("Paramètres : ouvrez Dossiers de téléchargement."); }
    else if (k === "links") { parent.location.hash = "#/setup"; FX.toast("Paramètres : ouvrez l'onglet du client, section Dossier de liens."); }
  });
  document.addEventListener("keydown", e => {
    const el = e.target.closest?.('[data-k="auto"]');
    if (el && (e.key === " " || e.key === "Enter")) { e.preventDefault(); el.click(); }
  });
  document.addEventListener("input", e => {
    const k = e.target.dataset?.k;
    if (k === "tpl") {
      S.templates[e.target.dataset.lib] = e.target.value;
      // Only the preview parts change, so the field keeps its focus.
      const sel = [e.target.selectionStart, e.target.selectionEnd];
      FX.render();
      const again = document.querySelector(`input[data-k="tpl"][data-lib="${e.target.dataset.lib}"]`); again.focus(); again.setSelectionRange(...sel);
    }
  });
  document.addEventListener("change", e => {
    const k = e.target.dataset?.k;
    if (k === "ret") { S.retention = +e.target.value; FX.render(); }
    else if (k === "simkind") { S.sim.kind = e.target.value; FX.render(); }
    else if (k === "simgb") { S.sim.gb = Math.max(0.1, +e.target.value || 1); FX.render(); }
    else if (k === "scope") { S.orgScope = e.target.value; FX.render(); }
    else if (k === "orgtoggle") { const rows = orgRows().filter(applicable); e.target.checked ? S.orgOff = new Set() : rows.forEach(p => S.orgOff.add(p.r.path)); FX.render(); }
    else if (k === "orgrow") { e.target.checked ? S.orgOff.delete(e.target.dataset.p) : S.orgOff.add(e.target.dataset.p); FX.render(); }
  });
  // A download that has just finished in a Download Folder with "Ranger automatiquement" on.
  function simulateDownload(id) {
    const dl = S.roots[id]?.find(n => n.dl) || (S.roots[id] || []).find(n => n.n === "Téléchargements") || (() => { const n = { n: "Téléchargements", d: 1, dl: 1, age: 0, c: [] }; S.roots[id].push(n); return n; })();
    const name = "Interstellar.2014.MULTi.2160p.UHD.BluRay.x265-FRATERNiTY";
    if (dl.c.some(c => c.n === name)) return FX.toast("Ce téléchargement simulé est déjà rangé ou en cours.");
    const seed = { client: "qBittorrent", ratio: 0, hours: 0, hash: "sim" };
    dl.c.push({ n: name, d: 1, age: 0, seed, c: [{ n: name + ".mkv", s: 24.5, age: 0, hash: "sim-mkv", seed }] });
    const r = { path: `Téléchargements/${name}`, kind: "film", title: "Interstellar", year: 2014, tmdb: 157336, res: "2160p", codec: "x265", src: "UHD BluRay", lang: "MULTi", seed: "qBittorrent", poster: null };
    S.orgExtra.push(r);
    const loc = { node: dl.c.at(-1), disk: id, folder: "Téléchargements", name };
    const p = propose(r, loc);
    FX.toast("Téléchargement terminé : rangement automatique.");
    FX.enqueue({ kind: "organise", label: `Ranger automatiquement « ${r.title} »`, who: "Rangement automatique", items: [orgItem(p)] });
    FX.show("tasks");
  }

  // ---- scenario hooks for the bar
  FX.api.scope = v => { S.orgScope = v; FX.show("organisation"); };
  FX.api.failNext = on => { S.failNext = !!on; };
  FX.api.demo = () => {
    const mv = (disk, folder, name, to) => { const n = nodeAt(disk, [folder]).c.find(c => c.n === name); return n && FX.makeItem("move", n, { disk, path: [folder] }, to); };
    const items = [
      mv("d1", "Téléchargements", "Oppenheimer.2023.MULTi.2160p.UHD.BluRay.x265.HDR-ELiTE.mkv", { disk: S.hddMounted ? "d3" : "d1", path: ["Films"] }),
      mv("d1", "Téléchargements", "Breaking.Bad.S01.MULTi.1080p.BluRay.x264-HDS", { disk: "d1", path: ["Séries"] }),
      mv("d1", "Téléchargements", "Dune.Part.Two.2024.MULTi.1080p.BluRay.x265-FRATERNiTY", { disk: "d2", path: ["Films"] }),
    ].filter(Boolean);
    if (!items.length) return FX.toast("Les exemples ont déjà été déplacés : réinitialisez.");
    for (const it of items) FX.enqueue({ kind: "move", label: `Déplacer « ${it.name} »`, items: [it] });
    FX.show("tasks");
  };
  FX.api.smartctl = on => { S.smartctl = !!on; FX.render(); };
  FX.api.reset = () => FX.reset();
  S.smartctl = true;
})();
