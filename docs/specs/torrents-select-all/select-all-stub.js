"use strict";
/* The host the Torrents panel normally talks to, replaced by canned answers.

   panel/transport.js is left out of the preview and this file supplies TLPanel.connect in
   its place, so torrents/transport.js resolves to the stub below. Nothing here reaches a
   torrent client or the application. `list` filters, sorts and pages the fixture the way
   `TorrentsWorkspace.list` does (src/torrentlinker/torrents_workspace.py); `match` is the
   one action the proposal adds, and `list` takes any `limit` (the app caps it at 200). */

const PREVIEW = (() => {
  const films = ["Dune", "Heat", "Alien", "Arrival", "Le Samouraï", "Blade Runner", "Amélie", "Oldboy", "Drive", "Inception", "La Haine", "Parasite", "Memento", "Zodiac", "Prisoners", "Sicario"];
  const shows = ["The Wire", "Dark", "Le Bureau des légendes", "Severance", "Fargo", "Chernobyl"];
  const qualities = ["1080p.BluRay.x264", "2160p.WEB-DL.DDP5.1.HDR.H265", "720p.HDTV.x264", "1080p.WEB.H264", "MULTi.1080p.BluRay.x265"];
  const states = ["seeding", "seeding", "seeding", "seeding", "paused", "downloading", "checking", "error"];
  const trackers = ["c411.org", "c411.org", "c411.org", "tr4ker.net", "other.example"];
  const categories = [["Films"], ["Films", "4K"], ["Séries"], ["Musique"], []];
  const tags = [["c411"], ["archive"], [], ["c411", "favori"], []];
  const clients = [{ id: "default", name: "qBittorrent" }];
  const capabilities = ["pause", "resume", "recheck", "remove", "delete", "skip_files", "want_files", "reannounce", "limits", "category", "location"];
  let seed = 7;
  const random = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
  const rows = [];
  for (let i = 0; i < 2412; i++) {
    const show = i % 3 === 0,
      title = show ? shows[i % shows.length] : films[i % films.length],
      year = 1990 + (i % 35),
      name = show
        ? `${title}.S0${1 + (i % 5)}E${String(1 + (i % 12)).padStart(2, "0")}.${qualities[i % qualities.length]}`
        : `${title.replaceAll(" ", ".")}.${year}.${qualities[i % qualities.length]}`,
      hash = (i.toString(16).padStart(8, "0") + "a1b2c3d4e5f60718293a4b5c6d7e8f90").slice(0, 40),
      status = states[i % states.length],
      tracker = trackers[i % trackers.length],
      c411 = tracker === "c411.org",
      size = Math.round((0.7 + random() * 40) * 1024 ** 3),
      known = c411 && i % 4 !== 0,
      total_seeds = Math.floor(random() * 60),
      total_peers = Math.floor(random() * 15);
    rows.push({
      key: `default:${hash}`,
      hash,
      name,
      client_id: "default",
      client_name: "qBittorrent",
      folder: show ? `/data/series/${title}` : "/data/films",
      categories: [categories[i % categories.length]].filter((c) => c.length),
      trackers: [`https://${tracker}/announce`],
      tags: tags[i % tags.length],
      status,
      progress: status === "downloading" ? random() : status === "checking" ? 0.4 : 1,
      size,
      ratio: random() * 4,
      download: status === "downloading" ? Math.round(random() * 4e6) : 0,
      upload: status === "seeding" ? Math.round(random() * 9e5) : 0,
      seeds: Math.min(total_seeds, Math.floor(random() * 8)),
      peers: Math.min(total_peers, Math.floor(random() * 4)),
      total_seeds,
      total_peers,
      note: known ? 2 + random() * 3 : null,
      zen: known ? random() * 6 : null,
      weight: c411 ? Math.min(1, size / 1024 ** 3 / 40) : null,
      c411,
      seedtime: (i % 400) + random(),
      capabilities,
      observed_at: Date.now() / 1000,
    });
  }
  const group = (url) => new URL(url).hostname;
  function matching(body) {
    const q = (body.q || "").toLowerCase();
    const ranges = [
      ["size_min", "size", true],
      ["size_max", "size", false],
      ["note_min", "note", true],
      ["zen_min", "zen", true],
      ["weight_min", "weight", true],
      ["seed_max", "total_seeds", false],
      ["days_min", "seedtime", true],
    ];
    return rows.filter((r) => {
      if (q && !r.name.toLowerCase().includes(q) && q !== r.hash) return false;
      if (body.hashes?.length && !body.hashes.includes(r.hash)) return false;
      if (body.state && r.status !== body.state) return false;
      if (body.tracker && !r.trackers.map(group).includes(body.tracker)) return false;
      if (body.category && !r.categories.map((c) => c.join(" / ")).includes(body.category)) return false;
      if (body.tag && !r.tags.includes(body.tag)) return false;
      if (body.scope && r.c411 !== (body.scope === "c411")) return false;
      for (const [field, key, minimum] of ranges) {
        if (body[field] === undefined) continue;
        const v = r[key];
        if (v == null || (minimum ? v < body[field] : v > body[field])) return false;
      }
      return true;
    });
  }
  function sorted(found, body) {
    const key = { seeds: "total_seeds", peers: "total_peers" }[body.sort] || body.sort || "name";
    const known = found.filter((r) => r[key] != null),
      unknown = found.filter((r) => r[key] == null);
    known.sort((a, b) => {
      const x = typeof a[key] === "string" ? a[key].toLowerCase() : a[key],
        y = typeof b[key] === "string" ? b[key].toLowerCase() : b[key];
      return (x > y) - (x < y);
    });
    if (body.descending) known.reverse();
    return known.concat(unknown);
  }
  const answers = {
    preferences: () => ({ columns: {}, widths: {} }),
    list(body) {
      const found = sorted(matching(body), body),
        limit = body.limit || 100,
        offset = Math.min(body.offset || 0, Math.max(0, Math.floor((found.length - 1) / limit)) * limit);
      return {
        rows: found.slice(offset, offset + limit),
        total: found.length,
        offset,
        client_errors: [],
        clients,
        trackers: [...new Set(rows.flatMap((r) => r.trackers.map(group)))].sort(),
        categories: [...new Set(rows.flatMap((r) => r.categories.map((c) => c.join(" / "))))].sort(),
        tags: [...new Set(rows.flatMap((r) => r.tags))].sort(),
        summary: {
          count: rows.length,
          download: rows.reduce((s, r) => s + r.download, 0),
          upload: rows.reduce((s, r) => s + r.upload, 0),
        },
        observed_at: Date.now() / 1000,
      };
    },
    // Proposed: every torrent the current filters match, across all pages, in one answer.
    match: (body) => ({ rows: sorted(matching(body), body) }),
    review(body) {
      const keys = new Set(body.items.map((i) => `${i.client_id}:${i.hash}`));
      return { token: "preview", rows: rows.filter((r) => keys.has(r.key)) };
    },
    apply(body) {
      const keys = new Set(body.items.map((i) => `${i.client_id}:${i.hash}`));
      for (const r of rows)
        if (keys.has(r.key)) {
          if (body.action === "pause") r.status = "paused";
          if (body.action === "resume") r.status = r.progress < 1 ? "downloading" : "seeding";
        }
      if (["remove", "delete"].includes(body.action))
        for (let i = rows.length - 1; i >= 0; i--) if (keys.has(rows[i].key)) rows.splice(i, 1);
      return { rows: [{ client_id: "default", hash: body.items[0].hash, outcome: "sent" }].concat(body.items.length > 1 ? [{ client_id: "default", hash: `+ ${body.items.length - 1}`, outcome: "sent" }] : []) };
    },
    files: () => ({ files: [{ index: 0, name: "release.mkv", size: 8 * 1024 ** 3, wanted: true }] }),
    "audit-list": () => ({ reports: [] }),
    "target-client": () => ({}),
  };
  return { answers, rows };
})();

window.TLPanel.connect = () =>
  Promise.resolve(async (action, body) => {
    await new Promise((resolve) => setTimeout(resolve, action === "list" ? 120 : 60));
    const answer = PREVIEW.answers[action];
    if (!answer) throw Error("Non disponible dans l’aperçu.");
    return structuredClone(answer(body || {}));
  });
window.torrentsReady = () =>
  window.dispatchEvent(
    new CustomEvent("torrents-environment", {
      detail: { mode: "web", client: "default", language: "fr", theme: "dark", active: true },
    }),
  );
