# c411 RSS map

Observed on 2026-10-26 (Europe/Paris). This investigation made 20 read-only HTTP requests to c411, including public client assets, capabilities, small authenticated feeds and a bounded pagination check. It downloaded no `.torrent` files and changed nothing on c411. Credentials stayed in the OS keyring and process memory. Response summaries retained only schema, counts, dates and redacted URL shapes.

c411's working RSS feed is its authenticated Torznab search endpoint with no text query. Both `/api` and `/api/torznab` work. The main integration risks are repeated pages after the accessible result window and feed rows whose `pubDate` values are not strictly ordered. Deduplicate by infohash and detect repeated page contents; a timestamp alone cannot establish that an update has caught everything.

Throughout this note, **observed** means a request made during this investigation, **documented** means c411's current first-party client or capabilities, and **proposed** means an integration recommendation. Older research is identified by date.

## Endpoint map

`<API_KEY>` and `<infoHash>` below are placeholders. Links to authenticated routes omit credentials deliberately.

| Route or shape | Authentication | Evidence and purpose |
| --- | --- | --- |
| `GET /api?t=caps` | None | Observed 200 XML. Public capabilities and Torznab category tree. [Endpoint](https://c411.org/api?t=caps). |
| `GET /api?t=search&apikey=<API_KEY>&limit=100` | API key in query string | Observed RSS 2.0 XML, without `q`. This is the native new-release RSS feed described in the [integration guide](https://c411.org/user/integrations/guide). |
| `GET /api/torznab?t=search&apikey=<API_KEY>&cat=8010&limit=5` | API key in query string | Observed 200 and the same five infohashes as `/api` for this query. This is also the endpoint used by the repo's [probe](../../scripts/probe_c411.py). |
| Same feed with `cat`, `q`, `offset`, `limit`, `extended` | Same key | Category, text, offset and limit requests observed below. `extended=1` was accepted, but its incremental effect was not isolated. |
| `/api?t=movie...`, `t=tvsearch...`, `t=music...`, `t=book...` | API key | Capability-advertised search modes and existing app integration, not separately exercised in this run. These return search feeds rather than distinct public subscriptions. [Capabilities](https://c411.org/api?t=caps), [app modes](../../src/torrentlinker/indexer.py). |
| `GET /api?t=get&id=<infoHash>&apikey=<API_KEY>` | API key in query string | Observed in RSS enclosure URLs. Downloads a torrent; intentionally not followed. |
| `/torrents/<infoHash>` | Website access policy | Observed RSS `link` and `comments` destinations. A details page, not the enclosure. |
| `GET /api/categories` | Bearer API key worked | Observed JSON native category tree. These IDs differ from Torznab IDs. [Endpoint](https://c411.org/api/categories). |
| `GET /api/torrents?...` | Bearer API key | Separate JSON listing. Previously verified in [full Catalogue research](full-catalogue.md), not re-probed here. It is not RSS. |
| `GET /api/torrents/by-tmdb?tmdbId=...&tmdbType=movie` | Bearer key or session, according to c411 | Documented lookup of up to ten approved releases for a known TMDB ID, with a 30-per-minute limit. It does not enumerate the Catalogue. [Current guide client](https://c411.org/_nuxt/DlXcVhKv.js). |
| Separate `/rss`, `/rss.xml`, Atom, passkey RSS or user-created feed endpoints | Unestablished | No independent feed route or RSS autodiscovery link was found in the homepage or the inspected integration assets. These possible shapes were not probed, and their existence is not claimed. |

An anonymous search returned HTTP 401 and `<error code="100" description="Invalid API Key"/>`. A request with only a Bearer header, without the `apikey` query argument, was rejected by the app's 401/403 handler. Keep query-key authentication for Torznab. Successful Bearer access to JSON categories does not establish Bearer access to RSS. The official guide calls the default read scope Torznab/RSS; the app identifies it as `torznab:read`. [Guide](https://c411.org/user/integrations/guide), [Indexer](../../src/torrentlinker/indexer.py).

## Filters and category map

[Capabilities](https://c411.org/api?t=caps) advertise these mode-specific parameters. Common paging and category parameters are additional to these lists.

| `t` value | Advertised parameters |
| --- | --- |
| `search` | `q` |
| `movie` | `q,imdbid,tmdbid` |
| `tvsearch` | `q,season,ep,tmdbid,imdbid` |
| `music` | `q` |
| `book` | `q` |

Observed `cat=2030` yielded only Torznab category 2030, and `cat=8010` only 8010. `cat=2030,8010` yielded both categories in one five-item response. `q=2026` returned five items, but this run did not characterize tokenization, Boolean expressions or exact title matching. Date, size, uploader, language, resolution and arbitrary native subcategory filters were not established for RSS. Use the JSON filter contract where those distinctions matter, as described in [search filter research](search-filters.md).

The table below joins the observed native tree, current Torznab capabilities, and the repo's explicit [native-to-Torznab mapping](../../src/torrentlinker/catalogue_sync.py). Shared Torznab IDs lose distinctions that the native API retains.

| Native root ID | Native family | Torznab family ID | Useful examples and collisions |
| --- | --- | --- | --- |
| 1 | Films & Vidéos | 2000 | Native Film 6 → 2030; Série TV 7 → 5000; Animation 1 → 2060; Animation Série 2 → 5070; Documentaire 4 → 2070; Série Documentaire 57 → 2000. TV children sit inside this native family. |
| 2 | Ebook | 7000 | Audio 11 → 3030; BDs 12, Comics 13 and Manga 15 → 7030; Livres 14, Partitions 59 and technical manuals 60 → 7020; Presse 16 → 7010. |
| 3 | Audio | 3000 | Musique 18 → 3010; Karaoké 17, Podcast Radio 19 and Samples 20 → 3050. |
| 4 | Applications | 4000 | Linux 23 and MacOS 24 → 4030; Smartphone 25 and Tablette 26 → 4060; Windows 27 → 4000. |
| 5 | Jeux Vidéo | 1000 | Linux 29, MacOS 30 and Windows 36 → 4050; Microsoft 31 → 1040; Nintendo 32 → 1030; Sony 34 → 1080. |
| 6 | Emulation | 1000 | Émulateur 37 → 4050; ROM/ISO 38 → 1090. Shares a family ID with games. |
| 7 | GPS | 4050 | Applications 39 and Cartes 40 → 4060; Divers 41 → 4050. Collides with software and games. |
| 8 | XXX | 6000 | Advertised by Torznab caps, absent from this authenticated JSON category-tree response. Native mapping comes from repo code and prior investigation, not a returned native row in this run. |
| 9 | Nulled | 4000 | Divers 47, Scripts PHP & CMS 49 and Wordpress 50 → 4050; Mobile 48 → 4060. Shares several IDs with other families. |
| 10 | Imprimante 3D | 8010 | Objets 51, Personnages 52 and Pack 53 all → 8010. RSS cannot distinguish these three through `cat` alone. |

Use `cat=8010` for all Imprimante 3D RSS, not `cat=10` or `cat=51`. For a native 3D distinction, the JSON listing uses the separate `category=10&subcat=51` contract. That JSON URL shape comes from existing first-party listing research, not a new RSS probe. [Listing research](full-catalogue.md).

## Feed fields and identity

Observed responses use `application/xml; charset=utf-8`, an `rss` root and the Torznab namespace `http://torznab.com/schemas/2015/feed`. Channel fields were `title`, `description`, `link`, `language` and `lastBuildDate`. No `newznab:response` total/offset element appeared in the inspected responses. [Authenticated source](https://c411.org/api?t=search).

| Field | Observed shape or meaning |
| --- | --- |
| `title` | Torrent title. |
| `guid` | Forty-character torrent infohash. No separate numeric torrent ID was exposed here. |
| `link`, `comments` | `https://c411.org/torrents/<infoHash>`. |
| `pubDate` | RFC-style timestamp including timezone. It is not a monotonic cursor. |
| `size` | Byte count; also supplied as a Torznab attribute. |
| `description` | Present. Content format was not exhaustively characterized. |
| `enclosure` | URL `https://c411.org/api?t=get&id=<infoHash>&apikey=<API_KEY>`, type `application/x-bittorrent`, `length` as byte count. It contains a secret. |
| `torznab:attr` | Observed names across samples: `category`, `infohash`, `seeders`, `peers`, `grabs`, `size`, `downloadvolumefactor`, `uploadvolumefactor`; some Film rows also supplied `imdbid` and `tmdbid`. |

The category lives in `torznab:attr name="category"`, not an ordinary `<category>` element in these samples. No direct `leechers` attribute appeared. `peers` was present, but this run did not independently verify its arithmetic relationship to seeders and leechers. Preserve absence rather than inventing a count. The app currently retains title, size, seeders, infohash, details URL, categories, publication time and enclosure URL in a [Candidate](../../src/torrentlinker/indexer.py).

## Paging, freshness and limits

Observed counts confirm the advertised default of 25 and maximum of 100. With `cat=8010`, omitting `limit` returned 25 and `limit=1000` returned 100. [Capabilities](https://c411.org/api?t=caps).

For `cat=2030&limit=100`, offsets 0, 500 and 600 each returned 100 rows. Offsets 500 and 600 returned exactly the same set of 100 infohashes. Their page fingerprints were both `c264bf2ef8a0`, the first twelve hex characters of SHA-256 over sorted, concatenated hashes. This re-confirms the limited window found on [2026-10-22](full-catalogue.md). It does not prove that the whole category has only 600 torrents, and larger offsets do not establish access to older history.

The five-item 8010 response started with `Sat, 24 Oct 2026 09:30:19 +0000` and ended with `Sun, 25 Oct 2026 19:09:19 +0000`. The response is therefore not strictly newest-first by `pubDate`. This run did not establish whether edits, promotion or another server ordering caused it. Stop conditions based on a single oldest date or first previously seen item are unsafe.

The official [RSS section of the integration client](https://c411.org/_nuxt/DlXcVhKv.js) describes a five-minute cache, ETag support and an RSS Sync Interval of 15–60 minutes. Live observations differed:

| Request | Observed headers or result |
| --- | --- |
| `t=search`, no `q`, including category feeds | `Cache-Control: public, max-age=1800, stale-while-revalidate=60`, weak ETag, `Last-Modified`. |
| Immediate identical request with matching `If-None-Match` | HTTP 200 with the same ETag and same five hashes. A 304 optimization was not demonstrated. |
| `t=search&q=2026&limit=5` | `Cache-Control: private, max-age=30, stale-while-revalidate=30`; no ETag in this sample. |
| Anonymous caps and rejected search | `Cache-Control: private, no-cache, no-store`. |

These are response directives, not measurements of the server's internal cache or actual upstream freshness. The successful responses contained user-specific enclosure keys despite the `public` cache directive. Keep authenticated feed bodies and enclosure URLs out of shared application caches, reports and logs.

No `x-ratelimit-*` or `Retry-After` headers appeared in these successful RSS samples, and this investigation did not deliberately trigger 429. The guide still describes a 120-per-minute shared key budget in its profile section. Earlier [rate-limit measurements](rate-limits.md), dated 2026-10-22, found a shared 1,200-per-hour search/JSON budget across tested keys and the site session, and a separate download limit. Those historical measurements are not a new quota guarantee. Respect the app's existing limiter and any future 429 response, including its first comma-separated `Retry-After` value. [Limiter](../../src/torrentlinker/ratelimit.py), [request handling](../../src/torrentlinker/indexer.py).

## TorrentLinker integration

Observed in repository code:

- [SearchQuery and Indexer](../../src/torrentlinker/indexer.py) already build RSS searches, parse Candidates, redact API keys from cached bodies, and route metadata and torrent downloads through separate queues. Generic search caching lasts 24 hours, so a live subscription should use `cached=False`.
- [Catalogue refresh](../../src/torrentlinker/catalogue.py) already uses `cached=False`, pages of 100 and infohash-set fingerprints. A repeated page sets `limited=True`, `complete=False`. Its ordinary update stops at a page containing only known hashes. That is a bounded update heuristic, not proof that earlier history is complete.
- [c411 Catalogue sync](../../src/torrentlinker/catalogue_sync.py) combines the third-party Zen Lab baseline with direct c411 JSON updates and a Torznab fallback for the category omitted by JSON. [ADR-0005](../adr/0005-own-catalogue-and-zen-rules.md) keeps coverage limits visible.

Proposed use of RSS is a bounded discovery update for selected categories, with review before any torrent download or Reseed. A feed item alone cannot establish a Match because it has no file tree. Keep the existing Verification and Reseed workflow.

A practical update policy would poll selected feeds every 30 minutes initially, within the guide's 15–60-minute range and consistent with the observed 1,800-second no-query cache directive. Fetch at most a small configured number of 100-item pages per category, for example three, then deduplicate all observed infohashes against the Catalogue. Keep overlapping reads on later polls. Stop on repeated page fingerprints and record a paging limit. If the budget ends or the accessible window repeats before adequate overlap is found, record an incomplete update and offer the existing Catalogue refresh. Never claim complete history or guaranteed gap-free discovery. Even an all-known page is only a heuristic with this ordering.

Store a local fetch time separately from `pubDate`. Keep ETags only with the exact endpoint, filters and credential identity that produced them. Attempt conditional requests if useful, but accept ordinary 200 responses. A future client that accepts 304 must handle that status before XML parsing; the current request helper calls `raise_for_status()` and is not a ready-made conditional-feed client. Retain metadata only; fetching an enclosure is a separate action and consumes download quota.

## Safe reproducible probes

Public capabilities require no secret:

```bash
curl --fail --silent --show-error 'https://c411.org/api?t=caps'
```

Run this from the repo using its virtual environment. It uses the saved key through the app and prints only counts and category IDs. Do not print the returned XML or enclosure URLs.

```bash
.venv/bin/python - <<'PY'
from torrentlinker.credentials import get_secret
from torrentlinker.indexer import Indexer, SearchQuery

key = get_secret("indexer-api-key")
if not key:
    raise SystemExit("No Indexer API key available in this session")
indexer = Indexer("https://c411.org/api", key)
for category in (2030, 8010):
    rows = indexer.search(
        SearchQuery(categories=(category,), limit=5, extended=True),
        cached=False,
    )
    print({
        "requested_category": category,
        "items": len(rows),
        "unique_infohashes": len({r.infohash for r in rows if r.infohash}),
        "returned_categories": sorted({c for r in rows for c in r.categories}),
    })
PY
```

For a bounded paging reproduction, request `SearchQuery(categories=(2030,), limit=100, offset=500)` and then offset 600 with `cached=False`, compare sets of `Candidate.infohash` in memory, and print only equality and counts. A repeat establishes a paging limit for that query at that time; it does not establish Catalogue size.

## Evidence boundaries

This map establishes a working authenticated RSS route, public capabilities, two single-category filters, one combined filter, limited paging, response fields and current cache behavior. It does not establish a separate public release feed, arbitrary custom feed definitions, lossless native category filtering through RSS, a deletion/change stream, stable server ordering, a complete history, or reliable 304 responses. No unsupported route or parameter should become an app promise without a fresh successful probe.

Primary sources are the live endpoints linked above and the current public [route manifest](https://c411.org/_nuxt/8foCh-9s.js), [integration guide client](https://c411.org/_nuxt/DlXcVhKv.js) and [integration settings client](https://c411.org/_nuxt/DpXwwtsQ.js). Asset names are build-specific and may change. Authenticated probe results in this note are dated observations, not public URLs that reproduce without the user's own key.
