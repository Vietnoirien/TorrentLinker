# Upgrade and offline restore checks, 2026-10-31

Workstation evidence for [#50](https://github.com/Vietnoirien/TorrentLinker/issues/50).
Application revision: `b021a7cc31758b81f4ef840b57ba05f882e7684b`.
Environment: Linux, Python 3.13.11, the checkout's installed development dependencies.
[Machine-readable results](upgrade-restore-2026-10-31.json).

| Original version | Upgrade | Second restart | Offline backup restore |
| --- | --- | --- | --- |
| `v0.12.2`, `f4685ecc1fc0d08424520099fcd79bdd0488aa43` | Passed | Passed | Passed |
| `v1.0.0-beta.27`, `ad24628ae879e856a74c7b5e6509ddd0500a43ff` | Passed | Passed | Passed |

## Method

`scripts/check_upgrade.py` extracts each tag's actual `src` tree from local Git
objects and runs it in a separate process. That old code writes disposable settings,
Local Drafts, queues, a conversation and encrypted server credentials. The process
exits before its whole data directory is copied. The current code opens an upgrade
copy twice and a separate restored copy once. Hashes confirm that the original and
backup directories remain unchanged throughout.

The child processes block socket connections and OS keyring reads/writes. The
application constructors and persistent-state readers run, but HTTP servers,
provider requests, schedulers and Torrent Clients do not. No user data or active
application process is involved.

Assertions cover:

- Every saved setting survives a load/save round trip, including two named clients,
  client type/host, Library Folders, Download Folders, Path Mappings, language and theme.
- Desktop `state.db` and web `catalogue.sqlite` retain exact Local Draft IDs, revisions,
  forms, file manifests, findings and client scope for both clients.
- Both stores retain complete download payloads. Queued entries remain queued;
  interrupted `sending` entries become `uncertain` with automatic retry disabled.
- Conversation name, folder, permissions and limits survive, along with the stored
  question and answer. A previously running application job becomes `interrupted`.
- The restored `credentials.key` and `credentials.enc` decrypt the original fixture
  credential. OS keyring migration is deliberately outside this check.
- Media fixture bytes and saved Upload attachment bytes match their original hashes.
  SQLite integrity checks pass for both stores, assistant history and job history.
- No network or keyring access was attempted. No work was submitted or replayed.

To rerun, first make the historical tags available locally, then use:

```bash
.venv/bin/python scripts/check_upgrade.py --output /tmp/torrentlinker-upgrade-results.json
```

The script uses only temporary directories and removes them after completion. The
JSON output records the target commit and historical source commits. It tests the
working checkout, so commit application changes before using its commit identifier
as release evidence.

## Backup instructions and limits

The [English](../guide/en/data.md#back-up-before-upgrading) and
[French](../guide/fr/donnees.md#sauvegarder-avant-une-mise-à-jour) guides now describe
this stopped-app, whole-directory copy procedure. They distinguish the desktop
keyring from server credential files and cover original paths, permissions and
inspection of remote outcomes before retrying restored work. Ten existing desktop
and browser documentation tests passed after the guide updates.

This is source-level migration and offline-copy evidence. It is not a packaged
Windows, AppImage or Docker upgrade, an OS-keyring transfer, a filesystem-permission
migration, a live SQLite backup, or a rollback against already migrated databases.
The Local Draft fixtures exercise persisted metadata, not tracker publication or
complete presentation preparation. Enabled schedules and actual remote-state
reconciliation still need their separate acceptance scenarios. Repeat these checks
against the chosen release candidate and finish the platform/support matrix and
real-user observation before closing #50.
