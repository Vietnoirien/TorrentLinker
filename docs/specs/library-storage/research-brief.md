# Library storage: research brief

Covers three requests: replacing a library film by a better release, a file manager for moving files across folders and disks, and automatic library organization. Sources are the three research reports from 2026-11-27, summarized below.

## What the field does

**Replacing a film (Radarr/Sonarr)**
- A quality profile sets a cutoff plus a minimum custom-format score. TorrentLinker already has the equivalent: ReleaseScore with `UPGRADE_MARGIN` in `media_tracker.py:344`.
- On upgrade, Radarr imports the new file and sends the old one to a recycle bin purged after N days. Seeding the old torrent is left to qbit_manage. It tags `noHL` and uses share limits (ratio and/or seed time, with cleanup off by default).
- Known failures:
  - the old file gets deleted before the new one is in place;
  - Plex resets watched state because the path changed;
  - a seeded file disappears without the client being told.

**Organizing the library**
- Radarr renames from templates and shows a rename preview before applying. Its Interactive Import is a table of detected title, year and quality, with a per-row fix and a Move or Hardlink choice.
- Jellyfin naming: `Film (Year) [tmdbid-…]/Film (Year) [tmdbid-…].mkv`, with multi-version suffixes. Jellyfin dropped its own auto-organize, and Emby's is weak. Organizing is done by a separate tool.
- The TRaSH layout puts torrents and media on one filesystem (`/data/torrents` and `/data/media`), so a hardlink acts as an instant move. Hardlinks never cross disks or mounts. Editing a seeded file in place breaks its torrent.

**File managers and multiple disks**
- Common UX:
  - dual pane, single pane on mobile;
  - a background job queue with per-item progress and verification (unRAID Dynamix);
  - a conflict dialog (Skip, Overwrite or Rename, "apply to all");
  - trash instead of delete.
- Silent partial copies are the most common complaint.
- mergerfs picks a disk by policy: `mfs` (most free space) or `ep*` (keep next to the files already there). unRAID's mover pauses torrents first.
- Moving seeded data per client:

  | Client | How it moves |
  |---|---|
  | qBittorrent | `setLocation`; copy then delete when the disk changes |
  | Deluge | `move_storage` |
  | Transmission | `torrent-set-location move=true`; `free-space` reports the client's side |
  | rTorrent | stop, mv, `d.directory.set`, start |
  | µTorrent | manual steps |

- Generic recipe: pause, move (copy, verify, delete), re-point, recheck, resume in a `finally` block.
- Disk health: read Scrutiny or smartctl, don't reimplement it.

## What TorrentLinker already has
- Finding better releases: the "Meilleures versions sur le tracker" row, the daily recheck, and the tracker download button.
- The replace prototype (`docs/specs/media-replace/replace-prototype.html`):
  - toggles "Remplacer l'ancienne version" and "Attendre la fin de son partage";
  - a timeline;
  - a "Fin du partage" rule (time and/or ratio).

  No backend exists for it.
- Client transfers (`transfers.py`): copy, verify, confirm seeding, then a reviewed unlink with a journal. This is the safe move engine to reuse.
- `set_location` exists for qBittorrent only (`qbit.py:456`). Deluge, Transmission and rTorrent have no move.
- Free-space checks inside Plans and transfers (`plan.py:620`, `transfers.py:197`), but nothing about disks is shown anywhere.
- Undo journal for disk renames (`disk_rename.py`), symlink Link Folders (ADR-0020/0021).

## Constraints to settle
- ADR-0004: the app never writes a file it did not create. Moving or renaming the user's library files breaks this rule, so the decision needs a new ADR.
- Member grants (`accounts.py:64`) and Link Folder manifests are keyed by path string. Moving a folder orphans them.
- Watch state must follow the film, not its path, across a replace or a move.
