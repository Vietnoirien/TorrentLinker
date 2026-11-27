# The app moves, renames and trashes files under its storage roots

ADR-0004 kept TorrentLinker from writing to any file it did not create, apart from two narrow exceptions: deleting a torrent with its files from the torrent manager, and cleaning up after a client transfer. The Owner now wants three things that this rule forbids:
- Médias replaces a library film with a better release;
- a file manager, Fichiers, moves files between folders and disks, the new 14 To disk among them;
- Organisation renames the library to a Jellyfin layout.

The decisions are in `docs/specs/library-storage/README.md`.

This amends ADR-0004. The app may move, rename and trash files and create folders anywhere under its storage roots (`TL_STORAGE_ROOTS`), and only there. The rule applies to the user's own files as well as to files the app created.

## Rules

1. **Delete means trash.** Each disk has its own trash folder, so trashing is an instant rename. The trash is purged after 7 days by default (configurable) and every item can be restored. The only ways to delete data for good are emptying the trash and the torrent manager's delete with files (ADR-0004). Both are Owner-only and both ask for confirmation.
2. **A seeded file moves through its client.**

   | Client | Move | Rename |
   |---|---|---|
   | qBittorrent | `setLocation` | client renames the file paths |
   | Deluge | `move_storage` | client renames the file paths |
   | Transmission | `torrent-set-location` with `move=true` | client renames the file paths |
   | rTorrent, µTorrent | stop, move, re-point, recheck, start | rename on disk with re-point and recheck (ADR-0013, ADR-0017) |

   For rTorrent and µTorrent, a failed step still restarts the torrent. A torrent whose layout cannot be renamed in its client keeps its paths through the per-client Link Folder (ADR-0020, ADR-0021). A torrent under Reseed Verification is never moved.
3. **A move across disks is a copy.** The source is removed only after the copy is verified (by hash for torrent data, by size and content otherwise) and the client seeds from the new place.
   - A file no client seeds, or one seeded by rTorrent or µTorrent, is copied by the app, which reuses the client-transfer engine and its journal. The source then goes to that disk's trash.
   - A torrent in qBittorrent, Deluge or Transmission is moved by the client itself. The client copies the data, rechecks it and deletes the source, so nothing goes to the trash and the old disk frees its space at once. The Owner accepted this on 2026-11-27, because the recheck proves the copy.
   A file shared by several torrents (cross-seeds) moves once, through one torrent's client. The app then re-points each other torrent to the new place and rechecks it. Where a torrent's names or folders differ from the moved files, it goes through symlinks in its client's Link Folder instead. Every torrent keeps seeding, and the data stays as one copy (Owner, 2026-11-27).
4. **Every operation is journaled** before it starts, with who asked for it. A finished move or rename can be undone from Tâches, and an interrupted one is reconciled at startup. Nothing fails silently: each item ends verified, failed with a reason, or cancelled.
5. **Never in place.** The app never edits a seeded file's content (remux, tags, transcode). Conversions write a new file.
6. **Paths keyed by string follow the move.** Member folder grants, Library Folders, Download Folders, Link Folder manifests and path mappings are rewritten in the same operation. Watch state, progress and playlists follow the film, never its path.
7. **Who may do it.**
   - A Member with the new "Gérer les fichiers" Permission may move, rename and trash files inside their granted Library Folders.
   - Only the Owner may empty the trash, change disks, settings and placement rules, and replace a film.

8. **Ranging is one pass** (#223). Organisation moves and renames each item to its library's template as one Tâche item: the files are renamed inside their own folder (through the client when seeded), then moved to the library, and a failure puts every name back. The batch is kept on disk and resumes after a restart. Nothing moves in a request handler, and an item with no recognisable title is never moved.

## Considered Options

- **Keep ADR-0004, organize only with links** (a clean tree of hardlinks or symlinks beside the originals): rejected. Hardlinks never cross disks, the library would show two trees, and the Owner asked for a real file manager.
- **TRaSH layout with separate `torrents/` and `media/` trees joined by hardlinks**: rejected. Every film would exist under two names, and a release replacing the film would drop the hardlink silently. Renaming inside the client keeps one file.
- **Delete through the client when a replaced release finishes seeding**: rejected in favour of the trash. A replaced 4K release is too costly to lose to a wrong rule.
- **Letting the app format or mount disks**: rejected. Preparing a disk stays the Owner's job, and Disques explains the steps.

## Consequences

- Storage roots mounted read-only, as in the Owner's container today, must become writable before the trash, Fichiers or Organisation can work. Disques reports a read-only root instead of failing on its first move.
- Each client adapter gains move and rename calls, and the client protocol gains `move_storage`.
- A new journal table holds operations and their undo, and trash entries remember their original path, who trashed them and when.
- The glossary gains Corbeille, Tâche and the "Gérer les fichiers" Permission.
