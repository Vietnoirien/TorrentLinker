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
    if (name === "media/tracker-films/revision") return request(scoped(`media/tracker-series/revision?${query}`, scope), options);
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


  // ---- the Member: where a series stands, the request sheet (#216) ---------------------------
  const asking = s => (typeof requests === "undefined" ? [] : requests.rows).filter(r => r.film?.startsWith(`${s.tseries}:`) && !["refused", "cancelled", "expired"].includes(r.state));
  const seasonOfAsk = r => Number(r.film.split(":")[1]);
  TS.status = (s, season) => {
    if (owner()) return null;
    return asking(s).some(r => seasonOfAsk(r) === season.n) ? [say("Requested", "Demandée"), "asked"] : null;
  };
  TS.actions = (s, copy, actions) => {
    if (owner()) return;
    const mine = asking(s), seasons = mine.map(seasonOfAsk).sort((a, b) => a - b);
    if (mine.length) {
      const first = mine[0], [label, tone] = requestState(first), line = element("div", undefined, "media-request-state");
      const said = first.answer ? `${first.answered_by || say("The owner", "Le propriétaire")} : « ${first.answer} »` : "";
      line.append(element("span", label, `media-poster-badge ${tone}`), element("span", `${seasonsText(seasons).replace(/^./, c => c.toUpperCase())} · ${first.state === "pending" ? say(`asked ${mediaAge(first.created)}`, `demandé ${mediaAge(first.created)}`) : ""}${said ? ` · ${said}` : ""}`, "media-quota"));
      copy.append(line);
      const waiting = mine.filter(r => r.state === "pending");
      if (waiting.length) actions.append(button(say("Cancel the Request", "Annuler la demande"), async () => { for (const r of waiting) await requestCancel(r); await requestsLoad(); mediaRenderFeature(); }, "media-secondary"));
    }
    const following = requests.following.includes(s.tseries);
    if (following) {
      copy.append(element("p", say("You follow this series: each new complete season pack creates a pending Request for the owner, never an automatic download.", "Vous suivez cette série : chaque nouveau pack de saison complet crée une demande en attente pour le propriétaire, jamais un téléchargement automatique."), "media-quota"));
      actions.append(button(say("Stop following", "Ne plus suivre"), async () => { await api("requests/series/follow", {client_id: mediaClient(), series: s.tseries, on: false}); await requestsLoad(); mediaRenderFeature(); }, "media-secondary"));
    }
    if (requestPermission("request")) {
      const left = s.seasons.filter(x => x.askable && !seasons.includes(x.n));
      if (left.length || (airing(s) && !following)) actions.prepend(button(mine.length ? say("Ask for other seasons", "Demander d'autres saisons") : say("Ask the owner", "Demander au propriétaire"), () => askSheet(s), "media-primary"));
      else if (!mine.length) copy.append(element("p", say("No season can be asked for yet.", "Aucune saison ne peut être demandée pour l'instant."), "media-quota"));
    }
    copy.append(actions);
  };
  const airing = s => !!s.status && !/ended|canceled/i.test(s.status);
  async function quoteOf(s, seasons) {
    if (!seasons.length) return {size: 0, integrale: false};
    return api(`media/tracker-series/${encodeURIComponent(s.tseries)}/quote`, {client_id: mediaClient(), seasons});
  }
  function askSheet(s) {
    const dialog = $("media-wish"), form = element("form", undefined, "ts-sheet-form");
    dialog.classList.add("ts-sheet"); dialog.onclose = () => dialog.classList.remove("ts-sheet");
    form.method = "dialog";
    const asked = asking(s).map(seasonOfAsk), all = s.seasons.filter(x => x.askable && !asked.includes(x.n)).map(x => x.n), picked = new Set(), checks = new Map();
    form.append(element("h2", s.title), element("p", say("Tick the seasons you want. The owner picks the releases.", "Cochez les saisons voulues. Le propriétaire choisit les releases."), "media-row-note"));
    const whole = element("input"); whole.type = "checkbox"; whole.disabled = all.length < 1;
    const wholeLabel = element("label", undefined, "ts-check ts-whole");
    wholeLabel.append(whole, element("strong", say("Whole series", "Toute la série")), element("span", say(`${all.length} season${all.length > 1 ? "s" : ""} available`, `${all.length} saison${all.length > 1 ? "s" : ""} disponible${all.length > 1 ? "s" : ""}`), "ts-count"));
    form.append(wholeLabel);
    const list = element("ul", undefined, "ts-sheet-seasons");
    for (const season of s.seasons) {
      const line = element("li"), label = element("label", undefined, "ts-check"), box = element("input"); box.type = "checkbox";
      const can = all.includes(season.n);
      box.disabled = !can; checks.set(season.n, box);
      const note = season.owned ? say("In the Library", "Dans la médiathèque") : asked.includes(season.n) ? say("Already requested", "Déjà demandée")
        : season.state === "episodes" ? say("Episodes only, no pack", "Épisodes seulement, pas de pack") : season.state === "none" ? say("Not on the tracker", "Pas sur le tracker") : kindOf(season)[0];
      label.append(box, element("strong", say(`Season ${season.n}`, `Saison ${season.n}`)), element("span", say(`${season.count} episodes`, `${season.count} épisodes`), "ts-count"), element("span", note, `ts-pill ${can ? "ok" : season.owned ? "own" : asked.includes(season.n) ? "asked" : "eps"}`));
      if (!can) label.classList.add("off");
      box.onchange = () => { box.checked ? picked.add(season.n) : picked.delete(season.n); sync(); };
      line.append(label); list.append(line);
    }
    form.append(list);
    let follow = null;
    if (airing(s) && !requests.following.includes(s.tseries)) {
      follow = element("input"); follow.type = "checkbox";
      const label = element("label", undefined, "ts-check ts-follow"), copy = element("span");
      copy.append(element("strong", say("Follow the series", "Suivre la série")), element("small", say("Each new complete season pack on the tracker creates a pending Request for the owner, never an automatic download. You are notified.", "Chaque nouveau pack de saison complet sur le tracker crée une demande en attente pour le propriétaire, jamais un téléchargement automatique. Vous êtes prévenu."), "ts-note"));
      label.append(follow, copy); form.append(label);
      follow.onchange = () => sync();
    }
    const quota = element("div", undefined, "ts-quota"), actions = element("div", undefined, "media-feature-actions");
    const send = element("button", say("Send the Request", "Envoyer la demande"), "media-primary"); send.type = "submit";
    actions.append(send, button(say("Cancel", "Annuler"), () => dialog.close(), "media-secondary"));
    form.append(quota, actions);
    whole.onchange = () => { for (const n of all) { checks.get(n).checked = whole.checked; whole.checked ? picked.add(n) : picked.delete(n); } sync(); };
    let version = 0;
    async function sync() {
      const mine = ++version, chosen = [...picked].sort((a, b) => a - b);
      whole.checked = all.length > 0 && chosen.length === all.length;
      send.disabled = !chosen.length && !follow?.checked;
      let quote = {size: 0};
      try { quote = await quoteOf(s, chosen); } catch { /* the server checks again */ }
      if (mine !== version) return;
      const blocked = requestBlocked(quote.size);
      quota.replaceChildren(requestQuotaLine(quote.size));
      if (chosen.length) quota.append(element("p", say(`This Request counts ${requestSize(quote.size)} of your quota, the packs the owner would pre-select. A bigger choice costs you nothing more.`, `Cette demande compte ${requestSize(quote.size)} sur votre quota, d'après les packs que le propriétaire aurait pré-sélectionnés. Un choix plus gros ne vous coûte rien de plus.`), "ts-note"));
      send.disabled = !!blocked || (!chosen.length && !follow?.checked); send.title = blocked;
    }
    sync();
    form.onsubmit = event => {
      event.preventDefault();
      guard(async () => {
        await api("requests/series", {client_id: mediaClient(), series: s.tseries, seasons: [...picked].sort((a, b) => a - b), follow: !!follow?.checked});
        dialog.close(); toast(say(`Request sent for ${s.title}`, `Demande envoyée pour ${s.title}`));
        await requestsLoad(); mediaRenderFeature(); mediaRenderHome(); await mediaRenderEpisodes(media.selected);
      });
    };
    dialog.replaceChildren(form); dialog.showModal();
  }

  // ---- the Owner: every release of a season, and one episode on its own (#219) ----------------
  const better = (a, b) => (b.score ?? 0) - (a.score ?? 0) || b.seeders - a.seeders;
  const releasesOf = (season, kind) => (season.releases || []).filter(r => r.kind === kind).sort(better);
  const download = (release, control) => guard(() => filmsDownload(release, control));
  TS.seasonActions = (s, season, head) => {
    if (!owner()) return;
    const best = releasesOf(season, "season")[0];
    if (best) { const get = button(say("Download", "Télécharger"), () => download(best, get), "media-secondary ts-get"); head.append(get); }
  };
  TS.seasonReleases = (s, season, body) => {
    if (!owner() || !(season.releases || []).length) return;
    const box = element("div", undefined, "ts-releases");
    const packs = releasesOf(season, "season");
    for (const release of [...packs, ...releasesOf(season, "integrale")]) {
      const line = mediaTrackerRelease({...release, published_at: null});
      if (release === packs[0]) line.prepend(element("span", say("Pre-selected", "Pré-sélection"), "media-poster-badge films-inline"));
      if (release.kind === "integrale") line.prepend(element("span", "Intégrale", "ts-pill integ"));
      const get = button(say("Download", "Télécharger"), () => download(release, get), "media-secondary ts-get"); line.append(get);
      box.append(line);
    }
    if (box.childElementCount) body.append(box);
  };
  TS.episodeActions = (s, season, ep, line) => {
    if (!owner() || !ep.on_tracker) return;
    const release = releasesOf(season, "episode").find(r => r.episode === ep.n);
    if (!release) return;
    const get = button(say("Download", "Télécharger"), () => download(release, get), "media-secondary ts-get"); line.append(get);
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
