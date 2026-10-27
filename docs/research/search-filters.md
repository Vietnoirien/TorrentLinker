# c411 category-specific search filters

Checked on 2026-10-23 against the current first-party [listing client](https://c411.org/_nuxt/o7Qf9Ugw.js), [profile definitions](https://c411.org/_nuxt/sZ70szZm.js), and bounded live metadata requests. Requests used the configured c411 API key as a Bearer token. No torrent files were downloaded and no account settings were changed.

## Implementation contract

Use c411's native JSON listing for its advanced Search UI. Torznab category IDs collapse distinct native categories and cannot represent the website's full filter set. Keep Torznab search for other Indexers and existing Library reconciliation.

Three read endpoints suffice:

| Endpoint | Purpose | Live result |
| --- | --- | --- |
| [GET /api/categories](https://c411.org/api/categories) | Native category tree | 200 with Bearer; 401 anonymously |
| [GET /api/categories/1/filter-options](https://c411.org/api/categories/1/filter-options) | Option groups for native root category 1 | 200 with Bearer; 401 anonymously |
| [GET /api/torrents](https://c411.org/api/torrents) | Filtered, paginated torrent metadata | 200 with Bearer |

`filter-options` takes the **root category ID**, whereas the existing upload `GET /api/categories/{subcategoryId}/options` takes a subcategory. These endpoints have different purposes. Root 10 search filter options returned an empty list despite the Upload UI having additional fields.

The category response is `{ "data": [...] }`. Each root has `id`, `name`, `slug`, presentation properties, and `subcategories`. Each child has `id`, `categoryId`, `name`, and `slug`. Root and subcategory IDs occupy separate namespaces: root 1 and subcategory 1 both exist. Store a selection as a root plus optional child, not one ambiguous integer. The live response returned roots 1 Films & Vidéos, 2 Ebook, 3 Audio, 4 Applications, 5 Jeux Vidéo, 6 Emulation, 7 GPS, 9 Nulled, and 10 Imprimante 3D. It did not return root 8 for this account. Respect the fetched list rather than inventing missing categories.

Example shape with a subset of the actual categories:

```json
{"data":[{"id":1,"name":"Films & Vidéos","slug":"films-videos","subcategories":[
  {"id":6,"categoryId":1,"name":"Film","slug":"film"},
  {"id":7,"categoryId":1,"name":"Série TV","slug":"serie-tv"}
]}]}
```

The filter response has no upload-required flags and no per-subcategory visibility map:

```json
{"data":[{"id":5,"name":"Genre","slug":"genre","values":[
  {"id":39,"value":"Action","slug":"action"},
  {"id":40,"value":"Animalier","slug":"animalier"}
]}]}
```

Every group allows a set of selected values in the website. Send selected **value IDs**, not group IDs, flattened into `options=39,40`. Preserve labels from the response and cache these public definitions by root category. Switching root clears selected subcategories and options; switching subcategories clears selected options. The website keeps video technical filters when switching between video subcategories.

## Which filters to show

The current listing client shows the root's fetched option groups regardless of selected child, with explicit video exceptions. Do not derive search filters from Upload's mandatory fields.

| Selection | Filters from `/filter-options` |
| --- | --- |
| All categories | No category option groups or video technical filters |
| Root 1 Films & Vidéos | `type`, `genre`; video language uses separate `lang` values |
| Root 1, no child or a series child | Also `saison` and `episode` |
| Root 2 Ebook | `format-audio`, `type-audio`, `langue-ebook`, `genre-audio-ebook`, `format-ebook`, `langue-bd`, `genre-ebook`, `style-litteraire`, `demographique` |
| Root 10 Imprimante 3D | No groups in the observed response |
| Other roots | Fetch and render the returned groups |

The client identifies series children by slug `serie-tv`, `animation-serie`, `emission-tv`, or `serie-documentaire`. Season and episode are **option values**, not numeric `season` or `ep` query parameters. Example values include season group 7, `serie-integrale` value 118; episode group 6, `saison-complete` value 96, and `episode-01` value 97. Read their full available values from the endpoint. A straightforward multiselect works; the website adds shortcuts for full series, full seasons, and individual episodes.

Year and uploader are available across categories. Year is release year, sent directly as `year`; the website input permits 1900 through 2100. Uploader is `uploader` with a 100-character input. Search text is `name`, limited to 200 characters in the client. Exclusivity and palliative filters are also global. These visibility rules come from the [listing client](https://c411.org/_nuxt/o7Qf9Ugw.js).

## Video technical filters

These choices are defined in the first-party JavaScript rather than returned by `filter-options`. Show them for native root 1. Values are comma-separated strings, with case and punctuation preserved.

| API parameter | Values sent by the website |
| --- | --- |
| `resolution` | `2160p`, `1080p`, `720p`, `SD` |
| `source` | `BluRay`, `Remux`, `BDMV`, `WEB-DL`, `WEBRip`, `DVDRip`, `HDTV`, `SDTV` |
| `codec` | `H.265`, `H.264`, `H.263`, `H.262`, `AV1` |
| `hdr` | `SDR`, `HDR10`, `HDR10+`, `DV`, `DV.HDR10`, `DV.HDR10+` |
| `audioType` | `lossless`, `lossy` |
| `channels` | `7.1`, `5.1`, `2.0`, `1.0` |
| `profile` | `compatibility`, `pure`, `hc_optimized`, `optimization` |
| `lang` | `MULTI`, `VFF`, `TRUEFRENCH`, `VOSTFR`, `VFQ`, `VF`, `MULTI.VF2`, `VF2` |

The profile labels are Compatibilité, Home Cinéma Pure, Home Cinéma Optimisé, and Optimisation in the [profile definitions](https://c411.org/_nuxt/sZ70szZm.js). Let the server apply their matching rules; do not approximate them locally.

Source requires care if copying the website's two-level control. UI `WEB` serializes as API `WEB-DL`. UI `BluRay` with no variant serializes as `BluRay,Remux,BDMV`. With variants selected, `Encode` becomes `BluRay`, `Remux` stays `Remux`, and `BDMV` stays `BDMV`. `variant` is a website URL parameter only; the API receives the expanded `source`. A desktop UI can instead expose those three API source choices individually with clear labels.

The client offers `crew=true` for searching actors, directors and screenwriters. This is separate from the ordinary title search and is cleared when leaving video. The current screenshots did not request this toggle explicitly, but it is a supported additional filter.

## Listing parameters and results

The [listing client](https://c411.org/_nuxt/o7Qf9Ugw.js) sends `page`, `perPage`, `sortBy`, `sortOrder`, `category`, `subcat`, `name`, `year`, `uploader`, `options`, the video parameters above, `exclusive`, `palliative`, `palliativeTail`, and `crew`. `subcat` is comma-separated native child IDs. The website supports multiple children within the selected root. Its sort fields are `createdAt`, `seeders`, `leechers`, `size`, `completions`, `comments`, `name`, `category`, and `relevance` for text search. Sort order is `asc` or `desc`.

Use `viewMode=flat` for selectable individual torrents. Two live requests verified:

```text
GET /api/torrents?page=1&perPage=2&viewMode=flat&category=1&subcat=6&resolution=1080p&sortBy=createdAt&sortOrder=desc
GET /api/torrents?page=1&perPage=2&viewMode=flat&category=2&options=201&sortBy=createdAt&sortOrder=desc
```

Both returned 200 and **clamped `perPage` to 10**. The first returned Film rows whose `tech.resolution` was `1080p`, with `total=41789`, `page=1`, `perPage=10`, and `totalPages=1000`. The second returned Ebook Audio rows with `total=4092`, `perPage=10`, and `totalPages=410`. These changing counts are observations, not constants. The first result still has a 10,000-row window despite its larger total. Honor the returned page metadata and show an explicit limit when `totalPages * perPage < total`. Do not infer completeness from a short page or from the advertised total alone.

Response shape, with invented identifying fields and representative actual types:

```json
{
  "data": [{
    "id": 1,
    "infoHash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "name": "Example torrent",
    "category": {"id": 1, "name": "Films & Vidéos", "slug": "films-videos"},
    "subcategory": {"id": 6, "name": "Film", "slug": "film"},
    "size": 1000000000,
    "seeders": 10,
    "leechers": 1,
    "completions": 20,
    "createdAt": "2026-10-23T10:00:00.000Z",
    "isExclusive": false,
    "isFreeleech": false,
    "status": "approved",
    "tech": {"resolution":"1080p","source":"WEB-DL","videoCodec":"H.265","hdrFormat":"SDR","audioCodec":"AAC","audioChannels":"2.0","languages":["VFF"],"season":null,"episode":null},
    "palliativeSince": null,
    "bountyZen": 0,
    "palliativeCountdown": null
  }],
  "meta": {"total":41789,"totalTorrents":41789,"page":1,"perPage":10,"totalPages":1000,"palliativeMatches":0,"palliativeFallback":false,"palliativeCount":764}
}
```

Rows can also include `description`, `language`, `quality`, `seasonEpisode`, `comments`, `uploader`, `hasNfo`, `contentStatus`, `isOwner`, `posterUrl`, `music`, and `media`. `tech` can be null, as observed for Ebook results. Metadata also includes global category and subcategory counts and total size. These category counts need not equal the filtered total. No download URL appeared in these rows; reuse TorrentLinker's existing validated hash-based c411 download URL builder.

## Listing fields for the Search page (verified 2026-10-27)

One read-only `GET /api/torrents?category=1&perPage=3&viewMode=flat` with the configured key. Values below are shapes, not data.

- **Row**: `leechers`, `completions`, `comments` (ints), `uploader` (string), `isExclusive`, `isFreeleech` (bools), `posterUrl` (a `https://image.tmdb.org/t/p/w500/…` URL, null when unknown), `language` (display string such as `Français (VFF/TrueFrench)`), and a `media` block for video: `kind` (`movie`), `title`, `originalTitle`, `year`, `runtime`, `genres`, `rating` (0 to 10), `directors`, `cast`, `overview`, `backdropUrl`. `tech` carries the parsed release facts: `resolution`, `source`, `videoCodec`, `hdrFormat`, `audioCodec`, `audioChannels`, `languages` (list), `season`, `episode`.
- **Meta**: `total`, `totalTorrents`, `totalSize` (bytes, over every torrent), `categories` (`[{id, count}]` for every native root), `subcategories` (`[{id, name, slug, count}]` for the selected root), `palliativeCount`. Counts and size come in the same response as the rows, so category pills with counts cost no extra request. Whether the counts follow the text query and filters was not tested: compare one filtered request before showing counts next to a search.
- The Search page reads these through `ListingRow` and `SearchPage.details`, `root_counts`, `subcategory_counts` and `total_size` in `torrent_search.py`. Badges come from `tech`, not from parsing the release name. Posters are TMDB URLs: do not fetch one per row without a cache and a bound.

## Palliative search

The website URL `palliative=true` becomes API `palliative=include`. The dedicated revival page uses `palliative=only`; see [palliative research](palliative.md). Normal text searches send `palliativeTail=true` when the toggle is off, so the website may append fallback revival matches. A desktop UI should label explicit modes such as Available, Include revival, and Revival only rather than assuming a Boolean means “only”. A row's `palliativeSince`, `bountyZen`, and `palliativeCountdown` describe this status. Do not infer it solely from zero seeders.

## Local reference fixtures

Public metadata snapshots from this investigation are at `/tmp/c411-search-categories.json`, `/tmp/c411-search-filter-options-1.json`, `/tmp/c411-search-filter-options-2.json`, and `/tmp/c411-search-filter-options-10.json`. Sanitized, shortened listing examples are `/tmp/c411-search-listing-0.json` and `/tmp/c411-search-listing-1.json`. They contain no API keys, private download URLs, uploader identity, descriptions, or original torrent names and hashes. Tests should use minimal synthetic fixtures with these shapes, rather than committing the whole live catalogue response.

## Agent and Assistant discovery tools

The shared `search_indexer_options` and `search_indexer` tools now expose the native
Search UI's controls directly. Assistant/shared-server instructions prefer these
live tools for title/genre/year discovery; Catalogue queries remain explicit cached
bulk/ranking/offline operations. An unavailable live query never silently substitutes
a cached title or guesses a genre from its name.

Filter metadata reports the category namespace, dynamic visible facets/value IDs,
all global and video controls, exact-year bounds and unsupported range semantics.
Video choices and facet visibility are shared with the desktop Search UI. Invalid
category namespaces, unavailable option IDs and incompatible filters fail before
the listing request. Native multi-subcategory CSV searches are supported within one
root. Non-c411 Indexers retain basic Torznab searches and explicitly reject advanced
native filters instead of silently ignoring them.

Search retains an immutable exact returned-page selection, usable directly with
comparison, durable lists and owner-reviewed queueing. It does not queue/download by
itself. Lists preserve the live query/filter/page/backend provenance. True server
pagination, accessible-window limits and explicit revival-fallback metadata are
returned; upload/publication timestamps are separate from release-year filtering.
Optional exclusion of completed client torrents is page-local (paused included),
never fills from other pages and fails if the client observation is unavailable.

A provider-boundary regression also covers valid JSON-encoded operation arguments
in prior history during context compaction; these are normalized safely rather than
indexed as dictionaries.

Validation uses shared MCP, actual owner approval, native UI filters and simulated
c411 HTTP. The local Qwen baseline used only cached Catalogue discovery and failed
the live-query assertion. After the change, four natural French requests passed:
science-fiction film in 2024, jazz music in 2023, fantasy ebook in 2022, and a
science-fiction film after 2020 (no invented year-range parameter). They fetched
native definitions, sent actual category/subcategory/year/option IDs and returned
the live title without queueing. The four-case run passed in 61.3 seconds; a more
faithful category-options fixture was then checked with the unchanged ebook case
(1 passed, 13.5 seconds). Model correction after invalid filter attempts was observed;
these opt-in checks do not guarantee future model behavior.

Final validation: **1,266 passed, 97 skipped** in the complete suite (205.74 seconds),
plus the opt-in local-model runs above. **60 focused tests** passed, including exact
native page → owner approval → queueing only the returned hash, durable provenance,
all native filter parameters, client/category isolation, unavailable-client exclusions,
revival fallback and JSON-encoded history compaction. Ruff, formatting, mypy and
whitespace checks passed. Parallel Standards and Spec reviews reported no remaining
actionable findings. The previously known upload-view teardown callback failure did
not recur in this full run. No release or push was performed.
