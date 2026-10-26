# Media center implementation specification

Baseline: `1d8da5f245c909ec5002c44f66046763e721d35f`.

TorrentLinker gains a Media area with Video and Music views. It reads all media in registered Library Folders, including files unrelated to c411. Adding a media folder uses existing Library Folder registration. Media discovery does not require contacting an Indexer or Torrent Client. A refresh scans folders in a background job, reports progress, supports cancellation and retains the previous inventory for unavailable folders. Browsing and Assistant queries read the saved inventory instead of scanning again.

## Modules and interfaces

`MediaLibrary` owns discovery, metadata, durable inventory, resume and watched state, playlists, opaque saved selections, player sessions and their command queues in `media.sqlite`. `AgentService.media` provides the same instance to desktop, HTTP routes and MCP tools. File paths stay inside this module. Public rows expose opaque media IDs and authenticated media/artwork/subtitle URLs. Each stream request rechecks the current Library Folder registration, Setup storage roots, symlinks, file size and known incomplete Torrent Client observations. A removed folder immediately removes access even before refresh. Files are opened read-only. No transcoding, uploads, media deletion or remote hosting is added.

Desktop uses QtMultimedia `QMediaPlayer`, `QAudioOutput` and `QVideoWidget`. Web uses native HTML video and audio elements with ranged HTTP streaming under existing cookie authentication. Unsupported formats show a clear codec error and an explicit external-player fallback. Opening chat, navigating away or changing filters keeps the current player and queue alive.

Media metadata comes from filenames, existing mutagen/MediaInfo readers and bounded local sidecars. Missing tags, genre, language, synopsis and artwork stay unknown. Filename guesses are labelled as such and do not establish canonical identity. Video releases group only when a local metadata sidecar supplies a shared explicit TMDb/IMDb identity; otherwise each release keeps its own card. Episode numbers can come from release parsing and are labelled filename metadata. Album grouping requires matching tagged artist/album plus the same parent folder, so different editions stay separate. Artwork and subtitle sidecars are read only within the registered media directory, subject to the same root and symlink checks. SRT is converted to WebVTT in memory for browser playback; no media file is modified.

Video supports recent, continue watching, film and series browsing, search, available metadata filters, poster/fallback cards, synopsis, release choice, episode browsing, subtitles, resume and watched state. Music supports album, artist and track browsing, artwork, search, filters, queue, shuffle, repeat and saved playlists. Playlists are independent of Download Queues.

## Playback session protocol

Every browser or desktop instance opens its own player session with an unguessable session ID and token. Owner routes require both the existing authenticated owner connection and that session token. Session reports contain current item, position, duration, paused state and queue state. Control requests append ordered commands; only that session can consume them. Old sessions expire for remote control after missed heartbeats. Session state and playlist/resume data survive app restarts; browser credentials remain local to that browser instance.

A contextual Chat button opens an existing Assistant UI in a right panel and places or reuses a conversation in the Media folder. Binding requires an owner action with the session token. The binding records the conversation actor, session and current permitted client. Assistant/MCP commands resolve through this binding and recheck the actor grant and client permission. Tools cannot pick a different session by supplying an ID. Rebinding detaches the previous conversation/session association. Ordinary unbound MCP callers can search permitted media but cannot control another instance's playback.

Context is refreshed from the bound session and browsing selection/filters when a run begins. It includes the current video/release/position or music track/album/queue/playlist. The Assistant instruction avoids plot spoilers beyond the current video position. Descriptions and local sidecars remain untrusted content. Search tools save exact selections server side and return numbered summaries plus a selection handle. Playback and presentation tools resolve selection handles and positions instead of asking the model to copy lists of media IDs.

## HTTP contract

- `GET /api/media?client_id=...&kind=video|music&q=...&view=all|continue|recent|films|series|albums|artists|tracks&genre=...&year=...&language=...&availability=...` returns `{rows,total,filters,scanning,errors}`. Rows contain `id`, `content_id`, `title`, `kind`, `release`, `year`, `artist`, `album`, `album_id`, `genre`, `language`, `series`, `season`, `episode`, `duration`, `position`, `watched`, `available`, `availability`, `reason`, `description`, `artwork_url`, `added`, `subtitles`.
- `POST /api/media/scan` with `{client_id}` submits a cancellable existing job.
- `GET /api/media/items/{id}?client_id=...` returns the row plus `releases` and `episodes`.
- `GET /api/media/items/{id}/stream?client_id=...` supports single byte ranges and HEAD.
- `GET /api/media/items/{id}/artwork?client_id=...` and `/subtitles/{subtitle_id}` return checked local sidecars.
- `POST /api/media/sessions` with `{client_id,platform}` returns `{id,token,state,commands:[]}`.
- `POST /api/media/sessions/{id}` with `{token,report?,action?,media_ids?,index?,position?,volume?,shuffle?,repeat?,context?}` reports state and/or queues an action, returns `{id,state,commands}`. Supported actions: `play`, `pause`, `seek`, `volume`, `queue`, `next`, `previous`, `shuffle`, `repeat`.
- `GET /api/media/playlists?client_id=...` and `POST /api/media/playlists` with `{client_id,id?,name,media_ids}` persist playlists. `DELETE /api/media/playlists/{id}?client_id=...` removes a playlist only.
- `POST /api/media/items/{id}/watched` with `{client_id,watched}` updates watched state.
- `POST /api/media/sessions/{id}/chat` with `{token,conversation_id?}` binds/reuses a Media conversation and returns `{conversation_id}`.

All owner mutations retain existing CSRF protection. Agent media reads use allowed client IDs; mutations require the new owner-selectable media permission and execute mode. Contextual chat can explicitly authorize media control for its bound player, without broad torrent-control permission.

## Confirmed test seams

The user confirmed all three public seams on 2026-10-26. Tests proceed in vertical slices, red before green.

1. Media library and streaming HTTP interfaces: discovery independent of tracker, real tagged audio/video, incomplete/missing media, removal and symlink/root denial, byte ranges, subtitles, resume and playlist persistence. These catch backend behavior and storage access. They do not establish native codec support.
2. Assistant/MCP tools: search/presentation, context, permission checks and bound-session isolation. These catch wrong-player control and server selection mistakes. They do not establish browser or Qt rendering.
3. Desktop/web user flows: browse, actual fixture playback, seek/resume, queue/playlist changes and contextual chat preserving playback. These establish user-visible behavior for supported codecs in the test environment. Codec support elsewhere remains a platform limitation with a visible fallback.

Focused tests and type checks run during implementation. The parent agent runs one full suite and the code-review skill after integration, then commits reviewed changes. No version bump or publication is authorized.

## Agreed amendments during implementation

The user explicitly added preview of unfinished qBittorrent sequential downloads. Ordinary Play still requires a complete accessible file. **Preview downloaded portion** is a separate owner action. The first implementation accepts only single-file torrents with live `seq_dl=true`, a proven piece range starting at zero, positive piece size and a complete live piece-state map. Only contiguous downloaded pieces with state 2 at the beginning of that file are readable. File size or allocation alone never proves downloaded bytes. Growing files and qBittorrent's `.!qB` filename suffix are supported. Other clients and ambiguous multi-file offsets remain unavailable for preview.

Each preview attempt freezes the verified prefix length. The authenticated web endpoint returns only that prefix with Range/HEAD support and refuses ranges outside it. The native player receives a held QIODevice capped to the same prefix. It never receives the unrestricted incomplete file. An explicit Refresh preview obtains a new window; there is no seamless growing-stream promise. Formats needing missing tail metadata can still refuse playback and say so. Preview handles are closed on replacement/stop and application shutdown. No download-priority change or transcoding is performed.

Poster browsing also reuses saved verified movie descriptions/artwork when an exact Torrent Client hash, a single video file, its local mapped path and size prove the association. Verified cached movie identity is required; matching title words is insufficient. Local NFO and cached identities use the same provider/movie namespace. TV identities use a separate namespace. Embedded album artwork is copied into private app-owned image cache after type, size and dimension checks. Public artwork URLs are fetched only through the existing bounded public-image reader when requested, away from the GUI thread.

Episode and release details expose explicit totals and next offsets. Album and artist views group on the server before paging. Current availability filters validate accessible files, and a grouped movie card selects an accessible release when another release is missing. Playback queue edits compose over unacknowledged commands while preserving the current item when entries before it are removed. Desktop session credentials live in a private app-owned file so queue, shuffle/repeat and chat association survive a restart, without auto-starting partial preview.
