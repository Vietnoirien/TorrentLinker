# Data, updates and troubleshooting

[Documentation](../../README.md) · [Français](../fr/donnees.md)

[Updates](#updates) · [Reporting a problem](#reporting-a-problem) · [Where TorrentLinker keeps its data](#where-torrentlinker-keeps-its-data)

## Updates

TorrentLinker checks GitHub for a newer stable release at startup and every 30 minutes while running, reusing successful checks for 30 minutes. A small, dismissible notice links to the release page when an update is available. Downloads and installation remain manual. The comparison uses the version the running window started with, even if a newer version is installed on disk. The check uses your configured internet proxy, sends no account or torrent information, and stays silent when GitHub is unreachable.

## Reporting a problem

Check your Indexer and client connections in Settings. For NAS or Docker setups, also check [Path Mappings](getting-started.md). Include the app version, operating system, torrent client and reproduction steps in a [GitHub issue](https://github.com/Vietnoirien/TorrentLinker/issues). Remove API keys, passwords and private announce URLs from logs or screenshots before sharing them.

Use **Settings → General → Export support report…** on desktop, or **Settings → Interface → Export support report…** in the browser. The JSON report includes app and system versions, client types, path-mapping formats, configuration counts, queue-state counts and the 20 most recent job kinds and outcomes. Client names and IDs become report-local aliases. It excludes credentials, server addresses, folder paths, torrent names, conversations and raw logs. Exporting does not contact your clients, restart jobs or send the file anywhere. Choose whether to attach it to your report.

This report describes the current application state. It does not check available disk space or prove a Path Mapping works. Desktop job history is included when the local agent service is running; otherwise `recent_jobs` is `null`. Reproduction steps and the visible error still help locate the problem.

## Where TorrentLinker keeps its data

| System | Folder |
| --- | --- |
| Linux | `~/.local/share/TorrentLinker/TorrentLinker/` |
| Windows | `%APPDATA%\TorrentLinker\TorrentLinker\` (`C:\Users\<you>\AppData\Roaming\TorrentLinker\TorrentLinker\`) |

It holds:

- `torrents/`: every `.torrent` downloaded from c411, so none is requested twice, even after a restart or when a saved Plan is sent again. Files are named after a fingerprint of their download address, without your key. Deleting the folder is harmless: the files are fetched again when needed.
- `uploads/`: the `.torrent` and `.nfo` of each Upload, as sent in its Draft, and a folder per Upload with the images captured for its description.
- `state.db`: the Catalogue, remembered searches, Rejections, Verifications in progress, the saved Plan, the Uploads made and c411's Category Options.
- `settings.json`: your settings. API keys and passwords are not in it: they stay in the system keyring.
- `torrentlinker.log`: the log, useful when reporting a problem.

Your torrent client keeps its own copy of every torrent added to it, in its own profile folder.

[Documentation](../../README.md) · [Français](../fr/donnees.md)
