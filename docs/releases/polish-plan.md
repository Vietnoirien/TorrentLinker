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
| 1 | [#44: native-media deadlock](https://github.com/Vietnoirien/TorrentLinker/issues/44) | Reproduce the combined-run freeze, identify its cause and verify playback plus shutdown together. |
| 1 | [#45: browser acceptance](https://github.com/Vietnoirien/TorrentLinker/issues/45) | Repair stale Upload fixtures and verify Profile, Seeding and Plan navigation against the real page. |
| 1 | [#46: local-model failures](https://github.com/Vietnoirien/TorrentLinker/issues/46) | Classify all 16 failures; fix application/test defects and record model limitations without weakening safeguards. |
| 2 | [#47: interruption and recovery](https://github.com/Vietnoirien/TorrentLinker/issues/47) | Scenario-to-test coverage for cancellation, restart, uncertain sends and destination scope. |
| 3 | [#48: desktop/web walkthrough](https://github.com/Vietnoirien/TorrentLinker/issues/48) | Paired screenshots, reproducible usability findings and verified fixes. |
| 4 | [#49: support and performance](https://github.com/Vietnoirien/TorrentLinker/issues/49) | Recorded baselines and useful, credential-redacted diagnostic exports. |
| 5 | [#50: upgrades and release readiness](https://github.com/Vietnoirien/TorrentLinker/issues/50) | Candidate upgrades, backup/restore, platform/support matrix and real-user observation. |

The issues distinguish known failures from missing evidence. Their acceptance checks are the completion criteria. Features already delivered include the Search, Torrents, Upload and Library desktop/web redesigns, web Zen planning parity and the companion setup guide. Audit those workflows in their current form; do not restart their redesigns.

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
| Media storage cleanup | `tests/test_media_lifecycle.py` | Original combined-run deadlock remains unexplained. |

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
