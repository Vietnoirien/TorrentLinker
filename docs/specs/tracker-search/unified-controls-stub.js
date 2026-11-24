"use strict";
/* The host the Search panel normally talks to, replaced by canned answers.

   panel/transport.js is left out of the preview and this file supplies TLPanel.connect in
   its place, so search/transport.js resolves to the stub below. Nothing here reaches c411,
   tr4ker or the application: the rows, the category tree and the facet choices are the
   shapes `Operations.search_options` and the `search` job really return (see
   src/torrentlinker/indexer_search.py and src/torrentlinker/web/operations.py). */

const PREVIEW = {
  // c411's own roots, children, colours and facet choices, read from a running instance
  // through its MCP endpoint (search_indexer_options) on 24 November 2026. The counts are
  // the ones that instance showed.
  roots: [
    ["1", "Films & Vidéos", 163431, "#3b82f6"],
    ["2", "Ebook", 54396, "#f59e0b"],
    ["3", "Audio", 42791, "#8b5cf6"],
    ["4", "Applications", 1895, "#6366f1"],
    ["5", "Jeux Vidéo", 8780, "#10b981"],
    ["6", "Emulation", 248, "#a855f7"],
    ["7", "GPS", 378, "#ef4444"],
    ["8", "XXX", 0, "#ec4899"],
    ["9", "Nulled", 1685, "#14b8a6"],
    ["10", "Imprimante 3D", 2409, "#f97316"],
  ],
  children: {
    1: [
      ["-1", "Animation"],
      ["-2", "Animation Série"],
      ["-3", "Concert"],
      ["-4", "Documentaire"],
      ["-5", "Emission TV"],
      ["-6", "Film"],
      ["-7", "Série TV"],
      ["-8", "Spectacle"],
      ["-9", "Sport"],
      ["-10", "Vidéo-clips"],
      ["-54", "Collection"],
      ["-57", "Série Documentaire"],
    ],
    2: [
      ["-11", "Audio"],
      ["-12", "BDs"],
      ["-13", "Comics"],
      ["-14", "Livres"],
      ["-15", "Manga"],
      ["-16", "Presse"],
      ["-59", "Partitions & Tablatures"],
      ["-60", "Revues & Manuels techniques"],
      ["-61", "Publications scientifiques"],
    ],
  },
};

/* c411's roots on tr4ker. tr4ker splits films and series where c411 keeps one root, and
   has no GPS at all, so one pill cannot always become one `cat=` slug. Its tree is
   src/torrentlinker/assets/tr4ker-categories.json. */
const TR4KER_ROOTS = {
  1: ["films", "series"],
  2: ["livres"],
  3: ["audio"],
  4: ["applications"],
  5: ["jeux-video"],
  6: ["emulation"],
  7: [],
  8: ["porno"],
  9: ["nulled"],
  10: ["impression-3d"],
};
/* A sub-category can restore a one-to-one slug where its root could not give one: c411's
   Films & Vidéos children land on tr4ker's `films` or its `series`. Collection spans both,
   so it stays unmapped and its tr4ker rows are kept here instead. */
const TR4KER_CHILDREN = {
  "-1": "films",   // Animation
  "-2": "series",  // Animation Série
  "-3": "films",   // Concert
  "-4": "films",   // Documentaire
  "-5": "series",  // Emission TV
  "-6": "films",   // Film
  "-7": "series",  // Série TV
  "-8": "films",   // Spectacle
  "-9": "films",   // Sport
  "-10": "films",  // Vidéo-clips
  "-57": "series", // Série Documentaire
};

const VIDEO_CHOICES = {
  resolution: ["2160p", "1080p", "720p", "SD"],
  source: ["BluRay", "Remux", "BDMV", "WEB-DL", "WEBRip", "DVDRip", "HDTV", "SDTV"],
  codec: ["H.265", "H.264", "H.263", "H.262", "AV1"],
  hdr: ["SDR", "HDR10", "HDR10+", "DV", "DV.HDR10", "DV.HDR10+"],
  audioType: ["lossless", "lossy"],
  channels: ["7.1", "5.1", "2.0", "1.0"],
  lang: ["MULTI", "VFF", "TRUEFRENCH", "VOSTFR", "VFQ", "VF", "MULTI.VF2", "VF2"],
  profile: ["compatibility", "pure", "hc_optimized", "optimization"],
};

// Option facets: c411 answers these per root; tr4ker's native search has no equivalent.
const OPTION_FACETS = [
  {
    slug: "type",
    label: "Type",
    // 4 choices on c411; the preview keeps the first few.
    choices: [
      ["2D", "35"],
      ["3D FSBS", "424"],
      ["3D", "38"],
      ["3D HSBS", "425"],
    ],
  },
  {
    slug: "genre",
    label: "Genre",
    // 58 choices on c411; the preview keeps the first few.
    choices: [
      ["Action", "39"],
      ["Animalier", "40"],
      ["Animation", "41"],
      ["Arts", "42"],
      ["Arts martiaux", "43"],
      ["Aventure", "44"],
      ["Ballet", "45"],
      ["Biopic", "46"],
    ],
  },
  {
    slug: "episode",
    label: "Episode",
    // 2002 choices on c411; the preview keeps the first few.
    choices: [
      ["Saison complète", "96"],
      ["Épisode 01", "97"],
      ["Épisode 02", "98"],
      ["Épisode 03", "99"],
      ["Épisode 04", "100"],
      ["Épisode 05", "101"],
      ["Épisode 06", "102"],
      ["Épisode 07", "103"],
    ],
  },
  {
    slug: "saison",
    label: "Saison",
    // 103 choices on c411; the preview keeps the first few.
    choices: [
      ["Série intégrale", "118"],
      ["Hors saison", "119"],
      ["Non communiqué", "120"],
      ["Saison 01", "121"],
      ["Saison 02", "122"],
      ["Saison 03", "123"],
      ["Saison 04", "124"],
      ["Saison 05", "125"],
    ],
  },
];

/* ---- release names: the facts tr4ker does not publish ---------------------------- */
/* c411 answers listing tags for its own rows, which is why tr4ker rows are bare today.
   The server already parses every release name for ReleaseScore, so the same parse can tag
   tr4ker rows and let the page-scope facets narrow them. It stands in here for c411's own
   filtering too, so the preview's c411 side answers a filtered search the way c411 does. */
const NAME_TAGS = [
  ["resolution", [[/\b2160p|\b4k\b|\buhd\b/i, "2160p"], [/\b1080[pi]\b/i, "1080p"], [/\b720p\b/i, "720p"], [/\bsd\b|\bdvdrip\b/i, "SD"]]],
  ["source", [[/\bremux\b/i, "Remux"], [/\bbdmv\b/i, "BDMV"], [/\bblu-?ray\b/i, "BluRay"], [/\bweb-?dl\b/i, "WEB-DL"], [/\bwebrip\b/i, "WEBRip"], [/\bdvdrip\b/i, "DVDRip"], [/\bhdtv\b/i, "HDTV"]]],
  ["codec", [[/\bx?h?\.?265\b|\bhevc\b/i, "H.265"], [/\bx?h?\.?264\b|\bavc\b|\bxvid\b/i, "H.264"], [/\bav1\b/i, "AV1"]]],
  ["hdr", [[/\bdv\.hdr10\+/i, "DV.HDR10+"], [/\bdv\.hdr10\b/i, "DV.HDR10"], [/\bhdr10\+/i, "HDR10+"], [/\bhdr10\b/i, "HDR10"], [/\bdv\b|\bdolby.?vision\b/i, "DV"]]],
  ["channels", [[/\b7\.1\b/i, "7.1"], [/\b5\.1\b/i, "5.1"], [/\b2\.0\b/i, "2.0"], [/\b1\.0\b/i, "1.0"]]],
  ["audioType", [[/\btruehd\b|\bflac\b|\bdts-?hd\b|\batmos\b/i, "lossless"], [/\baac\b|\bac3\b|\beac3\b|\bmp3\b|\bvorbis\b|\bopus\b/i, "lossy"]]],
  ["lang", [[/\bmulti\.vf2\b/i, "MULTI.VF2"], [/\bmulti\b/i, "MULTI"], [/\btruefrench\b/i, "TRUEFRENCH"], [/\bvostfr\b/i, "VOSTFR"], [/\bvff\b/i, "VFF"], [/\bvfq\b/i, "VFQ"], [/\bvf2\b/i, "VF2"], [/\bvf\b|\bfrench\b/i, "VF"]]],
];
const AUDIO_NAMES = [[/\btruehd\b/i, "TrueHD"], [/\beac3\b/i, "EAC3"], [/\bac3\b/i, "AC3"], [/\baac\b/i, "AAC"], [/\bflac\b/i, "FLAC"], [/\bvorbis\b/i, "Vorbis"], [/\bdts\b/i, "DTS"]];

function derived(title) {
  const found = {};
  for (const [kind, rules] of NAME_TAGS)
    for (const [pattern, value] of rules)
      if (pattern.test(title)) {
        found[kind] = value;
        break;
      }
  return found;
}

function derivedYear(title) {
  const match = title.match(/\b(19\d{2}|20\d{2})\b/);
  return match ? Number(match[1]) : null;
}

// The tags a tr4ker row would show, in the shape c411's listing uses.
function derivedTags(title) {
  const f = derived(title);
  const audio = AUDIO_NAMES.find(([p]) => p.test(title));
  const tags = [];
  if (f.lang) tags.push(["lang", f.lang]);
  if (f.resolution) tags.push(["resolution", f.resolution]);
  if (f.source) tags.push(["source", f.source]);
  if (f.hdr && f.hdr !== "SDR") tags.push(["hdr", f.hdr]);
  if (audio) tags.push(["audio", audio[1] + (f.channels ? ` ${f.channels}` : "")]);
  if (f.codec) tags.push(["codec", f.codec]);
  return tags;
}


const DAY = 86400;
const NOW = Math.floor(Date.now() / 1000);
const score = (n, color, best) => ({
  score: n,
  color,
  best: !!best,
  estimated: true,
  profile: "HDLight 1080p",
  summary: "Estimated from the release name and size.",
  summary_fr: "Estimé d’après le nom de release et la taille.",
  video: { note: n / 12 },
  audio: n / 14,
  size_factor: 1.0,
  gb_per_hour: 3.1,
  video_derived: true,
  criteria: [],
});

/* Rows exactly as the `search` job returns them: c411 rows carry an info hash, Zen and a
   note; tr4ker rows are keyed by slug, carry leechers, completions and freeleech, and have
   no Zen (ADR-0027). `native_category_label` is c411's own label. */
const ROWS = [
  {
    hash: "a1".repeat(20),
    title: "Dune.Partie.Deux.2024.MULTi.VFF.2160p.UHD.BluRay.DV.HDR10.TrueHD.7.1-ELiTE",
    size: 64.2e9,
    seeders: 86,
    leechers: 7,
    completions: 412,
    published_at: NOW - 2 * DAY,
    native_category_label: "Films & Vidéos / Film",
    root: "1",
    tracker: "c411",
    zen: 1.84,
    note: 2.35,
    revival: null,
    freeleech: false,
    release_score: score(94, "green", true),
  },
  {
    hash: "tr4ker:dune-partie-deux-2024-multi-vff-2160p-uhd-bluray-dv-hdr10-t9-41022",
    title: "Dune.Partie.Deux.2024.MULTi.VFF.2160p.UHD.BluRay.DV.HDR10.TrueHD.7.1-ELiTE",
    size: 64.2e9,
    seeders: 31,
    leechers: 2,
    completions: 118,
    published_at: NOW - 2 * DAY - 7200,
    native_category_label: "Films",
    cat_slug: "films",
    tracker: "tr4ker",
    zen: null,
    note: null,
    freeleech: true,
    slug: "dune-partie-deux-2024-multi-vff-2160p-uhd-bluray-dv-hdr10-t9-41022",
    release_score: score(94, "green"),
  },
  {
    hash: "b2".repeat(20),
    title: "Eaux.Turbulentes.S02.VFQ.1080p.WEB.AAC.2.0.H264-COLL3CTiF",
    size: 12.9e9,
    seeders: 1,
    leechers: 0,
    completions: 0,
    published_at: NOW - 600,
    native_category_label: "Films & Vidéos / Série TV",
    root: "1",
    tracker: "c411",
    zen: 0.32,
    note: 1.5,
    revival: null,
    freeleech: false,
    release_score: score(71, "yellow"),
  },
  {
    hash: "tr4ker:the-hunting-party-s02e10-multi-vff-1080p-webrip-10bits-eac3-t9-45120",
    title: "The.Hunting.Party.S02E10.MULTi.VFF.1080p.WEBRip.10bits.EAC3.2.0.x265-GL0P",
    size: 520e6,
    seeders: 9,
    leechers: 2,
    completions: 9,
    published_at: NOW - 900,
    native_category_label: "Séries",
    cat_slug: "series",
    tracker: "tr4ker",
    zen: null,
    note: null,
    freeleech: false,
    slug: "the-hunting-party-s02e10-multi-vff-1080p-webrip-10bits-eac3-t9-45120",
    release_score: score(68, "yellow"),
  },
  {
    hash: "c3".repeat(20),
    title: "Fahrenheit.9.11.2004.DOC.VFF.SD.DVDRip.AAC.2.0.x264-zlgr",
    size: 1.4e9,
    seeders: 0,
    leechers: 0,
    completions: 0,
    published_at: NOW - 1800,
    native_category_label: "Films & Vidéos / Documentaire",
    root: "1",
    tracker: "c411",
    zen: 0.09,
    note: 1.35,
    revival: true,
    freeleech: false,
    release_score: score(38, "red"),
  },
  {
    hash: "tr4ker:triple-je-2026-french-sd-webrip-aac-2-0-x264-jave-t9-45801",
    title: "Triple.Je.2026.FRENCH.SD.WEBRip.AAC.2.0.x264-JAVE",
    size: 785e6,
    seeders: 1,
    leechers: 2,
    completions: 0,
    published_at: NOW - 2400,
    native_category_label: "Films",
    cat_slug: "films",
    tracker: "tr4ker",
    zen: null,
    note: null,
    freeleech: false,
    slug: "triple-je-2026-french-sd-webrip-aac-2-0-x264-jave-t9-45801",
    release_score: score(31, "red"),
  },
  {
    hash: "d4".repeat(20),
    title: "Das.System.Karl.Olsberg.2007.FR.[EPUB]-NOTAG",
    size: 554e3,
    seeders: 1,
    leechers: 8,
    completions: 0,
    published_at: NOW - 3000,
    native_category_label: "Ebook / Livres",
    root: "2",
    tracker: "c411",
    zen: 0.0,
    note: 1.2,
    revival: null,
    freeleech: false,
    release_score: null,
  },
  {
    hash: "tr4ker:dans-l-ombre-de-la-reine-t01-ai-kozaki-fr-cbz-t9-44980",
    title: "Dans.l.Ombre.de.la.Reine.[T01].Ai.Kozaki.FR.[CBZ]-NEORipClub",
    size: 182.9e6,
    seeders: 2,
    leechers: 1,
    completions: 2,
    published_at: NOW - 3600,
    native_category_label: "Livres",
    cat_slug: "livres",
    tracker: "tr4ker",
    zen: null,
    note: null,
    freeleech: true,
    slug: "dans-l-ombre-de-la-reine-t01-ai-kozaki-fr-cbz-t9-44980",
    release_score: null,
  },
];

// c411's listing facts, which the rows themselves never carry. tr4ker publishes no
// equivalent, which is exactly why its rows show no tags today.
const LISTING = {
  [ROWS[0].hash]: {
    title: "Dune : Deuxième partie",
    year: 2024,
    rating: 8.1,
    completions: 412,
    leechers: 7,
    uploader: "ELiTE",
    exclusive: true,
    tags: [
      ["lang", "MULTi.VFF"],
      ["resolution", "2160p"],
      ["source", "BluRay"],
      ["hdr", "DV.HDR10"],
      ["audio", "TrueHD 7.1"],
      ["codec", "H.265"],
    ],
  },
  [ROWS[2].hash]: {
    title: "Eaux turbulentes",
    year: 2019,
    rating: 7.5,
    completions: 0,
    leechers: 0,
    uploader: "Ampli",
    tags: [
      ["lang", "VFQ"],
      ["resolution", "1080p"],
      ["source", "WEB-DL"],
      ["audio", "AAC 2.0"],
      ["codec", "H.264"],
    ],
  },
  [ROWS[4].hash]: {
    title: "Fahrenheit 9/11",
    year: 2004,
    rating: 7.1,
    completions: 0,
    leechers: 0,
    uploader: "baudelaine",
    tags: [
      ["lang", "VFF"],
      ["resolution", "SD"],
      ["source", "DVDRip"],
      ["audio", "AAC 2.0"],
      ["codec", "H.264"],
    ],
  },
  [ROWS[6].hash]: {
    title: "Das System",
    year: 2007,
    completions: 0,
    leechers: 8,
    uploader: "LeGritche",
    tags: [],
  },
};

const STUB = {
  // What the preview bar flips; the stub answers accordingly.
  trackers: ["c411", "tr4ker"],
  preferences: { "tl-search-density": "comfortable", "tl-search-posters": "0" },
};

// A child id belongs to its root; c411's children are negative ids under a positive root,
// so the tree itself says which (the preview holds c411's real tree).
function searchRootOf(category) {
  const key = String(category);
  for (const [root, kids] of Object.entries(PREVIEW.children))
    if (kids.some(([id]) => id === key)) return Number(root);
  return Math.abs(Number(category));
}

function searchOptions(category) {
  const root = category ? String(searchRootOf(category)) : null;
  const categories = {};
  for (const [id, name, , color] of PREVIEW.roots)
    categories[id] = { name, parent: null, color };
  for (const [parent, kids] of Object.entries(PREVIEW.children))
    for (const [id, name] of kids) categories[id] = { name, parent: Number(parent) };
  return {
    backend: "c411-native",
    categories,
    root_colors: Object.fromEntries(PREVIEW.roots.map(([id, , , color]) => [id, color])),
    root_category: root ? Number(root) : null,
    facets: root === "1" ? OPTION_FACETS : [],
    video_filters: root === "1" ? VIDEO_CHOICES : {},
    adult_filters: "",
    trackers: STUB.trackers,
    // As Operations.search_options reports it, from tracker_categories.
    tr4ker_scopes: Object.fromEntries(
      Object.keys(categories).map((key) => {
        const id = Number(key);
        if (TR4KER_CHILDREN[key]) return [key, "server"];
        const slugs = TR4KER_ROOTS[id];
        if (slugs === undefined) return [key, "page"];
        if (!slugs.length) return [key, "none"];
        return [key, slugs.length === 1 ? "server" : "page"];
      }),
    ),
  };
}

// The native video filters c411 answers on its side, applied to the preview's own rows.
function matchesFilters(row, filters = {}) {
  const facts = derived(row.title);
  for (const name of Object.keys(VIDEO_CHOICES)) {
    const wanted = (filters[name] || "").split(",").filter(Boolean);
    if (wanted.length && !wanted.includes(facts[name])) return false;
  }
  if (filters.year && derivedYear(row.title) !== Number(filters.year)) return false;
  return true;
}

function tr4kerSlug(category) {
  const key = String(category || "");
  if (!key) return "";
  if (TR4KER_CHILDREN[key]) return TR4KER_CHILDREN[key];
  const slugs = TR4KER_ROOTS[key] || [];
  return slugs.length === 1 ? slugs[0] : "";
}

function searchResult(body) {
  const root = body.category ? String(searchRootOf(body.category)) : "";
  const slug = tr4kerSlug(body.category);
  const rows = ROWS.filter((r) => STUB.trackers.includes(r.tracker)).filter((r) => {
    // c411 narrows its whole catalogue to the chosen root, as it does today.
    if (r.tracker === "c411") return (!root || r.root === root) && matchesFilters(r, body.filters);
    // tr4ker is only sent `cat=` when the root maps to one of its slugs; otherwise its
    // page comes back unnarrowed, which is what the proposal makes visible.
    return !slug || r.cat_slug === slug;
  });
  return {
    rows: rows.map((r) => ({ ...r })),
    page: body.page || 1,
    pages: 100,
    total: 276013,
    per_page: 100,
    has_more: true,
    window_limited: false,
    listing: LISTING,
    known: {},
    root_counts: Object.fromEntries(PREVIEW.roots.map(([id, , count]) => [id, count])),
    total_size: null,
    palliative_count: 584,
    selection_kind: "live-search",
    trackers: STUB.trackers,
    tr4ker: STUB.trackers.includes("tr4ker")
      ? { backend: "tr4ker-native", total: 1001, total_capped: true, notes: [] }
      : {},
    // The preview echoes the request so the proposal can show what each Tracker was sent.
    request: body,
  };
}

const JOBS = new Map();
let jobId = 0;

function answer(action, body) {
  if (action === "preferences") {
    if (Object.keys(body).filter((k) => k !== "_client").length)
      Object.assign(STUB.preferences, body);
    return STUB.preferences;
  }
  if (action === "job") {
    const id = ++jobId;
    const result =
      body.kind === "search-options" ? searchOptions(body.category) : searchResult(body);
    JOBS.set(id, { status: "completed", result });
    if (window.previewRequest) window.previewRequest(body);
    return { job: id };
  }
  if (action === "job-status") return JOBS.get(body.job) || { status: "failed", error: "gone" };
  if (action === "state")
    return { rows: [], search: [], score_profiles: ["HDLight 1080p", "Remux"], score_active: "HDLight 1080p", score_revision: 1 };
  if (action === "queue") return [];
  if (action === "navigate") return {};
  if (action === "detail") throw new Error("Le détail n’est pas dans l’aperçu.");
  return {};
}

window.TLPanel.connect = () =>
  Promise.resolve((action, body) => Promise.resolve(answer(action, body || {})));
