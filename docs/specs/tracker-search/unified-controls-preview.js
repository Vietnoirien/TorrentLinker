"use strict";
/* The proposal, wrapped around the real Search panel (issue: unified Tracker controls).

   Nothing in src/ is changed here. The real renderers run first and this file adds what the
   change would add, so the preview shows the application's own screen with the proposal on
   top of it — the bar at the top switches it off to compare against today.

   The idea: every control says where it bites. A Tracker gets one of three marks.

     ● server  the Tracker filters its whole catalogue, as c411 does today
     ◐ page    the Tracker cannot filter it, so TorrentLinker filters the rows it fetched
     ○ none    the Tracker has no equivalent; its rows are not narrowed at all

   Today every control is silently ● for c411 and ○ for tr4ker, which is why a search looks
   filtered while half the rows are not. Verified tr4ker native parameters are q, cat,
   tmdb_id, freeleech and sort=recent|completed (docs/research/tr4ker-integration.md). */

let proposal = true;

/* ---- what each Tracker does with each control ------------------------------------ */
// TR4KER_ROOTS and TR4KER_CHILDREN come from the stub, with the rest of the tracker data.
const SCOPES = {
  "v:resolution": "page",
  "v:source": "page",
  "v:codec": "page",
  "v:hdr": "page",
  "v:audioType": "page",
  "v:channels": "page",
  "v:lang": "page",
  "v:profile": "none",
  "o:genre": "none",
  "o:type": "none",
  "o:saison": "none",
  "o:episode": "none",
  year: "page",
  team: "none",
  uploader: "none",
};

const MARKS = { server: "●", page: "◐", none: "○" };
const SCOPE_TEXT = {
  server: [
    "filters the whole tracker",
    "filtre tout le tracker",
  ],
  page: [
    "no equivalent on this tracker: its rows are filtered here, within the page fetched",
    "sans équivalent sur ce tracker : ses lignes sont filtrées ici, dans la page reçue",
  ],
  none: [
    "this tracker has no equivalent: its rows are not narrowed",
    "ce tracker n’a pas d’équivalent : ses lignes ne sont pas restreintes",
  ],
};

/* The two dots a control carries. `c411` is the scope on c411, `tr4ker` on tr4ker. */
function scopeMark(scopes) {
  const span = element("span", undefined, "scope-mark");
  const parts = [];
  for (const [name, scope] of Object.entries(scopes)) {
    const dot = element("span", MARKS[scope], `scope-dot scope-${scope}`);
    dot.dataset.tracker = name;
    span.append(dot);
    parts.push(`${name} ${MARKS[scope]} ${say(...SCOPE_TEXT[scope])}`);
  }
  span.title = parts.join("\n");
  span.setAttribute("aria-label", parts.join(". "));
  return span;
}

// tr4ker's scope for the category currently chosen, and why.
function categoryScope(id) {
  const key = String(id || "");
  if (!key) return { scope: "server", slug: "", why: ["every category", "toutes les catégories"] };
  if (TR4KER_CHILDREN[key])
    return { scope: "server", slug: TR4KER_CHILDREN[key], why: [`cat=${TR4KER_CHILDREN[key]}`, `cat=${TR4KER_CHILDREN[key]}`] };
  const slugs = TR4KER_ROOTS[key] || [];
  if (!slugs.length)
    return { scope: "none", slug: "", why: ["tr4ker has no such category", "tr4ker n’a pas cette catégorie"] };
  if (slugs.length === 1)
    return { scope: "server", slug: slugs[0], why: [`cat=${slugs[0]}`, `cat=${slugs[0]}`] };
  return {
    scope: "page",
    slug: "",
    why: [
      `tr4ker splits this root into ${slugs.join(" + ")}: its rows are kept here`,
      `tr4ker découpe cette racine en ${slugs.join(" + ")} : ses lignes sont retenues ici`,
    ],
  };
}

/* ---- the page-scope filter: what tr4ker's rows are narrowed by here --------------
   `derived`, `derivedYear` and `derivedTags` come from the stub: they stand in for the
   ReleaseScore estimator the server already runs on every release name. */
function pageFilters() {
  const active = [];
  for (const def of SS.facetDefs) {
    const values = [...(SS.chosen.get(def.key) || [])];
    if (values.length && SCOPES[def.key] === "page")
      active.push({ key: def.key, param: def.param, values, label: def.label });
  }
  if (SS.inputs.year && SCOPES.year === "page")
    active.push({ key: "year", param: "year", values: [SS.inputs.year], label: say("Year", "Année") });
  return active;
}

function keepsRow(row) {
  if (row.tracker !== "tr4ker") return true;
  const scope = categoryScope(SS.category);
  if (SS.category && scope.scope === "none") return false;
  // The root tr4ker could not be sent as one `cat=`: its rows are kept here instead.
  if (SS.category && scope.scope === "page")
    if (!(TR4KER_ROOTS[String(SS.category)] || []).includes(row.cat_slug)) return false;
  const facts = derived(row.title);
  for (const filter of pageFilters()) {
    if (filter.param === "year") {
      if (derivedYear(row.title) !== Number(filter.values[0])) return false;
    } else if (!filter.values.includes(facts[filter.param])) return false;
  }
  return true;
}

/* ---- the legend under the Tracker chips ------------------------------------------ */
function renderLegend() {
  let host = $("scope-legend");
  if (!host) {
    host = element("p", undefined, "scope-legend");
    host.id = "scope-legend";
    $("search-trackers").after(host);
  }
  host.hidden = !(proposal && SS.trackers.includes("tr4ker"));
  if (host.hidden) return;
  host.replaceChildren(
    element("span", say("Each control says where it applies:", "Chaque contrôle indique où il s’applique :"), "muted"),
    element("span", `${MARKS.server} ${say("the whole tracker", "tout le tracker")}`, "scope-key scope-server"),
    element("span", `${MARKS.page} ${say("the page fetched", "la page reçue")}`, "scope-key scope-page"),
    element("span", `${MARKS.none} ${say("not applied", "non appliqué")}`, "scope-key scope-none"),
  );
}

/* ---- the controls, wrapped ------------------------------------------------------- */
const basePills = renderPills;
renderPills = function () {
  basePills();
  renderLegend();
  if (!proposal || !SS.trackers.includes("tr4ker")) return;
  const roots = searchRoots();
  const pills = [...$("search-pills").children];
  // The first pill is "All"; the rest follow searchRoots() in order.
  pills.forEach((pill, index) => {
    if (!index) {
      pill.append(scopeMark({ c411: "server", tr4ker: "server" }));
      return;
    }
    const id = roots[index - 1]?.[0];
    const scope = categoryScope(id);
    const mark = scopeMark({ c411: "server", tr4ker: scope.scope });
    mark.title += `\ntr4ker: ${say(...scope.why)}`;
    // tr4ker publishes no per-category total (its listing total is capped), so the number
    // on the pill is c411's alone and now says so.
    const count = pill.querySelector(".pill-count");
    if (count) count.title = say("c411 only: tr4ker publishes no category total.", "c411 seulement : tr4ker ne publie pas de total par catégorie.");
    if (count) count.classList.add("c411-count");
    pill.append(mark);
  });
};

const baseFacets = renderFacets;
renderFacets = function () {
  baseFacets();
  if (!proposal) return;
  const host = $("search-facets");
  const defs = [...SS.facetDefs.map((d) => d.key), "year", "team", "uploader"];
  [...host.querySelectorAll(".fdrop")].forEach((drop, index) => {
    const key = defs[index];
    const scope = SCOPES[key] || "none";
    if (!SS.trackers.includes("tr4ker")) return;
    const summary = drop.querySelector("summary");
    const mark = scopeMark({ c411: "server", tr4ker: scope });
    // setLabel rewrites the summary's text when a choice is made, so the mark is put back.
    const baseSetLabel = drop.setLabel;
    drop.setLabel = (count, text = "") => {
      baseSetLabel(count, text);
      summary.append(mark);
    };
    summary.append(mark);
  });
};

const baseToggles = syncToggles;
syncToggles = function () {
  baseToggles();
  if (!proposal) return;
  // Freeleech is the one control tr4ker answers natively and c411 has no equivalent for.
  let free = $("search-freeleech");
  if (!free) {
    free = chipButton("", false, () => {
      SS.freeleech = !SS.freeleech;
      criteriaChanged();
    }, "chip");
    free.id = "search-freeleech";
    $("search-palliative").after(free);
  }
  free.hidden = !SS.trackers.includes("tr4ker");
  free.setAttribute("aria-pressed", String(!!SS.freeleech));
  free.replaceChildren(
    document.createTextNode("⚡ Freeleech"),
    ...(SS.trackers.includes("tr4ker") ? [scopeMark({ c411: "none", tr4ker: "server" })] : []),
  );
  if (!SS.trackers.includes("tr4ker")) return;
  for (const [id, scope] of [["search-exclusive", "none"], ["search-palliative", "none"], ["search-crew", "none"]]) {
    const node = $(id);
    if (node.hidden || node.querySelector(".scope-mark")) continue;
    node.append(scopeMark({ c411: "server", tr4ker: scope }));
  }
};

// The blanket "Absent sur tr4ker" sentence is replaced by the marks on the controls.
const baseNotes = renderTrackerNotes;
renderTrackerNotes = function () {
  baseNotes();
  if (proposal) $("search-unavailable").textContent = "";
};

/* ---- the rows -------------------------------------------------------------------- */
const baseRichRow = richRow;
richRow = function (row) {
  const node = baseRichRow(row);
  if (!proposal || row.tracker !== "tr4ker") return node;
  const tags = node.querySelector(".sr-main > .sr-line:last-child");
  const found = derivedTags(row.title);
  if (tags && found.length) {
    for (const [kind, text] of found) {
      const tag = element("span", text, `tag tag-${kind} tag-derived`);
      tag.title = say(
        "Read from the release name: tr4ker publishes no listing facts.",
        "Lu dans le nom de release : tr4ker ne publie pas les faits de listing.",
      );
      tags.append(tag);
    }
  }
  return node;
};

const baseResults = renderResults;
renderResults = function () {
  if (!proposal) return baseResults();
  const all = SS.rows;
  const kept = all.filter(keepsRow);
  SS.rows = kept;
  try {
    baseResults();
  } finally {
    SS.rows = all;
  }
  const dropped = all.length - kept.length;
  const summary = $("search-summary");
  if (dropped && SS.trackers.includes("tr4ker")) {
    const fetched = all.filter((r) => r.tracker === "tr4ker").length;
    summary.textContent =
      `${kept.length} ${say("results", "résultats")}` +
      ` · c411 ${kept.filter((r) => r.tracker === "c411").length}` +
      ` · tr4ker ${kept.filter((r) => r.tracker === "tr4ker").length}` +
      say(
        ` of ${fetched} fetched`,
        ` sur ${fetched} reçus`,
      );
    summary.title = say(
      "tr4ker cannot filter on these criteria, so its rows are narrowed here, within the page it returned.",
      "tr4ker ne sait pas filtrer sur ces critères : ses lignes sont restreintes ici, dans la page reçue.",
    );
  }
};

/* ---- the preview bar -------------------------------------------------------------- */
window.previewRequest = (body) => {
  if (body.kind !== "search") return;
  const scope = categoryScope(body.category);
  const sent = [`q=${body.query || "∅"}`];
  if (body.category) sent.push(`category=${body.category}`);
  const t4k = [`q=${body.query || "∅"}`];
  if (body.category && scope.slug) t4k.push(`cat=${scope.slug}`);
  if (SS.freeleech) t4k.push("freeleech=1");
  const page = pageFilters();
  $("demo-hint").textContent = proposal
    ? `c411 ← ${sent.concat(Object.keys(body.filters || {}).filter((k) => !["sortBy", "sortOrder"].includes(k)).map((k) => `${k}=${body.filters[k]}`)).join(" ")}   ·   tr4ker ← ${t4k.join(" ")}` +
      (page.length ? `   ·   ${say("here", "ici")}: ${page.map((f) => f.label).join(", ")}` : "")
    : "";
};

$("demo-theme").onclick = () => {
  const light = document.documentElement.dataset.theme !== "light";
  document.documentElement.dataset.theme = light ? "light" : "dark";
  $("demo-theme").textContent = light ? "Thème : clair" : "Thème : sombre";
};
$("demo-lang").onclick = () => {
  language = language === "fr" ? "en" : "fr";
  $("demo-lang").textContent = language.toUpperCase();
  translate();
  searchRetranslate();
  renderPills();
  renderFacets();
  renderChosen();
  syncToggles();
  renderSort();
  renderResults();
};
$("demo-proposal").onclick = () => {
  proposal = !proposal;
  $("demo-proposal").setAttribute("aria-pressed", String(proposal));
  $("demo-proposal").textContent = proposal ? "Proposition : activée" : "Proposition : désactivée";
  document.body.classList.toggle("no-proposal", !proposal);
  document.querySelectorAll(".scope-mark").forEach((n) => n.remove());
  renderPills();
  renderFacets();
  syncToggles();
  renderTrackerNotes();
  renderResults();
};

// Films & Vidéos from the start: it is the root that carries every control, and the one
// where c411 and tr4ker disagree most (tr4ker splits it into films and series).
SS.category = "1";

// Boot the panel the way the shell does.
window.dispatchEvent(
  new CustomEvent("search-environment", {
    detail: {
      client: "preview",
      language: "fr",
      theme: "dark",
      page: "search",
      active: true,
      adult: false,
      indexer: "https://c411.org",
      readonly: false,
      mode: "web",
    },
  }),
);
