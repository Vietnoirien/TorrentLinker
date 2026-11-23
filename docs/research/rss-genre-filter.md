# RSS genre filter: where an item's genres come from

Fact-finding for "horror 4K 4-8 GB" and "science fiction" subscriptions on c411 and tr4ker. No code changed. Source lines are from `main` at fca0fa5; "unverified" marks what was not observed live.

## Today

`Preferences` (`feeds.py`) filters on size, seeders and the metadata fields `quality, codec, audio, subtitles, format, bitrate, platform, license`. There is no genre. `evaluate` already treats a required or excluded field the release does not carry as `unknown`, never accepted ("Missing required metadata is never accepted", editor legend), and `enrich()` writes only structured facts, never free text or release names.

## Sources, by Tracker

| | Genre text | Verified id | Notes |
|---|---|---|---|
| c411 | `media.genres` in the listing row (`torrent_search.parse_listing_row`, French names) and in the detail JSON (`torrent_details._media`, `Media.genres`, from `metadata.tmdbData`) | detail `tmdbId` / `tmdbType` (`feeds.enrich` already stores them as `tmdbid` / `kind`) or `metadata.ids` entries `tmdb*` | Names only, no genre ids. The RSS/Torznab item itself carries `tmdbid` only when the Indexer sets that attr (`indexer.py` keeps it in `metadata`). |
| tr4ker, passkey feed (`/api/rss`) | none | none | `tr4ker_rss.py` keeps title, guid, size, category slug, freeleech. No tmdb attr is read from the feed. Not verified whether the feed XML has one. |
| tr4ker, Torznab (query subscriptions) | none | `tmdbid` attr (optional, observed in `docs/research/tr4ker-integration.md`) | Kept in `metadata.tmdbid` by `indexer.py`. Movie search advertises `tmdbid`. |
| tr4ker, native detail (`/api/torrents/{slug}`) | none (`docs/research/tr4ker-torrent-detail-schema.json` has no genre) | `tmdb_id` (int) and `tmdb_type` (`tr4ker_native.py` -> `Media.tmdb_id`) | Native *search* has a `genre` filter in tr4ker's own UI (`tr4ker-integration.md`); its value format and whether it is usable for a feed are unverified. The feed itself has no such parameter. |

TMDb client (`tmdb.py`): `Tmdb.details(id, "movie"|"tv")` asks `language=fr-FR` and returns `raw`, whose `genres` is `[{id, name}]` (French names). The app has no genre-list call (`/genre/movie/list`, `/genre/tv/list`) yet.

How the rest of the app reads TMDb genres:

- Upload: `Tmdb.details(...).raw` goes to c411 as the draft's `tmdbData`, genres included. Nothing is cached or read back as a genre.
- Médias: `media.py` sets `genre` from the release details text (`genres_of` splits on commas) or the file tags; the tracker suggestions split `film["genre"]`. These are display strings, not TMDb ids, and Médias never calls TMDb for them.
- The one existing TMDb cache is Age Ratings (`media_ratings.py`): key `tmdb-age:<type>:<id>` in `media_options`, retry after 7 days when TMDb gave nothing, key `tmdb-api-key`. The genre lookup should copy it (`tmdb-genres:<type>:<id>`).

## Reliable genre, in order

1. TMDb id carried by the release (c411 detail `tmdbId`, tr4ker native `tmdb_id`, Torznab `tmdbid`) plus its type -> `Tmdb.details().raw.genres`, stored as genre **ids**. Ids are stable across languages and across the movie/TV lists.
2. c411 `media.genres` names, mapped to ids through TMDb's French genre lists. Accepted because c411 copies TMDb; a name the table does not know stays unmapped, so the item is unknown, not a guess.
3. Nothing else. A genre read from the title, the category name, tags or the description is a guess and never counts (`feeds.py` already separates verified attributes from guesses).

For the passkey feed (no hash, no tmdb attr) a genre needs enrichment first: native detail by slug gives `tmdb_id`, then TMDb gives genres. That costs one native call and one TMDb call per new item, cacheable by TMDb id.

## When no TMDb id exists, or TMDb has no genre

Never pass, never fail. The item is `unknown` for `genre`, like any other missing verified field, and **waits in review with "genre unknown"**:

- Review-only subscription: the item stays in the inbox, marked "genre ?" (dashed badge), decision status `review`, reason "Genre unknown: TMDb gives none for this release. It waits in review."
- Queue and automatic subscriptions: the item is not queued or sent; same decision. The owner can set the genre by accepting the release by hand (a manual override, not a rule change).
- Retry: when `enrich` later finds a TMDb id or TMDb later has genres, the item is judged again (same weekly retry as Age Ratings).
- This holds for Excluded too: an "exclude Horreur" rule cannot clear an item whose genre is unknown.
- No TMDb key in Settings: every genre rule is `unknown` for all items, and the editor says so instead of showing zero matches.

## Open points (not verified)

- TMDb's French names for TV-only genres (10759, 10762-10768): the preview keeps TMDb's English labels for them; a live `/genre/tv/list?language=fr-FR` call settles it.
- Whether tr4ker's feed XML carries a tmdb attribute (it would skip the native detail call).
- A single required genre means "has this genre" (any genre of the item), several required genres mean "has any of them", as for the other fields.
