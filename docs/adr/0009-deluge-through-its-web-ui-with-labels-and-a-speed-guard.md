# Deluge through its Web UI, with labels for tags and a speed guard during checks

Some users seed with Deluge instead of qBittorrent. The user chooses one Torrent Client in Settings. Everything else — Reseeds, Plans, the Seeding view, Path Mappings — keeps going through the same port (`Qbit` in `qbit.py`, named when qBittorrent was the only client), and Deluge gets an adapter for it (`deluge.py`).

The adapter talks to Deluge's Web UI JSON-RPC, not to the daemon's own RPC: it needs only the address and the Web UI password that Sonarr, Radarr or Prowlarr already use, and no new dependency (`httpx` is already there). When the Web UI is not connected to a daemon, the adapter connects it to the first one of its host list. Deluge 2.x is supported; 2.1.1 (Debian and Ubuntu's) and 2.2.0 are tested in CI.

The adapter speaks the port's qBittorrent vocabulary, so the Reseed flow did not change:

- **States** are translated into qBittorrent's names (`Paused` → `stoppedUP`/`stoppedDL`, `Seeding` → `uploading`, `Checking` → `checkingUP`/`checkingDL`…).
- **Tags** become Deluge labels, from its Label plugin, which ships with Deluge but is off by default. A Reseed must carry its `verifying` tag so that an interrupted one is found again, so the connection test, and any add carrying tags, are refused until the plugin is on, rather than the app turning a plugin on in the user's client. A torrent has one label: `torrentlinker:partial` is written `torrentlinker-partial` and read back as `torrentlinker` and `torrentlinker:partial`, and adding such a tag replaces the previous one, which is all the Reseed flow needs.
- **Pieces**: Deluge marks a verified piece 3, not 2, and sends no list when it has every piece.
- **File priorities**: 0 skips a file in both clients; any other priority becomes Deluge's normal (4).

## The speed guard

Deluge rechecks a stopped torrent by resuming it, and stops it again once the check ends (`Torrent.force_recheck` in Deluge 2). For that moment the torrent can connect to peers and fetch pieces, which would be written into the user's files: a Partial Match's pieces shared with absent files, or the pieces that differ when Verification fails. qBittorrent checks a stopped torrent without starting it, and ADR-0002 and ADR-0004 rely on that.

So a torrent the adapter adds stopped is added with its download speed limited to 0.001 KiB/s, which Deluge applies as 1 byte/s: a 16 KiB block cannot arrive before Deluge stops the torrent again. The limit is lifted when the torrent is started or when its Verification ends, so a Partial Match the user starts later downloads at full speed. While Deluge reports `Paused` but is not actually paused (its recheck), the adapter reports a checking state, so the Reseed flow waits for the real verdict.

Tests run against real Deluge in throwaway Docker containers (`scripts/deluge_sandbox.py`): one sees the data at its own path, the other as `/data` through a Path Mapping. Both check that library files keep their bytes.

## Consequences

- Strings in the interface say "your torrent client" where they meant qBittorrent; the qBittorrent and Deluge connection forms keep their own names.
- Code identifiers (`Qbit`, `MappedQbit`, `PathMapping.qbit`, the `qbit` key in settings) keep the old name, to avoid churn and keep settings files readable by older versions.
- A user who sets their own label options in Deluge on the `torrentlinker…` labels (moving completed torrents, for example) changes what happens to these torrents; the app sets none.
