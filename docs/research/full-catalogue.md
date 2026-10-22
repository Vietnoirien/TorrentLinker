# Fetching the full c411 catalogue

## Implemented outcome

The user approved Zen Lab metadata on 2026-10-22, then requested direct c411 JSON listing updates for current planning data. They later removed pre-Plan per-torrent verification because its four-second request interval made large Plans impractical. The implementation imports the anonymous snapshot, refreshes new rows through the c411 listing, and builds provisional Plans from cached data. qBittorrent's reported swarm counts update Seeding estimates and the cached seeder counts after tracker responses. They do not confirm snapshot categories or sizes.

A live Bearer request had verified that `GET /api/torrents/{infoHash}` returns size, seeders, status and `metadata.category` / `metadata.subcategory` without downloading a torrent. This remains a research finding; Plan creation no longer calls this endpoint.

A live Torznab search verified its enclosure uses `https://c411.org/api?t=get&id=<infoHash>&apikey=<key>`, confirming the direct download format without grabbing a .torrent. Snapshot-derived rows store a placeholder for the key.

A full implementation smoke test in a temporary Catalogue imported 192,090 snapshot entries, added three missing entries through c411, and refreshed all 1,715 torrents of category 8010. The resulting Catalogue held 192,093 torrents. Its stored download URLs all pointed to c411 and contained no API key. Counts are observations of a changing catalogue, not completeness guarantees for the whole tracker.

Investigated on 2026-10-22. The JSON catalogue endpoint is the best lead. It accepts the existing `torznab:read` API key as a Bearer token, but its reported page count has another limit. Full coverage still needs verification before Plan creation can promise it.

## What the live requests established

The recovered user probe found that Torznab `offset=500`, `600`, `700`, `1000`, and `5000` returned the same 100 hashes. The tested `minsize` and `maxsize` values did not change those results. `q=2015` changed the result window. Those observations show a limited result window per query; they do not establish an exhaustive search partition. The `maxage` tests were inconclusive.

The anonymous [Torznab capabilities endpoint](https://c411.org/api?t=caps) reports `max=100` and `default=25`. Its generic search advertises only `q`; movie search also advertises `imdbid` and `tmdbid`; TV search also advertises `season`, `ep`, `tmdbid`, and `imdbid`. It does not advertise size bounds, upload-date bounds, a prefix filter, or a replacement for offset. The absence from capabilities alone does not prove a parameter is ignored.

Anonymous `GET /api/torrents?page=7&perPage=100&viewMode=flat&sortBy=createdAt&sortOrder=asc` returned HTTP 401 with a restricted-site message. No anonymous full-catalogue endpoint was established.

In this session the parent agent made read-only Bearer requests to the JSON endpoint with `page=1` and `page=7`, `perPage=100`, `viewMode=flat`, `sortBy=createdAt`, and `sortOrder=desc`. Both returned HTTP 200. Both reported `total=204891`, `totalTorrents=204891`, `perPage=100`, and `totalPages=100`; the returned page matched the requested page. A follow-up request for page 101 returned `meta.page=100`, and `perPage=1000` was clamped to 100. The JSON endpoint therefore works with the saved key, but also clamps pagination.

The response contains `data` and `meta`. Observed torrent fields include `id`, `infoHash`, `name`, `category`, `subcategory`, `size`, `seeders`, `leechers`, `completions`, `uploader`, `createdAt`, `isExclusive`, `isFreeleech`, `status`, `music`, `media`, `tech`, and palliative information. No `downloadUrl` field was observed in these rows.

## Parameters the website actually sends

The first-party [catalogue listing bundle](https://c411.org/_nuxt/CAIcxzAK.js), still served when checked, builds these query parameters for `GET /api/torrents`:

| Parameter | Value used by the client |
| --- | --- |
| `page` | One-based page number |
| `perPage` | Listing client defaults to 25 |
| `sortBy` | `createdAt`, `seeders`, `leechers`, `size`, `completions`, `comments`, `name`, `category`; also `relevance` for a name search |
| `sortOrder` | `asc` or `desc` |
| `category` | Internal category ID, distinct from Torznab IDs |
| `subcat` | Comma-separated internal subcategory IDs |
| `name` | Search string, maximum 200 characters in the client |
| `year` | Release year; the UI uses a numeric input from 1900 to 2100 |
| `uploader` | Username |
| `options` | Comma-separated option-value IDs |
| `resolution`, `source`, `codec`, `audioType`, `channels`, `hdr`, `profile`, `lang` | Comma-separated filter values |
| `exclusive` | `true` when selected |
| `palliative` | `include` when selected; another listing uses `only` |
| `palliativeTail` | `true` for name searches that do not include palliative torrents |
| `crew` | `true` when selected |

The uploader's [own-torrents bundle](https://c411.org/_nuxt/B81mN3oc.js) also uses `viewMode=flat`. Use it when counting individual torrents so grouped releases do not conceal rows. Its effect on the general listing was used in the successful Bearer probe, but should also be checked against row counts.

The [integration guide bundle](https://c411.org/_nuxt/BggWbbiX.js) documents `GET /api/categories` and `GET /api/categories/{subcategoryId}/options` with Bearer authentication. Its examples use `categoryId=1`, `subcategoryId=6` for films and `subcategoryId=7` for TV. Fetch the category tree instead of hard-coding those examples.

There are no size bounds or upload-date bounds in the listing query builder. `year` filters the work's release year, not its upload date. Neither this source nor the capabilities endpoint establishes support for `createdAfter`, `createdBefore`, `dateFrom`, `dateTo`, `minsize`, `maxsize`, prefix matching, or a cursor on the general catalogue endpoint.

The [search administration bundle](https://c411.org/_nuxt/Qsm1Vmeo.js) identifies Meilisearch as the catalogue search engine and describes weighted title, content, and metadata fields. No official starts-with-title, exclusion, regex, or Boolean search syntax was found in the saved public client bundles or indexed official pages. A text query cannot be assumed to define a disjoint title prefix.

## The daily listing is a separate lead

The [daily listing bundle](https://c411.org/_nuxt/DA2o3ccD.js) calls two routes:

```text
GET /api/torrents/today?period=day&initialPerPage=15
GET /api/torrents/today-paginated?period=day&categoryId=1&offset=0&perPage=15&sortBy=createdAt&sortOrder=desc
```

The paginated route accepts an optional internal `subcategoryId`, uses a row offset rather than a page number, and returns `meta.total` and `meta.hasMore`. The initial route returns categories with their torrent lists and date metadata including `period`, `startDate`, and `endDate`. Its client allows `day`, `week`, and `month` only. There is no client evidence for `period=all`, arbitrary date windows, or unbounded history. A successful request with `period=all` would need its returned date range and total checked to distinguish genuine full history from a silent fallback to today.

## API scopes and downloads

The [API-key settings bundle](https://c411.org/_nuxt/Ds--TzgH.js) lists `torznab:read` as the default scope and describes it as catalogue search and torrent download. Other scopes include `upload:write`, `drafts:rw`, `slots:reassign`, `profile:read`, and `torrents:delete`. No additional read scope is needed for the successful listing requests above.

The integration guide explicitly documents Bearer `torznab:read` access to `GET /api/torrents/by-tmdb?tmdbId=27205&tmdbType=movie`. That endpoint returns releases for a known TMDB ID, including `infoHash`, size, seeders, leechers, completion count, technical fields when available, upload date, and a torrent-page `url`. It does not enumerate TMDB IDs and therefore does not solve catalogue discovery.

The [download client bundle](https://c411.org/_nuxt/CzjZljMS.js) uses `GET /api/torrents/{infoHash}/download` with same-origin browser credentials. This proves the route exists, but the JavaScript alone does not establish how to authenticate that route with an API key. Keep the currently working Torznab download mechanism until an API-key download request is verified. Listing metadata does not require downloading torrent payloads.

## What to verify next

Use the existing Bearer key in memory and print only counts, metadata, and hash digests. There is no need to copy the key into logs or use browser cookies.

1. Repeat the JSON page-boundary check with `perPage=25` to distinguish a page-count cap from a result-count cap. Page 101 at `perPage=100` already clamps to page 100.
2. Fetch `/api/categories`, then count each `subcat` separately with `viewMode=flat`. Subcategories with totals below the verified result window can be paged completely. Confirm that their union covers the selected Plan categories.
3. If a subcategory exceeds the window, compare `sortBy=createdAt&sortOrder=asc` against `desc`. If both ends are independently reachable, they can cover a subcategory whose total is no more than twice the result window, provided the complete union count matches its total. They do not solve larger subcategories by themselves.
4. Test `year` only as a possible further partition. It cannot prove completeness unless an explicit unknown-year bucket is available or the sum and union of all year partitions match the unfiltered total. The same problem applies to resolution, source, and other optional metadata filters.
5. If the endpoint clamps pages and exposes no exhaustive partition, keep the fetch marked incomplete and show that limitation in Plan creation. A term scan such as `q=2015` can find extra rows, but cannot certify the full catalogue.

Do not label a fetch complete merely because a page is short, repeated, or reaches the reported final page. Compare the number of unique info hashes against the applicable ungrouped total, while accounting for catalogue changes during the run.

## Uploader enumeration and catalogue exports

An uploader partition needs a complete uploader list, coverage of anonymous uploads, and verified exact matching by username. The public source does not establish all three.

The [uploader moderation bundle](https://c411.org/_nuxt/o76_oQ-Q.js) contains an explicitly paginated uploader list:

```text
GET /api/team-pending/uploaders?page=1&perPage=25&blocked=all&certification=all&uploaderType=all&popularity=all&uploaderRole=all&sortBy=validatedUploadsCount&sortOrder=desc
```

Its response has `data` and `meta.total`, `page`, `perPage`, and `totalPages`. However, the [route manifest](https://c411.org/_nuxt/CypyUCaG.js) marks the uploader page with `team-pending` middleware. This is a staff workflow, not a documented ordinary catalogue-read endpoint. Its server pagination limits and Bearer accessibility were not tested in this source-only follow-up.

Other discovered member endpoints do not prove complete coverage:

| Endpoint | Limitation shown by the client |
| --- | --- |
| `/api/economy/members?page=1&perPage=100` | [Economy client](https://c411.org/_nuxt/CI2HoYxI.js) describes accounts holding Zen and caps pagination at the first 10,000. Filters include role, class, balance, and level. It is not an all-uploader registry. |
| `/api/messages/users/search?query=...` | [Messaging client](https://c411.org/_nuxt/BW2WKYm8.js) requires two characters by default, reads `users`, and supplies no page, cursor, total, or next-page contract. |
| `/api/teams/members/search?q=...` | [Team client](https://c411.org/_nuxt/CyH1uHbK.js) requires two characters and reads `users`, also without pagination. |
| `/api/ic/leaderboard/all_time?cursor=...` | [Leaderboard client](https://c411.org/_nuxt/BPOV6LPG.js) reads `entries` and `nextCursor`. It documents a ranking, not all registered users or uploaders, and exposes no registry total in this client. |

The [permission definitions](https://c411.org/_nuxt/B6bTYZiA.js) reserve `torrent:view_anonymous_uploader` for viewing the real uploader behind anonymous uploads. This is a moderation permission. Enumerating visible usernames alone therefore cannot certify coverage of anonymous uploads. There is no public-client evidence for an `uploader=anonymous`, missing-uploader, or numeric-ID partition on the general listing.

No metadata catalogue export or dump endpoint was found among the downloaded public route references. The similarly named `POST /api/torrents/archive` serves a ZIP containing up to 100 `.torrent` files and requires `torrent:bulk_download`, according to those same permission definitions. It is not a metadata export and would download torrent payloads. `/api/admin/search-index/torrents` belongs to search administration; no ordinary `torznab:read` metadata-export contract was found for it.

These are source findings, not proof that no other server endpoint exists. They do rule out presenting the discovered autocomplete and ranking endpoints as an established exhaustive uploader strategy.

## Zen Lab metadata bootstrap

The user approved Zen Lab as a third-party metadata source, with credentials and `.torrent` downloads kept on c411. The following requests sent no API key or browser credentials to Zen Lab.

The public [Zen Lab catalogue](https://zen.mma.dev/api/catalog) returned HTTP 200 and 192,089 rows during this investigation. The uncompressed JSON was 24,965,752 bytes. Its complete top-level shape was:

```json
{
  "stored": 192089,
  "hash": ["40-character hexadecimal info hash"],
  "title": ["Torrent title"],
  "sizeBytes": [426975656],
  "seeders": [16],
  "category": [5000]
}
```

The example illustrates types; it is not a complete catalogue or a literal single-row response. Each array has the same length, and values at the same index describe one torrent. All 192,089 observed hashes were unique valid 40-character hex strings. Sizes and seeder counts were integers. The observed size range was 27,836 to 6,089,480,564,736 bytes; the seeder range was 1 to 3,592. There were no zero-seed rows in this response.

The [Zen Lab client bundle](https://zen.mma.dev/_next/static/chunks/0x6uru_52tma6.js) validates this parallel-array shape and converts it to records containing `hash`, `title`, `sizeBytes`, `seeders`, and `category`. It supplies `leechers=0` and `link=""` locally because the response lacks those fields. Do not treat that synthetic zero as an observed leecher count. The [calculation bundle](https://zen.mma.dev/_next/static/chunks/1dvdt641-59m9.js) divides `sizeBytes` by `1e9` to calculate decimal gigabytes.

The client requests all stored metadata with `GET /api/catalog` and does not paginate. It uses `?cat=<family>` for category selection. The response has no `page`, `cursor`, `total`, `hasMore`, `truncated`, `generatedAt`, or per-row observation timestamp. `stored` matched the returned row count in both successful probes; it is not c411's authoritative catalogue total. Record the local fetch time as such, without presenting it as the source metadata's age. Zen's stored metadata cannot by itself certify complete or current coverage of c411.

Its family IDs are Torznab-style IDs, not c411's native category IDs. The client accepts these families:

| Family ID | Zen label | Child IDs in the client |
| --- | --- | --- |
| 1000 | Jeux & émulation | 1030, 1040, 1080, 1090 |
| 2000 | Films & vidéos | 2010, 2030, 2050, 2060, 2070, 2080, 2090 |
| 3000 | Audio | 3010, 3030, 3050 |
| 4000 | Applications | 4030, 4040, 4050, 4060, 4070 |
| 5000 | Séries TV | 5060, 5070, 5080 |
| 7000 | Ebooks | 7010, 7020, 7030 |
| 4050 | GPS | 4060 |
| 8020 | Nulled | 4050, 4060; the scan client omits family ID 8020 itself |
| 8010 | Imprimante 3D | None |

`GET /api/catalog?cat=2000` returned `stored=74851`, with exactly 74,851 rows spanning category IDs 2000, 2010, 2030, 2060, 2070, 2080, and 2090. It therefore expands the family rather than matching category 2000 alone. `GET /api/catalog?cat=7030` returned HTTP 400, `{"detail":"Catégorie invalide."}`. Fetching once without a category and filtering rows locally supports arbitrary selected subcategories and avoids relying on Zen's family definitions. Its separate TV family is especially relevant because c411's capabilities place TV under the broad Films & Vidéos category. IDs such as 4050 and 4060 also have several meanings in c411's capabilities; metadata cannot recover distinctions that its category field does not carry.

For delivery, Zen's client constructs direct c411 URLs in two modes:

```text
https://c411.org/api?t=get&id=<infohash>&apikey=<key>
https://c411.org/api/torrents/<infohash>/download
```

The first is its API-key mode, the second its browser-session mode. This is evidence from Zen's implementation. The c411 client independently confirms the native `/api/torrents/{infoHash}/download` route, but its public source alone does not confirm Bearer authentication on that download route. Reuse the app's direct c411 Torznab download mechanism and validate its current response contract separately. Never derive a download destination from the metadata provider, and never send the c411 key to Zen Lab.
