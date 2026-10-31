# Linux package follow-up, 2026-10-31

Local artifact built from `908c589` plus the PySide metadata and smoke-check fix
committed with this report. Python 3.13.11, PySide 6.12.0, Linux x86-64. This is a
workstation build, not the Ubuntu 22.04/Python 3.12 release workflow artifact.

## Packaging defect found and fixed

The first frozen support report returned `pyside: unavailable`: the PyInstaller
spec copied app metadata but not PySide metadata. The spec now includes it, and the
existing package MCP smoke test checks that support reports contain both the app
version and a known PySide version. The rebuilt authenticated server report returns
`1.0.0b27` and `6.12.0`. The application version was not bumped.

The frozen server also served the updated English and French backup/restore guides.
Unauthenticated report requests returned 401; an owner login could download the JSON.
Server shutdown completed without a traceback. Its SIGTERM exit follows Uvicorn's
signal behavior and was checked against the complete shutdown log.

## Execution evidence

All runs used disposable configuration and a null keyring inside a private network
namespace with only loopback enabled. They did not access production clients or
tracker services.

| Check | Exit | Seconds | Result |
| --- | --- | --- | --- |
| Frozen executable | 0 | 4.82 | Media playback, MCP, support-report metadata and shutdown passed |
| AppImage, run 1 | 0 | 6.48 | Same checks passed |
| AppImage, run 2 | 0 | 5.43 | Same checks passed |
| AppImage, run 3 | 0 | 5.48 | Same checks passed |
| AppImage opening 0.12.2 fixture copy | 0 | 6.59 | Smoke checks and post-exit persisted-state checks passed |
| AppImage opening beta.27 fixture copy | 0 | 6.94 | Smoke checks and post-exit persisted-state checks passed |

Each historical fixture was produced by the actual tagged sources using
`scripts/check_upgrade.py`, then copied into the AppImage's isolated XDG data folder.
The package log confirmed that folder was used. After exit, the current state readers
checked every saved setting, both clients' Local Drafts, full queue payloads,
conversation settings/text, interrupted jobs and fixture credentials. Media and
Upload attachment hashes matched, and the untouched original fixture still matched
its initial directory hashes. See the [source upgrade report](upgrade-restore-2026-10-31.md)
for fixture contents and limits.

Thirteen focused packaging, diagnostics and desktop-shutdown tests also passed.
Lint, formatting and typechecking passed.

## Artifact and remaining limits

Former local artifact: `/tmp/tl-polish-package-20261031/dist/TorrentLinker-x86_64.AppImage`.
SHA-256: `03ce752ca5eb74ed0b7e565d605aba57a04411497ee79ab04bd8a6c308c32dc5`.
The temporary package, build files and raw results under `/tmp/tl-polish-package-20261031/`
were deleted at the owner's request after validation to free RAM-backed `/tmp` storage.
The measurements and conclusions above remain the recorded evidence.
Nothing was published and the user's running app was not replaced or restarted.

These offscreen checks add Linux package startup, migration and shutdown evidence.
They do not establish complete installed user workflows, graphical playback with a
real audio device, Windows/macOS behavior, Docker deployment migration, live remote
reconciliation or enabled-schedule recovery. Repeat the required checks on the exact
release candidate and finish the remaining platform coverage in #47 and #50.
