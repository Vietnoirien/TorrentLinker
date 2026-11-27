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
  S.rebal = null;
  const srcOf = d => {
    if (d.source === "scrutiny") return S.scrutinyUrl ? "Scrutiny" : S.smartctl ? "smartctl" : null;
    return S.smartctl ? "smartctl" : S.scrutinyUrl ? "Scrutiny" : null;
  };
  function smartHTML(d) {
    const src = srcOf(d);
    if (!src) return `<dt>Santé</dt><dd><span class="badge warn">inconnue</span> <small style="display:inline">smartctl n'est pas autorisé et Scrutiny n'est pas configuré (voir plus haut)</small></dd>`;
    const m = d.smart;
    const status = m.status === "ok" ? `<span class="badge ok">SMART : OK</span>` : `<span class="badge bad">Alerte : ${m.realloc} secteurs réalloués${m.pending ? `, ${m.pending} en attente` : ""}</span>`;
    return `<dt>Santé</dt><dd>${status}</dd><dt>Température</dt><dd>${m.temp} °C</dd><dt>Heures</dt><dd>${num(m.hours)} h</dd><dt>Source</dt><dd>${src}</dd>`;
  }
  function diskCard(id) {
    const d = S.disks[id], u = discUsage(id);
    const used = u.used / d.total * 100, below = u.free < u.margin;
    const other = Math.max(0, u.used - u.lib - u.dl - u.tr);
    const seg = (v, c) => `<i class="${c}" style="width:${Math.max(0, v) / d.total * 100}%" title="${size(v)}"></i>`;
    return `<article class="card disk" data-disk="${id}">
      <div class="row between"><h3>${esc(d.name)}</h3><span class="row"><span class="badge">${d.fs}</span><span class="badge">${d.capacity || size(d.total)}</span></span></div>
      <small>${esc(d.model)} · ${esc(d.mount)}${d.note ? " · " + esc(d.note) : ""}</small>
      <div><div class="bar stack" title="Marge de 10 % marquée">${seg(u.lib, "c-lib")}${seg(u.dl, "c-dl")}${seg(u.tr, "c-tr")}${seg(other, "c-ot")}</div>
        <div class="bar" style="margin-top:6px;height:6px"><i class="${used > 99.5 ? "bad" : used > 90 ? "warn" : ""}" style="width:${Math.min(100, used)}%"></i><u style="left:90%"></u></div></div>
      <div class="legend"><span><b class="c-lib"></b>Médiathèque ${size(u.lib)}</span><span><b class="c-dl"></b>Téléchargements ${size(u.dl)}</span><span><b class="c-tr"></b>Corbeille ${size(u.tr)}</span><span><b class="c-ot"></b>Autres données ${size(other)}</span></div>
      <div class="row"><b>${size(u.used)} utilisés</b><span>·</span><b>${size(u.free)} libres (${pct(100 - used)} %)</b>
        ${u.free <= 0 ? `<span class="badge bad">plein</span>` : ""}${below ? `<span class="badge ${u.free <= 0 ? "bad" : "warn"}">sous la marge de 10 % (${size(u.margin)})</span>` : `<span class="badge ok">marge de 10 % respectée</span>`}</div>
      ${below ? `<div class="note warn">${u.free <= 0 ? "Ce disque est plein : plus aucun téléchargement n'y sera placé." : "Ce disque est sous la marge : la règle de placement l'évite."} ${size(Math.max(0, u.margin - u.free))} à libérer pour retrouver la marge. Voir la proposition plus bas.</div>` : ""}
      <dl class="kv"><dt>Films</dt><dd>${u.films} film${u.films > 1 ? "s" : ""} dans les dossiers de bibliothèque</dd>${smartHTML(d)}</dl></article>`;
  }
  const unmountedCard = () => {
    const d = S.disks.d3;
    return `<article class="card disk" style="border:1px dashed #edbf73aa;grid-column:1/-1"><div class="row between"><h3>${esc(d.model)}</h3><span class="row"><span class="badge-preview">Aperçu</span><span class="badge warn">absent du conteneur</span></span></div>
      <small>${d.capacity} · ext4, étiquette « library » · monté par l'hôte sur /library, mais pas encore visible par TorrentLinker</small>
      <div class="note warn">Le disque est prêt sur la machine. Il reste <b>une seule étape</b>, à faire vous-même : ajouter le volume au conteneur, puis le redémarrer. TorrentLinker ne partitionne ni ne formate jamais un disque.</div>
      <div><b>Dans le fichier compose</b>, sous <code>volumes</code> du service torrentlinker :${code("services:\n  torrentlinker:\n    volumes:\n      - /library:/library")}</div>
      <div><b>Puis redémarrer</b> le conteneur :${code("docker compose up -d")}</div>
      <div class="row"><button data-k="remount" class="primary">C'est fait : le conteneur voit /library (aperçu)</button><small>Dans l'application, le disque apparaît ensuite ici et dans l'Explorateur, et reçoit les prochains téléchargements.</small></div></article>`;
  };
  function placement() {
    const films = [];
    for (const id of live()) for (const r of FX.S.roots[id]) if (r.lib === "Films") for (const f of r.c) if (f.film && f.poster !== undefined) films.push({ id, f });
    const together = S.sim.kind === "new" ? null : S.sim.kind === "series" ? "d1" : films.find(x => x.f.film === S.sim.kind)?.id;
    const r = FX.place(S.sim.gb, together);
    return `<section class="card sect"><div class="row between"><h3>Règle de placement</h3><span class="badge-preview">Aperçu</span></div>
      <p><b>« Garder ensemble, sinon le disque le plus libre. »</b> Les versions d'un film et les épisodes d'une série restent sur le disque qu'ils partagent déjà. Sinon, le téléchargement va sur le disque qui a le plus de place libre <b>au-dessus de la marge de 10 %</b>.</p>
      <div class="sim"><div class="row"><label>Prochain téléchargement<select data-k="simkind"><option value="new" ${S.sim.kind === "new" ? "selected" : ""}>Un nouveau film</option><option value="series" ${S.sim.kind === "series" ? "selected" : ""}>Un épisode de The Office (déjà sur /saves)</option>
        ${films.map(x => `<option value="${esc(x.f.film)}" ${S.sim.kind === x.f.film ? "selected" : ""}>Une autre version de ${esc(x.f.film)} (sur ${esc(diskName(x.id))})</option>`).join("")}</select></label>
        <label>Taille (Go)<input type="number" min="0.1" step="0.1" value="${S.sim.gb}" data-k="simgb" style="width:100px"></label></div>
        <div class="note ${r.disk === together || !together ? "" : "warn"}">Ce téléchargement de ${size(S.sim.gb)} irait sur <b>${esc(diskName(r.disk))}</b> : ${esc(r.why)}.
        ${live().map(id => `<div><small>${esc(diskName(id))} : ${size(discUsage(id).usable)} utilisables au-dessus de la marge</small></div>`).join("")}</div></div></section>`;
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
    if (!S.hddMounted) return `<section class="card sect"><h3>Rééquilibrer</h3><p class="muted">Dès que le conteneur voit le disque ${esc(S.disks.d3.model)} (/library), TorrentLinker propose d'y déplacer des films depuis les disques sous la marge.</p></section>`;
    const blocks = rebalanceCandidates();
    if (!blocks.length) return `<section class="card sect"><h3>Rééquilibrer</h3><p class="muted">Aucun disque n'est sous la marge de 10 %.</p></section>`;
    if (!S.rebal) S.rebal = new Set(blocks.flatMap(b => b.films.slice(0, 3).map(f => f.n)));
    let total = 0, count = 0;
    const html = blocks.map(b => {
      const picked = b.films.filter(f => S.rebal.has(f.n)), gb = picked.reduce((a, f) => a + sizeOf(f), 0);
      total += gb; count += picked.length;
      return `<div class="sect"><p><b>${esc(diskName(b.id))}</b> ${b.u.free <= 0 ? "est plein" : "est presque plein"} (${size(b.u.free)} libres, marge de 10 % = ${size(b.u.margin)}). ${picked.length ? `Déplacer ${picked.length} film${picked.length > 1 ? "s" : ""} (${size(gb)}) vers ${esc(diskName("d3"))} libérerait ${size(gb)}.` : "Cochez des films à déplacer."}
        ${gb < b.u.margin - b.u.free ? `<small>La marge demanderait ${size(b.u.margin - b.u.free)} : ce qui reste est hors des dossiers de bibliothèque, TorrentLinker n'y touche pas.</small>` : ""}</p>
        <div class="panel"><table class="list"><tbody>${b.films.map(f => { const s = seedOf(f); return `<tr data-k="film" data-n="${esc(f.n)}" style="cursor:pointer"><td style="width:30px"><input type="checkbox" data-k="reb" data-n="${esc(f.n)}" ${S.rebal.has(f.n) ? "checked" : ""}></td>
          <td style="width:40px"><span class="ico"><img src="${FX.base || "/library-storage-preview/"}poster-${f.poster}.png" alt="" width="28" height="42"></span></td><td class="name">${esc(f.film)}<small>${esc(f.n)}</small></td><td class="num">${size(sizeOf(f))}</td>
          <td>${s ? `<span class="badge ok">▲ ${esc(s.client)} · ratio ${num(s.ratio)}</span>` : ""}</td></tr>`; }).join("")}</tbody></table></div></div>`;
    }).join("");
    const eta = total / SPEED;
    return `<section class="card sect"><div class="row between"><h3>Proposition : rééquilibrer vers ${esc(diskName("d3"))}</h3><span class="badge-preview">Aperçu</span></div>
      ${html}<div class="note">${count} film${count > 1 ? "s" : ""} · ${size(total)} · copie entre disques d'environ ${dur(eta)}. Chaque film en partage est déplacé <b>par son client</b> (qBittorrent : déplacement natif, le partage continue), puis l'original est supprimé après vérification.</div>
      <div class="row"><button class="primary" data-k="rebgo" ${count ? "" : "disabled"}>Déplacer ${count} film${count > 1 ? "s" : ""} vers ${esc(diskName("d3"))}</button><small>Les déplacements s'ouvrent dans Tâches, vous pouvez les annuler.</small></div></section>`;
  }
  FX.disksHTML = () => {
    const hint = !S.smartctl ? `<div class="note warn"><b>smartctl n'est pas autorisé</b> pour ce serveur : la santé des disques est inconnue${S.scrutinyUrl ? ", Scrutiny la fournit pour les disques qu'il connaît" : ""}. Pour l'autoriser (lecture seule) :
      ${code("# docker compose\nservices:\n  torrentlinker:\n    cap_add:\n      - SYS_RAWIO\n    devices:\n      - /dev/sda:/dev/sda\n      - /dev/sdb:/dev/sdb")}</div>` : "";
    return `<p class="muted hint">Chaque disque est monté séparément et identifié par son périphérique (<code>st_dev</code>). La corbeille est comptée à part. Les alertes viennent de smartctl ou de Scrutiny.</p>
      <section class="card sect"><div class="row between"><h3>Santé des disques</h3><span class="badge-preview">Aperçu</span></div>
        <div class="row"><span>smartctl : <b>${S.smartctl ? "autorisé" : "non autorisé"}</b></span><span class="grow"></span>
        <label class="row">Scrutiny (API) <input data-k="scr" value="${esc(S.scrutinyUrl)}" placeholder="http://scrutiny:8080" style="width:260px"></label><button data-k="scrsave">Enregistrer</button><button data-k="scrtest">Tester</button></div>${hint}</section>
      <div class="disks">${live().map(diskCard).join("")}${S.hddMounted ? "" : unmountedCard()}</div>
      <div style="height:14px"></div>${placement()}${rebalance()}`;
  };

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
  FX.trashHTML = () => {
    const sections = live().map(id => {
      const items = S.trash.filter(t => t.disk === id && visible(t));
      const total = items.reduce((a, t) => a + t.size, 0);
      return `<section class="sect"><h3>Corbeille de ${esc(diskName(id))} <span class="badge">${size(total)}</span>
        ${owner() && items.length ? `<button class="danger" data-k="empty" data-d="${id}">Vider maintenant</button>` : ""}</h3>
        <div class="panel">${items.length ? `<table class="list"><thead><tr><th>Nom</th><th>Emplacement d'origine</th><th>Supprimé</th><th class="num">Taille</th><th>Purge</th><th></th></tr></thead><tbody>
        ${items.map(t => `<tr><td class="name">${esc(t.name)}${t.reason ? `<small>${esc(t.reason)}</small>` : ""}</td><td class="name" style="font-size:12.5px;color:var(--muted)">${esc(t.from)}</td>
          <td>${esc(t.by)}<small>${ago(t.ts)}</small></td><td class="num">${size(t.size)}</td>
          <td>${left(t) <= 1 ? `<span class="badge warn">${left(t) === 0 ? "ce soir" : "dans 1 j"}</span>` : `<span class="badge">purgée dans ${left(t)} j</span>`}</td>
          <td class="num"><button data-k="restore" data-id="${t.id}">Restaurer</button></td></tr>`).join("")}</tbody></table>` : `<div class="empty">La corbeille de ce disque est vide.</div>`}</div></section>`;
    }).join("");
    return `<p class="muted hint">Supprimer, dans Fichiers, veut toujours dire mettre à la corbeille. Chaque disque a la sienne : le déplacement est instantané. ${S.member ? "Vous ne voyez que ce qui vient de vos dossiers de bibliothèque accordés." : ""}</p>
      ${owner() ? `<section class="card sect"><div class="row"><h3>Conservation</h3><label class="row">Purger après <select data-k="ret">${[1, 3, 7, 14, 30].map(n => `<option value="${n}" ${S.retention === n ? "selected" : ""}>${n} jour${n > 1 ? "s" : ""}</option>`).join("")}</select></label>
        <small style="display:inline">7 jours par défaut. L'espace de la corbeille est compté à part dans Disques.</small></div></section>` : ""}${sections}`;
  };

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
  FX.orgHTML = () => {
    const rows = orgRows(), sel = rows.filter(checked);
    const scopes = ["Films", "Séries", "Téléchargements"];
    const tplCard = lib => {
      const r = exampleRow(lib), err = tplError(S.templates[lib]);
      const ex = err ? "" : fill(S.templates[lib], r, 1).split("/").map(clean).join(" / ") + ".mkv";
      return `<div class="card tpl"><div class="row between"><h3>Modèle de nommage · ${lib}</h3><span class="badge">Dossier de bibliothèque</span></div>
        <small>Un « / » sépare un dossier du suivant, le nom du fichier est le dernier niveau, l'extension est ajoutée.</small>
        <input data-k="tpl" data-lib="${lib}" value="${esc(S.templates[lib])}" spellcheck="false" aria-label="Modèle ${lib}">
        <div class="tokens">${TOKENS.map(t => `<button data-k="token" data-lib="${lib}" data-t="${esc(t)}">${esc(t)}</button>`).join("")}</div>
        ${err ? `<div class="err">${esc(err)}</div>` : `<div class="example"><small>Exemple (${esc(r.title)})</small>${esc(ex)}</div>`}
        <div class="row"><button data-k="tplreset" data-lib="${lib}" ${S.templates[lib] === DEFAULTS[lib] ? "disabled" : ""}>Rétablir le modèle Jellyfin</button></div></div>`;
    };
    const folders = [["d1", "/saves/Téléchargements"], ...(S.hddMounted ? [["d3", "/library/Téléchargements"]] : [])];
    const dlCard = `<div class="card"><h3>Ranger automatiquement</h3><p class="muted">Par Dossier de téléchargement. Désactivé par défaut : rien n'est rangé sans que vous l'ayez demandé.</p>
      ${folders.map(([id, path]) => {
        const on = !!S.autoTidy[id];
        const p = FX.place(4.2, null);
        return `<div class="sect"><div class="switch" role="switch" tabindex="0" data-k="auto" data-d="${id}" aria-checked="${on}"><span class="sw"></span><span><b>${esc(path)}</b>
          <small>${on ? `À la fin d'un téléchargement, la version est renommée avec le modèle de sa bibliothèque puis <b>déplacée vers l'endroit que choisit la règle de placement</b> (par exemple ${esc(diskName(p.disk))}), sans cesser de partager : le client la suit. Tout est dans Tâches et annulable.` : "Désactivé : les téléchargements terminés restent où ils sont."}</small></span></div>
          ${on ? `<div style="margin:8px 0 0 46px"><button data-k="simdl" data-d="${id}">Simuler un téléchargement terminé</button></div>` : ""}</div>`;
      }).join("")}</div>`;
    const flags = rows.filter(p => p.link).length;
    return `<p class="muted hint">Aperçu des renommages au format Jellyfin. Rien n'est appliqué tant que vous ne confirmez pas des lignes. Un torrent en partage est renommé <b>dans son client</b>.</p>
      <section class="sect"><div class="row"><h3>Renommages proposés</h3><label class="row">Dossier <select data-k="scope">${scopes.map(s => `<option ${s === S.orgScope ? "selected" : ""}>${s}</option>`).join("")}</select></label>
        <span class="grow"></span><button data-k="orgall">Tout cocher</button><button data-k="orgnone">Tout décocher</button>
        <button class="primary" data-k="orgapply" ${sel.length ? "" : "disabled"}>Appliquer la sélection (${sel.length})</button></div>
        ${flags ? `<div class="note warn">${flags} ligne${flags > 1 ? "s" : ""} nécessite${flags > 1 ? "nt" : ""} un Dossier de liens : le client ne sait pas les renommer sans changer leur disposition. Configurez-le dans Paramètres, onglet du client. <button data-k="links">Ouvrir Paramètres</button></div>` : ""}
        <div class="panel"><table class="list diff"><thead><tr><th></th><th>Actuel</th><th>Proposé (Jellyfin)</th><th>Partage</th></tr></thead><tbody>
        ${rows.map(p => `<tr class="${p.same ? "unchanged" : ""} ${p.link ? "blocked" : ""}"><td><input type="checkbox" data-k="orgrow" data-p="${esc(p.r.path)}" ${checked(p) ? "checked" : ""} ${applicable(p) ? "" : "disabled"} aria-label="Appliquer ${esc(p.r.title)}"></td>
          <td class="cur">${esc(curTop(p))}</td>
          <td class="new">${p.same ? "<small>Déjà conforme au modèle</small>" : p.error ? `<span style="color:var(--danger)">${esc(p.error)}</span>` : `${p.moving ? `<small>${esc(diskName(p.destDisk))} · ${p.lib}/</small>` : ""}<b>${esc(p.first)}</b>${esc(p.more)}${p.moving && p.why ? `<small>Placement : ${esc(p.why)}</small>` : ""}`}</td>
          <td>${!p.r.seed ? `<small>Aucun torrent</small>` : p.link ? `<span class="badge warn" title="${esc(p.r.layout || "Ce client ne sait pas renommer les fichiers d'un torrent.")}">nécessite un Dossier de liens</span><small>${esc(p.r.seed)} · ${esc(p.r.layout || (FX.clientOf(p.r.seed)?.native ? "" : "ce client ne renomme pas dans le torrent"))}</small>`
            : `<span class="badge ok">renommé dans le client</span><small>${esc(p.r.seed)}</small>`}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">Rien à ranger dans ce dossier.</td></tr>`}</tbody></table></div></section>
      <div class="grid2">${tplCard("Films")}${tplCard("Séries")}</div><div style="height:14px"></div>${dlCard}`;
  };

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
    else if (k === "scrsave") { S.scrutinyUrl = document.querySelector('[data-k="scr"]').value.trim(); FX.toast(S.scrutinyUrl ? "Adresse de Scrutiny enregistrée." : "Scrutiny retiré."); FX.render(); }
    else if (k === "scrtest") {
      const v = document.querySelector('[data-k="scr"]').value.trim();
      FX.toast(/^https?:\/\/.+/.test(v) ? `Scrutiny répond (${S.data.disks.length} disques connus).` : "Adresse invalide : commencez par http:// ou https://.", /^https?:\/\/.+/.test(v) ? "ok" : "bad");
    } else if (k === "reb" || k === "film") {
      const n = el.dataset.n;
      if (k === "film" && e.target.closest("input")) return;
      S.rebal.has(n) ? S.rebal.delete(n) : S.rebal.add(n);
      FX.render();
    } else if (k === "rebgo") {
      const items = [];
      for (const b of rebalanceCandidates()) for (const f of b.films.filter(x => S.rebal.has(x.n)))
        items.push(FX.makeItem("move", f, { disk: b.id, path: ["Films"] }, { disk: "d3", path: ["Films"] }));
      if (!items.length) return;
      S.rebal = null;
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
      const d = FX.modal(`<h2>Vider la corbeille de ${esc(diskName(id))} ?</h2><p><b>${items.length} élément${items.length > 1 ? "s" : ""} (${size(items.reduce((a, t) => a + t.size, 0))}) ${items.length > 1 ? "seront supprimés" : "sera supprimé"} définitivement.</b> Cette action ne peut pas être annulée ; elle est réservée au propriétaire.</p>
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
    else if (k === "simdl") simulateDownload(el.dataset.d);
    else if (k === "orgall") { S.orgOff = new Set(); FX.render(); }
    else if (k === "orgnone") { orgRows().forEach(p => S.orgOff.add(p.r.path)); FX.render(); }
    else if (k === "orgapply") {
      const sel = orgRows().filter(checked);
      if (!sel.length) return;
      FX.enqueue({ kind: "organise", label: `Ranger ${sel.length} élément${sel.length > 1 ? "s" : ""} (format Jellyfin)`, items: sel.map(orgItem) });
      FX.show("tasks");
    } else if (k === "links") { parent.location.hash = "#/setup"; FX.toast("Paramètres : ouvrez l'onglet du client, section Dossier de liens."); }
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
