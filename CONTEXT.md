# TorrentLinker

Reconciles files a user already has on disk with torrents on a private tracker, so the data can be seeded again from the Torrent Client without re-downloading or touching the files, and plans which new torrents to seed to earn the tracker's Zen reward.

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
_Avoid_: Type, category (category is a tracker/Torrent Client term)

**Path Mapping**:
A correspondence between a path prefix as this app sees it and the same location as the Torrent Client sees it, for a client in Docker, on a NAS or on another computer. One list of them applies to every path exchanged with the Torrent Client: Library Folders, Download Folders and Reseeds.
_Avoid_: Remote path, docker path

**Ignored File**:
A file (.nfo, thumbnails, samples, partial downloads…) excluded from every comparison between a Local Item and a torrent.
_Avoid_: Junk, extra

### Reconciliation

**Seeded Item**:
A Local Item whose files are already content of an Indexer torrent in the Torrent Client. A torrent of another tracker does not count: its files can still be cross-seeded.

**Partially Seeded Item**:
A Local Item of which some files, but not all, are content of Indexer torrents in the Torrent Client; not searched unless the user forces it.

**Orphan**:
A Local Item that no Indexer torrent in the Torrent Client covers, even if a torrent of another tracker does; the only kind of Local Item that gets searched.
_Avoid_: Missing, unseeded

**Indexer**:
A Torznab endpoint (URL + API key) where Candidates are searched; c411 is the first one.
_Avoid_: Tracker (when meaning the search API), site

**Candidate**:
A torrent returned by an Indexer search for an Orphan, not yet verified against local data.
_Avoid_: Result, hit

**Match**:
A Candidate whose file tree has been compared to the Orphan's files and found to correspond by size; either Full (every torrent file has a local counterpart) or Partial (some torrent files are absent locally and will be skipped).
A Match inside an archive pairs the torrent's files with what a .zip, .rar or .7z Local Item holds; Reseeding it means unpacking the archive first, which only the user decides.
_Avoid_: Link

**Rejection**:
A user decision that a given Candidate is not the Orphan, remembered so it is never proposed again.

### Seeding

**Torrent Client**:
The program that seeds, qBittorrent or Deluge, as the user chooses; Reseeds and Plans are added to it, and its torrents decide which Local Items are Seeded.
_Avoid_: Client (alone, when the Indexer's API client could be meant), qBit (outside code)

**Reseed**:
Adding a Match to the Torrent Client pointed at the existing data, renaming inside the torrent so its paths line up with the local files, then verifying by hash check before seeding.
_Avoid_: Inject, cross-seed, relink

**Verification**:
The Torrent Client's hash check a Reseed must pass at 100% before the torrent is started; a failed Verification removes the torrent (never the data) and becomes a Rejection.

### Zen

**Zen**:
The c411 reward earned by seeding, spent as download credit (1 Zen covers 1 Go downloaded).
_Avoid_: Token, points, bonus

**Zen Estimate**:
The Zen per day a torrent is expected to earn for this user, from its size, seeders and seed age.
_Avoid_: Yield, reward (alone)

**Zen Profile**:
The user's own parameters that change Zen: Class, progression tree already unlocked, seed hours per day and torrent cap; read from the user's c411 profile where the API allows, entered by hand otherwise.

**Zen Balance**:
The Zen the user currently holds on c411, as reported by their profile; distinct from any Zen Estimate.

**Class**:
The c411 role a user picks, which decides how Zen is paid; Tanker and Swarm Keeper are paid on seeding, Reuploader on uploads.

**Catalogue**:
The locally stored list of torrents available on an Indexer, with size, seeders and category, that a Plan chooses from.
For c411, a public Zen Lab metadata snapshot supplies older entries, and direct c411 metadata takes precedence. A snapshot or paging limit does not establish complete tracker coverage.
_Avoid_: Database, index

**Plan**:
A recommended set of Catalogue torrents to download and seed, chosen for estimated Zen or highest torrent notes within the user's free space, maximum download size, torrent limits and per-torrent size range.
_Avoid_: Portfolio, selection

**Download Folder**:
Where a Plan's torrents are downloaded, set per Indexer category or subcategory (falling back to the category's, then a default); it may lie inside a Library Folder.
_Avoid_: Save path (qBittorrent's term), download location (Deluge's), destination
