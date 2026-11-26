"use strict";
/* The host the Médias panel normally talks to, answered from fixtures.js.

   panel/transport.js is left out and this file supplies TLPanel.connect in its place, so
   media/view.js receives the request function below. The data is a running instance's, read
   only (extract_fixtures.py, build_fixtures.py): its Library films and artwork, the tracker
   suggestions with their TMDB facts, each film's seeded releases from the Catalogue, scored
   with the Owner's active ReleaseScore profile. Nothing here reaches the app, c411 or tr4ker. */

const PREVIEW = {
  role: "owner", // owner | member | viewer (demo bar)
  trackerHome: false, // the "Sur le tracker" landing (genre rows)
  trackerGrid: null, // {genres: [...], sort, q} while the full grid shows
  revision: 1,
  requests: [],
  // Household Asks: what Tom, a Viewer on Léa's living-room TV, asked her for (decision 24).
  household: [],
  householdSeen: true,
  // Films another Member already asked for, so joining a shared Request can be tried.
  othersAsked: new Set(),
  quota: {requests_left: 3, bytes_left: 60e9, pending_left: 2, reset: Date.now() / 1000 + 4 * 86400},
};
const DATA = PREVIEW_DATA;
const FILMS = new Map(DATA.films.map(film => [film.id, film]));
const LIBRARY = new Map(DATA.library.map(item => [item.id, item]));
for (const film of DATA.films.slice(3, 400).filter((_, i) => i % 9 === 0)) PREVIEW.othersAsked.add(film.id);

// TMDB's French film genres (decision 16), in TMDB's order.
const TMDB_GENRES = ["Action", "Aventure", "Animation", "Comédie", "Crime", "Documentaire", "Drame", "Familial", "Fantastique", "Histoire", "Horreur", "Musique", "Mystère", "Romance", "Science-Fiction", "Téléfilm", "Thriller", "Guerre", "Western"];

const owner = () => PREVIEW.role === "owner";
const best = film => film.releases[0];
// What a Member may see: identified films, never one already in the Library (decisions 11, 21).
const visibleFilms = () => DATA.films.filter(film => owner() || (film.identified && !film.in_library));

function filmRow(film) {
  const release = best(film);
  return {
    id: film.id,
    kind: "video",
    title: film.title,
    year: film.year,
    rating: film.rating,
    genre: film.genres.join(", "),
    description: film.description,
    duration: film.duration,
    artwork_url: film.poster ? "tracker" : "",
    available: true,
    film: true,
    // The Owner sees the pre-selected release; a Member only a size to check the quota with.
    tracker: owner()
      ? {site: release.tracker, hash: release.hash, name: release.name, size: release.size, seeders: release.seeders, score: release.score, color: release.color, published_at: release.published_at}
      : {hash: film.id, size: release.size},
  };
}
function libraryRow(item) {
  return {id: item.id, kind: "video", title: item.title, year: item.year, genre: item.genre, description: item.description, duration: item.duration, artwork_url: item.artwork ? "api/media/items/" + item.id + "/artwork" : "", available: true, content_id: item.content_id, release: item.release, series: item.series};
}

function sortFilms(films, sort) {
  const by = {
    new: (a, b) => b.published_at - a.published_at,
    shared: (a, b) => b.seeders - a.seeders,
    year: (a, b) => Number(b.year) - Number(a.year),
    title: (a, b) => a.title.localeCompare(b.title, "fr"),
  }[sort || "new"];
  return [...films].sort(by);
}
function trackerFilms({genres = [], sort = "new", q = ""} = {}) {
  const words = q.trim().toLowerCase();
  return sortFilms(
    visibleFilms().filter(film => genres.every(genre => film.genres.includes(genre)) && (!words || `${film.title} ${film.original_title}`.toLowerCase().includes(words))),
    sort,
  );
}

function libraryGenres() {
  const counts = new Map();
  for (const item of DATA.library) for (const genre of (item.genre || "").split(",").map(g => g.trim()).filter(Boolean)) counts.set(genre, (counts.get(genre) || 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1]).map(([genre]) => genre);
}

function home(params) {
  const include = params.get("include");
  if (PREVIEW.trackerHome) {
    if (include === "tracker") return {rows: []};
    const rows = [];
    const add = (key, title, films, filters) => films.length && rows.push({key: "genre", title, preview: key, filters: {tracker: "films", ...filters}, total: films.length, rows: films.slice(0, 20).map(filmRow)});
    add("new", "Nouveautés sur le tracker", trackerFilms({sort: "new"}), {sort: "new"});
    add("shared", "Les plus partagés", trackerFilms({sort: "shared"}), {sort: "shared"});
    for (const genre of TMDB_GENRES) add("genre", genre, trackerFilms({genres: [genre]}), {genre});
    return {rows};
  }
  if (include === "tracker") {
    const films = trackerFilms({sort: "new"});
    const rows = [{key: "genre", title: "Sur le tracker", preview: "tracker", filters: {tracker: "films"}, total: films.length, rows: films.slice(0, 60).map(filmRow), state: "ready"}];
    return {rows};
  }
  const library = [...DATA.library].sort((a, b) => b.added - a.added).filter(item => !item.series);
  const rows = [{key: "recent", title: "", filters: {view: "recent"}, total: library.length, rows: library.slice(0, 20).map(libraryRow)}];
  for (const genre of libraryGenres().slice(0, 6)) {
    const items = library.filter(item => (item.genre || "").includes(genre));
    if (items.length >= 3) rows.push({key: "genre", title: genre, filters: {view: "all", genre}, total: items.length, rows: items.slice(0, 20).map(libraryRow)});
  }
  return {rows};
}

function listing(params) {
  const offset = Number(params.get("offset") || 0), limit = Number(params.get("limit") || 100);
  if (params.get("view") === "continue") return {rows: [], total: 0, has_more: false, next_offset: null};
  if (PREVIEW.trackerGrid || PREVIEW.trackerHome) {
    const films = trackerFilms({...(PREVIEW.trackerGrid || {}), q: params.get("q") || ""});
    const page = films.slice(offset, offset + limit).map(filmRow);
    return {rows: page, total: films.length, has_more: offset + limit < films.length, next_offset: offset + limit, filters: {genres: TMDB_GENRES}};
  }
  const genre = params.get("genre"), q = (params.get("q") || "").toLowerCase();
  const items = [...DATA.library].sort((a, b) => b.added - a.added).filter(item => (!genre || (item.genre || "").includes(genre)) && (!q || item.title.toLowerCase().includes(q)));
  return {rows: items.slice(offset, offset + limit).map(libraryRow), total: items.length, has_more: offset + limit < items.length, next_offset: offset + limit, filters: {genres: libraryGenres(), years: []}};
}

function requestsAnswer() {
  const waiting = PREVIEW.household.filter(item => item.state === "pending").length;
  return {requests: PREVIEW.requests, quota: PREVIEW.quota, unread: PREVIEW.householdSeen ? 0 : waiting};
}
function ask(body) {
  const film = FILMS.get(body.infohash);
  const shared = PREVIEW.othersAsked.has(film.id) ? 2 : 1;
  const size = best(film).size;
  PREVIEW.requests.unshift({id: "r" + Date.now(), kind: "request", state: "pending", infohash: film.id, title: film.title, year: film.year, created: Date.now() / 1000, size: size / shared, shared_with: shared - 1, quoted: size});
  PREVIEW.quota = {...PREVIEW.quota, requests_left: PREVIEW.quota.requests_left - 1, pending_left: PREVIEW.quota.pending_left - 1, bytes_left: PREVIEW.quota.bytes_left - size / shared};
  return requestsAnswer();
}

function answer(path, {body, method}) {
  const [route, query = ""] = path.split("?");
  const params = new URLSearchParams(query);
  if (route === "preferences") return {layout: "cinematic", horizon: "home"};
  if (route === "host") return {};
  if (route === "media/home") return home(params);
  if (route === "media") return listing(params);
  let match = /^media\/items\/([^/]+)\/artwork$/.exec(route);
  if (match) {
    const id = decodeURIComponent(match[1]);
    return {data_url: FILMS.get(id)?.poster || LIBRARY.get(id)?.artwork || ""};
  }
  match = /^media\/items\/([^/]+)$/.exec(route);
  if (match) {
    const id = decodeURIComponent(match[1]);
    return FILMS.has(id) ? filmRow(FILMS.get(id)) : {...libraryRow(LIBRARY.get(id) || {}), episodes: []};
  }
  if (route === "requests" && method === "POST") return ask(body);
  if (route === "requests") return requestsAnswer();
  if (route === "requests/seen") { PREVIEW.householdSeen = true; return requestsAnswer(); }
  match = /^requests\/([^/]+)\/cancel$/.exec(route);
  if (match) {
    const row = PREVIEW.requests.find(item => item.id === match[1]);
    if (row) { row.state = "cancelled"; PREVIEW.quota = {...PREVIEW.quota, requests_left: PREVIEW.quota.requests_left + 1, pending_left: PREVIEW.quota.pending_left + 1, bytes_left: PREVIEW.quota.bytes_left + row.size}; }
    return requestsAnswer();
  }
  if (/^media\/tracker\/.+\/download$/.test(route)) return {queued: true};
  if (route.startsWith("media/playlists") || route.startsWith("media/ratings")) return {rows: [], total: 0};
  return {rows: [], total: 0};
}

window.TLPanel = window.TLPanel || {};
window.TLPanel.connect = () => {
  const request = (path, options = {}) => new Promise(resolve => setTimeout(() => resolve(answer(path, options)), 60));
  return Promise.resolve(request);
};

function previewEnvironment() {
  const permissions = {owner: [], member: ["films", "request", "wish", "media-center"], viewer: ["films", "media-center"]}[PREVIEW.role];
  window.dispatchEvent(new CustomEvent("media-environment", {detail: {
    mode: "web", app_base: location.href, active: true, kind: "video", view: "recent", queue: [], queue_client: "default", queue_music: false,
    player_clearance: 0, playback: null, chat_open: false, center_mode: false, clients: [{id: "default", name: "qBittorrent"}], client_busy: false,
    revision: PREVIEW.revision++, language: document.documentElement.lang === "en" ? "en" : "fr", theme: document.documentElement.dataset.theme || "dark",
    client_id: "default", adult_content: false, owner: PREVIEW.role === "owner", permissions,
  }}));
}
// The preview layer (preview.js) loads after the panel; the page speaks once all of it is there.
window.mediaReady = () => document.readyState === "loading" ? addEventListener("DOMContentLoaded", previewEnvironment, {once: true}) : previewEnvironment();
