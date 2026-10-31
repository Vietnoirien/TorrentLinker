# Polish and stabilization plan

Status: active stabilization plan, approved on 2026-10-30. Freeze feature scope and resolve the known validation failures before the final product walkthrough. Release publication remains a separate decision.

Baseline: published `1.0.0-beta.25`, application revision `ff101a4`, release revision `0bce037` and documentation revision `5afcbe4`. This plan applies the accepted [1.0.0 criteria](1.0.0-readiness-decision.md) and [stabilization priorities](beta-and-stabilization.md).

## Objective and scope

Make the existing application understandable, consistent and dependable from setup through completed work. Core workflows must work without an assistant. A model can help users perform them, but cannot replace application validation.

Keep new feature development separate from this phase. Stabilize the already shipped browser companion, session downloads, Zen Profile, Library evidence and experimental Repair Copy alongside the other workflows. No new endpoint investigation, rate-limit changes or bulk API experiments are included here.

The [beta.25 validation report](../research/reseed-path-review.md#expanded-validation-before-beta25) records 1,925 passing tests, 19 failures and a combined-run native-media hang. All four tested Torrent Client integrations passed. The [older beta report](../research/beta-0.13.0-validation.md) supplies limited upgrade evidence, not final candidate readiness. Routine green CI does not cover every opt-in browser and model scenario.

## Prioritized backlog

| Order | Tracking issue | Remaining evidence |
| --- | --- | --- |
| 1 | [#51: Windows Library rescan freeze](https://github.com/Vietnoirien/TorrentLinker/issues/51) | Forty Windows source checks and packaged ten-rescan/media/MCP smoke pass at `c2965bb`; the Linux bundle/AppImage also pass. Fixed the stall monitor's failure to write stacks before recovery. Reported freeze remains unreproduced; affected-machine stacks remain. See [investigation](../research/windows-library-rescan.md). |
| 1 | [#44: native-media deadlock](https://github.com/Vietnoirien/TorrentLinker/issues/44) | Workaround and regression pass. Frozen Linux playback/shutdown and three isolated AppImage runs pass. Official release-platform/Qt matrix remains. |
| 1 | [#45: browser acceptance](https://github.com/Vietnoirien/TorrentLinker/issues/45) | Original browser failures fixed; browser and full CI pass through packaged-rescan commit `c2965bb`. Final release-candidate validation remains. |
| 1 | [#46: local-model failures](https://github.com/Vietnoirien/TorrentLinker/issues/46) | All 16 historical scenarios passed twice with saved temperature 0 on Radiance; exact-removal approval enforced. Later false send/retry claims reproduced after restart; execution-history grounding and visible no-action labels now pass the controlled replay twice with server defaults. See [execution evidence](../research/assistant-execution-evidence.md). Final candidate validation and documented model limitations remain. |
| 2 | [#47: interruption and recovery](https://github.com/Vietnoirien/TorrentLinker/issues/47) | Shutdown fix, interrupted Upload POST and desktop/browser Upload reset and uncertain-download checks pass; unresolved Upload wording now avoids claiming an active send after restart. See the [evidence matrix](../research/recovery-audit.md). Actual remote reconciliation, real extension lifecycle and platform checks remain. |
| 3 | [#48: desktop/web walkthrough](https://github.com/Vietnoirien/TorrentLinker/issues/48) | Paired screenshots, reproducible usability findings and verified fixes. |
| 4 | [#49: support and performance](https://github.com/Vietnoirien/TorrentLinker/issues/49) | Native Torrents baselines at 1k/12k/50k recorded; redundant sorting/filtering and unbounded tag-sidebar height fixed. Desktop/web support-report export now includes only allowlisted metadata. Queue baselines and idle/status/selection fixes are also recorded. Chat updates now retain unchanged runs, with a 100-run baseline recorded. Native retry-wait cancellation passes. Large first-display/filter-expansion stalls, full queue rebuilds, history loading and broader cancellation evidence remain. See [measurements](../research/torrents-performance.md). |
| 5 | [#50: upgrades and release readiness](https://github.com/Vietnoirien/TorrentLinker/issues/50) | Source upgrades from 0.12.2 and beta.27, second restart and offline restore passed. Bilingual backup/restore procedures added. Exact candidate packaged upgrades, platform/support matrix and real-user observation remain. |

The issues distinguish known failures from missing evidence. Their acceptance checks are the completion criteria. Features already delivered include the Search, Torrents, Upload and Library desktop/web redesigns, web Zen planning parity and the companion setup guide. Audit those workflows in their current form; do not restart their redesigns.

### Windows user report, 2026-10-30

> Toute dernière version. Page principale pour vérifier les fichiers (Bibliothèque)
> La première analyse passe, mais si je fais d'autres analyses là c'est bon il freeze

Recorded as [#51](https://github.com/Vietnoirien/TorrentLinker/issues/51), a P1 blocker before the final 1.0 walkthrough/readiness decision. The report identifies Windows desktop and Library rescans in the same session. "Latest version" is the user's description; the exact release, Windows version, Torrent Client, library size and storage type are still needed. The report does not establish whether every second scan freezes or whether it takes several scans.

Investigate scan worker completion, Qt callback lifetimes, database access and cleanup between scans, guided by captured stacks. Do not attribute this to the media deadlock in #44 without evidence. Completion requires a reproduced trigger or a documented evidence gap, a bounded regression, and at least ten consecutive scans on a packaged Windows build with a responsive UI, preserved files/results and clean shutdown. Linux-only results do not close this report. It is not claimed fixed by beta.27.

### Reports during beta.27 publication

- Assistant truthfulness, #46: the running source installation still advertised beta.17 because its editable-package metadata was stale. Its saved "oui" and "retry" turns each contain only a user message and an assistant answer, with no tool calls or tool events, despite claiming a download retry and disk-space rejection. One quoted error was not present in application code or the recorded tool events. The destination had about 16.6 GB free at inspection. An earlier real free-space-reserve rejection exists, but does not substantiate these later retry claims. The process was restarted on beta.27 and source metadata refreshed. Current-build reproduction and a grounded-action regression remain; no download was retried and no space limit was changed during diagnosis.
- Linux/GNOME theme detection, #48: the published AppImage's bundled GLib/GIO libraries made the host `gsettings` command return `default` instead of the actual `prefer-dark`, with module symbol errors. Restoring the host library search path for both the initial probe and its change monitor fixes the reproduced cause. The application's own environment and the owner's System setting remain unchanged. Seven theme tests pass, including absent, empty and non-empty original library paths; the corrected probe reads `prefer-dark` in the actual failing AppImage environment. This is a post-beta.27 fix, not part of the published artifact.

The local theme-fix AppImage passed the isolated playback/MCP/shutdown smoke check with a private profile, null keyring and no external network. Ruff, formatting and mypy passed. The user-facing app was restarted from this local build with the normal profile; the official beta.27 download remains unchanged and its release notes disclose the GNOME issue.

The assistant send report was subsequently reproduced on the restarted app and in an isolated Radiance replay. The model invented outcomes without invoking tools; the session-download code was not reached. The [execution-evidence follow-up](../research/assistant-execution-evidence.md) records the fix and its limits. New controlled runs request approval for the exact queued film under the unchanged media-only grant.

The subsequent real send receipt hit the configured 10 GiB reserve. At the owner's request, extra reserve is now opt-in for new discussions and agent connections, and direct sends no longer inherit the Plan percentage. Existing reserves remain owner-controlled. Checks for selected and pending downloads still apply, with separate errors for insufficient space and optional reserve. See the same follow-up for the regression evidence.

The next download succeeded, then exposed a repeating native queue-display `KeyError`. Successful sends remove their entries while the table can still display its previous snapshot. Seeding refreshes incorrectly looked up those displayed keys in a newer database read. Queue estimates now use the same snapshot as the displayed rows; the normal poll reconciles removals. Two deterministic regressions reproduce removal before a seeding refresh and during a table rebuild. Both failed at the reported lookup before the fix; all 67 related native search and download-queue tests now pass, preserving sorting and selection.

A Windows beta.23 report identified a separate Transmission-in-Docker send failure: resolving a mapped drive to its UNC path caused the queued destination to miss its configured mapping. The real RPC adapter reproduced the exact "download directory path is not absolute" rejection with controlled data. Mapping now recognizes resolved local roots; 86 related tests pass, and the RPC regression was added to Windows CI. Beta.27 has the same original gap. The [investigation and published-build workaround](../research/windows-transmission-paths.md) preserve the uncertain-send recovery requirement; the reporter's environment has not yet verified the fix.

## First stabilization pass, 2026-10-30

- Browser acceptance reproduced all three beta.25 failures. The two Upload cases used an obsolete partial page; they now reload the production workspace and open the saved-draft preview from Description. Guided setup explicitly checks Profile, then selects Seeding and Plan. Both files pass together: 12 tests. Screenshot capture also exposed a CSP-incompatible expression in a test wait; function-form predicates preserve the existing image-loaded assertion without relaxing CSP.
- CI now includes those browser acceptance files with Chromium and `TL_WEB_BROWSER=1`. The new job has been verified locally; its remote result is pending a future push.
- The native playback test passed alone, and a sequence of earlier GUI tests plus the native-player file passed 101 tests with four optional skips. The combined suite with browser tests enabled completed 1,825 passing tests and 119 optional skips, with no failures. Its ten-minute process limit interrupted the last 51 tests; a 53-test continuation included two overlapping cases and passed. Inventory reconciliation accounted for all 1,944 distinct tests. The native-media section completed without hanging. These results do not explain or close the original deadlock. Lint, formatting and typechecking of 201 source files also passed.
- Screenshot review covered saved-draft preview, narrow Torrents and French/light Upload review. The initial Upload review exposed `paid-creators:` instead of a human explanation. The continuation below fixes the browser wording; #48 tracks the remaining walkthrough. The complete paired desktop/web audit remains open.
- The user confirmed Radiance uses the same endpoint as the earlier tests. It now advertises `Qwen3.8-27B-MXFP4-off` through vLLM; that API identifier is recorded separately from the user-provided model name. The first rerun of the 16 historical failing scenarios completed with seven passes and nine failures against this confirmed target. Description review, film cards, multi-client pause, ebook Local Draft creation, capability probing, audio presentation and documentation guidance passed. Remaining failures covered repeated card prose for ebooks/music, the RSS book category, missing pause approval, a Plan awaiting input, series/ebook formatting, the raw-byte prose assertion and overbroad queue removal. Narrower queue-edit guidance and explicit RSS category schema descriptions passed both focused Radiance scenarios with the original exact-state assertions unchanged: only Film 01 and Film 02 were removed, and RSS category/preferences survived editing and reopening. The changed code also passed 124 focused application tests, lint, formatting and typechecking. A second run passed eight and failed eight: RSS, ebook cards and queue-only editing passed, while description review and multi-client scope regressed. This run started before the strict argument validation described below; individual model passes do not establish deterministic reliability. An earlier transient endpoint advertised a different Qwen ID and rejected three Upload-bearing tool schemas at grammar initialization; that observation is not attributed to Radiance.
- The second Radiance run exposed an application defect behind the multi-client failure: the MCP SDK silently discarded unknown top-level arguments. A misspelled `selection` parameter was ignored in favor of the default `criteria`, selecting five torrents instead of the requested four and eventually pausing an extra ebook. The MCP server now rejects unknown arguments before dispatch and advertises `additionalProperties: false`. Both external MCP and built-in assistant paths have regression coverage, including a valid argument accompanied by an unknown one and successful correction after rejection. These tests failed before the fix and pass afterward. The broader agent, assistant and RSS regression set passed 207 tests; the final schema/error checks passed four tests. Lint, formatting and typechecking passed. The affected Radiance multi-client scenario also passed against this fix with its original exact-instance assertions: only the requested two local instances and one NAS instance were paused; the extra ebook and third client were untouched. This validation does not establish that a model always chooses the correct values for valid arguments.

### Continuation after the first commit, 2026-10-30

- Committed the first batch as `a8b1834`.
- Browser Upload preview and saved-review messages now explain all 60 known category warnings/refusals using the existing desktop English and French wording. Language changes update already rendered messages; details remain plain text, and unknown messages remain visible. Stored draft review codes and send validation are unchanged. The browser regression first reproduced `paid-creators:` instead of an explanation. All 12 browser tests then passed, including language changes after reopening and saving. French/light review screenshots were inspected.
- Fixed the live approval test's synchronization. Approving the proposal resumes the existing assistant run asynchronously; a paused simulated client does not mean that run has finished. The test now waits for a terminal run before sending the follow-up. The Radiance scenario passes and still checks exactly one pause.
- Corrected the oversized-queue acceptance test's prose requirement. It now accepts a correctly rounded total with an explicit GB/Go or GiB/Gio unit, while strengthening saved-state checks to require the exact 500 intended hashes and 536,871,037,250 bytes. No-download, zero-reservation and no-folder-change checks remain. The preserved Radiance response and incorrect-size counterexamples were checked, and a fresh Radiance run passed.
- Approval recovery and queue regressions passed 36 tests. Browser and live-model results above are focused follow-ups, not a new full-suite or 16-scenario pass. The original media deadlock and remaining model workflow/presentation failures remain open.

### Further stabilization, 2026-10-30

- Desktop review of web/MCP-created Local Drafts now uses the same localized category rule formatters as desktop preparation. Desktop saves retain stable diagnostic codes, so browser review can translate them after a desktop edit. Older prose and unknown findings remain visible. Identical saved/current findings appear once. Cross-interface tests first reproduced raw codes, duplicate findings and translated prose replacing codes; the fixes pass in English and French without changing or approving the draft. The Upload and translation suite passed 91 tests, and review screenshots were inspected. Presentation-completeness messages such as `description.image` still need user-facing localization in #48.
- Clarified Catalogue versus Library/Media in assistant guidance and tool descriptions. A requested Plan requires a completed planning job, and goal categories use Torznab IDs from `catalogue_categories`. The Search/Plan test now grants both queue and download permissions because it explicitly requests both operations. Download-only permission tests continue to require approval for queue edits; application permission rules are unchanged. The focused description-review and Search/Plan scenarios both passed against Radiance.
- A full rerun of the 16 historical Radiance failures passed 11 and failed five. Remaining failures: description review omitted the requested saved list; the approval scenario stopped without proposing the pause; ebook and audio writing ignored the no-tool instruction; queue-only editing removed all ten entries instead of the named two. The queue-scope failure remains a release blocker. Strict argument validation prevents unknown fields from silently applying defaults, but cannot establish that a valid selection matches the user's intent. Do not treat an isolated passing model run or added guidance as a reliable scope guarantee.
- Repeated the native seek/browse/playback test 20 times in one Qt process using distinct test parameters: all 20 passed in 19.42 seconds. Combined-suite evidence and this stress run still do not reproduce or explain the original native deadlock. No speculative player change was made; #44 stays open.
- Ruff, formatting and typechecking of 202 source files pass. The 70 agent/access/assistant tests in the broader regression run also passed. These focused results do not replace final full-suite, installed-package or platform validation.

### Upload completeness wording, 2026-10-30

- Continued #48 with missing title, NFO, hosted image, synopsis and required-field messages in desktop and browser Upload review. Recognized diagnostics now have English/French display wording without technical field prefixes. Required BBCode labels remain exact so the suggested correction still satisfies validation. The original-NFO preservation instructions remain explicit.
- Stored diagnostics, draft revisions, validation and send permissions are unchanged. Desktop deduplicates the translated saved/current findings; browser language changes update rendered findings. Unknown messages and other conflict diagnostics remain visible verbatim. This covers missing-field wording, not every presentation diagnostic: conflicting facts, track durations, artwork coverage and language restrictions still need localization.
- The paired regression first failed in both interfaces. After the fix, 97 Upload, translation and browser tests passed, including reopening/editing a saved draft, explicit send, unchanged review state, NFO guidance and unknown-message preservation. English/French review screenshots were inspected. Ruff, formatting and typechecking passed. Screenshots also retain two separate #48 follow-ups: the browser's French status badge says "Up to date", and the English desktop draft category says "Imprimante 3D".
- This is a source fix after beta.27. No package was published or user draft submitted during this check. The complete paired workflow audit remains open.

### Upload diagnostic and browser status follow-up, 2026-10-31

- Completed the remaining known presentation diagnostic wording from the previous #48 pass: NFO and extracted-fact conflicts, missing track/chapter durations, artwork coverage, actual file counts, ebook language restrictions and invalid category choices. Desktop and browser show matching English/French explanations. Conflicts retain both values and the exact editable field label; duration messages identify the NFO or description and the affected row. Filenames and language metadata remain literal text, and original-NFO preservation instructions remain explicit. Unknown diagnostics still pass through unchanged. Validation, stored review data and send approvals are unchanged.
- Fixed the browser work-status badge retaining its old language until the next poll. Idle, active-job and incomplete-scan messages now participate in immediate language switching. The regression first reproduced "Up to date" after switching to French, then verified both directions for active and incomplete-scan states without another poll.
- Corrected the earlier classification of "Imprimante 3D" as an English UI translation defect. `category_name` intentionally uses c411's official category names, consistent with the domain documentation and English Upload guide. That label remains unchanged.
- Validation: 97 tests passed in the broader Upload/translation/browser run. Its final browser case stalled because the new test route callback treated Playwright's request argument as a default status value. After correcting that fixture signature, the final case passed separately, completing all 98 selected tests. It checks desktop/browser diagnostic parity in both languages, literal markup in filenames, unchanged draft data and the existing explicit-send flow. Ruff, formatting of 399 files and typechecking of 203 source files pass. Desktop diagnostic and browser review screenshots were inspected in English/French. No real submission, package publication or Windows freeze fix is claimed.

### Download-queue responsiveness, 2026-10-31

- Recorded 1k/12k/50k queue baselines. Idle polling no longer decodes every saved entry each second; a database change token detects both own and external writes. Selection uses the displayed snapshot for button state. Status-only polls update affected cells without replacing estimates, with one database read per changed poll.
- At 12k entries, a status poll fell from 2,176 to 361 ms and selection from 384 to 22 ms. At 50k, idle polling fell from 1,356 to 21 ms, mostly the benchmark's 20 ms event-loop drain. First display, full rebuilds and estimate updates remain slow. Native progress now shares incremental status refreshes; successful sends still rebuild the table when entries leave the queue. See [method, results and limits](../research/queue-performance.md).
- A native-progress follow-up reduced 12k-entry status notifications from 1,580 to 274 ms and unchanged retry notifications from 1,537 to 21 ms. A real background-worker test interrupts a two-minute retry wait with Pause, then resumes and sends exactly once. Worker failure retains uncertain entries without automatic retry.
- Eighty-three focused regressions passed, including external writers, client/connection changes, concurrent snapshot writes, exact selection, retry safety and scoped removals. Lint, formatting and typechecking passed. The preceding shutdown fix passed the full local suite, 1,874 passed / 148 skipped, and all CI jobs on `9cdd729`; the queue patch has its own CI gate.

### Packaged Library rescans and integrated checks, 2026-10-31

- Extended packaged smoke testing to ten native Library scans with temporary data, GUI-heartbeat checks, modified-file assertions and a simulated Torrent Client. The Linux executable and AppImage pass, including copied 0.12.2 and beta.27 upgrade fixtures. Windows CI also passed the same probe inside its frozen executable at `c2965bb`, with stall diagnostics enabled. The affected Windows user's freeze is still unreproduced. See [probe evidence](../research/windows-library-rescan.md#packaged-rescan-probe-2026-10-31).
- The integrated local suite at `e054892` passed 1,885 tests with 148 optional skips. The subsequent smoke hook and failure cleanup passed 31 focused checks; lint, formatting and typechecking of 206 source files pass. All CI jobs passed through `c2965bb`: the main suite passed 1,881 tests with 154 environment-dependent skips, alongside browser acceptance, client integrations and frozen Windows checks.
- Two focused Radiance replays passed with server-default sampling: the false-download-claim scenario reached exact send approval, and queue removal required approval of the two named entries while preserving the other eight. These do not replace the full model-acceptance matrix. See [replay evidence](../research/assistant-execution-evidence.md#workstation-acceptance-replay-2026-10-31).

### Native chat-history refresh, 2026-10-31

- Reproduced full transcript reconstruction when only one response changed. Unchanged runs and expanded receipts now stay in place. Changed approvals replace old controls; language, appearance, discussion headings and chronological insertion/removal remain covered.
- At the current 100-run history limit, one changed response fell from 825 to 28 ms. First rendering remained about 800 ms. Sixty-four focused checks pass, with 11 optional browser skips; lint, formatting and typechecking pass. See [method, results and limits](../research/chat-performance.md). History database reads, remote images, browser chat and installed Windows performance remain outside this measurement.

### Assistant shutdown race and CI follow-up, 2026-10-31

- CI on `908c589` crashed while a Qt-pool provider assessment wrote to SQLite and the web application's shutdown closed that same connection. A controlled two-thread local reproduction produced the same segmentation fault at the assessment insert. The durable regression uses a gated connection to detect premature close without deliberately crashing SQLite.
- Assistant shutdown now closes its database under the same lock used by readers and writers. Capability probes reject work started or completed after shutdown, before accessing a closed database. Late provider UI notifications/errors are ignored after service shutdown or widget destruction. The UI test waits for its own background assessments before changing sampling again or leaving the service context.
- CI on `b021a7c` separately completed with three failures because older Settings-dialog test doubles lacked the newly added diagnostic-export signal. Those doubles now implement that signal; startup and Library-folder rescan assertions are unchanged.
- Validation: the initial assistant/shutdown group passed 51 tests with two optional browser skips. The final shutdown/UI/startup/Upload/diagnostic group passed 63 tests with two optional browser skips. Lint, formatting and typechecking passed. Full-suite CI is the next gate; the earlier package artifact predates this shutdown fix.

### Linux package follow-up, 2026-10-31

- A fresh frozen server exposed missing PySide version metadata in the support report. The package spec now includes it; the existing smoke test checks report versions so future bundles fail if metadata is lost.
- The corrected executable and three AppImage runs passed media playback, MCP, report-version and shutdown checks. The AppImage also opened isolated fixtures created by actual 0.12.2 and beta.27 sources; settings, client-scoped drafts, queues, conversation state and fixture-file hashes survived. Authentication and bilingual packaged guides passed in the frozen server.
- Recorded [artifact, timings and limits](../research/linux-package-2026-10-31.md). Thirteen focused packaging/diagnostic/shutdown tests, lint, formatting and typechecking passed. This is local offscreen Linux evidence; complete installed workflows and other platforms remain open. No release or restart of the user's app occurred.

### Workstation upgrade and restore evidence, 2026-10-31

- Actual 0.12.2 and beta.27 source processes produced isolated settings, both clients’ Local Drafts, desktop/web queues, conversation history, fixture credentials and Upload attachments. Current code preserved their settings and payloads through upgrade, second restart and offline backup restoration. Interrupted downloads became uncertain and running jobs became interrupted without replay.
- Added a repeatable `scripts/check_upgrade.py` check with blocked network/keyring access and unchanged-original/backup hash assertions. Recorded [results and limits](../research/upgrade-restore-2026-10-31.md). The English/French guides now explain stopped-app whole-folder backup/restore, credential storage and remote-state review after restore. Ten documentation tests passed.
- This advances #50 locally. Packaged upgrades, OS keyring transfer, enabled schedule recovery, the final support matrix and real-user observation remain separate release gates.

### Support-report export, 2026-10-31

- Added a JSON support report under desktop Settings → General and browser Settings → Interface, in French and English. The authenticated browser download works under a reverse-proxy mount prefix. The user chooses the desktop destination and whether to share either export.
- Reports contain app/system versions, client types and aliases, mapping path formats, configuration and cache counts, queue-state counts and up to 20 recent job kinds/outcomes. Credentials, hosts, folders, torrent names, raw logs and conversations are never copied into the report. Unknown state/kind values become `other`; private client IDs become report-local aliases.
- Export reads existing stores and jobs without opening replacement databases, connecting to clients, looking up credentials or replaying work. Desktop export also works without an agent service, with job history explicitly unavailable. Available disk space and working Path Mappings still require separate checks.
- Validation: 94 diagnostic/privacy, file-picker, translation, settings, job and GUI checks passed, plus the real-browser setup/management workflow including an English/French support-report download. Lint, formatting and typechecking passed. This closes the report-export part of #49, not its remaining performance work or the final packaged platform checks.

### Workstation performance and CI lifecycle follow-up, 2026-10-31

- Added an isolated Linux native-Torrents benchmark and recorded first-display, refresh, filtering, heartbeat-gap and peak-memory measurements at 1,000, 12,000 and 50,000 torrents. Removed redundant whole-table sorts and filter reevaluation for unrelated rate/ratio changes. State and tag counts now use one pass. At 12,000 rows, first display improved from 1.92 to 0.76 seconds and median changing refresh from 472 to 152 ms. At 50,000, first display improved from 8.27 to 3.22 seconds and changing refresh from 1.88 to 0.56 seconds; initial display and filter expansion still stall and remain follow-ups. Exact fixture, raw samples, limitations and local targets are in the [performance report](../research/torrents-performance.md).
- A 100-tag fixture also reproduced a 2,043-pixel minimum window height. Status/tag lists now show at most eight rows and scroll, keeping the tracker tree reachable. All 37 native Torrents tests pass, including changed filter memberships, numeric sort updates, exact selection preservation, legacy header preferences and last-tag access. The broader native/client/seeding/shutdown/browser batch passed 129 tests before this final sidebar change. Synthetic screenshots were inspected; no real client was contacted.
- CI for `f1cbef1` completed with 1,846 passing tests, 154 skips and one asynchronous Qt callback failure. A profile refresh finished after its MainWindow had been destroyed, then accessed a deleted button. A controlled delayed worker reproduced the identical failure for both successful and failed profile requests. Profile callbacks now check the window lifetime before updating widgets. The background request and profile caching remain unchanged. Final full-suite CI is still required on the follow-up commit.

### Owner approval for queue removals, 2026-10-30

- The user chose mandatory owner approval for assistant-initiated queue removals. The shared Agent Service now enforces this for external MCP and the built-in assistant, including execute mode with queue permission. The generic action tool and direct unapproved execution cannot bypass the rule. Priority changes and safe retries retain their existing permissions.
- Desktop and browser review show the exact entry count, client, names, identifiers and folders before approval. Agent settings use the same review. English and French guidance and execute-mode explanations include the new rule. Browser approval coverage is included in CI; remote CI remains pending a push.
- Three queue-approval tests failed before the guard and passed afterward. Regression coverage checks correct approved removal, rejection of an overbroad selection, generic-tool resubmission and a built-in assistant proposing the wrong entries. Rejection preserves the original queue. Native and browser review tests passed, and the English/French browser screenshots were inspected.
- Radiance passed the focused queue preview, batch and removal scenario in 45.18 seconds. The acceptance test checks that the queue remains unchanged while approval is pending and approves only the requested entries. It rejects an incorrect proposal before reporting failure. Final assertions still require exactly Film 03 through Film 10 to remain, with no downloads or reservations. This closes the automatic-removal path; it does not establish that Radiance always proposes the correct selection.
- The broader regression run exposed two scripted card-receipt tests whose small default context window triggered compaction after tool descriptions grew. The scripted provider expected a raw tool message and raised `StopIteration`. Those tests now declare enough context for their receipt-only scenario; production limits and separate compaction/recovery tests are unchanged.
- After that correction, the broader agent/assistant/translation run passed 241 tests with 41 optional skips and one browser navigation timeout. The browser clicked Discussion settings while New discussion was still rebuilding the page. It now waits for the old composer to disappear and the new one to become visible. The complete affected browser/native assistant UI, request-details, card-receipt and context-recovery follow-up passed all 42 tests. Ruff, formatting, JavaScript syntax checks and typechecking of 202 source files passed.
- The other historical Radiance workflow/presentation failures and the unexplained native-media deadlock remain open. These focused results do not establish final 1.0.0 readiness.

### Assistant workflow guidance and repeatability, 2026-10-30

- Removed a conflicting unconditional instruction to call `overview` first. Writing from supplied material now explicitly skips application tools when the user requests no tools; saved Upload Draft preparation is separate from standalone writing. MCP guidance uses the same condition. Clarified that action approval needs a real tool-created proposal, and that saving reviewed recommendations requires a torrent list even when the user has not supplied a list name. These are guidance corrections, not deterministic enforcement of natural-language intent.
- The four remaining historical scenarios all passed once before these edits. Two unchanged acceptance runs afterward passed five of eight cases. Description review saved the correct list in both runs. One approval scenario paused the exact requested torrent once, then unnecessarily called `ask_user` to request confirmation again, despite receiving a completed-job receipt. One audio writing run asked to classify the discussion despite the no-tool instruction; the other passed. One ebook response failed the single-BBCode-block contract. The baseline and repeat results demonstrate variability, not a measured reliability improvement. #46 remains open.
- The live approval helper previously waited until its deadline when the resumed model asked another question. It now waits past the original pending event but returns a new question/proposal immediately, so the existing completion assertion reports the actual failure. A controlled replay checked completion, a new question and a new proposal without accepting any of them as equivalent outcomes.
- Application regressions passed 106 tests, including permission enforcement, approval/rejection recovery, queue scope, card receipts and context recovery. The scripted queue-rejection provider now declares enough context for its raw-receipt scenario; tracing confirmed that its default window had compacted the receipt and raised `StopIteration`. Production context limits are unchanged. Ruff, formatting and typechecking of 202 source files pass.

### Saved sampling and narrow Upload edits, 2026-10-30

- Investigated the Radiance failures beyond prompt changes. The app previously omitted sampling parameters and offered no saved override. An experiment sending `temperature=0` passed the four remaining scenarios twice, then all 16 historical scenarios once. A saved optional temperature override now supports Ollama, LM Studio and compatible endpoints in both desktop and web. Existing connections retain server defaults. Zero survives storage and restart; restoring server defaults omits the parameter. Changing sampling while a discussion is active is refused, and a change invalidates capability assessments, including assessments still in progress.
- Two full runs through the saved-provider path each passed 15 of 16. One omitted the requested Plan after showing cards. The other changed the image form field during a description-only edit after repeatedly misplacing synopsis arguments. These results did not clear #46 and were retained as failures. The tested server remains the user's Radiance endpoint, advertising the API identifier `Qwen3.8-27B-MXFP4-off`; this identifier is not a claim about its underlying weights.
- Fixed the narrow Upload edit interface: `synopsis` can now be supplied without an empty `fields` mapping. Putting prose keys into `fields` returns the exact correction without changing the draft. A failing MCP regression reproduced the missing required argument, then passed with exact preservation of every other form field, the original NFO, file contents, draft ID and revision ordering. The card display receipt now distinguishes showing cards from completing other requested operations, including a Plan.
- Sampling configuration tests cover restart, protocol dispatch, return to server defaults, invalid values, active-discussion protection and stale capability results. Desktop and browser editor tests cover saving/reopening zero and unsupported providers. Screenshot review caught clipped native help text; the enlarged dialog was checked again. Browser field labels now explicitly name their controls, including selects. These browser flows are included in CI. Remote CI still requires a push.
- The expanded regression run exposed a context-recovery fixture that triggered proactive compaction before its deliberate provider rejection. It now declares enough context to isolate that rejection while retaining the assertion that recovery compacts exactly once. Production context handling is unchanged.
- After the Upload interface and card receipt changes, the Plan and synopsis-edit scenarios passed twice each. Two final runs of all 16 historical scenarios then passed through the saved-provider configuration with `temperature=0`, in 255.13 and 289.11 seconds. Existing acceptance assertions still check exact state, scope and preservation. This verifies the tested Radiance configuration; existing connections keep server defaults until explicitly changed, and these runs do not guarantee future model behavior. Local evidence is retained under `/tmp/tl-polish-issues/radiance-final-{1,2}` as logs, XML reports and conversation records. No real torrent clients or tracker mutations were used.
- Final affected regression coverage passed 305 tests with 41 skipped in 135.02 seconds, including enabled browser checks. Ruff, formatting of 393 files, typechecking of 202 source files, JavaScript syntax and diff checks passed. The separate native-media deadlock remains unresolved, and installed-platform and release checks remain outstanding.

### Native-media deadlock diagnosis and workaround, 2026-10-30

- Reproduced the GUI/audio lock inversion in an isolated Qt playback program, including with Python's normal scheduling interval. Full stacks show audio renderer destruction requesting the GIL through PySide's virtual-method lookup while widget construction waits for a Qt connection mutex. Qt's destructor holds a connection mutex during `disconnectNotify`. The old eight-frame capture showed the same waits but omitted the audio caller. See the [investigation and evidence](../research/native-media-deadlock.md).
- Disabled garbage collection as a control; the deadlock persisted. Replacing only the Python-created audio output with a Qt-created QML `AudioOutput` completed 100 cycles. The native player now uses that factory, with the output and its QML engine owned and destroyed together. The package smoke check constructs this output to detect missing QML plugins.
- The regression first froze on cycle 0 and failed at its 30-second subprocess deadline. With the workaround, 29 focused media tests passed. The final combined run passed 115 tests, including earlier GUI workflows, native audio/video playback, track selection, shutdown, themes, packaging smoke checks and another 80-cycle deadlock regression. Ruff, formatting, typechecking and diff checks passed. Installed-package/platform validation remains outstanding; no release or remote issue closure is implied.
- A separate dark-theme layout assertion surfaced during diagnosis: the Media pane's minimum width was 548 pixels against a 520-pixel expectation. That is a layout follow-up, not the deadlock; the diagnostic log is `/tmp/tl-media-freeze/styled-single.log`.

### Linux package and recovery follow-up, 2026-10-30

- The first frozen Linux smoke run aborted because a desktop worker emitted after Qt deleted its signal object. A controlled application-lifecycle subprocess reproduced that failure in 1.76 seconds. Shutdown now cancels queued desktop tasks, refuses follow-up work, and drains running tasks and their callbacks before Qt teardown. Five cases cover success, failure, progress, failed smoke checks and a late dialog.
- Expanded the packaged smoke test to decode eight generated muted WAV streams, stop playback and create widgets during cleanup. The frozen Linux executable and three consecutive AppImage runs passed playback, MCP smoke and traceback checks in a private loopback-only network namespace, with fresh data and a null keyring. The initial XDG-only diagnostic runs did not isolate the system keyring and are excluded from those isolated results. Windows/macOS smoke commands now have the same 120-second bound as Linux, but have not run remotely.
- Added actual process-exit coverage immediately after a simulated download acceptance: restart preserves uncertainty, client/folder scope, other queued work and source bytes, with no resend. Companion disconnect/restart tests reject stale responses, redispatch nothing automatically and complete only a fresh explicit descriptor request.
- The final affected recovery, GUI, shutdown and native-media suite passed 209 tests in 101.88 seconds. Lint, formatting, typechecking, workflow YAML and diff checks passed. The [recovery audit](../research/recovery-audit.md) records the artifact hash, evidence matrix and remaining work. Linux/offscreen package checks do not establish Windows/macOS, official release-runner, upgrade or graphical-desktop readiness. No artifacts or issue updates were published.

### Historical assistant failure triage

These are observations from the preserved beta.25 artifacts, not results for Radiance. No assertion or permission rule has been relaxed to make them pass.

| Failing scenario | Observed behavior | Disposition |
| --- | --- | --- |
| Description-based recommendation | Exhausted model calls without completing the requested review. | Workflow/model reliability. |
| Film cards | Repeated card items in the final prose. | Presentation quality. |
| Ebook cards | Presented movie items for the ebook request. | Wrong selection scope; high priority. |
| Music cards | Repeated items in prose in the recorded failing run. | Presentation quality; repeat with verified model. |
| RSS creation/editing | Saved the EPUB subscription under category 3010 instead of 7020. | Wrong category; high priority. |
| Multi-client pause | Completed the three-instance selection, then paused one instance again. | Duplicate action; high priority. |
| Ebook Local Draft | Created distinct Local Draft IDs while correcting the same preparation; initial correction involved `1,3 Ko` versus extracted `1.3 Ko`. | Saved-work reliability; separate fact normalization from model correction behavior. |
| Provider capability probe | Returned unexpected structured arguments. | Provider/model assessment; do not infer capability from endpoint availability. |
| Approval follow-up | Submitted a new message before the automatically resumed run finished. | Test synchronization candidate; verify resume completion before changing expectations. |
| Search and Plan | Exhausted model calls after repeated polling and planning. | Workflow/model reliability. |
| Series presentation | Asked for input instead of completing the fixture-based writing task. | Instruction following. |
| Ebook presentation | Omitted supplied facts and produced malformed/incomplete output. | Content correctness. |
| Audio presentation | Called classification despite the user's explicit no-tool instruction. | Instruction following; retain the no-tool assertion. |
| Oversized queue | Queued 500 films without downloads; final response used rounded GB/GiB while the test requires exact byte text. | Review the prose assertion separately from exact saved-state checks. |
| Queue-only editing | Removed all ten entries instead of only Film 01 and Film 02. | Wrong mutation scope; highest assistant priority. |
| Documentation guidance | Read documentation, then ended with only a chat-classification notice. | Missing answer and citations. |

### Existing recovery coverage to build on

The audit starts from these tests rather than assuming recovery is unimplemented. Their existence is not proof of installed-platform coverage.

| Requirement | Existing automated evidence | Remaining check |
| --- | --- | --- |
| Uncertain download handoff | `tests/test_download_queue.py::test_uncertain_handoff_stays_visible_and_is_not_retried` | Desktop/web recovery affordance and installed restart. |
| Uncertain Upload send | `tests/test_upload_queue.py::test_uncertain_send_is_kept_and_does_not_retry_automatically` | Owner reconciliation across interfaces. |
| Interrupted jobs | `tests/test_web_jobs.py::test_abrupt_restart_records_interruption_without_replaying_mutation` | Packaged shutdown and real interrupted work. |
| Reseed Verification recovery | `tests/test_reseed.py::test_verification_started_before_a_restart_is_settled_after_it` | Supported-client/platform combinations. |
| Approved disk-rename recovery | `tests/test_disk_rename.py::test_recovery_before_add_and_after_interrupted_verification_is_client_specific` | Installed µTorrent/BitTorrent recovery and conflict handling. |
| Assistant approval recovery | `tests/test_assistant_waits.py::test_approval_resumes_batch_once_after_restart` | Real-provider follow-up synchronization. |
| RSS queue-only behavior | `tests/test_feed_api.py::test_app_queue_scheduler_never_contacts_clients_and_restart_keeps_rule` | User-visible waiting, cancellation and resumption. |
| Destination scope | `tests/test_enqueue_destinations.py` and `tests/test_web_jobs.py::test_selected_download_uses_verified_client_path_and_survives_queue_reload` | Changing active client/folder with existing work. |
| Companion refusal/rate limit | `tests/test_companion_downloads.py` and `tests/test_indexer_session.py` | Browser disconnect/reconnect and process restart during dispatch. |
| Media and desktop cleanup | `tests/test_media_lifecycle.py`, `tests/test_media_audio.py`, `tests/test_desktop_shutdown.py` | Audio lock inversion and desktop task teardown now covered locally and in Linux package smoke; broader installed-platform checks remain. |

## Delivery order

| Stage | Work | Exit evidence |
| --- | --- | --- |
| 1. Resolve known validation failures | Reproduce and triage the Qt hang, browser failures and local-model failures tracked above. | Each failure has a verified fix or an explicit support limitation; no unsafe behavior is waived. |
| 2. Make operations dependable | Fix blocking problems in progress reporting, cancellation, retries, restart recovery and resource cleanup. Reconcile uncertain remote outcomes before repeating actions. | Interrupted and repeated operations preserve files, drafts and selections without duplicate submissions or unintended downloads. |
| 3. Walk through the product | Audit setup, Zen, Library, Search, Torrents, Upload, RSS, download queue, Media, Assistant, Activity and Settings. Compare desktop and web with the same data; map corresponding MCP operations. | Screenshot pairs and a ranked list of reproducible gaps, each with expected behavior and an acceptance check. |
| 4. Polish the interface | Apply common navigation, spacing, typography, table behavior, dialog layouts, action labels and empty/loading/error states. Improve the highest-friction workflows first. | Essential actions are available on both desktop and web, and representative screenshots pass review at the supported sizes and themes. |
| 5. Refine assisted workflows | Make model scope, selection changes, incomplete presentations and tool outcomes easy to understand. Preserve saved work across turns and failures. | Scripted local-model conversations complete or identify an actionable blocker, with correct saved state and no false success claims. |
| 6. Measure performance and improve support | Profile large local libraries, tables, queues and chat histories. Add useful diagnostics, including path/permission checks and redacted support exports. | Recorded baseline and improved measurements; users can identify the affected operation and provide a useful report without exposing credentials. |
| 7. Validate upgrades and releases | Test migrations, backup/restore and installed packages across the agreed support matrix. Gate publication on checks for the exact release commit. | Packaged workflows and upgrade evidence pass, known limitations are published, and the beta observation criteria are met before an RC. |

Stages are not isolated silos. A file-safety or unintended-action defect found during visual review takes priority immediately. Small visual changes can be delivered alongside reliability fixes when they do not obscure verification.

## First audit: what to inspect

For every view, inspect a populated state, an empty state, loading, failure and recovery. Record the app version, deployment, client, language and viewport with each finding.

| Workflow | Questions and acceptance targets |
| --- | --- |
| Setup and Settings | Can a new user connect a Torrent Client, distinguish local and remote paths, choose Download Folders and resolve a permission error? Category changes must affect only the chosen scope. |
| Zen and planning | Show the actual reason for an empty plan. Keep catalogue coverage, configured filters, torrent caps and disk constraints distinct. Missing folders should open the requested setup modal. Verify web Seeding, Plan and Catalogue parity. |
| Library and Reseed | Explain Orphan, Partially Seeded and Seeded states. Test app-downloaded files, nested packs, moves, extraction and rescans against the configured client. A failed title search must not imply that files are absent from c411. |
| Search, selections and clients | Distinguish live results from cached metadata. Preserve filters and selection scope. Show exact counts and totals, release deduplication and differences between clients. |
| Download queue | Make “save to app queue” and “start download” visibly different. A backlog may exceed disk capacity; actual dispatch checks its configured constraints. Explain waiting, failed and uncertain entries and their next action. |
| Upload | Review the presentation as it will be submitted. Keep exact files, category fields, technical facts, images and NFO aligned with the saved revision. Explain incomplete fields and make corrections practical. Test a complete album and a multi-piece 3D item, not only one-file fixtures. |
| RSS | Make active feed, unread state, matching rules, release choices and next refresh clear. Explain preferred versus required values, waiting for alternatives and unknown metadata. Defaults and automatic actions must match the user's explicit mode choice. |
| Media | Keep playback responsive during browsing, seeking, layout changes and exit. Explain unavailable files and unsupported playback without losing the queue. |
| Assistant | Keep concise activity lines with expandable details, inline tool errors and appropriate retry behavior. Put summaries above cards and avoid duplicate lists/images. Make the active client, saved selection and conversation folder understandable. |

## Visual consistency rules

- Agree on a compact set of shared patterns before restyling individual pages: page header, toolbar, filter row, table, card, dialog, progress area and status message.
- Keep primary actions, selection counts and the active Torrent Client visible and predictable. Preserve context when opening details or switching between views.
- Check contrast, focus visibility, keyboard navigation, text scaling and long labels. Do not communicate status using color alone.
- Check French and English, light and dark themes, a smaller desktop window and a narrow web viewport. Long torrent names and large quantities must remain usable.
- Keep technical detail expandable. The visible message should state what happened, what remains pending and the useful next action.
- Judge desktop/web parity by capability and behavior, not by requiring identical widgets.

## Reliability scenarios

Exercise the same operation through desktop, web and MCP where it is supported:

1. Cancel before dispatch, while waiting and during remote work.
2. Lose the client or Indexer connection, then reconnect.
3. Receive a rate-limit response and display the scheduled retry without freezing the UI.
4. Restart with queued work, an incomplete draft or an uncertain remote result.
5. Retry an action whose remote submission may already have succeeded.
6. Change the selected client or folder while work exists and verify that existing work retains its intended destination.
7. Close the application with active background work and reopen it. Check database handles and worker shutdown, beyond the packaging smoke-test cleanup.

Use isolated data and controlled failures first. Real client tests should use dedicated fixtures. Record which live operations were actually exercised; preview tests do not establish successful tracker publication.

## Test and support matrix

Start with Windows installed executable, Linux AppImage, and Docker web behind the documented reverse-proxy configuration. Cover one local and one remote Torrent Client, including Docker Path Mappings and unavailable folders.

Use the existing qBittorrent, Deluge and Transmission integration suites as a base. Record supported versions and any manual-only coverage, including the existing µTorrent Classic/BitTorrent Classic rename workflow. Do not infer support for an untested configuration from another client passing.

For the assistant, include the user-confirmed Radiance endpoint (recording its advertised API model ID separately), malformed tool arguments, text-only capability and rejected image input. Additional providers belong in the support matrix only after their behavior has been tested. RSS polling and core application workflows must continue without a model.

For performance, use saved/local fixtures at roughly 1,000, 12,000 and 50,000 torrents where relevant, plus long chat histories and large selections. Measure time to first useful content, UI responsiveness, memory and cancellation delay. Set targets after collecting the baseline; avoid arbitrary speed promises or live tracker load tests.

## Backlog and completion rules

Each audit item needs a reproduction, affected interfaces, expected behavior, severity and acceptance evidence. Mark unverified reports as needing information rather than confirmed defects.

- Release blocker: data loss, unintended downloads/submissions, duplicate consequential actions, broken upgrades, or a supported core workflow with no usable recovery.
- High priority: repeated freezes, incorrect previews/scope, missing essential parity, or errors that prevent users from completing a task.
- Polish: layout, wording, consistency and efficiency improvements that do not block correctness.

Close an item when the relevant behavior is verified and, for a visible change, the result has been inspected. Use focused regression tests for defects; do not add tests that merely mirror cosmetic implementation details. Keep the full suite, installed-package checks and required integration checks as release gates.

Before publication, run formatting as well as lint, and ensure CI and packaging target the exact release commit. A successful build alone is insufficient. Preserve published tags and report failures rather than silently replacing artifacts.

## Versioning and later decisions

Continue `1.0.0-beta.N` during stabilization. Use `1.0.0-rc.1` only for a specific candidate believed ready, with known release blockers resolved and final evidence under review. Publish stable `1.0.0` only after the accepted criteria pass. Later versions follow SemVer according to compatibility and scope. This plan does not authorize a version bump, tag or publication.

Before declaring an RC, agree on the support matrix and beta observation period using real-user coverage and defect recurrence. Before `1.0.0`, satisfy the separately accepted product promises and compatibility commitments.

The first implementation batch resolves the recorded validation failures. The paired desktop/web audit and recovery matrix follow, with support and release evidence tracked through the issues above. No claim of completion is made for untested deployments or workflows.
