# Changes since 1.0.0-beta.27

Draft notes for the next beta. These changes are on `main`; they are not in the
published beta.27 packages. No new version or release has been assigned.

## Downloads and client paths

- Fixed the repeating queue-display `KeyError` after a successful send. Estimates
  now use the same snapshot as the displayed rows while the queue catches up.
- Additional free-space reserve is opt-in for new direct-download grants. Existing
  nonzero reserves remain owner-controlled. Selected downloads, unfinished client
  downloads and unresolved reservations must still fit in the available space.
  Plan percentage margins no longer block direct sends.
- Fixed Windows mapped-drive destinations that resolve to UNC paths before being
  sent to a Linux/Docker Torrent Client. This addresses the reproduced Transmission
  "download directory path is not absolute" failure.
- Clarified uncertain Upload and download outcomes after interruption. Recovery
  continues to require checking the remote client or tracker before another send.

## Assistant and desktop reliability

- Follow-up prompts now include recorded execution evidence, so earlier assistant
  prose is not treated as proof that a download was sent or disk space was checked.
  Replies without tool calls visibly say that no application action was performed.
- Fixed unnecessary context compaction for fresh discussions without history.
- Fixed an Assistant shutdown race between closing SQLite and an in-flight provider
  assessment. Late provider and profile callbacks ignore destroyed windows.
- Fixed Linux/GNOME system-theme detection in the AppImage.
- Completed more English/French Upload diagnostic explanations and live browser
  status translation.

## Responsiveness and support

- Reduced redundant native Torrents sorting and filtering work and bounded the
  tag sidebar. On the Linux fixture with 12,000 torrents, first display fell from
  1.93 seconds to 765 ms.
- Queue selection and idle polling no longer repeatedly decode the entire queue.
  Status updates preserve existing rows and estimates. At 12,000 entries, selection
  fell from 384 to 22 ms; a native send-status notification fell from 1.58 seconds to
  274 ms. Successful sends still rebuild the table when entries leave the queue.
- Chat updates retain unchanged messages and expanded receipts. Updating one run
  in a 100-run history fell from 825 to 28 ms. First opening still takes about 800 ms
  on that fixture. These are workstation measurements, not platform guarantees.
- Added desktop and browser support-report downloads containing allowlisted version,
  configuration structure and status counts. Reports exclude credentials,
  server addresses, private paths, titles and conversations. Packaged reports include
  the bundled Qt/PySide version.
- Added English and French stopped-app backup and restore instructions. Controlled
  upgrade, second-start and restore checks pass for 0.12.2 and beta.27 fixtures.
- Stall diagnostics now write thread stacks before the GUI recovers. Packaged smoke
  testing now includes ten Library rescans as well as media, MCP and shutdown checks.

## Validation and remaining blockers

The integrated local suite at `e054892` passed 1,885 tests with 148 optional skips.
All CI jobs passed through `c2965bb`; its main suite passed 1,881 tests with 154
environment-dependent skips, including the queue and chat improvements. The subsequent packaged-rescan probe
passed 31 focused source checks and the frozen Linux executable/AppImage checks.
Windows CI also passed the ten rescans inside the packaged executable at `c2965bb`.

Two Radiance replays against the current code passed with server-default sampling: a real
approval proposal after earlier false send claims, and approval of the exact two
queue entries requested for removal. They do not replace the complete model matrix.

The reported Windows Library freeze is still unreproduced. Controlled tests do not
identify the cause on the affected computer. Remaining work includes affected-machine
stacks, final release-platform validation, real companion/recovery walkthroughs,
large-list first-display costs and the final paired desktop/browser audit.

See the [polish backlog](polish-plan.md), [queue measurements](../research/queue-performance.md),
[chat measurements](../research/chat-performance.md) and
[Windows investigation](../research/windows-library-rescan.md) for evidence and limits.
