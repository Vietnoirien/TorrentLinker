# Data, updates and troubleshooting

[Documentation](../../README.md) · [Français](../fr/donnees.md)

[Updates](#updates) · [Reporting a problem](#reporting-a-problem) · [Where TorrentLinker keeps its data](#where-torrentlinker-keeps-its-data)

## Updates

TorrentLinker checks GitHub for a newer stable release at startup and every 30 minutes while running, reusing successful checks for 30 minutes. A small, dismissible notice links to the release page when an update is available. Downloads and installation remain manual. The comparison uses the version the running window started with, even if a newer version is installed on disk. The check uses your configured internet proxy, sends no account or torrent information, and stays silent when GitHub is unreachable.

## Reporting a problem

Check your Indexer and client connections in Settings. For NAS or Docker setups, also check [Path Mappings](getting-started.md). Include the app version, operating system, torrent client and reproduction steps in a [GitHub issue](https://github.com/Vietnoirien/TorrentLinker/issues). Remove API keys, passwords and private announce URLs from logs or screenshots before sharing them.

Use **Settings → General → Export support report…** on desktop, or **Settings → Interface → Export support report…** in the browser. The JSON report includes app and system versions, client types, path-mapping formats, configuration counts, queue-state counts and the 20 most recent job kinds and outcomes. Client names and IDs become report-local aliases. It excludes credentials, server addresses, folder paths, torrent names, conversations and raw logs. Exporting does not contact your clients, restart jobs or send the file anywhere. Choose whether to attach it to your report.

This report describes the current application state. It does not check available disk space or prove a Path Mapping works. Desktop job history is included when the local agent service is running; otherwise `recent_jobs` is `null`. Reproduction steps and the visible error still help locate the problem.

## Back up before upgrading

1. Finish or cancel active work, then quit TorrentLinker. For Docker, stop the TorrentLinker service and wait for it to stop. A copy made while the app is writing its databases is not the procedure tested here.
2. Copy the **entire application data folder**, including subfolders, to a dated backup outside that folder. Use the desktop location below, the server's configured `--config` directory, or the Docker volume mounted at `/config`. Preserve permissions and include every file, including any SQLite journal files. Copy the whole folder rather than selecting individual databases.
3. Keep your deployment configuration and externally supplied secret/password files separately. Desktop credentials are in your operating system's keyring, outside this folder. On a new OS account or computer, enter those credentials again. The web server's `credentials.key` and `credentials.enc` belong together in the backup; externally supplied secret files still need their original mounts.
4. Install the new version and reopen the same data folder. Check client selection, Download Folders, Local Drafts, conversations and queues before starting new work. A download interrupted during submission should require checking the client, not be sent again automatically.

This backup contains private conversations, client configuration and, for the web server, decryptable credentials. Keep it private. The support-report export above is a separate, limited file intended for sharing. Neither backup includes your media files or the Torrent Client's own configuration; back those up separately if needed.

## Restore a backup

Stop TorrentLinker first. Keep a separate copy of the current data folder, then restore the complete backup into the original location with its original ownership and permissions. Do not merge selected database files from different backups. Reopen with the same app version that made the backup or a version whose upgrade path you have verified. Running older code against a database already migrated by newer code is not a tested downgrade procedure.

Keep the same Library and Download Folder mounts so saved paths still refer to the same files. Verify credentials and connections, then inspect pending and uncertain actions against the Torrent Client or c411 before retrying. Restoring app data does not undo downloads or Draft submissions accepted since that backup. Review any enabled schedules before resuming unattended operation.

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
- `assistant.sqlite`, `agents.sqlite`, `jobs.sqlite` and other state databases: conversations, permissions, job history and feature-specific state. The web server uses `catalogue.sqlite` for the state held in desktop `state.db`. Keep the whole folder to preserve these together.
- `torrentlinker.log`: the log, useful when reporting a problem.

Your torrent client keeps its own copy of every torrent added to it, in its own profile folder.

[Documentation](../../README.md) · [Français](../fr/donnees.md)
