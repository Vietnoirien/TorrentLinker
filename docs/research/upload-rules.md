# c411 upload rules

Summary of the c411 uploader guide (`/wiki/upload-rules`, member-only; pasted by the user on 2026-10-22) and the public integration guide bundle (`_nuxt/BggWbbiX.js`, "API Upload" tab). Only what bears on creating and uploading a torrent from an Orphan is kept. The per-category pages (`/wiki/cat-*`) were read through the user's logged-in browser. Not yet read: the "Guide des slots" (video duplicate slots) and the "PREZ HTML" page.

## Creating the .torrent

- A new .torrent is always made, reupload or not, carrying the user's private announce URL (it contains the passkey, a secret that acts as the account).
- Several files go in one folder, and the torrent is made from that folder.
- The private flag is set. The torrent is started seeding right after creation.
- Piece size is chosen by hand from the total size, never "auto":

  | Total size | Piece size |
  |---|---|
  | < 1 Go | 1 Mo |
  | < 2 Go | 2 Mo |
  | < 3 Go | 4 Mo |
  | < 8 Go | 8 Mo |
  | ≥ 8 Go | 16 Mo |

  Many small files under 1 Go may use a slightly larger piece. A .torrent above 16 Mo risks being refused by clients.

## Before publishing

- A reupload keeps the original release name exactly (e.g. `Babylon.2022.VFF.1080p.mHD.x264.AC3-ROMKENT.mkv`).
- A .nfo is required. For a reupload it usually comes from the original release page; otherwise see the description & NFO section (pending).
- The uploader must be seeding when the torrent is submitted, or it is refused, and must stay seeding until at least one leecher completes.

## Naming

General principles (games, applications and console emulation are exempt from the dot rule):

- Words are separated by dots: no spaces, dashes or exotic characters.
- No accents or non-standard characters.
- The original team tag is kept on a repost; adding a personal tag is forbidden without original work.
- With no findable original tag, the name ends in `-NOTAG`.
- Altering a release (subtitles, audio track, re-encode…) removes the source team tag from the title and file names, and the original release name goes in the description or NFO.

Templates by category (video is the strictest, for *arr parsing; resolution is optional below 720p):

| Kind | Template |
|---|---|
| Film, show, sport | `Nom.Année.Langue.Résolution.Source.[HDR details].CodecAudio.CodecVidéo-TEAM` |
| Remux/BDMV/ISO | `…Source.(REMUX\|BDMV\|ISO).[HDR].CodecAudio.CodecVidéo-TEAM` |
| Film collection | `Nom.COLLECTION.Années.Langue…-TEAM` |
| Clip, concert | `NOM.ANNÉE.RESOLUTION.SOURCE.CodecAudio.CodecVidéo-TEAM` |
| Documentary | `Nom.Année.DOC.Langue…-TEAM` |
| TV programme | `Nom.SXXEXX.DATE.Langue…-TEAM` |
| Series episode | `Nom.[Année].SXXEXX.Langue.Résolution.Source.CodecAudio.CodecVidéo-TEAM` |
| Season / seasons / complete | `Nom.SXX…`, `Nom.SXXSYY…`, `Nom.INTEGRALE…` (single-season complete keeps `S01`) |
| Music | `Artiste.Nom.Année.Codec[Bitrate.Frequence]-TAG` |
| Podcast | `NomÉmission.Date.[INTEGRALE].Codec.format-Team` |
| Samples | `Nom.Année.codec.bitrate` |
| PC game | scene/repack name kept as is; portable `Nom - version [OS - Langue - PORTABLE]`; GOG `Nom (Version) [Langue - OS][GOG]`; VR prefixed `[VR]` |
| Console game | `[Console]Nom [Région - Langue] Conteneur`; PS4/PS5 add `-CUSA…`/`-PPSA…` |
| Application | `Nom Version [OS Langue Type]`; mobile `[OS] Nom Version Langue [EXT]` |
| eBook | `Titre.Auteur.Langue.[Ext]-Team`; series member adds the set; packs `[T01 à T07]`, `[INTEGRALE]`, `[ANTHOLOGIE]` |
| Press | `Titre.Date.Langue.[Ext]-Team`; numbered `Titre.Rythme.Numéro.Date…` |
| GPS | `Marque.Zone.Année.Support` |
| 3D model | `Nom.source.format`; pack `NomDuPack.Source.[PACK].Format` |
| Adult | `[Studio].Titre.Acteur.Resolution.Codec`; JAV `JAV.[CODE].Titre`; hentai = series + `[HENTAI]` |

Each category also has an eligibility page (`/wiki/cat-video`, `cat-audio`, `cat-jeux-video`, `cat-applications`, `cat-ebook`, `cat-emulation`, `cat-gps`, `cat-impression-3d`, `cat-adulte`), not yet read.

## Description and NFO

- The description is BBCode with: an image or banner, a synopsis, screenshots (recommended for video and games), and the technical facts drawn from the NFO. Raw HTML is reserved to staff, some internal teams and category-certified reuploaders.
- A .nfo is required for every upload, unaltered, and must describe exactly this upload.
- c411's auto description assistant (Films & Vidéos and games only for now) builds the description from a compliant NFO and name, with the official template or a user template.
- NFO tools: C411NFO (`gen.c411.org`, MediaInfo in WebAssembly, offline; can also create the .torrent with source, private flag, piece size), DUPEFR (`dupefr.com`, original NFOs by team, to check first on a reupload), nfo123, NFO Builder, MediaInfoOnline. The NFO kinds C411NFO produces: video = full MediaInfo output with an ASCII header; music = artist, album, tracklist, durations; audiobook = author, narrator, chapters; books and other = a file list with sizes.
- Required facts per category:
  - Video: full title, container, total duration, total size, file count, VOD platform (if WEB), source, video codec, bitrate, resolution, each audio track's codec, bitrate, channels and language, subtitles' format, type (full/forced/SDH) and language. A pack of more than 10 episodes need not list them all in the NFO.
  - Audio: artist, album, year, track count, total size, source (CD, WEB, vinyl), codec, bitrate, sample rate, bit depth (lossless), full tracklist with durations.
  - Games and applications (and GPS): title, version, OS, year, install size, languages (text, voice), region, crack/loader/firmware, system requirements, install instructions (in French when the NFO is in English).
  - eBook: title, author, format, language, page or file count, size; average image resolution for CBR/CBZ/JPG; full list for packs; codec, bitrate and duration for audiobooks.
  - 3D model: name, file count, total size, format.
  - Adult: the rules of its media kind, plus 3 images (4 for a pack).

## Team Pending and tiers

- Every upload enters Pending. A reviewer validates it, asks for a correction within 48 h (non-compliance, no seed, detag/retag), or refuses it (forbidden content, duplicate, no seed, no correction in time, non-compliance, detag/retag). Malicious content means a ban.
- Certification is per category and counts only validated uploads there; it caps how many torrents may wait in Pending in that category at once:

  | Tier | Validated uploads | Pending at once |
  |---|---|---|
  | Novice | 0 | 1 |
  | Apprenti | 5 | 5 |
  | Confirmé | 10 | 10 |
  | Certifié | 15 | unlimited (no Pending) |

  Thresholds can change per category; the user's own figures are on their "Mes certifications" page. Refused or removed torrents do not count, and losing a validated one can drop the tier.

## Detag rules (enforced by an automatic engine)

The team tag must agree across the title, the NFO and the media file names:

1. Filename detag: the title carries a tag no media file carries (typically a file renamed by Radarr/Sonarr). Media files must end with the original tag.
2. Coherence detag: title, NFO and files carry different tags.
3. Detag by omission: the title says `-NOTAG` while the NFO or a file carries a team. `-NOTAG` is valid only when no team can be found, and then appears in the title, the NFO and the media file names.
4. Retag: the original tag replaced by the uploader's own name. Tracker ban.

So a media file is named exactly as the release title plus its extension (title `…x264-TFA`, file `…x264-TFA.mkv`); for a single-file Upload the file inside the torrent is `<title>.<ext>`, e.g. `Petit.Etau.De.Bureau.NOTAG.3MF.3mf`.

Exceptions: BDMV/ISO sources carry no tag in their files; audio codec subtypes (`AAC-LC`, `DTS-HD MA`) and dashes inside team names (`Tsundere-Raws`, `WEB-DL`) are not mistaken for tags. Known detag sources (e.g. Wawacity) and banned teams (k0RE) are blocked outright.

## Content rules per category

Read on 2026-10-22 from `/wiki/cat-*` (video page last edited 2026-10-22). Only rules an upload tool could check or must surface are kept.

Common to almost every category: no RAR/ZIP/7z (exceptions: console and emulation packs, adult games, install files), no downloader executables, no malware, content in French (eBooks strictly; video needs French audio or full French subtitles).

### Films & Vidéos

- Title: the French release title (e.g. "Insaisissables", not "Now You See Me"); the original title goes in the description. Special characters in team tags are dropped (`Tsundere-Raws` → `TsundereRaws`).
- Accepted: films, series (episode, full season, complete series only when finished), anime, documentaries, TV programmes, concerts/clips/shows, sport, non-amateur shorts. No incomplete seasons. Pack files must share the same specs and the same team.
- Containers: MKV, MP4, M4V, AVI, TS, M2TS; BDMV/ISO for Blu-ray, VIDEO_TS/ISO for DVD. Forbidden: WMV, MOV, SWF, FLV, RM, archives, burned-in subtitles (except broadcaster or anime).
- Resolution tags by minimum size: SD 640×360, 720p 1280×720, 1080p 1920×1080, 2160p 3840×2160.
- Codecs: H.264/H.265/AV1; MPEG-2 and XviD only for very old media; VC-1 only in untouched discs. Pure sources (REMUX/BDMV/ISO) say `AVC`/`HEVC`; untouched WEB-DL says `H264`/`H265`; re-encodes say `x264`/`x265`. GPU encoders (NVENC, QSV, AMF) forbidden; preset medium or slower; encode settings must be visible.
- Minimum video bitrates: 1080p x264 2,500 kb/s, x265 1,200, AV1 800; 2160p x265 2,800, AV1 2,200; SD XviD 1,500. None for an identified WEB-DL; Netflix 1080p 5,000–7,500.
- WEB-DL vs WEBRip: Team Pending checks the NFO for "untouched", then for an x264/x265 encoder, then for the VOD platform named in the description; missing platform → refused.
- HDR tags: `HDR10` (preferred over `HDR`), `HDR10PLUS`, `DV`; `DV.HDR10` only for profile 7 or 8. Rip DV must be profile 8. Nothing for SDR.
- Audio tags: e.g. `AAC.2.0`, `AC3.5.1`, `EAC3.5.1` (`DDP`), `EAC3.ATMOS.7.1`, `DTS.5.1`, `DTS.HD.MA.5.1`, `DTSX.7.1`, `TRUEHD.7.1`, `TRUEHD.ATMOS.7.1`, `LPCM`. In the title: the French track with most channels (lossy), or the track with most channels in any language (lossless). Stereo at least; 5.1 when the source has it.
- Language tags: one French track → `VOF`, `TRUEFRENCH`, `VFF`, `VFI`, `VFB` or `VFQ`; several languages → `MULTI.<one of those>`; VFF+VFQ → `MULTI.VF2`; no French audio → `VOSTFR` with full French subtitles (`FANSUB`/`FASTSUB` when unofficial; machine translation forbidden); silent → `MUET`.
- Sources: `WEB`/`WEB-DL`, `WEBRip`, `HDTV`, `PDTV`/`SDTV`, `BluRay`, `UHD.BluRay` (+ `BDMV`/`ISO`/`REMUX` when pure), `DVD`, `VIDEO_TS`, `DVDRip`. Forbidden: CAM, TS, SCR, MD, DVDSCR, DCPRip, encodes of encodes, DVD encodes (except old anime), upscales, YouTube-like rips, Plex transcodes, films still in cinemas.
- Duplicates: 28 slots per release in 4 profiles (Compatibilité 2, Home Cinéma Pure 7, Home Cinéma Optimisé 12, Optimisation 7). An upload must fill a free slot or beat its occupant (order: language, resolution, source, lossless/lossy, video codec, channels, audio codec, HDR). Identical releases: the earlier one wins. A WEBRip must weigh less than the existing WEB-DL and BluRay of the same resolution, unless it brings a better language. Corrective versions (PROPER, REPACK, FIX, RERIP, v2) replace the original. Special editions (UNCUT, EXTENDED, DC, IMAX, REMASTERED…) and a full season over existing episodes are not duplicates. The full slot table is on a separate "Guide des slots" page, not yet read.
- Zen: an upload in a main slot (COMPAT 1080p BluRay H.264, OPTI 1080p BluRay H.265 SDR, HCO 2160p H.265 DV/HDR) gets +0.50 on its note; another slot gets +0.35 while a main slot is still free, +0.50 once they are all filled. Fixed at upload.
- Banned tags: Wawacity, WAWA, k0RE/kORE, P2P, RARBG, FYR3N, Arkas, R3Z, ByPlex, WebVision, AgroaQc; MICKEY is a known detag to check closely.

### Audio

- Accepted: full albums, commercial box sets, complete discographies and complete studio/live sets (inactive artists only), podcasts and radio, sample packs. Singles only when 20 minutes or longer.
- Formats: lossless FLAC, ALAC, WAV, WV, AIF; lossy MP3, M4A (AAC), OGG, WMA; ISO only for SACD/Blu-ray Audio/DVD-Audio; one-track files only with a `.cue`.
- Minimum bitrates: MP3 320 kbps CBR (VBR accepted), AAC 256, podcasts/radio 128. Lossless must state bit depth and sample rate. One format and bitrate per album.
- Sources: CD, DVD-Audio, SACD, CD DTS, Blu-ray Audio, legitimate WEB, vinyl. Multichannel only from multichannel sources. No transcodes (MP3→FLAC, 128→320, stereo→5.1), no free-account streaming rips.
- A CD-Rip says `CD-Rip` in the title and holds `cover.jpg` (≥ 500×500) at the root, covers, a `.cue`, and an EAC `.log`; the description gives the catalogue number and a Discogs or MusicBrainz link.
- Duplicate: same format and bitrate, or a lower quality where a higher exists; an album also in a discography is not one; FLAC has no quality-based duplicate rule.

### eBooks

- Accepted: books, comics/BD/manga (whole volumes only; a BD pack holds every volume), press, audiobooks, sheet music, technical manuals, themed packs. French only.
- Formats: PDF, EPUB, MOBI, DjVu, CBR, CBZ, JPG/PNG in a folder; audiobooks MP3, M4A/M4B, FLAC at 64 kbps or more. At most two or three formats of the same book. External Calibre metadata files recommended.
- Duplicates strictly forbidden (a different format is not one). Press: a single issue may later go in a pack, never the reverse; a press pack with a quarter or more duplicates is refused.

### Games, applications, emulation, GPS

- Games: the release type (scene, repack, portable, GOG, DRM-free, preactivated) is decided from the files present (crack file, `.iso`, `setup.exe`, `steam_api`, GOG in the NFO) through a decision table. One scene release, plus one repack, one repacker release and one portable per scene release; one GOG version. Console: one version per game; containers per console (NSP/XCI, PKG, ISO…); regions PAL/EU, NTSC/US, NTSC-J/JP, HK. No archives except console packs (one archive per game).
- Applications: the title gives name, full version, OS, language and activation; an install note is mandatory except for portable. Release type from a table (keygen, crack, patch, installer). Archives forbidden (except install `.cab` and text/code support files). No alpha or early access, no IPTV software; an older version of the same generation is removed.
- Emulation: retro cartridge/floppy platforms and arcade, plus emulators and emulation OSes. Archives allowed only in packs of more than 50 files, with no password and an NFO listing every file. `.bin` needs a `.cue`; CloneCD needs `.ccd` and `.sub`. No mixing machines (except MAME).
- GPS: software, maps, packs, POI; version and activation stated; the application bans apply.

### 3D printing

- STL, OBJ, 3MF, STEP/STP, GCODE (with target printer and filament, STL source if possible); sources BLEND, F3D/F3Z, SLDPRT, FCStd. Packs must have one coherent theme, with every model listed in the NFO. No files stolen from independent creators who live off them.

### Adult

- Professional studio films and scenes, studio or performer packs in one format, JAV, hentai, adult games, structured image packs (one artist, photographer, studio, scene or performer, named in the title). Multi-tag allowed; MOV allowed (not for hentai). Hentai manga in French, English or Japanese (Korean for manhwa). No amateur videos, tube-site rips, SWF/FLV/RM, or archives (except games). Zero tolerance list means an immediate ban.

## Upload API

- `POST https://c411.org/api/torrents`, `Authorization: Bearer <key>`, `multipart/form-data`. The key needs the `upload:write` scope; the app's key today only has `torznab:read`.
- Required: `torrent` (file), `nfo` (file), `title`, `description` (BBCode by default), `categoryId`, `subcategoryId`.
- Optional: `options` (JSON keyed by option type, values from `GET /api/categories/{subId}/options`), `tmdbData` (JSON), `uploaderNote`, `descriptionFormat` (`html` needs `torrent:use_html_prez`).
- Same validation as the web form; goes to Team Pending unless the uploader is certified; rate limits by tier.
- Duplicates: `GET /api/torrents/by-tmdb?tmdbId=…&tmdbType=movie|tv` lists existing releases.
- Drafts (`drafts:rw`): `GET/POST /api/user/drafts`, `GET/PATCH/DELETE /api/user/drafts/{id}`, 15 per user, torrent and NFO as base64 in JSON.

### Draft fields

Read on 2026-10-22 from c411's upload page script (`_nuxt/CCL0Pfnp.js`) and a `GET /api/user/drafts` with the user's session, which answered `{"success":true,"data":[],"count":0,"maxAllowed":15}`.

The upload page saves a draft with `POST /api/user/drafts` (create, answers `data.id`) or `PATCH /api/user/drafts/{id}` (update), as a JSON body:

| Field | Content |
|---|---|
| `name` | Draft label: the release name, else "Brouillon sans titre" |
| `title` | Release name or `null` |
| `description` | BBCode or `null` |
| `categoryId`, `subcategoryId` | Category ids |
| `options` | Option values by option type id (as for `POST /api/torrents`) |
| `tmdbData`, `musicData`, `rawgData`, `bookData` | Metadata objects or `null` |
| `mediainfo` | MediaInfo text or `null` |
| `identifiers` | Work identifiers: a list of `{kind, value, raw}` |
| `templateId` | Presentation template |
| `uploaderNote` | Note for moderators or `null` |
| `ebookMetadata` | eBook metadata |
| `torrentFileName`, `torrentFileData` | .torrent name and base64 content |
| `nfoFileName`, `nfoFileData` | .nfo name and base64 content |

Missing metadata objects are sent as `null`. The browser authenticates with its session and a `csrf-token` header; an API key with `drafts:rw` uses Bearer instead, per the integration guide. `GET /api/user/drafts/{id}` returns a draft, `DELETE` removes it. A separate `/api/user/drafts/autosave` holds the page's own autosave.

Tried with an API key holding `drafts:rw` on 2026-10-22: `POST /api/user/drafts` with the fields above (3D model, category 10, subcategory 51, `options` `{}`) answered `{"success":true,"message":"Brouillon créé","data":{"id":…}}`. `GET /api/user/drafts/{id}` returns the same fields plus `category`, `subcategory`, `createdAt`, `updatedAt`, `isAutosave`, and `torrentFile` / `nfoFile` as `{name, data}`; the stored .torrent was byte-identical to the one sent. The draft showed on c411's upload page with its category, torrent and NFO. Drafts unused for 30 days are deleted automatically.

### Other upload endpoints

Listed in the site's route rules (`_nuxt/BFnh6W14.js`). Tried with an API key on 2026-10-22, all four refuse it: `parse` answers 403 "CSRF Cookie not found", `image` redirects to the login page, `flow` answers 401. They serve the logged-in site only, so the app cannot get c411's own checks before saving a draft, and the description's image is added by the user on c411 while reviewing the draft.

c411 category ids from `GET /api/categories` (same day): Imprimante 3D is category 10, with subcategories 51 Objets, 52 Personnages, 53 Pack.

- `POST /api/upload/parse`: the upload page's analysis. It takes `torrentName`, `nfoContent`, `mediainfoContent`, `nfoFileName`, `categoryId`, `subcategoryId`, `templateId`, `fileCount`, `fileSize`, `fileNames`, `releaseName` and more. It returns the parsed name, a suggested title, suggested option values with confidence, warnings, NFO validation, naming validation and similar torrents already on c411. Checking a draft with it before saving would show c411's own verdict, if it accepts an API key.
- `POST /api/upload/image`: image upload, a likely host for the description's required image. Refused with an API key (above), so the app saves the image as a PNG in its own `uploads/<release name>/` folder for the user to add on c411 (issue #30).
- `GET /api/upload/flow`: the upload mode (`manual` or `semi-auto`) and its configuration.
- `POST /api/presentation-templates/render`: renders a description from a template, metadata and the NFO.

## Open questions

- Does c411 rewrite the uploaded torrent (source tag, announce), changing its info hash, so the copy to seed must be downloaded back after upload?
- The exact size caps of the `torrent` and `nfo` fields (variables in the bundle).
- An app-generated NFO is accepted in practice (c411's own C411NFO is a MediaInfo dump), but the app would need MediaInfo (`pymediainfo` bundles libmediainfo on Windows and macOS, needs the system library on Linux).
