"use strict";
/* Tracker Series (ADR-0030, #215): the series the Trackers hold, in the Séries and Anime tabs.
   A "Sur le tracker" row and its "Tout voir" page reuse the Tracker Films ones, fed by the series
   routes; a series' banner gets its seasons and episodes. A Member never sees a release.
   Loaded before view.js, so the transport is wrapped before the first request. */
(() => {
  const TS = {scope: null, by: new Map(), picked: null, loading: new Set()};
  window.TSeries = TS;
  const inScope = () => TS.scope || (["series", "anime"].includes(media.view) ? media.view : null);
  const owner = () => state.setup?.owner !== false;
  const asRow = item => ({...item, film: item.tseries});
  const scoped = (path, scope) => path.replace(/^media\/tracker-films/, "media/tracker-series").replace(/\?/, `?scope=${scope}&`);

  // ---- the transport: series come from their own routes, everything else goes on as before ----
  async function mine(request, path, options) {
    const [name, query = ""] = path.split("?"), params = new URLSearchParams(query);
    if (name === "media/home" && ["series", "anime"].includes(params.get("scope")) && params.get("include") === "tracker") {
      let landing;
      try { landing = await request(`media/tracker-series/landing?client_id=${encodeURIComponent(params.get("client_id") || "")}&scope=${params.get("scope")}`, {}); } catch { return {rows: []}; }
      const first = landing.rows.find(row => row.key === "tracker");
      return {rows: first ? [{...first, rows: first.rows.map(asRow), filters: {tracker: "films"}, state: "ready", reason: ""}] : []};
    }
    const scope = inScope();
    if (!scope) return null;
    if (name === "media/tracker-films/landing") {
      const landing = await request(scoped(`${name}?${query}`, scope), options);
      return {rows: landing.rows.map(row => ({...row, rows: row.rows.map(asRow), filters: {...row.filters, tracker: "films"}}))};
    }
    if (name === "media/tracker-films") {
      const page = await request(scoped(`${name}?${query}`, scope), options);
      return {...page, rows: page.rows.map(asRow)};
    }
    if (name === "media/tracker-films/revision") return {revision: 1, running: false, identified: 1, total: 1};
    if (name === "media/tracker-films/focus") return {};
    return null;
  }
  const connect = TLPanel.connect;
  TLPanel.connect = (name, extra) => connect(name, extra).then(request => name === "media" ? async (path, options) => (await mine(request, path, options || {})) ?? request(path, options) : request);

  // ---- navigation: the Séries tab, its Tout voir page, back ----------------------------------
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
    title.textContent = scope === "anime" ? say("Anime on the tracker", "Animés sur le tracker") : say("Series on the tracker", "Séries sur le tracker");
    count.textContent = say("one row per genre", "une rangée par genre");
  };
  const originalShelf = filmsShelf;
  filmsShelf = function () {
    originalShelf();
    if (!TS.scope) return;
    const label = document.querySelector(".films-bar .films-label");
    if (label) label.textContent = TS.scope === "anime" ? say("Anime on the tracker ·", "Animés sur le tracker ·") : say("Series on the tracker ·", "Séries sur le tracker ·");
    const count = document.querySelector(".films-bar .media-home-row-count");
    if (count) count.textContent = count.textContent.replace(/film/, say("series", "série"));
  };
  new MutationObserver(() => {
    if (!TS.scope) return;
    for (const count of document.querySelectorAll(".films-bar .media-home-row-count")) if (/film/.test(count.textContent)) count.textContent = count.textContent.replace(/film/, say("series", "série"));
  }).observe(document.documentElement, {childList: true, subtree: true, characterData: true});
  // A card: its seasons beside the year, once the panel has told how many.
  const originalBadge = filmsBadge;
  filmsBadge = function (row, art) {
    originalBadge(row, art);
    if (row.tseries && owner() && !row.in_library && row.owned_seasons?.length) art.append(element("span", say("Partly in the Library", "En partie en bibliothèque"), "media-poster-badge wait"));
  };

  // ---- the series' banner and its seasons ----------------------------------------------
  const ranges = list => {
    const out = [];
    for (const n of [...list].sort((a, b) => a - b)) {
      if (out.length && out[out.length - 1][1] === n - 1) out[out.length - 1][1] = n; else out.push([n, n]);
    }
    return out.map(([a, b]) => a === b ? String(a) : `${a}–${b}`).join(", ");
  };
  const seasonsText = list => list.length === 1 ? say(`season ${list[0]}`, `saison ${list[0]}`) : say(`seasons ${ranges(list)}`, `saisons ${ranges(list)}`);
  TS.ranges = ranges; TS.seasonsText = seasonsText;
  async function panel(row) {
    if (TS.by.has(row.tseries)) return TS.by.get(row.tseries);
    if (TS.loading.has(row.tseries)) return null;
    TS.loading.add(row.tseries);
    try {
      const found = await api(`media/tracker-series/${encodeURIComponent(row.tseries)}?${mediaQuery({})}`);
      TS.by.set(row.tseries, found);
      return found;
    } catch (error) { TS.loading.delete(row.tseries); throw error; }
  }
  TS.panel = panel;
  TS.forget = id => { TS.by.delete(id); TS.loading.delete(id); };
  const originalFeature = filmsFeature;
  filmsFeature = function (row, content, description, actions) {
    if (!row.tseries) return originalFeature(row, content, description, actions);
    for (const tag of content.querySelectorAll(".media-feature-tag")) if (/Version|Poids|File size/.test(tag.textContent)) tag.remove();
    const title = content.querySelector("h2"), s = TS.by.get(row.tseries);
    if (!s) {
      panel(row).then(found => { if (found && media.featureId === row.id) mediaRenderFeature(); }).catch(() => {});
      return;
    }
    content.querySelector(".media-feature-meta")?.append(` · ${s.seasons.length} ${say("seasons", "saisons")}${s.status ? ` · ${/ended|canceled/i.test(s.status) ? say("ended", "terminée") : say("airing", "en cours")}` : ""}`);
    if (owner()) {
      const owned = s.seasons.filter(x => x.owned).map(x => x.n);
      if (s.in_library) title.append(element("span", say("In the Library", "Dans la bibliothèque"), "media-poster-badge films-inline"));
      else if (owned.length) title.append(element("span", say(`${seasonsText(owned)} in the Library`, `${seasonsText(owned).replace(/^./, c => c.toUpperCase())} dans la médiathèque`), "media-poster-badge films-inline"));
    }
    if (typeof TS.actions === "function") TS.actions(s, description, actions);
  };
  const originalEpisodes = mediaRenderEpisodes;
  mediaRenderEpisodes = async function (row) {
    if (!row?.tseries) return originalEpisodes(row);
    const root = $("media-episodes");
    // The seasons open under the banner for a series the viewer picked, not for the one shown by default.
    if (TS.picked !== row.id) { root.hidden = true; root.replaceChildren(); root.classList.remove("ts-seasons-box"); return; }
    const s = await panel(row).catch(() => null);
    if (!s || media.featureId !== row.id) return;
    root.hidden = false; root.dataset.owner = row.id; root.classList.add("ts-seasons-box");
    seasonsList(root, s);
  };
  const originalSelect = mediaSelectFeature;
  mediaSelectFeature = function (row) {
    TS.picked = row.tseries ? row.id : null;
    if (!row.tseries) $("media-episodes").classList.remove("ts-seasons-box");
    return originalSelect(row);
  };

  const open = new Set();  // "id:n" of the seasons unfolded
  TS.open = open;
  const kindOf = season => season.state === "pack" ? [say("Full pack", "Pack complet"), "ok"]
    : season.state === "complete" ? [say("Covered by the Intégrale", "Couvert par l'Intégrale"), "integ"]
      : [say(`Episodes only (${season.episodes.filter(e => e.on_tracker).length}/${season.count})`, `Épisodes seulement (${season.episodes.filter(e => e.on_tracker).length}/${season.count})`), "eps"];
  TS.kindOf = kindOf;
  function seasonsList(root, s) {
    root.replaceChildren();
    const episodes = s.seasons.reduce((a, x) => a + x.count, 0), header = element("div", undefined, "media-episodes-header ts-head");
    header.append(element("h2", say("Seasons", "Saisons")), element("span", say(`${s.seasons.length} seasons · ${episodes} episodes`, `${s.seasons.length} saisons · ${episodes} épisodes`), "media-row-note"));
    root.append(header);
    if (typeof TS.beforeSeasons === "function") TS.beforeSeasons(root, s);
    const list = element("ul", undefined, "ts-seasons");
    for (const season of s.seasons) list.append(seasonItem(s, season));
    root.append(list);
  }
  TS.seasonsList = seasonsList;
  function seasonItem(s, season) {
    const key = `${s.tseries}:${season.n}`, item = element("li", undefined, "ts-season");
    const head = element("div", undefined, "ts-season-head");
    const toggle = button("", () => { open.has(key) ? open.delete(key) : open.add(key); seasonsList($("media-episodes"), s); }, "ts-toggle");
    toggle.setAttribute("aria-expanded", String(open.has(key)));
    toggle.append(element("span", open.has(key) ? "▾" : "▸", "ts-caret"), element("strong", say(`Season ${season.n}`, `Saison ${season.n}`)), element("span", say(`${season.count} episodes`, `${season.count} épisodes`), "ts-count"));
    const [kind, tone] = kindOf(season), pills = element("span", undefined, "ts-pills");
    if (season.state !== "none") pills.append(element("span", kind, `ts-pill ${tone}`));
    if (season.owned) pills.append(element("span", say("In the Library", "Dans la médiathèque"), "ts-pill own"));
    else if (typeof TS.status === "function") { const extra = TS.status(s, season); if (extra) pills.append(element("span", extra[0], `ts-pill ${extra[1]}`)); }
    head.append(toggle, pills);
    if (typeof TS.seasonActions === "function") TS.seasonActions(s, season, head);
    item.append(head);
    if (open.has(key)) item.append(seasonBody(s, season));
    return item;
  }
  function seasonBody(s, season) {
    const body = element("div", undefined, "ts-season-body");
    if (season.state === "episodes" && !owner()) body.append(element("p", say("No full pack yet: the tracker has some episodes only.", "Pas encore de pack complet : le tracker n'a que certains épisodes."), "media-row-note"));
    if (typeof TS.seasonReleases === "function") TS.seasonReleases(s, season, body);
    const list = element("ol", undefined, "ts-episodes");
    for (const ep of season.episodes) {
      const line = element("li", undefined, "ts-episode"), text = element("div");
      text.append(element("strong", `${ep.n}. ${ep.title}`), element("p", ep.overview || ""));
      line.append(text, element("span", ep.on_tracker ? say("On the tracker", "Sur le tracker") : say("Not on the tracker", "Pas sur le tracker"), `ts-pill ${ep.on_tracker ? "ok" : "eps"}`));
      if (typeof TS.episodeActions === "function") TS.episodeActions(s, season, ep, line);
      list.append(line);
    }
    body.append(list);
    return body;
  }
})();
