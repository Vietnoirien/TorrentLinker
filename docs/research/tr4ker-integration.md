# tr4ker integration research

Observed on 23 November 2026. This is an integration investigation, not a declaration of official support. See [the application inventory](tr4ker-integration-inventory.md) for local source references and every existing feature that needs provider support.

## Evidence and credentials

Most exploration used sequential headless HTTPS requests after an initial signed-in Brave wiki inspection. Only `TR4KER_session` was extracted from the tr4ker cookie rows. A temporary cookie jar lives outside the repository in `/tmp/torrentlinker-tr4ker-session/cookies.txt`, inside a mode-0700 directory with a mode-0600 cookie file. It remains a live credential until expired or deleted. The session jar must clear the exported expiry of zero before requests prepares the Cookie header. Loading with `ignore_expires=True` alone does not make requests send an expired cookie.

An anonymous wiki request returned HTTP 403. The wiki shell returned HTTP 200 without proving authentication; signed-in native torrent and wiki JSON requests subsequently confirmed session access. An early 401 was caused by the temporary jar expiration handling, not evidence of browser fingerprint binding.

The user authorized reading and using the existing API key, then saving it in their keyring. It was stored through `torrentlinker.credentials.set_secret(Settings.indexer_secret('tr4ker'), key)` and verified with `get_secret`. The OS backend is `keyring.backends.SecretService.Keyring`, service `torrentlinker`, entry `indexer-key-tr4ker`. No API key value appears in the saved research. This prepares the credential name for an Indexer whose ID is `tr4ker`; it does not create that Indexer in Settings or activate full tracker support.

Three separate mechanisms exist: browser session for native JSON, API key for Torznab, and passkey for RSS and announces. Recovery passphrase is another credential entirely. Do not substitute one for another. `/api/me` includes both `api_key` and `passkey`, so account responses must be filtered before logging or storing. `/api/me/api-key` is a POST generation/regeneration action in the frontend, not a safe credential-discovery operation. It was never called.

Source provenance is in [tr4ker-research-sources.json](tr4ker-research-sources.json). Frontend contracts below were read from the first-party [JavaScript bundle](https://tr4ker.net/assets/V6OUW5OR.js), whose digest is recorded there. These are observed private frontend contracts, without a compatibility guarantee.

## Feature readiness

| TorrentLinker feature | tr4ker evidence | Integration implication |
| --- | --- | --- |
| Cross-seed / Candidate discovery | API-key-only Torznab search returned 200 and an item | Use `/api/torznab/all`, including zero-seeder torrents |
| Ordinary search / media discovery | Torznab modes and metadata IDs advertised, basic search verified | Implement advertised modes, test each mode separately |
| Torrent detail / file matching | Native detail returned info hash and full files array | Map native slug, numeric ID and hash separately |
| Download / Reseed | Torznab enclosure points at native slug download with API key | Preserve returned link securely; actual binary not downloaded |
| Catalogue / background refresh | Native pages 1 and 2 verified; total capped | Do not treat reported total as a complete catalogue count |
| RSS | Signed-in wiki UI supplies global/category/freeleech links | Passkey auth; feed parsing and pagination unverified |
| Profile / ratio / credits | Native account and stats contracts verified | Separate tr4ker economy from c411 Zen |
| Upload / import | Frontend builds `private=1`, `source=TR4KER`, sends multipart publish | Separate provider workflow; no remote draft API established |
| Tracker updates | Frontend announce construction observed | Do not reuse c411 announce hosts or rewrite info dictionaries |
| Companion | Existing app only permits c411 | Add explicit origin and endpoint allowlists; keep browser cookies inside browser in production |

## Torznab

The official [automation guide](https://tr4ker.net/wiki/prowlarr-radarr-sonarr) documents base origin `https://tr4ker.net`, default API path `/api`, legacy `/api/torznab`, and full catalogue `/api/torznab/all`. The guide labels the legacy path deprecated but later examples still mention it. Prefer `/api` for ordinary acquisition and `/api/torznab/all` for Cross-seed and reseed discovery. The [cross-seed guide](https://tr4ker.net/wiki/l-outil-cross-seed) explicitly says the latter includes torrents without seeders. We verified working caps and searches at both preferred routes, but did not independently verify zero-seeder coverage.

A session-only request to `/api/torznab/all?t=caps` returned 401. Adding the authorized API key returned XML 200. An additional request with a fresh HTTP client and API key only, without a browser cookie, also returned search results. `apikey` is a URL query parameter. Redact it from exceptions, cache keys, queue metadata, copied links and diagnostics.

Captured capabilities in [default caps](tr4ker-torznab-default-caps.xml) and [all caps](tr4ker-torznab-all-caps.xml): maximum page size 100, default 50; generic, TV, movie, music and book searches. TV advertises `season`, `ep`, `tvdbid`, `imdbid`; movie advertises `imdbid`, `tmdbid`; music advertises `artist`, `album`. All advertise `q`, `cat`, `limit`, `offset`, `apikey`. Advertisement is not proof of each filter's behavior.

Small searches for Big Buck Bunny returned RSS items with `title`, `guid`, `link`, `comments`, `pubDate`, enclosure and namespaced Torznab attributes. Observed attributes include category, size, seeders, leechers, peers, grabs, infohash, download/upload volume factors, and optional tmdbid. Both Newznab and Torznab response namespaces can expose pagination metadata; avoid double-counting. Observed total was 3, offset 0. One result was in Audio, so do not interpret the full-text query as an exact release match. A subsequent `cat=2000` query returned a movie result. See [observations](tr4ker-torznab-observations.json).

The enclosure uses `https://tr4ker.net/api/torrents/<slug>/download?apikey=<redacted>`. Only its origin, path and query parameter names were retained. No torrent was downloaded or added to a Torrent Client.

## Native API

All requests in this section are same-origin and session authenticated unless under `/api/public/`. The frontend uses `credentials: include`; inspected normal requests did not add a bearer token or CSRF header. Absence in the frontend is not proof that every mutation is CSRF-free.

- `GET /api/public/categories`: flat records with numeric `id`, string `slug`, name, optional `parent_id`, icon, sort order. Save the full tree separately from Torznab categories. Snapshot: [categories](tr4ker-categories.json).
- `GET /api/public/features`: runtime switches including upload, favorites, user-stats, requests, exclusivity, freeleech tokens. Read capabilities dynamically instead of treating all features as always available.
- `GET /api/torrents?limit=2` and `page=2`: 200, correct page values. Responses contain `limit`, `page`, `torrents`, `total`, `total_capped`. Observed `total=1001`, `total_capped=true`, so a complete-catalogue crawl cannot rely on this total.
- `GET /api/torrents/<slug>`: 200; numeric ID, canonical slug, 40-character `info_hash`, bytes, file count, piece length, category/subcategory metadata, description/NFO/tech XML, tags, optional media IDs, release metadata, status and freeleech flags. Files use `path` and `size_bytes`. Full field types are in [detail schema](tr4ker-torrent-detail-schema.json). Nullable metadata and anonymous uploaders need handling.
- `GET /api/torrents/<slug>/related`: frontend-observed only.
- `GET /api/torrents/<slug>/reseed`: 200; can_request, reason, seeders, completers, last request/notification state, is_uploader and next/available timestamps. POST to the same URL sends a reseed request to members and was not called.
- `GET /api/me`: 200, root account fields include ID, username, role/power, byte counters, bonuses, money, preferences, keys, freeleech and TOTP state. Saved only [field types](tr4ker-account-root-schema.json).
- `GET /api/me/stats`: 200, summary has uploaded/downloaded, raw counters, bonus counters, money, ratio_warning; also freeleech_count, snapshots and statistics. The observed account had empty snapshots and null statistics, so populated contracts remain unknown.
- `GET /api/me/downloads?limit=2&filter=all`: 200, items, limit, page, total, total_pages. Observed items were empty. Do not infer populated history item shape. Stats/history field types: [account schemas](tr4ker-account-schemas.json).

Frontend search builder supports `q`, category slug `cat`, `page`, `limit`, period, sort/order, genre, language, release_type, season, decade, uploader, team, tags, tmdb_id, imdb_id, tvdb_id, size_max in bytes, source, favorites, exclusive and freeleech. `search_in` may be title, description or omitted for both. Sort values observed include recent, title, size, seeders, leechers, completed. Native page pagination differs from Torznab offsets.

Two frontend-derived native search requests returned HTTP 500: `/api/torrents?limit=2&page=2&cat=films&sort=seeders&order=desc`, and `/api/torrents?q=Big%20Buck%20Bunny&limit=2&search_in=title`. Plain pagination worked. This establishes a server error for those requests at observation time, not its cause or which individual filter is responsible. Do not use retries or alternate query grids to conceal it. Native search is not yet a verified integration foundation. Sanitized results: [native observations](tr4ker-native-observations.json).

## RSS

The signed-in [RSS wiki page](https://tr4ker.net/wiki/flux-rss) is a generated feed-link page, not an ordinary article. It states 100 latest additions per feed and passkey authentication. Global pattern `/api/rss?passkey=<redacted>`; optional `freeleech=1` and `cat=<category-slug>`. It exposes parent and child category feeds. Do not include passkeys in logs or shareable Settings exports. No feed request was made, so XML item schema, volume factors, exact download auth, ordering and repeat/deduplication behavior remain unverified.

## Upload and torrent creation

Frontend-observed workflow, not a successful publication test:

1. Build from local files, or import a torrent and reconstruct its info dictionary with `private=1`, `source=TR4KER`. Existing payload names and pieces remain intact. Adding a source changes the info hash; preserve the original hash separately for duplicate/provenance checks.
2. Announce is constructed as `https://tr4ker.net/announce/<passkey>`, with a one-entry announce-list. Actual downloaded torrent source/announce/private bytes have not been independently verified.
3. `POST /api/torrents/preflight` sends JSON `info_hash`, `title`, `nfo`, optionally tmdb_id/tmdb_type. Frontend consumes hash_conflict and nfo_conflict. Not invoked during research.
4. `POST /api/torrents` publishes multipart form data. Common fields observed: torrent binary, info_hash, name, nfo, mediainfo, size_bytes, file_count, piece_length, category_slug, optional subcategory_slug, tags as JSON array, files as JSON array of path/size, description, tech_info_xml, extra_info/format, classic_description/format, is_anonymous and is_exclusive. Optional media metadata includes tmdb_id/type, poster_url, year, mbid, discogs_id, rawg_id. Manual import includes original_hash; automated flow may send title_auto, title_release_name and title_mkv. A request_id can link publication to an existing request.
5. Success handler consumes id/slug, checks request-link warnings, then downloads the resulting personalized torrent. There is no observed c411-style remote draft creation/commit stage. Keep local drafts local until an authorized publish action.

Respect [upload rules](https://tr4ker.net/wiki/regles-upload), last updated 13 November 2026: retain original file/folder names, check duplicates, require description and NFO, choose the correct category, supply suitable previews. Archives are generally disallowed except technical cases with very many small files. Videos need MediaInfo; ongoing seasons may use episodes, completed seasons should not be posted episode by episode. The frontend accepts original files as data, so never rename user data to match a generated display title.

Category-specific naming/validation needs independent rules for [films](https://tr4ker.net/wiki/regles-films), [series](https://tr4ker.net/wiki/regles-series), [audio](https://tr4ker.net/wiki/regles-audio), [books](https://tr4ker.net/wiki/regles-livres), [applications](https://tr4ker.net/wiki/regles-apps), [games](https://tr4ker.net/wiki/regles-jeux), [emulation](https://tr4ker.net/wiki/regles-emulation), [3D](https://tr4ker.net/wiki/regles-impression-3d), [training](https://tr4ker.net/wiki/regles-formations), [other](https://tr4ker.net/wiki/regles-autres) and adult content. All corresponding articles were read headlessly; provenance and update dates are recorded in the sources file. Avoid copying c411's option IDs or title templates.

The first-party rules conflict in places: general upload rules give a 650 MB executable VirusTotal threshold, while application rules say 1000 MB; the VO naming article requires a VO category, but category availability must come from the live tree; watermark acceptance differs between general and series articles; general emulation guidance requires region, while its naming page calls it optional. Surface these as guidance gaps instead of inventing one authoritative server validation rule.

## Ratio, reward and tracker maintenance

The [ratio guide](https://tr4ker.net/wiki/ratio) states a current minimum of 0.5 and blocks downloads below it; freeleech exempts downloaded bytes while upload continues to count. The frontend account display computes ratio from uploaded + bonus_upload and downloaded + bonus_download. Preserve raw and bonus counters separately; do not assume the display formula proves server enforcement details.

The [credits guide](https://tr4ker.net/wiki/credits) describes seedtime rewards dependent on size, category and seeder count, plus active badge multipliers. No numeric earning formula or client-estimable schedule is documented there. Do not expose c411 Zen forecasts, class factors, piece-size rules or profitability predictions as tr4ker facts. Support profile/ratio/credit display first; forecasts require verified tr4ker-specific rules.

The official [cross-seed guide](https://tr4ker.net/wiki/l-outil-cross-seed) requires separate torrents per tracker, never one torrent with multiple trackers. Preserve separate per-tracker torrent identities and use local data matching plus client hash recheck. Its example uses a daily search cadence; this is guidance, not a numeric HTTP request quota. Native frontend handles 429 using Retry-After with fallback 60 seconds, 401 as expired auth, 403 banned status separately from generic forbidden, and maintenance-coded 503 separately from transient 503. Implement bounded serialized requests, cancellation and backoff; do not claim an unmeasured exact rate limit.

## Work remaining before official support

- Generalize the primary tracker selection and account identity across the application, keeping C411 migration behavior intact. Namespace catalogue/category/options, caches, queued downloads and profile economics by provider/account.
- Add explicit tr4ker companion origin/account checks and separate endpoint permissions. Temporary research cookie extraction is not the production login design.
- Prefer verified Torznab discovery with `/api/torznab/all` for Cross-seed. Validate every advertised search mode, zero-seeder inclusion, pagination offsets, and actual torrent downloads. A download may write account history, so give it an intentional test.
- Validate native filtered-search reliability, max limits, catalogue cap behavior, sort stability and incremental refresh before promising complete catalogue sync.
- Verify RSS XML and download links with a narrowly scoped credential path. A passkey is not the API key.
- Test local torrent generation and safe fixtures for `TR4KER`, then authorized preflight/publication with a user-designated test item. Validate cleanup and moderation effects; no publication was attempted here.
- Populate account/history fixtures from real nonempty responses only when available. Establish which profile features have meaningful tr4ker equivalents; do not silently invent reward forecasts.
- Test both providers together for duplicate IDs, same data on different trackers, auth isolation, cookie/token redaction, Settings restoration and unaffected C411 flows.

Application code, installed versions, companion files and running processes were not changed. Only research files and the explicitly requested OS keyring entry were written. No CI/release or publication was requested.

## Human-step results, 23 November 2026 (evening)

Sanitized captures: [tr4ker-live-captures.json](tr4ker-live-captures.json).

- **Download.** A `.torrent` fetched through a Torznab enclosure with the API key returned 200 `application/x-bittorrent`. It is private, `info.source` is lowercase `tr4ker` (the frontend builds uploads with `TR4KER`), and the one-tier announce is `https://tk.tr4ker.net/announce/<passkey>`, so the announce host is `tk.tr4ker.net`, not `tr4ker.net`. The file embeds the passkey and not the API key. Cached torrent bytes are therefore secrets.
- **Cross-seed.** That torrent was a 2009 DVD remux with 0 seeders on tr4ker, matching a complete local c411 torrent by size. It was added stopped to qBittorrent with the same save path, rechecked to 100 % and started. The info-hashes differ, as expected.
- **Zero seeders.** `/api/torznab/all` name searches returned several items with `seeders=0`. The wiki's claim holds for these samples, and coverage was not measured.
- **RSS.** `/api/rss?passkey=…` with no session returned 100 items: title, guid, link (`/torrent/<slug>`), pubDate, category, an enclosure `/api/torrents/<slug>/download?passkey=…`, Torznab attrs (size, seeders, peers, downloadvolumefactor), and `https://tr4ker.net/rss` elements (size, seeders, leechers, freeleech). The feed authenticates downloads by passkey.
- **Profile.** `/api/me/stats`, `/api/me/downloads`, `/api/me/sw-rewards` and `/api/shop/history` return 200 but are still empty for this account. The cross-seed above should produce payouts after 6 h of seeding.
