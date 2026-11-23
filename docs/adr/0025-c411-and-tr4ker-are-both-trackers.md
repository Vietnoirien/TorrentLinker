# c411 and tr4ker are both Trackers

Until now c411 was the only site TorrentLinker fully supports. Search, Catalogue, Profile, Upload, Zen and the tracker community all assume it, and every other Indexer is search-only (ADR-0024). The Owner also belongs to tr4ker.net and wants it supported as fully as c411, not just as one more Cross-seed Indexer. The research is in docs/research/tr4ker-integration.md, with its inventory, community and credits notes beside it.

A **Tracker** is now a site the app fully supports: an account, a native API, Upload rules and an economy. Each Tracker owns one Indexer. The Trackers are c411 and tr4ker. Prowlarr, Jackett and hand-added Indexers stay search-only. The glossary's warning against "Tracker" for the search API still holds.

Settings > Connection gets one tab per Tracker (c411, tr4ker) and an Indexers tab for the search-only list and hub import. A tr4ker Indexer the user already imported from Prowlarr or Jackett is recognised by host. The tr4ker tab offers to adopt it, keeping its key and Cross-seed history, and it then leaves the Indexers list, so nothing searches tr4ker twice.

Discovery screens merge both Trackers. Search, Media, Catalogue, Reseed and Cross-seed show results from both, each row badged with its Tracker. The same release on both is two rows, because tr4ker adds `info.source = "TR4KER"` and c411 adds `C411`, so the info-hashes differ. Account screens (Profile, Upload, Plans) have a Tracker picker. When the app picks a release itself (Media, Requests, RSS), ReleaseScore decides first, then a Tracker order set in Settings, c411 first by default. The download then reaches the other Tracker through automatic Cross-seed (ADR-0024), with no path of its own.

Authentication follows c411's split. The tr4ker API key covers Torznab search, Cross-seed and `.torrent` downloads. It is already in the keyring as `indexer-key-tr4ker`. The passkey covers RSS and the Announce URL. Native JSON (torrent detail, profile, stats, publishing, community) needs a signed-in browser session, so it goes through the companion extension in a tr4ker tab, with tr4ker's own origin, endpoint allowlist and account binding. Session cookies never leave the browser. `/api/me` returns the API key and passkey, so the app filters it before logging or storing anything, and it never calls `/api/me/api-key`, which regenerates the key.

Everything tracker-specific gets a Tracker namespace: Catalogue, crawl state, unavailable torrents, category options, caches, queued downloads, Profile snapshots and Announce URLs. Existing rows migrate as c411. A same-hash torrent or a reused category ID on the other Tracker never overwrites them.

The tr4ker Catalogue is built by paging `/api/torznab/all` by offset (100 a page, paced, honouring `Retry-After`), then refreshing from the newest. This feed includes torrents without seeders, which Cross-seed and Reseed need. The native `/api/torrents` listing caps its total at 1001, and two filtered queries returned HTTP 500 during research, so it is used for detail only. No tr4ker snapshot ships with the app. Coverage is measured, never assumed.

Members keep their Permissions on both Trackers (ADR-0022). Account actions stay the Owner's on each.

Live checks that act on an account (a download that enters history, a publication, a comment, a reseed request) are a human step. The Owner designates the item and approves the call. Tests use sanitized fixtures from real responses only.

## Considered Options

- **Keep tr4ker as a plain Indexer**: rejected; it would never get detail, Catalogue, Profile, Upload or community.
- **One global switch for the active Tracker**: rejected; it hides the other Tracker's results, and Cross-seed between them is the main gain.
- **Store a tr4ker session cookie in the app**: rejected; the companion already keeps sessions inside the browser for c411.
- **Native paging for the Catalogue**: rejected for the 1001 cap and the server errors on filtered queries.
- **Per-Tracker Permissions**: rejected as more setup than the Owner needs today.

## Consequences

`Settings.indexer`, `indexer_for` and every feature bound to the primary Indexer take a Tracker. The companion's manifest, background tab handling, pairing and Profile checks stop assuming `https://c411.org`. Store tables gain a Tracker column and a migration. The glossary gains Tracker, and the c411-only terms (Owner, Upload Category, Draft, Catalogue, Zen) say which Tracker they belong to.
