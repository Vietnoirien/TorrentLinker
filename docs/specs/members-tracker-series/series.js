"use strict";
/* Tracker Series preview, inside the real Médias frame. The real Séries and Anime tabs, the real
   poster rows, the real banner and the real Request drawer draw everything; this file only adds
   what the spec adds: a "Sur le tracker" row and its "Tout voir" page for series, the seasons
   under the banner, the Member's request sheet. Series are served from fixture.json by wrapping
   the transport; nothing reaches a tracker. It runs before view.js, so it can wrap the transport
   before the first request. Everything it adds is marked with an "Aperçu" badge. */
(() => {
  const PREFIX = "tracker-series-preview";
  const API = `/api/${PREFIX}`;
  const RANK = {TP: 0, "10": 1, "12": 2, "16": 3, "18": 4};
  const ROLES = {
    owner: {label: "Propriétaire", limit: null},
    member: {label: "Membre", limit: null},
    limited: {label: "Membre avec limite d'âge", limit: 2},
  };
  const TS = {role: "owner", series: [], by: new Map(), ready: null, scope: null};
  window.TSPreview = TS;
  TS.ready = fetch(`/${PREFIX}/fixture.json`).then(r => r.json()).then(d => {
    TS.series = d.series;
    d.series.forEach((s, i) => { s.score = Math.round((7.2 + ((i * 7) % 20) / 10) * 10) / 10; TS.by.set(s.id, s); });
  });

  // ---- what each role sees ------------------------------------------------------------
  const owner = () => TS.role === "owner";
  const fully = s => s.seasons.every(season => s.owned.includes(season.n));
  const plain = text => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const visible = (s, scope) => {
    if ((scope === "anime") !== (s.kind === "anime")) return false;
    if (owner()) return true;
    if (fully(s)) return false;  // a series fully in the Library is hidden from Members
    const limit = ROLES[TS.role].limit;
    return limit === null || (RANK[s.rating] !== undefined && RANK[s.rating] <= limit);  // no rating: hidden under a limit
  };
  const seasonOf = (s, n) => s.seasons[n - 1];
  const asking = (s, season) => !s.owned.includes(season.n) && season.state !== "episodes";  // a Member can ask for it
  const ranges = list => {
    const out = [];
    for (const n of [...list].sort((a, b) => a - b)) {
      if (out.length && out[out.length - 1][1] === n - 1) out[out.length - 1][1] = n; else out.push([n, n]);
    }
    return out.map(([a, b]) => a === b ? String(a) : `${a}–${b}`).join(", ");
  };
  const seasonsText = list => list.length === 1 ? say(`season ${list[0]}`, `saison ${list[0]}`) : say(`seasons ${ranges(list)}`, `saisons ${ranges(list)}`);

  // The Approver's pre-selection: the best pack per season (ReleaseScore, then Tracker order, then seeders),
  // or the Intégrale when it covers every asked season and scores better (ADR-0025's tie-breaks).
  const order = {c411: 0, tr4ker: 1};
  const better = (a, b) => b.score - a.score || order[a.tracker] - order[b.tracker] || b.seeders - a.seeders;
  function preselect(s, seasons) {
    const packs = seasons.map(n => [...seasonOf(s, n).releases].sort(better)[0] || null);
    const integ = s.integrale;
    const covers = integ && seasons.every(n => integ.seasons.includes(n));
    const missing = packs.some(p => !p);
    const average = packs.filter(Boolean).reduce((a, p) => a + p.score, 0) / (packs.filter(Boolean).length || 1);
    if (covers && (missing || integ.release.score > average)) return {hashes: [integ.release.hash], integrale: true, size: integ.release.size};
    return {hashes: packs.filter(Boolean).map(p => p.hash), integrale: false, size: packs.filter(Boolean).reduce((a, p) => a + p.size, 0)};
  }
  const requestable = s => s.seasons.filter(season => asking(s, season)).map(season => season.n);
  TS.preselect = preselect;

  // ---- rows, as the film index serves them ---------------------------------------------
  function rowOf(s) {
    const full = fully(s);
    const releases = s.seasons.reduce((a, season) => a + season.releases.length, 0) + (s.integrale ? 1 : 0);
    return {
      id: `film-${s.id}`, kind: "video", film: s.id, tseries: true, title: s.title, year: String(s.year), rating: s.score,
      age_rating: {rating: s.rating, source: "tmdb", by: "", suggestion: null}, genre: s.genres.join(", "),
      description: s.synopsis, duration: 0, artwork_url: `api/${PREFIX}/poster-${s.id}.png`, available: true, identified: true,
      in_library: full, release_count: releases, language: "MULTI",
    };
  }
  const sorts = {
    new: (a, b) => b.published - a.published,
    shared: (a, b) => b.seeders - a.seeders,
    year: (a, b) => b.year - a.year || plain(a.title).localeCompare(plain(b.title)),
    title: (a, b) => plain(a.title).localeCompare(plain(b.title)),
  };
  function listing(params, scope) {
    const genres = params.getAll("genre"), q = plain(params.get("q") || ""), sort = sorts[params.get("sort")] || sorts.new;
    const all = TS.series.filter(s => visible(s, scope));
    const found = all.filter(s => genres.every(g => s.genres.includes(g)) && (!q || plain(`${s.title} ${s.original}`).includes(q))).sort(sort);
    const offset = Number(params.get("offset") || 0), limit = Number(params.get("limit") || 60);
    const names = [...new Set(all.flatMap(s => s.genres))].sort((a, b) => plain(a).localeCompare(plain(b)));
    return {
      rows: found.slice(offset, offset + limit).map(rowOf), total: found.length, has_more: offset + limit < found.length,
      next_offset: offset + limit < found.length ? offset + limit : null, filters: {genres: names},
    };
  }
  function landing(scope) {
    const all = TS.series.filter(s => visible(s, scope)), rows = [];
    const add = (key, title, filters, list) => { if (list.length) rows.push({key, title, filters: {tracker: "films", ...filters}, total: list.length, rows: list.slice(0, 20).map(rowOf)}); };
    add("tracker-new", "", {sort: "new"}, [...all].sort(sorts.new));
    add("tracker-shared", "", {sort: "shared"}, [...all].sort(sorts.shared));
    for (const genre of [...new Set(all.flatMap(s => s.genres))].sort((a, b) => plain(a).localeCompare(plain(b)))) {
      add("genre", genre, {genre}, all.filter(s => s.genres.includes(genre)).sort(sorts.new));
    }
    return {rows};
  }
  function trackerRow(scope) {
    const list = TS.series.filter(s => visible(s, scope)).sort(sorts.new);
    return {key: "tracker", title: "", filters: {tracker: "films"}, total: list.length, rows: list.slice(0, 40).map(rowOf), state: "ready", reason: ""};
  }

  // ---- the transport: series come from the fixture, everything else goes on as before ------
  async function mine(path, options) {
    const [name, query = ""] = path.split("?"), params = new URLSearchParams(query);
    const body = options?.body || {};
    await TS.ready;
    if (name === "media/home" && ["series", "anime"].includes(params.get("scope"))) {
      if (params.get("include") === "tracker") return {rows: [trackerRow(params.get("scope"))]};
      return null;
    }
    // On Séries and Animés the row's live merge asks the film routes too: it gets the series.
    const scope = TS.scope || (["series", "anime"].includes(media.view) ? media.view : null);
    if (scope && name === "media/tracker-films/landing") return landing(scope);
    if (scope && name === "media/tracker-films") return listing(params, scope);
    if (scope && name === "media/tracker-films/revision") return {revision: 1, running: false, identified: 1, total: 1};
    if (name === "media/tracker-films/focus") return {};
    if (/^media\/tracker\/[0-9a-f]{40}\/download$/.test(name)) return {};  // the preview downloads nothing
    if (!owner() && name === "requests") {
      if (options.method === "POST") {
        const s = TS.by.get(body.film);
        if (!s) return null;
        await fetch(`${API}/ask`, {method: "POST", body: JSON.stringify({series: body.film, seasons: body.seasons, follow: body.follow, quote: body.quote, pre: body.pre})});
        return {};
      }
      return (await fetch(`${API}/requests`)).json();
    }
    if (!owner() && name === "requests/seen") { await fetch(`${API}/seen`, {method: "POST", body: "{}"}); return (await fetch(`${API}/requests`)).json(); }
    if (!owner() && /^requests\/[0-9a-f]{32}\/cancel$/.test(name)) { await fetch(`${API}/cancel`, {method: "POST", body: JSON.stringify({id: name.split("/")[1]})}); return {}; }
    return null;
  }
  const wrap = request => async (path, options) => {
    const answer = await mine(path, options || {});
    return answer === null ? request(path, options) : answer;
  };
  const connect = TLPanel.connect;
  TLPanel.connect = (name, extra) => connect(name, extra).then(request => name === "media" ? wrap(request) : request);

  // ---- role --------------------------------------------------------------------------
  const applyReal = applyEnvironment;
  applyEnvironment = async function () {
    if (!owner()) environment = {...environment, owner: false, viewer: false, permissions: ["films", "series", "anime", "request"]};
    else environment = {...environment, owner: true, permissions: []};
    return applyReal();
  };
  TS.setRole = async name => {
    TS.role = name;
    TS.picked = null; requests.loaded = false; requests.rows = []; requests.quota = null;
    loadedEnvironment = ""; pendingEnvironment = ""; media.featureId = null; media.selected = null; TS.scope = null; media.films = null;
    await applyEnvironment();
    await TS.reload();
  };
  TS.reload = async () => { if (!owner()) await requestsLoad(); await loadMedia(); };

  // ---- the badge that marks what this preview adds ------------------------------------
  const preview = text => element("span", text || "Aperçu", "ts-preview");

  // ---- navigation: the Séries tab, its Tout voir page, back --------------------------------
  const originalLoad = loadMedia;
  loadMedia = function (...args) {
    if (media.view !== "tracker") TS.scope = null;
    return originalLoad.apply(this, args);
  };
  const originalOpenLanding = filmsOpenLanding;
  filmsOpenLanding = function () {
    if (["series", "anime"].includes(media.view)) TS.scope = media.view;
    else if (media.view !== "tracker") TS.scope = null;
    return originalOpenLanding();
  };
  const originalLandingHead = filmsLandingHead;
  filmsLandingHead = function (root) {
    originalLandingHead(root);
    if (!TS.scope) return;
    const head = root.querySelector(".films-landing");
    if (!head) return;
    const [back, title, count] = head.children, scope = TS.scope;
    back.textContent = scope === "anime" ? "‹ Animés" : "‹ Séries";
    back.onclick = () => guard(async () => {
      TS.scope = null; media.films = null; media.view = scope; $("media-view").value = scope; mediaViews(); await loadMedia();
    });
    title.textContent = scope === "anime" ? "Animés sur le tracker" : "Séries sur le tracker";
    count.textContent = "une rangée par genre";
    title.after(preview());
  };
  const originalShelf = filmsShelf;
  filmsShelf = function () {
    originalShelf();
    if (!TS.scope) return;
    const label = document.querySelector(".films-bar .films-label");
    if (label && !label.nextSibling?.classList?.contains("ts-preview")) {
      label.textContent = TS.scope === "anime" ? "Animés sur le tracker ·" : "Séries sur le tracker ·";
      label.after(preview());
    }
    const count = document.querySelector(".films-bar .media-home-row-count");
    if (count) count.textContent = count.textContent.replace(/film/, "série");
  };
  // The live merge redraws the count as "films": keep it right.
  new MutationObserver(() => {
    if (!TS.scope) return;
    for (const count of document.querySelectorAll(".films-bar .media-home-row-count")) if (/film/.test(count.textContent)) count.textContent = count.textContent.replace(/film/, "série");
  }).observe(document.documentElement, {childList: true, subtree: true, characterData: true});

  // The row's own title carries the badge on Séries and Animés.
  const originalHome = mediaRenderHome;
  mediaRenderHome = function () {
    originalHome();
    if (!["series", "anime"].includes(media.view)) return;
    for (const h of document.querySelectorAll("#media-home-rows .media-home-row h2")) {
      if (/^(Sur le tracker|On the tracker)$/.test(h.textContent) && !h.nextElementSibling?.classList.contains("ts-preview")) h.after(preview());
    }
  };
  // A card of the row or the grid: its seasons, beside the year.
  const originalRowCard = mediaRowCard;
  mediaRowCard = function (item, row, track) {
    const card = originalRowCard(item, row, track);
    if (item.tseries) {
      const s = TS.by.get(item.film), small = card.querySelector("span:last-child");
      if (small && !small.classList.contains("media-poster-badge")) small.textContent = `${item.year} · ${s.seasons.length} ${say("seasons", "saisons")}`;
    }
    return card;
  };
  // The Owner's poster badge: partly owned series say so.
  const originalBadge = filmsBadge;
  filmsBadge = function (row, art) {
    originalBadge(row, art);
    if (row.tseries && owner() && !row.in_library && TS.by.get(row.film).owned.length) art.append(element("span", say("Partly in the Library", "En partie en bibliothèque"), "media-poster-badge wait"));
  };

  // ---- the series' banner and its seasons ----------------------------------------------
  const originalFeature = filmsFeature;
  filmsFeature = function (row, content, description, actions) {
    if (!row.tseries) return originalFeature(row, content, description, actions);
    const s = TS.by.get(row.film);
    for (const tag of content.querySelectorAll(".media-feature-tag")) if (/Version|Poids|File size/.test(tag.textContent)) tag.remove();
    content.querySelector(".media-feature-meta")?.append(` · ${s.seasons.length} ${say("seasons", "saisons")} · ${s.airing ? say("airing", "en cours") : say("ended", "terminée")}`);
    if (owner()) {
      if (fully(s)) content.querySelector("h2").append(element("span", say("In the Library", "Dans la bibliothèque"), "media-poster-badge films-inline"));
      else if (s.owned.length) content.querySelector("h2").append(element("span", say(`${seasonsText(s.owned)} in the Library`, `${seasonsText(s.owned).replace(/^./, c => c.toUpperCase())} dans la médiathèque`), "media-poster-badge films-inline"));
      content.querySelector("h2").append(preview());
      const n = s.seasons.reduce((a, season) => a + season.releases.length, 0) + (s.integrale ? 1 : 0);
      actions.append(button(say(`Releases (${n})`, `Releases (${n})`), () => guard(() => seriesReleases(s)), "media-secondary"));
      return;
    }
    content.querySelector("h2").append(preview());
    memberActions(s, description, actions);
  };
  const originalEpisodes = mediaRenderEpisodes;
  mediaRenderEpisodes = async function (row) {
    if (!row?.tseries) return originalEpisodes(row);
    const root = $("media-episodes");
    // The seasons open under the banner for a series the viewer picked, not for the one the banner shows by default.
    if (TS.picked !== row.id) { root.hidden = true; root.replaceChildren(); return; }
    root.hidden = false; root.dataset.owner = row.id; root.classList.add("ts-seasons-box");
    seasonsList(root, TS.by.get(row.film));
  };
  const clearSeasons = () => $("media-episodes").classList.remove("ts-seasons-box");
  const originalSelect = mediaSelectFeature;
  mediaSelectFeature = function (row) { TS.picked = row.tseries ? row.id : null; if (!row.tseries) clearSeasons(); return originalSelect(row); };

  const open = new Set();  // "id:n" of the seasons unfolded
  function statusOf(s, season) {
    if (s.owned.includes(season.n)) return [say("In the Library", "Dans la médiathèque"), "own"];
    const asked = askedOf(s);
    if (asked?.seasons.includes(season.n) && !owner()) return [say("Requested", "Demandée"), "asked"];
    return null;
  }
  const kindOf = (s, season) => season.state === "pack" ? [say("Full pack", "Pack complet"), "ok"]
    : season.state === "integ" ? [say("Covered by the Intégrale", "Couvert par l'Intégrale"), "integ"]
      : [say(`Episodes only (${season.episodes.filter(e => e.tracker).length}/${season.count})`, `Épisodes seulement (${season.episodes.filter(e => e.tracker).length}/${season.count})`), "eps"];
  function seasonsList(root, s) {
    root.replaceChildren();
    const header = element("div", undefined, "media-episodes-header ts-head");
    header.append(element("h2", say("Seasons", "Saisons")), preview(), element("span", say(`${s.seasons.length} seasons · ${s.seasons.reduce((a, x) => a + x.count, 0)} episodes`, `${s.seasons.length} saisons · ${s.seasons.reduce((a, x) => a + x.count, 0)} épisodes`), "media-home-row-count"));
    root.append(header);
    if (owner() && s.integrale) root.append(integraleLine(s));
    const list = element("ul", undefined, "ts-seasons");
    for (const season of s.seasons) list.append(seasonItem(s, season));
    root.append(list);
  }
  function integraleLine(s) {
    const box = element("div", undefined, "ts-integrale"), release = s.integrale.release;
    box.append(element("strong", say(`Intégrale · seasons ${ranges(s.integrale.seasons)}`, `Intégrale · saisons ${ranges(s.integrale.seasons)}`)), mediaTrackerRelease(release));
    const get = button(say("Download", "Télécharger"), () => guard(() => filmsDownload(release, get)), "media-secondary"); box.append(get);
    return box;
  }
  function seasonItem(s, season) {
    const key = `${s.id}:${season.n}`, item = element("li", undefined, "ts-season");
    const head = element("div", undefined, "ts-season-head");
    const toggle = button("", () => { open.has(key) ? open.delete(key) : open.add(key); seasonsList($("media-episodes"), s); }, "ts-toggle");
    toggle.setAttribute("aria-expanded", String(open.has(key)));
    toggle.append(element("span", open.has(key) ? "▾" : "▸", "ts-caret"), element("strong", say(`Season ${season.n}`, `Saison ${season.n}`)), element("span", say(`${season.count} episodes`, `${season.count} épisodes`), "ts-count"));
    const [kind, tone] = kindOf(s, season), pills = element("span", undefined, "ts-pills");
    pills.append(element("span", kind, `ts-pill ${tone}`));
    const status = statusOf(s, season);
    if (status) pills.append(element("span", status[0], `ts-pill ${status[1]}`));
    head.append(toggle, pills);
    if (owner() && season.releases.length && season.state === "pack") {
      const best = [...season.releases].sort(better)[0];
      const get = button(say("Download", "Télécharger"), () => guard(() => filmsDownload(best, get)), "media-secondary ts-get"); head.append(get);
    }
    item.append(head);
    if (open.has(key)) item.append(seasonBody(s, season));
    return item;
  }
  function seasonBody(s, season) {
    const body = element("div", undefined, "ts-season-body");
    if (owner() && season.releases.length) {
      const best = [...season.releases].sort(better)[0], box = element("div", undefined, "ts-releases");
      if (season.state === "pack") {
        for (const release of [...season.releases].sort(better)) {
          const line = mediaTrackerRelease(release);
          if (release === best) line.prepend(element("span", say("Pre-selected", "Pré-sélection"), "media-poster-badge films-inline"));
          box.append(line);
        }
        body.append(box);
      }
    }
    if (owner() && season.state === "integ") body.append(element("p", say(`Only in the Intégrale (seasons ${ranges(s.integrale.seasons)}).`, `Seulement dans l'Intégrale (saisons ${ranges(s.integrale.seasons)}).`), "media-row-note"));
    if (season.state === "episodes" && !owner()) body.append(element("p", say("No full pack yet: the tracker has some episodes only.", "Pas encore de pack complet : le tracker n'a que certains épisodes."), "media-row-note"));
    const list = element("ol", undefined, "ts-episodes");
    for (const ep of season.episodes) {
      const line = element("li", undefined, "ts-episode"), text = element("div");
      text.append(element("strong", `${ep.n}. ${ep.title}`), element("p", ep.synopsis));
      const on = ep.tracker;
      line.append(text, element("span", on ? say("On the tracker", "Sur le tracker") : say("Not on the tracker", "Pas sur le tracker"), `ts-pill ${on ? "ok" : "eps"}`));
      if (owner() && on && season.state === "episodes") {
        const release = season.releases[ep.n - 1], get = button(say("Download", "Télécharger"), () => guard(() => filmsDownload(release, get)), "media-secondary ts-get");
        line.append(get);
      }
      list.append(line);
    }
    body.append(list);
    return body;
  }
  // The Owner's releases dialog: every release, by season, the Intégrale first.
  async function seriesReleases(s) {
    const root = $("media-details"); root.replaceChildren(); root.hidden = false;
    if (!root.open) root.showModal();
    root.append(button(say("Close details", "Fermer les détails"), () => root.close()), element("h2", s.title), preview());
    const list = element("div", undefined, "films-releases");
    const add = (title, releases, flag) => {
      list.append(element("h3", title, "ts-releases-title"));
      for (const release of releases) {
        const line = element("div", undefined, "films-release"), pill = element("span", String(release.score), `media-score score-${release.color}`);
        pill.title = "ReleaseScore";
        const facts = [mediaFileSize(release.size), say(`${release.seeders} seeders`, `${release.seeders} sources`), release.tracker].join(" · ");
        const get = button(say("Download", "Télécharger"), () => guard(() => filmsDownload(release, get)), "media-secondary");
        line.append(pill, element("span", release.name, "media-tracker-name"), element("span", facts, "media-tracker-facts"), element("span", undefined, "films-release-actions"));
        line.lastChild.append(get);
        if (flag === release) line.prepend(element("span", say("Pre-selected", "Pré-sélection"), "media-poster-badge films-inline"));
        list.append(line);
      }
    };
    if (s.integrale) add(`Intégrale · saisons ${ranges(s.integrale.seasons)}`, [s.integrale.release]);
    for (const season of s.seasons) {
      if (!season.releases.length) continue;
      add(season.state === "pack" ? `Saison ${season.n}` : `Saison ${season.n} · épisodes`, season.releases, [...season.releases].sort(better)[0]);
    }
    root.append(list);
  }

  // ---- the Member: where a series stands, the request sheet ----------------------------
  const askedOf = s => requests.rows.find(r => r.film === s.id && !["refused", "cancelled", "expired"].includes(r.state));
  function memberActions(s, copy, actions) {
    const asked = askedOf(s);
    const latest = asked || requests.rows.find(r => r.film === s.id && r.state !== "cancelled");
    if (latest) {
      const [label, tone] = requestState(latest), line = element("div", undefined, "media-request-state");
      const said = latest.answer ? `${latest.answered_by || say("The owner", "Le propriétaire")} : « ${latest.answer} »` : "";
      const which = latest.seasons.length === requestable(s).length && latest.seasons.length > 1 ? say("Whole series", "Toute la série") : seasonsText(latest.seasons).replace(/^./, c => c.toUpperCase());
      line.append(element("span", label, `media-poster-badge ${tone}`), element("span", latest.state === "pending" ? `${which} · ${say(`asked ${mediaAge(latest.created)}`, `demandé ${mediaAge(latest.created)}`)}${latest.follow ? ` · ${say("following", "suivie")}` : ""}.` : `${which}${said ? ` · ${said}` : ""}`));
      copy.append(line);
    }
    if (asked) {
      if (asked.state === "pending" && asked.shared_with) copy.append(element("p", say(`Asked together with ${asked.shared_with} other member${asked.shared_with > 1 ? "s" : ""}.`, `Demandé avec ${asked.shared_with} autre${asked.shared_with > 1 ? "s" : ""} membre${asked.shared_with > 1 ? "s" : ""} : une seule demande par saison, votre part du quota est réduite.`), "media-quota"));
      if (asked.state === "pending") actions.append(button(say("Cancel the Request", "Annuler la demande"), () => requestCancel(asked), "media-secondary"));
    }
    if (requestPermission("request")) {
      const left = requestable(s);
      const more = asked ? left.filter(n => !asked.seasons.includes(n)) : left;
      if (!asked) copy.append(requestQuotaLine(preselect(s, left).size));
      if (more.length || (s.airing && !asked)) {
        const ask = button(asked ? say("Ask for other seasons", "Demander d'autres saisons") : say("Ask the owner", "Demander au propriétaire"), () => askSheet(s), "media-primary");
        actions.prepend(ask);
      }
    }
    copy.append(actions);
  }
  function askSheet(s) {
    const dialog = $("media-wish"), form = element("form", undefined, "ts-sheet-form");
    dialog.classList.add("ts-sheet"); dialog.onclose = () => dialog.classList.remove("ts-sheet");
    form.method = "dialog";
    const asked = askedOf(s), all = requestable(s).filter(n => !asked?.seasons.includes(n)), picked = new Set(), checks = new Map();
    const title = element("h2", s.title); title.append(preview());
    form.append(title, element("p", say("Tick the seasons you want. The owner picks the releases.", "Cochez les saisons voulues. Le propriétaire choisit les releases."), "media-row-note"));
    const whole = element("input"); whole.type = "checkbox";
    const wholeLabel = element("label", undefined, "ts-check ts-whole"); wholeLabel.append(whole, element("strong", say("Whole series", "Toute la série")), element("span", all.length ? say(`${all.length} season${all.length > 1 ? "s" : ""} available`, `${all.length} saison${all.length > 1 ? "s" : ""} disponible${all.length > 1 ? "s" : ""}`) : "", "ts-count"));
    whole.disabled = all.length < 1;
    form.append(wholeLabel);
    const list = element("ul", undefined, "ts-sheet-seasons");
    for (const season of s.seasons) {
      const line = element("li"), label = element("label", undefined, "ts-check"), box = element("input"); box.type = "checkbox";
      const can = all.includes(season.n), status = statusOf(s, season);
      box.disabled = !can; checks.set(season.n, box);
      const note = s.owned.includes(season.n) ? say("In the Library", "Dans la médiathèque")
        : asked?.seasons.includes(season.n) ? say("Already requested", "Déjà demandée")
          : season.state === "episodes" ? say("Episodes only, no pack", "Épisodes seulement, pas de pack") : kindOf(s, season)[0];
      label.append(box, element("strong", say(`Season ${season.n}`, `Saison ${season.n}`)), element("span", say(`${season.count} episodes`, `${season.count} épisodes`), "ts-count"), element("span", note, `ts-pill ${can ? "ok" : status ? status[1] : "eps"}`));
      if (!can) label.classList.add("off");
      box.onchange = () => { box.checked ? picked.add(season.n) : picked.delete(season.n); sync(); };
      line.append(label); list.append(line);
    }
    form.append(list);
    let follow = null;
    if (s.airing) {
      follow = element("input"); follow.type = "checkbox"; follow.checked = false;
      const label = element("label", undefined, "ts-check ts-follow"), copy = element("span");
      copy.append(element("strong", say("Follow the series", "Suivre la série")), element("small", say("Each new complete season pack on the tracker creates a pending Request for the owner, never an automatic download. You are notified.", "Chaque nouvelle saison complète publiée sur le tracker crée une demande en attente pour le propriétaire, jamais un téléchargement automatique. Vous êtes prévenu."), "ts-note"));
      label.append(follow, copy); form.append(label);
      follow.onchange = sync;
    }
    const quota = element("div", undefined, "ts-quota"), actions = element("div", undefined, "media-feature-actions");
    const send = element("button", say("Send the Request", "Envoyer la demande"), "media-primary"); send.type = "submit";
    actions.append(send, button(say("Cancel", "Annuler"), () => dialog.close(), "media-secondary"));
    form.append(quota, actions);
    whole.onchange = () => { for (const n of all) { checks.get(n).checked = whole.checked; whole.checked ? picked.add(n) : picked.delete(n); } sync(); };
    function sync() {
      const chosen = [...picked].sort((a, b) => a - b), quote = chosen.length ? preselect(s, chosen).size : 0;
      whole.checked = all.length > 0 && chosen.length === all.length;
      const blocked = requestBlocked(quote);
      quota.replaceChildren(requestQuotaLine(quote));
      if (chosen.length) quota.append(element("p", say(`This Request counts ${requestSize(quote)} of your quota, the packs the owner would pre-select. A bigger choice costs you nothing more.`, `Cette demande compte ${requestSize(quote)} sur votre quota, d'après les packs que le propriétaire pré-sélectionnerait. Un choix plus lourd ne vous coûte rien de plus.`), "ts-note"));
      send.disabled = !!blocked || (!chosen.length && !follow?.checked);
      send.title = blocked;
    }
    sync();
    form.onsubmit = event => {
      event.preventDefault();
      guard(async () => {
        const chosen = [...picked].sort((a, b) => a - b), pre = preselect(s, chosen);
        await api("requests", {film: s.id, seasons: chosen, follow: !!follow?.checked, quote: pre.size, pre: pre.hashes});
        dialog.close(); toast(say(`Request sent for ${s.title}`, `Demande envoyée pour ${s.title}`));
        await requestsLoad(); mediaRenderFeature(); mediaRenderHome(); await mediaRenderEpisodes(media.selected);
      });
    };
    dialog.replaceChildren(form); dialog.showModal();
  }
  // The Request drawer says which seasons, as the real drawer shows the title.
  const originalDrawer = requestsDrawer;
  requestsDrawer = function () {
    originalDrawer();
    const mine = requests.rows.filter(row => row.series);
    [...$("media-requests").querySelectorAll(".media-request small")].forEach((small, i) => {
      const row = requests.rows[i];
      if (row?.series) small.textContent = `${seasonsText(row.seasons).replace(/^./, c => c.toUpperCase())}${row.follow ? ` · ${say("following", "suivie")}` : ""} · ${small.textContent}`;
    });
    return mine;
  };

  // ---- shortcuts for the preview bar --------------------------------------------------
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  TS.go = async (view = "series") => {
    media.kind = "video"; media.gridMode = false; media.films = null; media.ratingsPage = false; TS.scope = null;
    for (const key of ["genre", "year", "language", "availability"]) $(`media-${key}`).value = "";
    $("media-search").value = "";
    media.view = view; mediaViews(); $("media-view").value = view; await loadMedia(); await wait(400);
    window.scrollTo(0, 0); document.querySelector(".media-scroll").scrollTop = 0;
  };
  TS.seeAll = async (view = "series") => { await TS.go(view); await filmsOpenLanding(); };
  TS.grid = async (genre, view = "series") => { await TS.go(view); TS.scope = view; await filmsOpenLanding(); await filmsOpenGrid({genre}); };
  TS.panel = async (id, view = "series") => {
    await TS.go(view);
    const row = TS.series.find(x => x.id === id) && rowOf(TS.by.get(id));
    const card = document.querySelector(`#media-home-rows .media-row-card[data-id="film-${id}"]`);
    if (!card) return false;
    card.click(); await wait(300);
    card.scrollIntoView({block: "nearest", inline: "center"});
    return !!row;
  };
  TS.seasons = async n => { const s = TS.by.get(media.selected?.film); if (s) { open.add(`${s.id}:${n}`); seasonsList($("media-episodes"), s); } };
  TS.sheet = () => { const s = TS.by.get(media.selected?.film); if (s) askSheet(s); };
  TS.state = () => ({role: TS.role, view: media.view, scope: TS.scope, selected: media.selected?.film || "", rows: media.rows.length, home: media.homeRows.map(r => `${r.key}:${r.total}`)});
})();
