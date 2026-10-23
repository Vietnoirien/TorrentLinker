# c411 torrent details for Search

Checked on 2026-10-23 against c411's first-party [torrent page client](https://c411.org/_nuxt/D3klUg0B.js) and two bounded read-only API requests: one filtered listing and one torrent-detail request. Both returned 200 with the configured Bearer API key. No `.torrent` was downloaded, no image was fetched, and no account state was changed.

## One detail request supplies the preview

The canonical website route is `https://c411.org/torrents/{infoHash}`, where `infoHash` is the 40-character hexadecimal torrent hash. The website's [route configuration and deep-link mapping](https://c411.org/_nuxt/DvCJ89Mx.js) use this route. The native detail endpoint is `GET https://c411.org/api/torrents/{infoHash}`, already exposed by TorrentLinker's `Indexer.torrent_json`. The [page client](https://c411.org/_nuxt/D3klUg0B.js) reads that endpoint. Frontend bundle filenames can change; the app should use the route pattern, not depend on a bundle filename.

The live detail response is a **flat object**, not wrapped in `data`. Relevant shape, using invented identifying data:

```json
{
  "id": 1,
  "infoHash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "name": "Example torrent",
  "description": "<h1>Example</h1><p>Description</p><img src=\"https://image.tmdb.org/t/p/w500/example.jpg\">",
  "descriptionFormat": "standard",
  "category": {"id": 1, "name": "Films & Vidéos"},
  "size": 1000000000,
  "seeders": 10,
  "leechers": 1,
  "completions": 20,
  "uploader": "example",
  "createdAt": "2026-10-23T10:00:00Z",
  "files": [{"path": ["Example", "Example.mkv"], "length": 1000000000}],
  "metadata": {
    "category": {"id": 1, "name": "Films & Vidéos", "slug": "films-videos", "color": "#000000", "icon": "example"},
    "subcategory": {"id": 6, "name": "Film", "slug": "film"},
    "options": [{"id": 5, "name": "Genre", "slug": "genre", "values": [{"id": 39, "value": "Action", "slug": "action"}]}],
    "hasNfo": true,
    "nfoContent": "Plain text NFO content",
    "hasMediainfo": false,
    "tmdbData": {"posterUrl": "https://image.tmdb.org/t/p/w500/example.jpg", "backdropUrl": "https://image.tmdb.org/t/p/w1280/example.jpg", "overview": "Example overview", "title": "Example", "year": 2026},
    "rawgData": null,
    "musicData": null,
    "ebookMetadata": null,
    "bookData": null,
    "lowBitrateWarning": false,
    "isExclusive": false
  }
}
```

Other observed top-level keys include `team`, `isFreeleech`, `status`, `contentStatus`, `rejectionReason`, `isOwner`, `canEdit`, `canValidate`, `ownerDeletion`, `externalIds`, `trust`, and `revisionHistory`. Those are not needed for a read-only preview. This is an observed shape, not a guarantee that every field exists on every torrent. The frontend uses optional access for metadata and NFO.

## Description and images

**`descriptionFormat: "standard"` does not mean that the returned description is BBCode.** The sampled API response already contained rendered HTML: headings, paragraphs, strong text, tables, links, line breaks, and images. The [page client](https://c411.org/_nuxt/D3klUg0B.js) inserts `description` as HTML for the standard format. For `descriptionFormat: "html"`, it passes the same field to a component's `sanitized-html` property. Its editor calls the standard mode "Standard (BBCode)", but that does not describe the detail response's wire format.

The sampled description contained image URLs on `image.tmdb.org` and `flagcdn.com`. There was no top-level `posterUrl` in that detail response. `metadata.tmdbData.posterUrl` and `metadata.tmdbData.backdropUrl` were absolute HTTPS URLs. `tmdbData` also included `id`, `imdbId`, `type`, `title`, `originalTitle`, `year`, `overview`, `genres`, `rating`, `ratingCount`, `runtime`, `directors`, `writers`, `cast` entries with name and character, `releaseDate`, `countries`, `languages`, `productionCompanies`, `status`, `tagline`, and `keywords`. The other media metadata groups were null for this film; their image shapes were not checked.

Implementation recommendation: render a constrained, sanitized subset of HTML in the native preview. Retain text if a formatting feature is unsupported. Load approved remote image URLs asynchronously through the app's proxy-aware network client, without c411 authorization headers, and bound image count, response size, and decoded dimensions. Treat image URLs and link targets as untrusted metadata. Do not let the HTML renderer read local files, execute scripts, or initiate arbitrary requests. Website access remains the fallback for unsupported presentation elements.

## NFO and files

NFO is **already embedded** in `metadata.nfoContent`. The live sample contained 9,762 characters and `metadata.hasNfo` was true. The [page client](https://c411.org/_nuxt/D3klUg0B.js) previews it in a `pre` element as text. Its "download NFO" action creates a local text Blob from the same string; it does not fetch a separate `/nfo` endpoint. Therefore a plain-text, fixed-width NFO tab needs no additional request and should not interpret HTML inside the NFO.

The website's editing path prefers `metadata.nfoContentRaw` when present and falls back to `metadata.nfoContent`. That raw field was absent in the API response tested here. A viewer should use `nfoContent`, matching the website preview.

`files` is a list of objects with `path` as a list of path segments and `length` as a byte count. Display the joined segments and size. This is descriptive metadata: previewing it does not require a torrent file or access to the user's filesystem.

## Fetch scope

Load details only when the user opens a specific Search Candidate. Keep its website link available before metadata loads and after a failure. Cache successful detail responses for the session, with the selected hash as the identity; reject stale asynchronous results if the displayed Candidate changes. This follows [ADR-0005](../adr/0005-own-catalogue-and-zen-rules.md)'s distinction between user-requested detail reads and expensive per-torrent crawling during Plan construction. Do not fetch every Search row to render the Zen Estimate column: that estimate already uses listing metadata and the user's Zen Profile.
