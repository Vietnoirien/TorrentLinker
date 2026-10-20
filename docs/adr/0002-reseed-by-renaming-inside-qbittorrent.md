# Reseed by renaming inside qBittorrent, not by hardlinking

When a Match's paths differ from the local files, we add the torrent pointed at the existing data and use qBittorrent's per-torrent rename (save path, root folder, individual files) so the torrent fits the library as it is. The user's files are never moved, renamed or linked on disk. The alternative used by cross-seed — hardlinking the data into a separate folder laid out the way the torrent expects — keeps the torrent pristine but requires the link folder to share a filesystem with the data, doubles the directory trees to maintain, and isn't what the user asked for ("change the folders and the torrent names").

## Consequences

- A Reseed is only started after Verification passes at 100%; unmatched torrent files get priority 0, so qBittorrent never writes into the library.
- Restructured layouts (flattened folders, removed subfolders) are out of scope; hardlinking may be added later as a second Reseed strategy for those.
