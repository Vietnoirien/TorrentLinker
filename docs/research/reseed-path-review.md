# Reseed path review

Reviewed on 2026-10-30 at `7e595f6`, version `1.0.0-beta.24`. The reported screenshot came from `0.12.0`; the user also reproduced the problem with the latest beta available on October 29. The exact beta and the affected user's Torrent Client version are unknown.

The screenshot strongly indicates an existing torrent hash, hidden behind a filename-only exception. A desktop reproduction produces the same message structure. Series depth exposes separate discovery problems. The review also found a higher-priority defect: overlapping rename paths can move existing files on disk even though Reseeding promises to preserve their paths.

## Implemented corrections

The findings below describe the original revision. The follow-up implementation addresses the four defects:

- Reseed setup checks every planned rename source before adding the torrent and checks again before each rename. An occupied path, including a dangling symlink, is refused. An unreadable path is not treated as absent. This protects the original files rather than staging disk moves for filename swaps; incompatible layouts remain unsupported.
- `AlreadyInClient` is shared by Reseed and client adapters. Individual desktop reseeds display an informational notice, including available name, hash, state and location, with French translations. A torrent already seeding is distinguished from one needing attention. Concurrent additions receive the same handling. Existing torrents are not started, removed or retargeted.
- Generic season folders infer the show title from consistent video episode names. If episodes have no title, their parent show folder supplies it. Conflicting episode titles do not choose a show. The selected season is preserved, and a manual query override remains available.
- Both setup timeouts clear the Verification record after successful removal. A failed removal retains the record for later cleanup.

Regressions now live in `tests/test_reseed.py`, `tests/test_review_reseed.py`, `tests/test_queries.py`, `tests/test_i18n.py` and `tests/test_qbit_integration.py`. The qBittorrent 5.2.4 integration suite passed with seven tests and one optional authenticated-sandbox test skipped. The whole-series size gate below remains a documented workflow limitation.

Final validation passed with 1,800 tests and 144 skips in the full suite, clean Ruff checks and formatting, and successful typechecking of 201 source files. An initial full run caught a changed µTorrent preflight order; restoring compatibility checks before client reads fixed it, and the full rerun passed. Independent Standards and Spec reviews reported no findings, including a follow-up review of that correction.

## Expanded validation before beta.25

The subsequent full test run at `ff101a4` enabled every opt-in environment and
executed all 1,944 distinct tests: 1,925 passed, 19 failed, none skipped. Of the
144 previously skipped tests, 125 passed and 19 failed. No application or test
source was changed during this run.

Live integrations passed against qBittorrent 5.2.4, Deluge 2.2.0, Transmission
4.1.3 and µTorrent Classic 3.6 build 47390 in a disposable Wine prefix. This
included the authenticated qBittorrent sandbox, Docker path mappings, all 17
multi-client Docker scenarios, and all 15 application-container tests. The real
tracker search and metadata-matching test also passed, with reseeding disabled.
Client data was synthetic and temporary; production clients were not used.

The 41 assistant acceptance tests used the existing local
`Qwen3.8-27B-MXFP4-off` endpoint: 25 passed and 16 failed. Three browser checks
also failed and reproduced in isolation. Two upload-draft card fixtures omit
the `upload-draft-search` element expected by the current renderer. Guided setup
expects `zen-seeding-panel` to be visible, but it remains hidden.

The combined run deadlocked in native media playback. GDB showed the main thread
waiting in widget styling/`QObject::disconnect` while an audio thread waited for
the Python GIL. The blocked process was stopped, completed results were preserved,
and every unfinished test was run. All 13 native media tests passed in a separate
process. The cause of the combined-run hang is not yet established.

The local evidence is in `/tmp/tl-all-tests/results.txt`, `audit.json`, the pytest
logs and JUnit reports, `model-records/`, and `media-hang-stack.txt`. The inventory
audit found zero missing or unexpected tests. Temporary clients and the test
image were removed after validation.

## Findings

### P1 Reject overlapping disk paths before staging torrent renames

Location: `src/torrentlinker/reseed.py:114` and `:252`.

When the matched local filenames swap two original torrent paths, `rename_plan` stages both through `.torrentlinker-tmp`. Those are real rename requests, and qBittorrent can move files already occupying the original paths. The exception handler removes the torrent and clears Verification, but does not restore those paths or wait for pending disk operations.

Reproduced three times against an isolated qBittorrent 5.2.4 container, with fresh synthetic files each time:

```text
Torrent: Show/a.mkv = 40,000 bytes of a; Show/b.mkv = 50,000 bytes of b
Local:   Show/a.mkv = 50,000 bytes of b; Show/b.mkv = 40,000 bytes of a
Match:   Show/a.mkv -> Show/b.mkv; Show/b.mkv -> Show/a.mkv
Result:  ReseedAborted: The file already exists: 'Show/b.mkv'.
After removal and a two-second wait:
         a.mkv.torrentlinker-tmp and b.mkv.torrentlinker-tmp exist
         a.mkv and b.mkv no longer exist
```

Checksums confirmed that the contents survived under the temporary names. Their original paths did not. An immediate check can miss the damage because the queued operations complete after the error. This contradicts ADR-0002 and ADR-0004. The existing swap test only mutates an in-memory dictionary, so it cannot detect disk moves.

A diagnostic variant that waited after every rename completed the swap but moved the contents between the original filenames and failed Verification. Waiting between requests alone is therefore insufficient. The first correction should refuse hazardous occupied source paths before adding or renaming anything. A solution that permits these layouts must demonstrate that original paths and bytes remain unchanged, including after asynchronous failure. Do not silently extend the explicit µTorrent disk-rename exception to qBittorrent.

### P2 Explain existing torrents in the individual Reseed action

Location: `src/torrentlinker/reseed.py:100` and `src/torrentlinker/gui/review_panel.py:682`.

`_start_reseed` raises `AlreadyInClient(meta.name)` as soon as the client reports the candidate's infohash. This exception has no explanatory message. The review panel catches it as a generic error and displays `candidate.title: meta.name` under “Reseed failed.” That reproduces the screenshot's two release names with no reason for failure. The same exception and formatting are present in tag `v0.12.0`.

This happens before adding the torrent, renaming paths or running Verification. It is unrelated to the movie's filename length or a failed hash check in this reproduction. It is strong evidence for the reported cause, although the affected user's actual client state was not available for confirmation.

An existing torrent can still accompany an Orphan: it may point to a different location, or belong to another tracker and therefore be excluded from Library reconciliation. The guard checks every torrent in the client. It does not distinguish seeding, stopped, incomplete or missing-data states, and it does not resume or retarget an existing torrent. The batch Reseed actions already catch both duplicate exception classes and report an already-present result; the individual action does not.

Use a shared, descriptive duplicate result and show the existing torrent's name, hash, state and location. Distinguish an already-seeding torrent from one requiring attention. Retargeting or starting an existing torrent needs a separate deliberate action; the diagnostic fix should not delete or replace it automatically.

### P2 Preserve the show identity when scanning generic season folders

Location: `src/torrentlinker/queries.py:61` and `:90`.

For `Black Mirror/Season 1/Black.Mirror.S01E01.mkv`, selecting the season as the Local Item builds `tvsearch?q=Season 1&season=1`. `parse_name` only reads the Local Item's basename. It ignores the show name in the parent and episode filenames, as does the ordinary name-query fallback. Without an embedded IMDb/TMDb identifier or a manual query override, discovery searches for the wrong title. Compatible discovery reuses this base query, so expanding episode scopes does not repair its title.

The supplied Black Mirror season folders contain the show title and parse correctly. This defect is reproduced with a synthetic generic season folder, not claimed as an observed error in those named folders. Derive series identity from consistent episode metadata and appropriate parent context when the selected basename carries only season information. Preserve the selected season and episode scope, and refuse ambiguous mixed-show inference.

### P2 Clear Verification records when setup times out

Location: `src/torrentlinker/reseed.py:248`, called at `:112` and `:123`.

Both setup waits occur after `store.start_verification`. On timeout, `_wait_for` removes the torrent and raises without calling `store.end_verification`. Later `check_verifications` iterates only torrents still carrying the verifying tag, so it never finds the deleted torrent's record. The desktop timer also consults `verification_hashes`, which keeps that client in the polling cycle.

A deterministic fake client that remains in `checkingResumeData` reproduces this without waiting 30 seconds: setup aborts, the torrent is gone, another verification poll does nothing, and the stored hash remains pending. Both timeout sites need consistent cleanup. Preserve recovery state if client removal itself fails, rather than discarding uncertain ownership.

## What series depth actually changes

Scanning `/windocs/Séries` returned no scan errors:

| Depth | Local Items | Effect on this library |
| --- | ---: | --- |
| 1 | 3 | Whole Black Mirror and X-Files collections; one Severance season |
| 2 | 30 | Black Mirror and X-Files seasons; individual Severance episodes and loose files |
| 3 | 270 | Individual files, including NFOs and loose files encountered earlier |

One depth cannot select season packs consistently in this mixed layout. Depth determines the Local Item boundary; it does not truncate the recursive file manifest below that boundary. `LocalItem.save_path` and its relative filenames remain consistent at each depth.

Automatic candidate checking has a documented size gate at `src/torrentlinker/review.py:84`. The Black Mirror Local Item totals 98,017,749,308 bytes, while its season 7 totals 9,683,514,678 bytes. Direct file comparison accepts the season manifest as a Full Match inside the series. Automatic checking rejects its total size as outside the default 2% tolerance, leaving the Candidate untested. This is an existing workflow limitation, not a newly introduced rename bug. Once a series is Partially Seeded, ordinary automatic searches also skip it by design.

Current ways through that limitation are **Check Candidate**, **Find compatible torrents**, or Library Folder boundaries/depths appropriate to each layout. Registering the show folders themselves at depth 1 selects their seasons, while keeping a separate season-pack parent for Severance avoids splitting it into episodes. Manual query overrides work around generic season names. Compatible discovery requires every target file, including sidecars, and is bounded to 30 requests and 100 Candidates; it is not an exhaustive search guarantee.

Live synthetic reseeds through a `/data` Path Mapping passed at depths 1, 2 and 3 against qBittorrent 5.2.4. All reached 100%, started and retained original paths and checksums. This rules out a blanket qBittorrent inability to reseed nested series paths for those tested layouts.

Transmission has a separate, documented limitation in ADR-0010: it renames path components in place and refuses depth-changing moves. A size Match does not establish that a particular Torrent Client supports its rename plan. The client used in the series report remains unknown.

## Coverage and evidence

The review followed Library scan and reconciliation, query building, candidate size filtering, file matching, remembered candidates, individual and batch desktop/web entry points, Path Mappings, archive extraction, client adapters, rename planning, Verification and interrupted-setup recovery. The relevant ADRs were checked, including the explicit disk-rename exception for µTorrent and BitTorrent Classic.

- 153 focused existing tests passed for scanning, queries, review, matching, reconciliation, Path Mappings, Reseeding and all four client-adapter families.
- 53 existing tests passed for desktop/web Library batches and review, Library evidence, archives and explicit disk renames.
- 6 existing qBittorrent integration tests passed against the isolated 5.2.4 container; one optional concurrent-login test was skipped because its separate authenticated sandbox was not configured.
- Four original diagnostic assertions failed: duplicate message, generic season identity, whole-series size gate and stale Verification after timeout. The size-gate assertion illustrates the documented limitation; the other three became permanent regressions.
- Three fresh live swap trials reproduced the file-path damage at the reviewed revision. After the correction, all three trials of the persisted probe passed: unsafe setup was refused, original paths and checksums stayed unchanged, and no Verification record remained.

The live adapter checks used synthetic files under `/tmp`. The supplied series library was read for paths and sizes only. No tracker searches, downloads of real media or production Torrent Client mutations were performed. Deluge, Transmission and µTorrent/BitTorrent were reviewed through their source, ADRs and existing unit tests, not new live sessions. The graph was used for navigation; findings were verified against source and executable probes.

## Reproducing the findings

Run the permanent regressions from the repository root. The original failing desktop, query and timeout probes have been replaced by these tests:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q \
  tests/test_reseed.py tests/test_review_reseed.py tests/test_queries.py tests/test_i18n.py
```

The [live swap probe](reseed-path-review/live_swap.py) requires a throwaway qBittorrent instance and a new test directory mounted at `/data` in that instance. It creates tiny synthetic files, removes its torrents with data kept, waits for queued renames and compares filenames and checksums. Never point it at a production client. For the review sandbox, the invocation was:

```bash
TL_RESEED_AUDIT_HOST=http://127.0.0.1:18973 \
TL_RESEED_AUDIT_DATA=/tmp/tl-reseed-audit/data \
  .venv/bin/python docs/research/reseed-path-review/live_swap.py
```

The sandbox is stopped after the review. Restart a disposable instance with the corresponding mount before rerunning the live probe. Generated failure fixtures remain under the test directory for inspection.

Improvements to automatic cross-scope series discovery remain a separate behavior change, with explicit request and candidate limits.
