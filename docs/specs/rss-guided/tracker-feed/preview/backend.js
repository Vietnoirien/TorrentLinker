"use strict";
// Preview-only backend. It answers what feeds/view.js asks of the shell ("api" -> feed_workspace.py
// routes, "details") with fixture data held in memory. The view itself is the real one.
(() => {
  const now = () => Date.now() / 1000;
  const H = 3600, D = 86400;
  const hex = (seed) => {
    let h = "", x = seed * 2654435761 % 4294967296;
    while (h.length < 40) { x = (x * 1664525 + 1013904223) % 4294967296; h += x.toString(16).padStart(8, "0"); }
    return h.slice(0, 40);
  };
  const GIB = 1024 ** 3, MIB = 1024 ** 2;
  const CATEGORIES = {
    1000: { name: "Jeux", parent: null }, 1010: { name: "PC", parent: 1000 },
    2000: { name: "Films", parent: null }, 2040: { name: "Films HD", parent: 2000 }, 2045: { name: "Films UHD", parent: 2000 },
    3000: { name: "Audio", parent: null }, 3040: { name: "Audio lossless", parent: 3000 },
    4000: { name: "Applications", parent: null },
    5000: { name: "Séries TV", parent: null }, 5030: { name: "Séries SD", parent: 5000 }, 5040: { name: "Séries HD", parent: 5000 },
    7000: { name: "Livres", parent: null }, 7030: { name: "BD / Comics", parent: 7000 },
  };
  const CLIENTS = [
    { id: "qbit", name: "qBittorrent maison", folders: ["/data/downloads/films", "/data/downloads/musique", "/data/downloads/series"] },
    { id: "seedbox", name: "Seedbox", folders: ["/home/seedbox/watch", "/home/seedbox/films"] },
  ];

  // ---- releases (the Indexer's candidates) ----
  let seq = 0;
  const rel = (o) => {
    seq++;
    return {
      title: o.title, size: o.size, download_url: o.dl ?? "", seeders: o.seeders, infohash: o.infohash ?? hex(seq),
      details_url: o.url ?? "", categories: o.cats ?? [], published_at: now() - o.age * H, metadata: o.meta ?? {},
      tracker: o.tracker ?? "",
    };
  };
  const m = (quality, codec, audio, subs, extra = {}) => ({ quality, codec, audio, subtitles: subs, ...extra });
  const C411 = [
    rel({ title: "Dune.Part.Two.2024.MULTi.1080p.WEB-DL.H264-FRATERNiTY", size: 8.4 * GIB, seeders: 214, cats: [2040], age: 5, meta: m("1080p", "H264", ["multi", "fr"], ["fr"]) }),
    rel({ title: "Dune.Part.Two.2024.MULTi.2160p.UHD.BluRay.HDR.HEVC-FRATERNiTY", size: 56.2 * GIB, seeders: 98, cats: [2045], age: 9, meta: m("2160p", "HEVC", ["multi", "fr", "en"], ["fr", "en"]) }),
    rel({ title: "Oppenheimer.2023.TRUEFRENCH.1080p.BluRay.x264-NOTAG", size: 12.1 * GIB, seeders: 156, cats: [2040], age: 30, meta: m("1080p", "H264", ["fr"], []) }),
    rel({ title: "Anatomie.d.une.chute.2023.FRENCH.720p.WEB.H264-GLOUPS", size: 3.2 * GIB, seeders: 41, cats: [2040], age: 52, meta: m("720p", "H264", ["fr"], ["fr"]) }),
    rel({ title: "Poor.Things.2023.MULTi.1080p.WEB.AV1-SLAYER", size: 4.1 * GIB, seeders: 63, cats: [2040], age: 70, meta: m("1080p", "AV1", ["multi", "fr", "en"], ["fr"]) }),
    rel({ title: "Le.Comte.de.Monte-Cristo.2024.FRENCH.1080p.WEB.H264-FW", size: 5.9 * GIB, seeders: 120, cats: [2040], age: 96, meta: m("1080p", "H264", ["fr"], []) }),
    rel({ title: "Godzilla.Minus.One.2023.VOSTFR.480p.DVDRip.x264-OLD", size: 1.1 * GIB, seeders: 4, cats: [2000], age: 120, meta: m("480p", "H264", ["en"], ["fr"]) }),
    rel({ title: "The.Bear.S03E01.MULTi.1080p.WEB.H264-FW", size: 2.1 * GIB, seeders: 88, cats: [5040], age: 3, meta: m("1080p", "H264", ["multi", "fr", "en"], ["fr"]) }),
    rel({ title: "The.Bear.S03E02.MULTi.1080p.WEB.H264-FW", size: 2.3 * GIB, seeders: 71, cats: [5040], age: 3, meta: m("1080p", "H264", ["multi", "fr", "en"], ["fr"]) }),
    rel({ title: "The.Bear.S03.COMPLETE.MULTi.2160p.WEB.HEVC-PACK", size: 38 * GIB, seeders: 33, cats: [5040], age: 20, meta: m("2160p", "HEVC", ["multi"], ["fr"]) }),
    rel({ title: "Shogun.2024.S01E05.VOSTFR.1080p.WEB.H264-FLUX", size: 1.9 * GIB, seeders: 51, cats: [5040], age: 28, meta: m("1080p", "H264", ["en"], ["fr"]) }),
    rel({ title: "Daft.Punk-Random.Access.Memories-2013-FLAC-24bit", size: 1.4 * GIB, seeders: 29, cats: [3040], age: 200, meta: { format: "FLAC", bitrate: "24 bit" } }),
    rel({ title: "Radiohead-OK.Computer-1997-FLAC-REMASTER", size: 0.4 * GIB, seeders: 44, cats: [3040], age: 300, meta: { format: "FLAC", bitrate: "16 bit" } }),
    rel({ title: "Persepolis.Integrale.BD.FRENCH.CBZ", size: 180 * MIB, seeders: 12, cats: [7030], age: 400, meta: { format: "CBZ" } }),
  ];
  // Torznab polling of tr4ker: real info hashes, Tracker in metadata.
  const TORZ = [
    rel({ title: "Dune.1984.REMASTERED.MULTi.1080p.BluRay.x264-TR4", size: 9.8 * GIB, seeders: 37, cats: [2040], age: 40, tracker: "tr4ker", url: "https://tr4ker.net/torrent/dune-1984-remastered", meta: { ...m("1080p", "H264", ["multi", "fr"], ["fr"]), tracker: "tr4ker" } }),
    rel({ title: "Dune.Part.Two.2024.MULTi.1080p.WEB.H265-TR4", size: 6.2 * GIB, seeders: 58, cats: [2040], age: 14, tracker: "tr4ker", url: "https://tr4ker.net/torrent/dune-part-two-2024", meta: { ...m("1080p", "HEVC", ["multi", "fr"], ["fr"]), tracker: "tr4ker" } }),
    rel({ title: "Dune.Part.One.2021.MULTi.2160p.UHD.HDR.HEVC-TR4", size: 41 * GIB, seeders: 22, cats: [2045], age: 60, tracker: "tr4ker", url: "https://tr4ker.net/torrent/dune-part-one-2021", meta: { ...m("2160p", "HEVC", ["multi", "fr", "en"], ["fr"]), tracker: "tr4ker" } }),
  ];
  // tr4ker passkey feed (/api/rss): no info hash, rows keyed tr4ker:<guid>.
  const feedRow = (guid, title, size, seeders, slug, cat, age, freeleech) => ({
    ...rel({ title, size, seeders, age, infohash: "tr4ker:" + guid, url: "https://tr4ker.net/torrent/" + slug, dl: "https://tr4ker.net/torrent/download/" + slug + ".torrent", cats: [] }),
    metadata: { tracker: "tr4ker", guid, slug, leechers: Math.max(0, Math.round(seeders / 9)), freeleech, downloadvolumefactor: freeleech ? "0" : "1", feed_category: cat, source: "rss" },
  });
  const FEED = [
    feedRow("a1f", "Furiosa.A.Mad.Max.Saga.2024.MULTi.1080p.WEB.H264-TR4", 7.2 * GIB, 143, "furiosa-2024", "films", 2, true),
    feedRow("a2c", "Inside.Out.2.2024.MULTi.1080p.WEB.H264-TR4", 5.1 * GIB, 201, "inside-out-2-2024", "films-animation", 4, true),
    feedRow("a3d", "Kinds.of.Kindness.2024.FRENCH.720p.WEB.H264-TR4", 2.8 * GIB, 36, "kinds-of-kindness", "films", 7, false),
    feedRow("a4e", "Le.Mepris.1963.RESTORED.1080p.BluRay.x264-TR4", 11.4 * GIB, 19, "le-mepris-1963", "films-film", 12, false),
    feedRow("a5f", "Bao.2018.MULTi.1080p.BluRay.x264-TR4", 1.6 * GIB, 55, "bao-2018", "films-animation", 30, true),
    feedRow("b1a", "Fallout.S01E08.MULTi.1080p.WEB.H264-TR4", 2.6 * GIB, 99, "fallout-s01e08", "series-tv", 3, false),
    feedRow("b2b", "The.Boys.S04E06.VOSTFR.1080p.WEB.H264-TR4", 2.2 * GIB, 74, "the-boys-s04e06", "series-tv", 8, true),
    feedRow("b3c", "Arcane.S02.COMPLETE.MULTi.2160p.WEB.HEVC-TR4", 44 * GIB, 61, "arcane-s02", "series-animees", 50, false),
    feedRow("c1a", "Helldivers.2.v1.002.PC-TR4", 38 * GIB, 87, "helldivers-2", "jeux-pc", 60, false),
  ];

  // ---- subscriptions ----
  const prefsDefault = () => ({ required: {}, preferred: {}, excluded: {}, category_scopes: {}, priorities: ["quality", "codec", "audio", "subtitles", "size"], min_size: 0, min_seeders: 0, max_size: null, prefer_small: false });
  const sub = (o) => ({
    id: o.id, name: o.name, query: o.query ?? "", categories: o.categories ?? [], tracker: o.tracker ?? "c411", feed_category: o.feed_category ?? "", freeleech: o.freeleech ?? false,
    paused: o.paused ?? false, interval_minutes: o.interval ?? 30, mode: o.mode ?? "review_only", client_id: o.client_id ?? "qbit", folder: o.folder ?? "",
    preferences: o.prefs ?? prefsDefault(), include_current: false, wait_minutes: 0, replace_pending: false,
    download_hours: o.hours ?? Array.from({ length: 24 }, (_, i) => i), daily_bytes: o.daily ?? 10 * GIB, daily_torrents: 20, reserve_bytes: 10 * GIB,
    last_attempt: o.ok ? now() - o.ok * 60 : null, last_success: o.ok ? now() - o.ok * 60 : null, error: o.error ?? "", coverage: o.coverage ?? "Limited RSS discovery: c411 returns the newest releases of each source; history and gap-free updates are not guaranteed.",
  });
  const FEED_COVERAGE = "tr4ker's feed holds its 100 latest items: history and gap-free updates are not guaranteed.";
  const hdPrefs = () => ({ ...prefsDefault(), preferred: { quality: ["1080p", "2160p"], audio: ["multi"] }, required: { audio: ["fr"] }, category_scopes: { quality: [2000, 2040, 2045], audio: [2000, 2040, 2045] }, min_seeders: 5, min_size: 1 * GIB });
  const resetData = () => {
    seq = 1000;
    S.passkeyMissing = S.passkeyMissing ?? false;
    S.pool = [...C411, ...TORZ, ...FEED].map((r) => structuredClone(r));
    S.byHash = Object.fromEntries(S.pool.map((r) => [r.infohash, r]));
    S.subs = [
      sub({ id: "f-films", name: "Films FR en HD", categories: [2000], mode: "app_queue", folder: "/data/downloads/films", prefs: hdPrefs(), ok: 6, interval: 30 }),
      sub({ id: "f-bear", name: "The Bear", query: "The Bear", categories: [5000, 5040], ok: 22 }),
      sub({ id: "f-mus", name: "Musique lossless", categories: [3000], mode: "automatic_download", folder: "/data/downloads/musique", hours: [1, 2, 3, 4, 5, 6], ok: 95, interval: 360 }),
      sub({ id: "f-trfilms", name: "tr4ker : films freeleech", tracker: "tr4ker", feed_category: "films", freeleech: true, mode: "app_queue", folder: "/data/downloads/films", ok: 4, coverage: FEED_COVERAGE }),
      sub({ id: "f-trseries", name: "tr4ker : séries TV", tracker: "tr4ker", feed_category: "series-tv", ok: 75, error: "tr4ker refused the passkey (HTTP 403): check it in Settings", coverage: FEED_COVERAGE }),
      sub({ id: "f-dune", name: "Dune sur tr4ker (requête)", tracker: "tr4ker", query: "Dune", categories: [2000, 2040], paused: true, ok: 600, coverage: "Limited RSS discovery: tr4ker's Torznab returns the newest releases of each source; history and gap-free updates are not guaranteed." }),
    ];
    S.members = {};
    const add = (feed, hash, o = {}) => (S.members[feed] ??= []).push({ hash, unread: o.unread ?? false, saved: o.saved ?? false, dismissed: false, discovered: now() - (o.age ?? 1) * H });
    C411.slice(0, 7).forEach((r, i) => add("f-films", r.infohash, { unread: i < 3, saved: i === 2, age: 2 + i * 6 }));
    C411.slice(7, 11).forEach((r, i) => add("f-bear", r.infohash, { unread: i < 2, age: 2 + i * 8 }));
    C411.slice(11, 13).forEach((r, i) => add("f-mus", r.infohash, { unread: false, age: 80 + i }));
    FEED.slice(0, 5).forEach((r, i) => add("f-trfilms", r.infohash, { unread: i < 3, saved: i === 1, age: 1 + i * 3 }));
    FEED.slice(5, 8).forEach((r, i) => add("f-trseries", r.infohash, { unread: i === 0, age: 70 + i }));
    TORZ.forEach((r, i) => add("f-dune", r.infohash, { unread: i === 1, age: 500 + i }));
    S.queue = { [C411[1].infohash]: "queued" };
    S.inClients = { [C411[0].infohash]: ["qbit"], [C411[2].infohash]: ["qbit", "seedbox"], [C411[7].infohash]: ["seedbox"] };
    S.clientStates = { [C411[0].infohash]: { qbit: "seeding" }, [C411[2].infohash]: { qbit: "seeding", seedbox: "downloading" }, [C411[7].infohash]: { seedbox: "paused" } };
    S.decisions = [
      { feed: "f-films", infohash: C411[0].infohash, work: "dune part two", status: "queued", reason: "Best match for this work.", queue_key: "q1", decided: now() - 5 * H },
      { feed: "f-films", infohash: C411[1].infohash, work: "dune part two", status: "queued", reason: "Best match for this work.", queue_key: "q2", decided: now() - 8 * H },
      { feed: "f-films", infohash: C411[6].infohash, work: "godzilla minus one", status: "blocked", reason: "Required audio is missing.", queue_key: "", decided: now() - 20 * H },
      { feed: "f-mus", infohash: C411[11].infohash, work: "daft punk", status: "baseline", reason: "Available before activation; include-current is disabled.", queue_key: "", decided: now() - 90 * H },
      ...FEED.slice(0, 5).map((r) => ({ feed: "f-trfilms", infohash: r.infohash, work: "", status: "blocked", reason: "tr4ker's feed carries no info hash. Review the item in the inbox.", queue_key: "", decided: now() - 3 * H })),
    ];
    S.previews = new Set();
    S.selections = [];
    S.refreshed = 0;
  };
  const S = {};

  // ---- evaluate (mirrors feeds.evaluate) ----
  const arr = (v) => (Array.isArray(v) ? v : [v]);
  const evaluate = (row, prefs) => {
    const p = { ...prefsDefault(), ...prefs };
    const applicable = (k) => !(p.category_scopes[k] || []).length || !(row.categories || []).length || row.categories.some((c) => p.category_scopes[k].includes(c));
    const blockers = [], unknown = [];
    if (row.size <= 0 && (p.min_size || p.max_size != null)) unknown.push("size");
    else if (row.size < p.min_size || (p.max_size != null && row.size > p.max_size)) blockers.push("size outside required range");
    if (row.seeders < p.min_seeders) blockers.push("minimum seeders");
    for (const k of new Set([...Object.keys(p.required), ...Object.keys(p.excluded)])) {
      if (!applicable(k)) continue;
      const v = row.metadata?.[k];
      if (v == null) { unknown.push(k); continue; }
      const actual = new Set(arr(v).map((x) => String(x).toLowerCase()));
      if (p.required[k] && !p.required[k].some((x) => actual.has(x.toLowerCase()))) blockers.push(`required ${k}`);
      if ((p.excluded[k] || []).some((x) => actual.has(x.toLowerCase()))) blockers.push(`excluded ${k}`);
    }
    const scores = {};
    for (const [k, pref] of Object.entries(p.preferred)) {
      if (!applicable(k)) continue;
      const actual = new Set(arr(row.metadata?.[k]).map((x) => String(x).toLowerCase()));
      const i = pref.findIndex((x) => actual.has(x.toLowerCase()));
      scores[k] = i < 0 ? pref.length : i;
    }
    const rank = p.priorities.map((k) => (k === "size" && p.prefer_small ? [Number(row.size <= 0), Math.max(row.size, 0)] : k === "seeders" ? [Number(row.seeders < 0), -Math.max(row.seeders, 0)] : scores[k] ?? 0));
    return { eligible: !blockers.length && !unknown.length, excluded: blockers, unknown, rank, scores };
  };

  // ---- source search for the editor's live preview ----
  const descendants = (ids) => Object.keys(CATEGORIES).map(Number).filter((id) => ids.includes(id) || ids.includes(CATEGORIES[id].parent));
  const TR4 = () => TR4KER_CATEGORIES;
  const slugTree = (slug) => {
    const c = TR4().find((x) => x.slug === slug);
    return c ? [c.slug, ...TR4().filter((x) => x.parent === c.id).map((x) => x.slug)] : [slug];
  };
  const usesFeed = (s) => s.tracker === "tr4ker" && !s.query;
  function validate(s) {
    if (s.tracker !== "tr4ker" && (s.feed_category || s.freeleech)) throw Error("A feed category and freeleech belong to a tr4ker subscription.");
    if (s.tracker === "tr4ker" && (s.query || s.categories.length) && (s.feed_category || s.freeleech)) throw Error("A tr4ker subscription follows its feed (category slug, freeleech) or polls a query (Torznab), not both.");
    if (s.tracker === "tr4ker" && !s.query && s.categories.length) throw Error("tr4ker's feed filters by category slug; Torznab IDs need a query.");
    if (s.mode !== "review_only" && !s.folder) throw Error("Choose a Download Folder for queue rules.");
  }
  const signature = (s) => JSON.stringify({ ...s, id: undefined });
  function preview(s) {
    validate(s);
    let rows;
    if (usesFeed(s)) {
      if (S.passkeyMissing) throw Error("Add the tr4ker passkey in Settings first.");
      const slugs = s.feed_category ? slugTree(s.feed_category) : null;
      rows = S.pool.filter((r) => r.metadata.source === "rss" && (!slugs || slugs.includes(r.metadata.feed_category)) && (!s.freeleech || r.metadata.freeleech));
    } else {
      if (/erreur|error/i.test(s.query)) throw Error("The indexer answered HTTP 503. Try again in a few minutes.");
      const words = s.query.toLowerCase().split(/\s+/).filter(Boolean);
      const cats = s.categories.length ? descendants(s.categories) : null;
      const from = s.tracker === "c411" ? C411 : TORZ;
      rows = from.map((r) => S.byHash[r.infohash]).filter((r) => words.every((w) => r.title.toLowerCase().replace(/\./g, " ").includes(w)) && (!cats || r.categories.some((c) => cats.includes(c))));
    }
    S.previews.add(signature(s));
    return {
      rows: structuredClone(rows), limited: true, pages: usesFeed(s) ? 1 : 3,
      coverage: usesFeed(s) ? FEED_COVERAGE : "Limited RSS discovery: results are paged; history and gap-free updates are not guaranteed.",
      evaluations: Object.fromEntries(rows.map((r) => [r.infohash, evaluate(r, s.preferences)])),
    };
  }

  // ---- inbox ----
  const unreadOf = (id) => (S.members[id] || []).filter((x) => x.unread && !x.dismissed).length;
  const inbox = (feedId, unread, saved) => {
    const out = {};
    for (const [feed, list] of Object.entries(S.members)) {
      if (feedId && feed !== feedId) continue;
      for (const x of list) {
        if (x.dismissed || (unread && !x.unread) || (saved && !x.saved)) continue;
        const r = (out[x.hash] ??= { ...structuredClone(S.byHash[x.hash]), discovered_at: x.discovered, unread: false, saved: false, feeds: [], baseline: false });
        r.unread ||= x.unread; r.saved ||= x.saved; r.feeds.push(feed);
      }
    }
    return Object.values(out).sort((a, b) => b.discovered_at - a.discovered_at).map((r) => ({
      ...r, in_clients: S.inClients[r.infohash] || [], client_inventory_unknown: S.unavailable ? ["seedbox"] : [],
      queue_status: S.queue[r.infohash] || "", queued: Boolean(S.queue[r.infohash]),
      client_states: S.clientStates[r.infohash] || {},
    }));
  };
  const getSub = (id) => { const s = S.subs.find((x) => x.id === id); if (!s) throw Error("Unknown RSS subscription."); return s; };
  const refresh = (id) => {
    const s = getSub(id);
    s.last_attempt = now();
    if (usesFeed(s) && S.passkeyMissing) { s.error = "Add the tr4ker passkey in Settings first."; throw Error(s.error); }
    s.error = ""; s.last_success = now();
    const have = new Set((S.members[id] || []).map((x) => x.hash));
    const p = preview({ ...s, id: "" });
    const fresh = p.rows.find((r) => !have.has(r.infohash));
    if (fresh) (S.members[id] ??= []).unshift({ hash: fresh.infohash, unread: true, saved: false, dismissed: false, discovered: now() });
    return { status: "refreshed", added: fresh ? 1 : 0 };
  };
  const inventory = () => ({
    hashes: Object.keys(S.inClients).sort(), clients: Object.fromEntries(CLIENTS.map((c) => [c.id, Object.keys(S.inClients).filter((h) => S.inClients[h].includes(c.id))])),
    unavailable_clients: [], works: ["dune part two", "godzilla minus one"], unknown_work_hashes: [],
    work_identity_coverage: "Only verified identifiers from known feed releases. Other client items are not compared.",
  });

  const community = {
    browse: () => ({ items: [
      { id: "c1", version_id: "v1", title: "Films français HD", description: "Préfère 1080p, exige l’audio français.", version: 3, license: "CC-BY-4.0", bytes: 2100 },
      { id: "c2", version_id: "v2", title: "Séries VOSTFR", description: "Sous-titres français, 1080p.", version: 1, license: "CC0-1.0", bytes: 1800 },
    ] }),
    updates: () => ({ items: [] }),
    download: (b) => ({ review: "rev-" + b.id, rules: [{ name: "Films français HD", query: "", categories: [2000], preferences: {}, include: [], exclude: [] }] }),
    apply: () => { const id = "f-imp" + (++seq); S.subs.push(sub({ id, name: "Films français HD (importé)", categories: [2000], paused: true })); return { data: { rules: [{ name: "Films français HD", query: "", categories: [2000], preferences: {}, include: [], exclude: [] }] } }; },
    cancel: () => ({}),
    prepare: (b) => ({ review: "prep1", metadata: b.metadata, content: b.data, bytes: 512, sha256: "9f2c…" }),
    publish: () => ({ status: "published", version: 1 }),
    history: () => ({ items: [] }),
  };

  function api(path, body, method) {
    body = body ?? {};
    const url = new URL(path, "http://x/");
    const parts = url.pathname.replace(/^\//, "").split("/");
    const q = url.searchParams;
    if (parts[0] === "community-items") return community[parts[1]](body);
    // community-items.js picks its route from the page URL; outside the app it takes this one.
    if (parts[0] === "community-site" && parts[1]?.startsWith("items-")) return community[parts[1].slice(6)](body);
    if (path === "feed-options") return { categories: Object.fromEntries(Object.entries(CATEGORIES).map(([k, v]) => [k, v])), clients: structuredClone(CLIENTS) };
    if (parts.join("/") === "feeds") {
      if (method === "GET") return S.subs.map((s) => ({ ...structuredClone(s), unread_count: unreadOf(s.id) }));
      const def = body.subscription;
      validate(def);
      const old = def.id ? S.subs.find((x) => x.id === def.id) : null;
      if ((!old || old.query !== def.query || JSON.stringify(old.categories) !== JSON.stringify(def.categories)) && !S.previews.has(signature(def))) throw Error("Preview this definition before saving.");
      if (def.folder && !CLIENTS.find((c) => c.id === def.client_id)?.folders.includes(def.folder)) throw Error("Choose a configured Download Folder for this Torrent Client.");
      if (def.mode === "automatic_download" && !body.approve_automatic) throw Error("Automatic downloads need explicit owner approval of this rule.");
      const saved = { ...(old || {}), ...def, id: old?.id || "f-" + (++seq), last_attempt: old?.last_attempt ?? null, last_success: old?.last_success ?? null, error: old?.error ?? "", coverage: usesFeed(def) ? FEED_COVERAGE : old?.coverage || "Limited RSS discovery: results are paged; history and gap-free updates are not guaranteed." };
      if (old) {
        const moved = old.query !== def.query || JSON.stringify(old.categories) !== JSON.stringify(def.categories) || old.tracker !== def.tracker || old.feed_category !== def.feed_category || old.freeleech !== def.freeleech;
        if (moved) { S.members[saved.id] = []; saved.last_success = null; saved.error = ""; }
        S.subs[S.subs.indexOf(old)] = saved;
      } else {
        S.subs.push(saved);
        saved.last_success = now(); saved.last_attempt = now();
        S.members[saved.id] = preview({ ...saved, id: "" }).rows.slice(0, 3).map((r, i) => ({ hash: r.infohash, unread: true, saved: false, dismissed: false, discovered: now() - i * 600 }));
      }
      return saved;
    }
    if (parts.join("/") === "feeds/preview") return preview(body);
    if (parts.join("/") === "feeds/judge") return { evaluations: Object.fromEntries(body.rows.filter((r) => r.infohash).map((r) => [r.infohash, evaluate(r, body.subscription.preferences)])) };
    if (parts[0] === "feeds" && parts.length >= 2) {
      const id = parts[1];
      if (parts.length === 2 && method === "DELETE") { getSub(id); S.subs = S.subs.filter((x) => x.id !== id); delete S.members[id]; return { deleted: id }; }
      const action = parts[2];
      if (action === "decisions") return structuredClone(S.decisions.filter((d) => d.feed === id));
      if (action === "pause") { getSub(id).paused = q.get("paused") === "true"; return { paused: getSub(id).paused }; }
      if (action === "refresh") return refresh(id);
      if (action === "process") {
        const s = getSub(id);
        if (s.paused || s.mode === "review_only") return { rows: [], inventory: inventory() };
        const rows = inbox(id).map((r) => ({ feed: id, infohash: r.infohash, status: usesFeed(s) ? "blocked" : "queued", reason: usesFeed(s) ? "tr4ker's feed carries no info hash. Review the item in the inbox." : "Best match for this work." }));
        return { rows, inventory: inventory() };
      }
    }
    if (parts[0] === "feed-inbox") {
      if (parts.length === 1) return inbox(q.get("feed_id") || "", q.get("unread") === "true", q.get("saved") === "true");
      if (parts[1] === "mark") {
        const map = { read: (x) => (x.unread = false), unread: (x) => (x.unread = true), save: (x) => (x.saved = true), unsave: (x) => (x.saved = false), dismiss: (x) => (x.dismissed = true), restore: (x) => (x.dismissed = false) };
        for (const [feed, list] of Object.entries(S.members)) if (!body.feed_id || feed === body.feed_id) for (const x of list) if (body.hashes.includes(x.hash)) map[body.action](x);
        return { updated: body.hashes.length };
      }
      if (parts[1] === "client") {
        // Preview only: the app has no such route yet; it would pause or resume in each client.
        for (const h of body.hashes) for (const c of S.inClients[h] || []) (S.clientStates[h] ||= {})[c] = body.action === "pause" ? "paused" : "seeding";
        return { updated: body.hashes.length };
      }
      if (parts[1] === "compare") { for (const h of Object.keys(S.byHash)) if (S.byHash[h].title.includes("Oppenheimer")) S.inClients[h] = body.client_ids || []; return inventory(); }
    }
    if (parts[0] === "feed-selections") {
      if (parts.length === 1 && method === "GET") return S.selections.map((x) => ({ id: x.id, name: x.name, created: x.created, hashes: x.hashes }));
      if (parts.length === 1) { const x = { id: "sel" + (++seq), name: body.name || "RSS selection", hashes: body.hashes, created: now(), rows: body.hashes.map((h) => S.byHash[h]), indexer_url: "https://c411.example", client_ids: [] }; S.selections.unshift(x); return structuredClone(x); }
      const x = S.selections.find((s) => s.id === parts[1]); if (!x) throw Error("Unknown RSS selection.");
      if (parts[2] === "enqueue") {
        const c = CLIENTS.find((c) => c.id === body.client_id);
        if (!c || !c.folders.includes(body.folder)) throw Error("Choose a configured Download Folder.");
        x.hashes.forEach((h) => (S.queue[h] = "queued"));
        return { queued: x.hashes.length, client_id: body.client_id, folder: body.folder };
      }
      return structuredClone(x);
    }
    throw Error("Unknown RSS operation.");
  }

  // ---- what the Web shell does around the panel ----
  const env = { mode: "web", client: "qbit", language: "fr", theme: "dark", active: true, command: null };
  const dispatch = () => window.dispatchEvent(new CustomEvent("feeds-environment", { detail: { ...env } }));
  const details = (row) => {
    // The shell opens Search's details tabs here; the preview shows a plain stand-in.
    let d = document.getElementById("preview-details");
    if (!d) { d = document.createElement("dialog"); d.id = "preview-details"; document.body.append(d); }
    const lines = [["Titre", row.title], ["Tracker", row.tracker || row.metadata?.tracker || "c411"], ["Info hash", row.infohash], ["Taille", row.size], ["Seeders", row.seeders], ["Page", row.details_url || "—"]];
    d.replaceChildren(Object.assign(document.createElement("p"), { className: "muted", textContent: "Aperçu : dans l’application, cette fenêtre est le panneau de détails de la recherche." }), ...lines.map(([k, v]) => Object.assign(document.createElement("p"), { textContent: `${k} : ${v}` })), Object.assign(document.createElement("button"), { textContent: "Fermer", onclick: () => d.close() }));
    d.showModal();
    return {};
  };
  const delay = (v) => new Promise((r) => setTimeout(() => r(v), 60));
  window.previewBackend = {
    state: S,
    environment: () => dispatch(),
    set(key, value) { env[key] = value; if (key === "language" || key === "theme") dispatch(); },
    reset() { resetData(); dispatch(); },
    async request(name, path, body) {
      if (body._client !== undefined && body._client !== env.client) throw Error("The target client changed.");
      if (path === "details") return delay(details(body.row));
      if (path !== "api") throw Error("Unknown RSS operation.");
      return delay(structuredClone(api(body.path, body.body, body.method)));
    },
  };
  resetData();
})();
