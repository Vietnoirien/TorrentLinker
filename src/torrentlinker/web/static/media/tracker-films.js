"use strict";
/* Tracker Films (docs/specs/members-tracker-films, preview variant B): every seeded film on the
   Trackers as one poster per film, under "On the tracker". Its landing is one row per genre
   after "New" and "Most shared"; a grid always shows one genre (two with "Narrow with…"),
   paged from the server as it scrolls. A film's panel is the pinned banner: a Member reads the
   synopsis and asks, never seeing a release; the Owner sees the pre-selected release, every
   grouped release in the details dialog, and can correct the film.
   The index fills while the user looks (decision 25): the panel polls the index's revision
   and merges what changed into what is drawn, and tells the server which unidentified films
   are on screen so they are identified first. The server decides who sees what; hiding is
   only presentation. */
const filmsOwner = () => state.setup?.owner !== false;
const filmsAllowed = () => filmsOwner() || (state.setup?.permissions || []).includes("films");
const filmsSorts = () => [["new", say("New on the tracker", "Nouveautés")], ["shared", say("Most shared", "Les plus partagés")], ["year", say("Year", "Année")], ["title", say("Title", "Titre")]];
const filmsCount = total => say(`${total.toLocaleString("en-GB")} film${total === 1 ? "" : "s"}`, `${total.toLocaleString("fr-FR")} film${total === 1 ? "" : "s"}`);
// One page of a genre's grid (also what a Horizon row asks for to grow).
function filmsPage(filters, offset, limit) {
  const query = new URLSearchParams({client_id: mediaClient(), offset, limit, sort: filters.sort || "new", q: $("media-search").value.trim()});
  for (const genre of filters.genres || (filters.genre ? [filters.genre] : [])) query.append("genre", genre);
  return api(`media/tracker-films?${query}`);
}
async function filmsLoad(append = false) {
  const version = ++media.request;
  media.films ||= {genres: [], sort: "new", grid: false};
  const films = media.films, searching = !!$("media-search").value.trim();
  // Searching looks across every genre; clearing the search returns to the landing.
  if (searching) films.grid = true;
  else if (films.grid && !films.genres.length) films.grid = false;
  $("media-more").hidden = true;
  if (!films.grid) {
    const landing = await api(`media/tracker-films/landing?${mediaQuery({})}`);
    if (version !== media.request) return;
    media.homeRows = landing.rows; media.rows = []; media.continueRows = []; media.next = null; films.total = 0;
    for (const row of landing.rows.flatMap(r => r.rows)) mediaItems.set(row.id, row);
    mediaStatus("");
  } else {
    const page = await filmsPage(films, append ? media.next || 0 : 0, 60);
    if (version !== media.request) return;
    for (const row of page.rows) mediaItems.set(row.id, row);
    media.homeRows = []; media.continueRows = [];
    media.rows = append ? [...media.rows, ...page.rows] : page.rows;
    media.next = page.has_more ? page.next_offset : null;
    films.total = page.total; films.allGenres = page.filters?.genres || films.allGenres;
    $("media-more").hidden = !page.has_more;
    mediaStatus("");
  }
  const scroller = document.querySelector(".media-scroll"), savedScroll = window.scrollY, savedInner = scroller.scrollTop;
  mediaRender();
  window.scrollTo(0, savedScroll); scroller.scrollTop = savedInner;
}
async function filmsOpenLanding() {
  media.gridMode = false; media.films = {genres: [], sort: "new", grid: false}; media.view = "tracker";
  $("media-search").value = "";
  mediaViews(); await loadMedia();
  window.scrollTo({top: 0}); document.querySelector(".media-scroll").scrollTop = 0;
}
async function filmsOpenGrid(filters) {
  media.films = {genres: filters.genre ? [filters.genre] : [], sort: filters.sort || "new", grid: true};
  await loadMedia();
  window.scrollTo({top: 0}); document.querySelector(".media-scroll").scrollTop = 0;
}
const filmsLeave = () => guard(async () => { media.films = null; media.view = "recent"; $("media-view").value = "recent"; mediaViews(); await loadMedia(); });
// "See all" opens the landing from Médias' row, and a genre's grid from the landing. New and
// "Most shared" have none: a grid of every genre puts horror beside kids' animation.
function filmsRowActions(row, header) {
  if (row.key === "tracker") header.append(button(say("See all", "Tout voir"), () => guard(filmsOpenLanding), "quiet media-see-all"));
  else if (row.key === "genre") header.append(button(say("See all", "Tout voir"), () => guard(() => filmsOpenGrid(row.filters)), "quiet media-see-all"));
}
function filmsLandingHead(root) {
  const head = element("div", undefined, "media-home-row-header films-landing");
  queueMicrotask(filmsProgressLine);
  const total = new Set(media.homeRows.flatMap(row => row.rows.map(item => item.id))).size;
  head.append(button(say("‹ Media", "‹ Médias"), filmsLeave, "quiet"), element("h2", say("On the tracker", "Sur le tracker")), element("span", say("one row per genre", "une rangée par genre"), "media-home-row-count"));
  if (total) root.prepend(head);
}
// The one-genre grid's line, "On the tracker · Animation ▾", its second genre and its sort.
function filmsShelf() {
  queueMicrotask(filmsObserve);  // once the cards of this render are in the page
  document.querySelector(".films-bar")?.remove();
  const heading = document.querySelector(".media-section-heading"), films = media.films;
  heading.hidden = false;
  if (media.view !== "tracker" || media.kind !== "video" || !films?.grid || mediaHomeActive()) return;
  heading.hidden = true;
  const bar = element("div", undefined, "films-bar"); bar.setAttribute("role", "group"); bar.setAttribute("aria-label", say("Tracker films", "Films du tracker"));
  const genres = films.allGenres || [], chosen = films.genres;
  const genre = element("select", undefined, "films-genre"); genre.setAttribute("aria-label", say("Genre", "Genre"));
  if (!chosen.length) genre.append(new Option(say("All genres (search)", "Tous les genres (recherche)"), ""));
  for (const name of genres) genre.append(new Option(name, name));
  if (chosen.length > 1) genre.append(new Option(chosen.join(" + "), "combined"));
  genre.value = chosen.length > 1 ? "combined" : chosen[0] || "";
  genre.onchange = () => { if (genre.value !== "combined") filmsGenres(genre.value ? [genre.value] : []); };
  bar.append(element("span", say("On the tracker ·", "Sur le tracker ·"), "films-label"), genre);
  const narrow = element("select", undefined, "films-narrow"); narrow.setAttribute("aria-label", say("Narrow with a second genre", "Affiner avec un second genre"));
  narrow.append(new Option(chosen.length > 1 ? say("Combined genres", "Genres combinés") : say("Narrow with…", "Affiner avec…"), ""));
  if (chosen.length === 1) for (const name of genres) if (name !== chosen[0]) narrow.append(new Option(`${chosen[0]} + ${name}`, name));
  narrow.disabled = chosen.length !== 1;
  narrow.onchange = () => narrow.value && filmsGenres([...chosen, narrow.value]);
  const sort = element("select", undefined, "films-sort"); sort.setAttribute("aria-label", say("Sort", "Trier"));
  for (const [value, label] of filmsSorts()) sort.append(new Option(label, value));
  sort.value = films.sort; sort.onchange = () => { films.sort = sort.value; guard(loadMedia); };
  bar.append(narrow, sort, element("span", filmsCount(films.total || 0), "media-home-row-count"));
  if (chosen.length) bar.prepend(button(say("‹ Genres", "‹ Genres"), () => guard(filmsOpenLanding), "quiet"));
  $("media-results").before(bar);
}
function filmsGenres(genres) { media.films.genres = genres; media.films.grid = true; guard(loadMedia); }
// A poster's badge: the Owner sees what is in the Library or not yet identified; a Member the
// state of their own Request.
function filmsBadge(row, art) {
  if (filmsOwner() && row.in_library) art.append(element("span", say("In the Library", "Dans la bibliothèque"), "media-poster-badge"));
  else if (filmsOwner() && row.identified === false) art.append(element("span", say("Not identified", "Non identifié"), "media-poster-badge wait"));
  else if (typeof mediaRequestBadge === "function") mediaRequestBadge(row, art);
}
// A grid card opens the pinned banner; its badge is the film's, its one action "View".
function filmsDecorate(row, artwork, actions) {
  artwork.querySelector(".media-poster-badge")?.remove();
  filmsBadge(row, artwork.querySelector(".media-art") || artwork);
  actions.replaceChildren(button(say("View", "Voir la fiche"), () => filmsShow(row)));
}
// The banner is pinned: choosing a film fills it where it is, and the page does not move.
function filmsShow(row) {
  const scroller = document.querySelector(".media-scroll"), top = scroller.scrollTop, page = window.scrollY;
  mediaSelectFeature(row);
  scroller.scrollTop = top; window.scrollTo(0, page);
}
// The film's panel, after the synopsis and tags the banner already drew.
function filmsFeature(row, content, description, actions) {
  if (!filmsOwner()) { (state.setup?.viewer ? householdActions : mediaRequestActions)(row, description, actions); return; }
  if (row.in_library) content.querySelector("h2").append(element("span", say("In the Library", "Dans la bibliothèque"), "media-poster-badge films-inline"));
  if (row.tracker) {
    const chosen = mediaTrackerRelease(row.tracker);
    chosen.prepend(element("span", say("Pre-selected", "Pré-sélection"), "media-poster-badge films-inline"));
    description.append(chosen);
  }
  if (row.below_threshold) description.append(element("p", say("Below the threshold: no release reaches your ReleaseScore profile. The best is pre-selected.", "Sous le seuil : aucune release n’atteint votre profil ReleaseScore. La meilleure est pré-sélectionnée."), "media-quota full"));
  if (row.tracker) {
    const queue = button(say("Download", "Télécharger"), () => guard(() => filmsDownload(row.tracker, queue)), "media-primary");
    actions.append(queue);
  }
  actions.append(
    button(say(`Releases (${row.release_count || 0})`, `Releases (${row.release_count || 0})`), () => guard(() => filmsReleases(row)), "media-secondary"),
    button(say("Fix the film", "Corriger le film"), () => filmsRematch(row), "media-secondary"),
  );
}
async function filmsDownload(release, control) {
  control.disabled = true;
  try {
    await api(`media/tracker/${encodeURIComponent(release.hash)}/download`, {});
    toast(say(`Sending ${release.name} to the client.`, `Envoi de ${release.name} au client.`));
  } finally { control.disabled = false; }
}
// Every grouped release (all Trackers) in Médias' details dialog, the pre-selected one first.
async function filmsReleases(row) {
  const film = await api(`media/tracker-films/${encodeURIComponent(row.film)}?${mediaQuery({})}`);
  const root = $("media-details"); root.replaceChildren(); root.hidden = false;
  if (!root.open) root.showModal();
  root.append(button(say("Close details", "Fermer les détails"), () => root.close()), element("h2", film.title));
  const list = element("div", undefined, "films-releases");
  list.append(element("p", say(`${film.releases.length} releases · the pre-selected one first`, `${film.releases.length} releases · la pré-sélection en premier`), "muted"));
  for (const release of film.releases) {
    const line = element("div", undefined, "films-release"), pill = element("span", String(release.score ?? "?"), `media-score score-${release.color || "green"}`);
    pill.title = "ReleaseScore";
    const facts = [mediaFileSize(release.size), say(`${release.seeders} seeders`, `${release.seeders} sources`), release.tracker, mediaAge(release.published_at)].filter(Boolean).join(" · ");
    const actions = element("span", undefined, "films-release-actions");
    const download = button(say("Download", "Télécharger"), () => guard(() => filmsDownload(release, download)), "media-secondary");
    actions.append(download, button(say("Wrong film", "Mauvais film"), () => filmsRematch(film, release), "quiet"));
    line.append(pill, element("span", release.name, "media-tracker-name"), element("span", facts, "media-tracker-facts"), actions);
    list.append(line);
  }
  root.append(list);
}
// "Fix the film" and "Wrong film": the TMDb film they should be, kept across re-identification.
function filmsRematch(film, release) {
  const root = $("media-details"), form = element("form"), field = element("input");
  root.replaceChildren(); root.hidden = false; if (!root.open) root.showModal();
  field.required = true; field.inputMode = "numeric"; field.placeholder = "https://www.themoviedb.org/movie/…";
  const label = element("label", undefined, "media-wish-field");
  label.append(element("span", release ? say(`Match ${release.name} to another TMDb film: paste its link or number.`, `Associer ${release.name} à un autre film TMDb : collez son lien ou son numéro.`) : say(`Match ${film.title} (${film.year}) to another TMDb film: paste its link or number.`, `Associer ${film.title} (${film.year}) à un autre film TMDb : collez son lien ou son numéro.`)), field);
  const send = element("button", say("Save the correction", "Enregistrer la correction"), "media-primary"); send.type = "submit";
  const actions = element("div", undefined, "media-feature-actions"); actions.append(send, button(say("Cancel", "Annuler"), () => root.close(), "media-secondary"));
  form.append(element("h2", say("Fix the film", "Corriger le film")), label, actions);
  form.onsubmit = event => {
    event.preventDefault();
    const tmdb = (/movie\/(\d+)/.exec(field.value) || /^\s*(\d+)\s*$/.exec(field.value))?.[1];
    if (!tmdb) { toast(say("Give a TMDb film link or number.", "Donnez un lien ou un numéro de film TMDb."), "bad"); return; }
    guard(async () => {
      const path = release ? `media/tracker-films/releases/${encodeURIComponent(release.tracker)}/${release.hash}/rematch` : `media/tracker-films/${encodeURIComponent(film.film || film.id)}/rematch`;
      await api(path, {client_id: mediaClient(), tmdb});
      root.close(); toast(say("Correction saved; it is kept.", "Correction enregistrée ; elle est conservée.")); media.featureId = null; await loadMedia();
    });
  };
  root.append(form); field.focus();
}

/* The index fills while the user looks. Every few seconds, while the tracker row, the landing or
   a grid is on screen, the panel asks for the index's revision; when it moved, it fetches what
   is shown again and merges it: a changed card is replaced where it stands, new films join, and
   nothing else is touched, so the scroll positions and the film chosen in the banner stay. */
const filmsLive = {revision: null, busy: false, progress: null, visible: new Set(), sent: "", observer: null, timer: null};
const filmsHomeRow = () => media.homeRows?.find(row => row.key === "tracker" && row.filters?.tracker === "films");
function filmsWatched() {
  if (state.view !== "media" || document.hidden || media.kind !== "video" || !filmsAllowed()) return false;
  return media.view === "tracker" || (!!filmsHomeRow() && mediaHomeActive());
}
// What a card shows of a film: when it changes, the card is drawn again.
const filmsSig = item => item ? [item.title, item.year, item.identified, item.artwork_url, item.genre, item.age_rating?.rating, item.in_library, item.description].join("\u0001") : "";
// Run `work`, then move the scroller so the first card in view stays where it was.
function filmsKeepPlace(scroller, cards, horizontal, work) {
  const box = scroller.getBoundingClientRect(), edge = horizontal ? box.left : Math.max(0, box.top);
  const anchor = cards.find(card => { const rect = card.getBoundingClientRect(); return (horizontal ? rect.right : rect.bottom) > edge; });
  const before = anchor?.getBoundingClientRect();
  work();
  if (!anchor?.isConnected) return;
  const after = anchor.getBoundingClientRect(), moved = horizontal ? after.left - before.left : after.top - before.top;
  if (!moved) return;
  if (horizontal) scroller.scrollLeft += moved;
  else if (scroller.scrollHeight > scroller.clientHeight) scroller.scrollTop += moved;
  else window.scrollBy(0, moved);
}
// While a page is looked at, its cards keep their order: those still there stay where they are,
// new films join at the end. The index's order (newest, most shared) applies on the next visit.
function filmsSteady(drawn, items) {
  const fresh = new Map(items.map(item => [item.id, item]));
  const kept = drawn.filter(item => fresh.has(item.id)).map(item => fresh.get(item.id));
  const known = new Set(kept.map(item => item.id));
  return [...kept, ...items.filter(item => !known.has(item.id))];
}
// Put `items` in `container` as cards drawn by `draw`, keeping the cards that did not change.
function filmsPatchCards(container, selector, items, previous, draw) {
  const cards = new Map([...container.querySelectorAll(selector)].map(card => [card.dataset.id, card]));
  let cursor = container.querySelector(selector);
  for (const item of items) {
    let card = cards.get(item.id);
    if (card && filmsSig(previous.get(item.id)) !== filmsSig(item)) { const drawn = draw(item); card.replaceWith(drawn); if (cursor === card) cursor = drawn; card = drawn; }
    else if (!card) card = draw(item);
    cards.delete(item.id);
    if (card === cursor) cursor = cursor.nextElementSibling?.matches(selector) ? cursor.nextElementSibling : null;
    else container.insertBefore(card, cursor);
  }
  for (const card of cards.values()) card.remove();
}
function filmsPatchRow(row, fresh, track) {
  const previous = new Map(row.rows.map(item => [item.id, item])), ids = new Set(fresh.rows.map(item => item.id));
  for (const item of fresh.rows) mediaItems.set(item.id, item);
  row.rows = filmsSteady(row.rows, [...fresh.rows, ...row.rows.slice(fresh.rows.length).filter(item => !ids.has(item.id))]);
  row.total = fresh.total;
  filmsKeepPlace(track, [...track.querySelectorAll(".media-row-card")], true, () => filmsPatchCards(track, ".media-row-card", row.rows, previous, item => mediaRowCard(item, row, track)));
  const count = track.closest(".media-home-row")?.querySelector(".media-home-row-count");
  if (count) count.textContent = say(`${row.total} titles`, `${row.total} titres`);
}
function filmsRedraw() {
  const scroller = document.querySelector(".media-scroll"), page = window.scrollY, inner = scroller.scrollTop;
  const lefts = new Map([...document.querySelectorAll("#media-home-rows .media-row-track")].map((track, i) => [i, track.scrollLeft]));
  mediaRender();
  window.scrollTo(0, page); scroller.scrollTop = inner;
  for (const [i, track] of [...document.querySelectorAll("#media-home-rows .media-row-track")].entries()) track.scrollLeft = lefts.get(i) || 0;
}
// Rows (the landing, or Médias' tracker row): patch the cards, or draw again when the rows
// themselves changed (a genre's first film, the first answer after "loading").
function filmsMergeRows(fresh) {
  const shown = media.layout === "horizon" ? [mediaHorizonRow()] : media.homeRows;
  const keys = rows => rows.map(mediaRowKey).join("|");
  if (keys(fresh) !== keys(media.homeRows) || shown.some(row => row.state && row.state !== "ready")) {
    for (const row of fresh) for (const item of row.rows) mediaItems.set(item.id, item);
    media.homeRows = fresh; filmsRedraw(); return;
  }
  const sections = [...document.querySelectorAll("#media-home-rows .media-home-row")];
  for (const [i, row] of shown.entries()) {
    const update = fresh.find(other => mediaRowKey(other) === mediaRowKey(row)), track = sections[i]?.querySelector(".media-row-track");
    if (update && track) filmsPatchRow(row, update, track);
  }
  filmsObserve();
}
function filmsMergeGrid(rows, total, more) {
  const root = $("media-results"), previous = new Map(media.rows.map(item => [item.id, item]));
  rows = filmsSteady(media.rows, rows);
  for (const item of rows) mediaItems.set(item.id, item);
  media.films.total = total; media.rows = rows; media.next = more ? rows.length : null;
  $("media-more").hidden = !more;
  if (!previous.size || !rows.length) { filmsRedraw(); return; }
  filmsKeepPlace(document.querySelector(".media-scroll"), [...root.querySelectorAll(".media-card[data-id]")], false, () => filmsPatchCards(root, ".media-card[data-id]", rows, previous, item => mediaCard([item])));
  const count = document.querySelector(".films-bar .media-home-row-count");
  if (count) count.textContent = filmsCount(total);
  filmsObserve();
}
async function filmsMerge() {
  const version = media.request;
  if (media.view === "tracker" && !media.films?.grid) {
    const landing = await api(`media/tracker-films/landing?${mediaQuery({})}`);
    if (version === media.request && filmsWatched()) filmsMergeRows(landing.rows);
  } else if (media.view === "tracker") {
    const wanted = Math.max(60, media.rows.length), rows = [];
    let page;
    do {
      page = await filmsPage(media.films, rows.length, Math.min(100, wanted - rows.length));
      rows.push(...page.rows);
    } while (page.has_more && rows.length < wanted);
    if (version === media.request && filmsWatched()) filmsMergeGrid(rows, page.total, page.has_more);
  } else {
    const row = filmsHomeRow(), page = await filmsPage({}, 0, Math.max(20, row.rows.length));
    if (version !== media.request || !filmsWatched()) return;
    filmsMergeRows(media.homeRows.map(other => other === row ? {...row, rows: page.rows, total: page.total, state: "ready"} : other));
  }
}
// The Owner's one line on the landing, while the index is being identified.
function filmsProgressLine() {
  const root = $("media-home-rows"), answer = filmsLive.progress;
  const shown = filmsOwner() && media.view === "tracker" && !media.films?.grid && (answer?.running || answer?.resume_at) && answer.identified < answer.total;
  let line = root.querySelector(".films-progress");
  if (!shown) { line?.remove(); return; }
  if (!line) { line = element("p", undefined, "films-progress muted"); root.querySelector(".films-landing")?.after(line); }
  const number = value => value.toLocaleString(language === "fr" ? "fr-FR" : "en-GB");
  const resume = answer.running ? "" : new Date(answer.resume_at * 1000).toLocaleTimeString(language === "fr" ? "fr-FR" : "en-GB", {hour: "2-digit", minute: "2-digit"});
  line.textContent = say(`Film identification: ${number(answer.identified)} / ${number(answer.total)}`, `Identification des films : ${number(answer.identified)} / ${number(answer.total)}`)
    + (resume ? say(` · paused, resumes at ${resume}`, ` · en pause, reprend à ${resume}`) : "");
}
async function filmsPoll() {
  if (filmsLive.busy) return;
  if (!filmsWatched()) { filmsLive.revision = null; return; }
  filmsLive.busy = true;
  try {
    const answer = await api(`media/tracker-films/revision?client_id=${encodeURIComponent(mediaClient())}`);
    filmsLive.progress = answer;
    // What was drawn is as old as the page, and the revision it matches is unknown: the first
    // answer after the view opens merges once, then follows the revision.
    if (filmsLive.revision === null || answer.revision !== filmsLive.revision) await filmsMerge();
    filmsLive.revision = answer.revision;
    filmsProgressLine();
  } catch {
    /* The page shows what it has; the next tick asks again. */
  } finally { filmsLive.busy = false; }
}
// The unidentified films on screen, sent a moment after the last scroll.
function filmsObserve() {
  filmsLive.observer?.disconnect();
  if (!filmsOwner() || !filmsWatched()) return;
  filmsLive.observer ||= new IntersectionObserver(entries => {
    for (const entry of entries) {
      const id = entry.target.dataset.film || mediaItems.get(entry.target.dataset.id)?.film;
      if (entry.isIntersecting) filmsLive.visible.add(id); else filmsLive.visible.delete(id);
    }
    clearTimeout(filmsLive.debounce);
    filmsLive.debounce = setTimeout(filmsFocus, 400);
  });
  filmsLive.visible.clear();
  for (const card of document.querySelectorAll(".media-row-card[data-id], .media-card[data-id]")) {
    const item = mediaItems.get(card.dataset.id);
    if (item?.film && item.identified === false) { card.dataset.film = item.film; filmsLive.observer.observe(card); }
  }
}
async function filmsFocus() {
  const films = [...filmsLive.visible].filter(Boolean).sort(), key = films.join(",");
  if (key === filmsLive.sent) return;
  filmsLive.sent = key;
  try { await api("media/tracker-films/focus", {client_id: mediaClient(), films}); } catch { filmsLive.sent = ""; }
}
filmsLive.timer = setInterval(filmsPoll, 4000);
