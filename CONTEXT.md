# TorrentLinker

Reconciles files a user already has on disk with torrents on a private tracker, so the data can be seeded again from qBittorrent without re-downloading or touching the files.

## Language

### Library side

**Library Folder**:
A folder the user registers for scanning, with a scan depth and a Content Kind.
_Avoid_: Source folder, watch folder

**Local Item**:
One entry found in a Library Folder at its scan depth — a single file or a folder — treated as the unit that a torrent may correspond to.
_Avoid_: File, release, media

**Content Kind**:
The nature of a Library Folder's contents (movie, series, music, ebook, game, 3D model…), which decides how Local Items are searched.
_Avoid_: Type, category (category is a tracker/qBittorrent term)

**Path Mapping**:
A correspondence between a path as this app sees it and the same location as qBittorrent sees it.
_Avoid_: Remote path, docker path

**Ignored File**:
A file (.nfo, thumbnails, samples, partial downloads…) excluded from every comparison between a Local Item and a torrent.
_Avoid_: Junk, extra

### Reconciliation

**Seeded Item**:
A Local Item whose files are already content of a torrent in qBittorrent.

**Partially Seeded Item**:
A Local Item of which some files, but not all, are content of torrents in qBittorrent; not searched unless the user forces it.

**Orphan**:
A Local Item that no torrent in qBittorrent covers; the only kind of Local Item that gets searched.
_Avoid_: Missing, unseeded

**Indexer**:
A Torznab endpoint (URL + API key) where Candidates are searched; c411 is the first one.
_Avoid_: Tracker (when meaning the search API), site

**Candidate**:
A torrent returned by an Indexer search for an Orphan, not yet verified against local data.
_Avoid_: Result, hit

**Match**:
A Candidate whose file tree has been compared to the Orphan's files and found to correspond by size; either Full (every torrent file has a local counterpart) or Partial (some torrent files are absent locally and will be skipped).
_Avoid_: Link

**Rejection**:
A user decision that a given Candidate is not the Orphan, remembered so it is never proposed again.

### Seeding

**Reseed**:
Adding a Match to qBittorrent pointed at the existing data, renaming inside the torrent so its paths line up with the local files, then verifying by hash check before seeding.
_Avoid_: Inject, cross-seed, relink

**Verification**:
The qBittorrent hash check a Reseed must pass at 100% before the torrent is started; a failed Verification removes the torrent (never the data) and becomes a Rejection.
