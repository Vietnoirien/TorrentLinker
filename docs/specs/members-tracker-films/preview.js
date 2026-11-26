"use strict";
/* What docs/specs/members-tracker-films adds to the real Médias panel. Everything else on the
   page is the panel's own code. Each addition carries the class `preview-new` (outlined). */

const PREVIEW_SORTS = [["new", "Nouveautés"], ["shared", "Les plus partagés"], ["year", "Année"], ["title", "Titre"]];
const previewFilm = id => FILMS.get(id);
const previewSize = bytes => mediaFileSize(bytes);
function previewNew(node) { node.classList.add("preview-new"); return node; }

// Posters come from the fixtures: Library artwork embedded, tracker posters from TMDB.
mediaImage = (image, row) => {
  image.loading = "lazy"; image.decoding = "async";
  image.src = previewFilm(row.id)?.poster || LIBRARY.get(row.id)?.artwork || "";
};

function previewLeaveTracker() {
  PREVIEW.trackerHome = false; PREVIEW.trackerGrid = null;
}
// Leaving through Médias' own navigation leaves the tracker pages.
document.addEventListener("click", event => {
  if (event.target.closest("[data-media-view], #media-view")) previewLeaveTracker();
}, true);

async function previewOpenLanding() {
  PREVIEW.trackerHome = true; PREVIEW.trackerGrid = null;
  media.gridMode = false; media.view = "films"; $("media-view").value = "films";
  $("media-search").value = "";
  await loadMedia();
  window.scrollTo({top: 0}); document.querySelector(".media-scroll").scrollTop = 0;
}
async function previewOpenGrid(filters = {}) {
  PREVIEW.trackerGrid = {genres: filters.genre ? [filters.genre] : [], sort: filters.sort || "new"};
  await mediaSeeAll({view: "all"});
}

// Rows: "Sur le tracker" gets "Tout voir"; the landing's rows each open the grid.
const previewRenderHome = mediaRenderHome;
mediaRenderHome = function () {
  previewRenderHome();
  const root = $("media-home-rows");
  if (root.hidden) return;
  const sections = [...root.querySelectorAll(".media-home-row")];
  media.homeRows.forEach((row, index) => {
    const header = sections[index]?.querySelector(".media-home-row-header");
    if (!header || !row.preview) return;
    header.querySelector("button.quiet:not(.media-see-all)")?.remove(); // the Wish button moves to the panel
    // Only a genre opens a grid: a grid of every genre puts horror beside kids' animation.
    if (!["tracker", "genre"].includes(row.preview)) return;
    const all = previewNew(button(say("See all", "Tout voir"), () => row.preview === "tracker" ? previewOpenLanding() : previewOpenGrid(row.filters), "quiet media-see-all"));
    header.querySelector(".icon-button")?.before(all);
    if (row.preview === "tracker") previewNew(header.querySelector("h2"));
  });
  if (PREVIEW.trackerHome) {
    const head = previewNew(element("div", undefined, "media-home-row-header preview-landing"));
    const back = button("‹ Médias", () => { previewLeaveTracker(); media.view = "recent"; $("media-view").value = "recent"; return loadMedia(); }, "quiet");
    const total = trackerFilms({}).length;
    head.append(back, element("h2", say("On the tracker", "Sur le tracker")), element("span", `${total.toLocaleString("fr-FR")} films · ${say("one row per genre", "une rangée par genre")}`, "media-home-row-count"));
    root.prepend(head);
  }
};

// The grid: genre chips and sorts above the real cards, cards that open the film's panel.
const previewRender = mediaRender;
mediaRender = function () {
  previewRender();
  document.querySelector(".preview-chips")?.remove();
  document.querySelector(".media-section-heading").hidden = false;
  if (!PREVIEW.trackerGrid || media.homeRows.length && mediaHomeActive()) return;
  $("media-shelf-title").textContent = say("On the tracker", "Sur le tracker");
  const total = trackerFilms(PREVIEW.trackerGrid).length;
  $("media-shelf-count").textContent = `${total.toLocaleString("fr-FR")} films`;
  // A grid always shows one genre, named in a small line: "Sur le tracker · Animation ▾".
  // The arrow switches genre; "Affiner avec…" narrows to films of both.
  const bar = previewNew(element("div", undefined, "preview-chips"));
  bar.setAttribute("role", "group"); bar.setAttribute("aria-label", say("Genre", "Genre"));
  const chosen = PREVIEW.trackerGrid.genres;
  if (PREVIEW_VARIANT === "chips") {
    // Variant A: every genre as a chip; the chosen one is lit.
    for (const name of TMDB_GENRES) {
      const on = chosen.includes(name);
      const chip = button(name, () => previewGenres(on && chosen.length > 1 ? chosen.filter(g => g !== name) : [name]), "chip");
      chip.setAttribute("aria-pressed", String(on));
      bar.append(chip);
    }
  } else {
    // Variant B: one small line, "Sur le tracker · Animation ▾".
    const genre = element("select", undefined, "preview-genre"); genre.setAttribute("aria-label", say("Genre", "Genre"));
    for (const name of TMDB_GENRES) genre.append(new Option(name, name));
    if (chosen.length > 1) genre.append(new Option(chosen.join(" + "), "combined"));
    genre.value = chosen.length > 1 ? "combined" : chosen[0];
    genre.onchange = () => genre.value !== "combined" && previewGenres([genre.value]);
    bar.append(element("span", say("On the tracker ·", "Sur le tracker ·"), "preview-genre-label"), genre);
  }
  const narrow = element("select", undefined, "preview-sort"); narrow.setAttribute("aria-label", say("Narrow with a second genre", "Affiner avec un second genre"));
  narrow.append(new Option(chosen.length > 1 ? say("Combined genres", "Genres combinés") : say("Narrow with…", "Affiner avec…"), ""));
  for (const genre of TMDB_GENRES) {
    const count = chosen.includes(genre) ? 0 : trackerFilms({genres: [...chosen, genre]}).length;
    if (count && chosen.length < 2) narrow.append(new Option(`${chosen[0]} + ${genre} (${count})`, genre));
  }
  narrow.disabled = narrow.options.length < 2;
  narrow.onchange = () => narrow.value && previewGenres([...chosen, narrow.value]);
  bar.append(narrow);
  const sort = element("select", undefined, "preview-sort"); sort.setAttribute("aria-label", say("Sort", "Trier"));
  for (const [value, label] of PREVIEW_SORTS) sort.append(new Option(label, value));
  sort.value = PREVIEW.trackerGrid.sort; sort.onchange = () => { PREVIEW.trackerGrid.sort = sort.value; guard(loadMedia); };
  bar.append(sort);
  // Variant B's line takes the place of the section heading.
  document.querySelector(".media-section-heading").hidden = PREVIEW_VARIANT !== "chips";
  $("media-results").before(bar);
  for (const card of $("media-results").querySelectorAll(".media-card")) {
    const id = card.querySelector(".media-poster-button")?.getAttribute("aria-label");
    const film = media.rows.find(row => `${say("Details", "Détails")}: ${row.title}` === id || row.title === id);
    if (!film?.film) continue;
    const data = previewFilm(film.id), badge = card.querySelector(".media-poster-badge");
    badge?.remove();
    if (owner() && data.in_library) card.querySelector(".media-poster-button").append(previewNew(element("span", "Dans la bibliothèque", "media-poster-badge")));
    else if (owner() && !data.identified) card.querySelector(".media-poster-button").append(previewNew(element("span", "Non identifié", "media-poster-badge wait")));
    else if (typeof mediaRequestBadge === "function") mediaRequestBadge(film, card.querySelector(".media-art"));
    card.querySelector(".media-card-actions").replaceChildren(button(say("View", "Voir la fiche"), () => previewShow(film)));
  }
};
function previewGenres(genres) { PREVIEW.trackerGrid.genres = genres; guard(loadMedia); }
// The banner is pinned: choosing a film fills it where it is, and the page does not move.
function previewShow(row) {
  const scroller = document.querySelector(".media-scroll"), top = scroller.scrollTop, page = window.scrollY;
  mediaSelectFeature(row);
  scroller.scrollTop = top; window.scrollTo(0, page);
}
const previewDetails = mediaDetails;
mediaDetails = id => previewFilm(id) ? previewShow(media.rows.find(row => row.id === id) || filmRow(previewFilm(id))) : previewDetails(id);

// The film's panel.
const previewFeature = mediaRenderFeature;
mediaRenderFeature = function () {
  previewFeature();
  const row = media.selected, data = row && previewFilm(row.id), root = $("media-feature");
  if (!data || root.hidden) return;
  const content = root.querySelector(".media-feature-content"), description = root.querySelector(".media-feature-description");
  const genre = [...root.querySelectorAll(".media-feature-tag")];
  if (!owner()) {
    // A Member never sees releases: no release line, version or size (decision 2).
    root.querySelector(".media-tracker-release")?.remove();
    for (const tag of genre) if (["Version", "Poids", "File size"].includes(tag.querySelector("dt").textContent)) tag.remove();
    const asked = PREVIEW.requests.find(item => item.infohash === data.id && item.state === "pending");
    if (asked?.shared_with) description.append(previewNew(element("p", `Demandé avec ${asked.shared_with} autre membre : ${previewSize(asked.size)} comptés sur votre quota, la moitié des ${previewSize(asked.quoted)} de la release pré-sélectionnée.`, "media-quota")));
    else if (!asked && PREVIEW.othersAsked.has(data.id) && PREVIEW.role === "member") description.append(previewNew(element("p", `Déjà demandé par un autre membre : en le demandant aussi, vous partagez la demande et le quota (${previewSize(best(data).size / 2)} pour vous).`, "media-quota")));
    if (PREVIEW.role === "member") {
      const quota = description.querySelector(".media-quota:not(.preview-new)");
      if (quota && !asked) quota.textContent += " Le quota compte la release que le propriétaire a pré-sélectionnée ; s’il en choisit une plus lourde, cela ne vous coûte rien de plus.";
      if (quota) previewNew(quota);
    }
    if (PREVIEW.role === "viewer") previewViewerAsk(data, description, root.querySelector(".media-feature-actions") || content);
    return;
  }
  // The Owner: the pre-selected release, every grouped release, corrections (decisions 4, 12, 19, 23).
  const pre = root.querySelector(".media-tracker-release");
  if (pre) pre.prepend(previewNew(element("span", "Pré-sélection", "media-poster-badge")));
  if (best(data).score < DATA.threshold) description.append(previewNew(element("p", `Sous le seuil : aucune release n’atteint ${DATA.threshold} avec le profil « ${DATA.profile} ». La meilleure est pré-sélectionnée.`, "media-quota full")));
  if (data.in_library) content.querySelector("h2").append(previewNew(element("span", "Dans la bibliothèque", "media-poster-badge")));
  // The grouped releases open in Médias' own details dialog: nothing is inserted into the page.
  const count = data.releases.length + data.more_releases;
  root.querySelector(".media-feature-actions")?.append(previewNew(button(`Releases (${count})`, () => previewReleases(data), "media-secondary")));
  root.querySelector(".media-feature-actions")?.append(previewNew(button("Corriger le film", () => previewRematch(data), "media-secondary")));
};
function previewReleases(data) {
  const root = $("media-details"); root.replaceChildren(); root.hidden = false;
  if (!root.open) root.showModal();
  const count = data.releases.length + data.more_releases;
  root.append(button(say("Close details", "Fermer les détails"), () => root.close()), element("h2", data.title));
  const list = previewNew(element("div", undefined, "preview-releases"));
  list.append(element("p", `${count} releases · c411 et tr4ker · la pré-sélection en premier`, "muted"));
  for (const release of data.releases) {
    const line = element("div", undefined, "preview-release");
    const pill = element("span", String(release.score), `media-score score-${release.color || "green"}`); pill.title = "ReleaseScore";
    const facts = element("span", [previewSize(release.size), `${release.seeders} sources`, release.tracker, mediaAge(release.published_at)].filter(Boolean).join(" · "), "media-tracker-facts");
    const name = element("span", release.name, "media-tracker-name");
    const actions = element("span", undefined, "preview-release-actions");
    actions.append(button("Télécharger", () => toast(`Envoi de ${release.name} au client.`), "media-secondary"), button("Mauvais film", () => previewRematch(data, release), "quiet"));
    line.append(pill, name, facts, actions); list.append(line);
  }
  if (data.more_releases) list.append(element("p", `… et ${data.more_releases} autres releases.`, "media-tracker-facts"));
  root.append(list);
}
// A Viewer asks the account holder, never the Owner (decision 24).
function previewViewerAsk(data, description, actions) {
  const ask = PREVIEW.household.find(item => item.film === data.id && item.state !== "cancelled");
  if (ask) {
    const said = {pending: "En attente de Léa", accepted: "Léa l’a demandé au propriétaire", refused: `Léa a refusé${ask.note ? ` : « ${ask.note} »` : ""}`}[ask.state];
    const line = previewNew(element("div", undefined, "media-request-state"));
    line.append(element("span", said, `media-poster-badge ${ask.state === "refused" ? "no" : ask.state === "pending" ? "wait" : ""}`));
    description.append(line);
    if (ask.state === "pending") actions.append(previewNew(button("Annuler", () => { ask.state = "cancelled"; mediaRenderFeature(); }, "media-secondary")));
    return;
  }
  description.append(previewNew(element("p", "Tom regarde sur la télé du salon, sous le compte de Léa. Léa lui permet de demander des films : elle décide, puis demande au propriétaire.", "media-quota")));
  actions.append(previewNew(button("Demander à Léa", () => {
    PREVIEW.household.unshift({id: "h" + Date.now(), film: data.id, title: data.title, year: data.year, state: "pending", created: Date.now() / 1000});
    PREVIEW.householdSeen = false;
    toast(`Demande envoyée à Léa pour ${data.title}`);
    mediaRenderFeature();
  }, "media-primary")));
}
// Léa's bell drawer: her household's asks above her own Requests.
const previewDrawer = requestsDrawer;
requestsDrawer = function () {
  previewDrawer();
  if (PREVIEW.role !== "member") return;
  const root = $("media-requests"), box = previewNew(element("section", undefined, "preview-household"));
  box.append(element("h3", "Demandes de mon foyer"));
  if (!PREVIEW.household.length) box.append(element("p", "Ce que Tom demande sur la télé du salon arrive ici.", "media-row-note"));
  for (const ask of PREVIEW.household) {
    const film = previewFilm(ask.film), item = element("div", undefined, "media-request"), copy = element("div");
    copy.append(element("strong", [ask.title, ask.year].filter(Boolean).join(" · ")), element("small", `Tom · Télé du salon · ${({pending: "en attente", accepted: "acceptée, demandée au propriétaire", refused: "refusée", cancelled: "annulée par Tom"})[ask.state]}`));
    if (ask.state === "pending") {
      copy.append(requestQuotaLine(best(film).size));
      const row = element("div", undefined, "media-feature-actions");
      row.append(button("Accepter", async () => {
        await api("requests", {infohash: film.id});
        ask.state = "accepted"; await requestsLoad(); requestsDrawer(); mediaRenderFeature();
        toast(`${ask.title} demandé au propriétaire`);
      }, "media-primary"), button("Refuser", () => {
        ask.state = "refused"; ask.note = prompt("Un mot pour Tom (facultatif)", "") || ""; requestsDrawer();
      }, "media-secondary"));
      copy.append(row);
    }
    const art = mediaArt({id: film.id, title: ask.title, kind: "video", artwork_url: film.poster ? "tracker" : ""});
    item.append(art, copy); box.append(item);
  }
  root.firstChild.after(box);
};
function previewRematch(film, release) {
  const id = prompt(release ? `Associer « ${release.name} » à un autre film TMDB : collez son lien ou son numéro.` : `Associer « ${film.title} (${film.year}) » à un autre film TMDB : collez son lien ou son numéro.`, "https://www.themoviedb.org/movie/");
  if (id) toast(release ? "La release sera regroupée sous ce film ; la correction est conservée." : "Le film sera ré-identifié ; la correction est conservée.");
}

// Demo bar: who looks at the page.
function previewBar() {
  const bar = element("div", undefined, "preview-bar"); bar.setAttribute("role", "group"); bar.setAttribute("aria-label", "Aperçu");
  const label = element("strong", "Aperçu ⓘ"); label.onclick = () => bar.classList.toggle("open");
  bar.append(label);
  const role = element("select"); role.setAttribute("aria-label", "Rôle");
  for (const [value, label] of [["owner", "Propriétaire"], ["member", "Léa · membre"], ["viewer", "Tom · télé du salon de Léa"]]) role.append(new Option(label, value));
  role.onchange = () => { PREVIEW.role = role.value; media.featureId = null; previewEnvironment(); };
  const lang = button("FR", () => { const fr = document.documentElement.lang !== "en"; document.documentElement.lang = fr ? "en" : "fr"; lang.textContent = fr ? "EN" : "FR"; previewEnvironment(); }, "chip");
  const theme = button("Thème", () => { const dark = document.documentElement.dataset.theme !== "light"; document.documentElement.dataset.theme = dark ? "light" : "dark"; previewEnvironment(); }, "chip");
  const hint = element("span", `Données réelles de l’instance, lecture seule : ${DATA.films.length.toLocaleString("fr-FR")} films du tracker, ${DATA.films.reduce((n, f) => n + f.releases.length + f.more_releases, 0).toLocaleString("fr-FR")} releases notées avec « ${DATA.profile} ». La page « Recherche c411 · consultation » des membres ouvre la même page « Sur le tracker ». Encadré = nouveau.`, "preview-hint");
  bar.append(role, lang, theme, hint);
  document.body.append(bar);
}
previewBar();
