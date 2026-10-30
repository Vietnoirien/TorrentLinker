# Recovery audit for 1.0

First audit pass on 2026-10-30 for [#47](https://github.com/Vietnoirien/TorrentLinker/issues/47). This records tested behavior and missing evidence separately. It does not close the issue or establish release readiness.

## Finding fixed in this pass

The first newly built Linux executable aborted during shutdown. A Qt background task emitted `done` after its signal object had been deleted. The exception hook then attempted to create a dialog after `QApplication` destruction. A second package run and a source smoke run passed, confirming that a single green exit was insufficient.

A controlled subprocess using the real `app.main()` lifecycle reproduced the same `Signal source has been deleted` error in 1.76 seconds. Its task remained active when the application returned. This established a lifecycle defect independent of packaging and the earlier audio mutex deadlock.

The application now closes its views and drains desktop work before Qt teardown, including when a smoke check fails. The task runner removes its own queued jobs from the Qt pool and refuses new work during exit. Running jobs finish while the GUI thread delivers progress and completion/error callbacks, preserving callback-owned results. The shutdown checks also verify that callbacks cannot start follow-up work and that a late message box does not prevent exit.

This does not forcibly terminate an in-flight remote mutation. Cancellation and uncertainty rules for those operations remain in their existing workflow implementations.

Validation: the initial recovery baseline passed 115 tests. The final affected recovery, GUI, native-media and shutdown suite passed 209 tests in 101.88 seconds. Ruff, formatting of 396 files, mypy over 200 source files, release-workflow YAML parsing and diff checks passed.

## Scenario-to-evidence matrix

Paths below are under `tests/`. All application operations use fake clients or controlled transports unless explicitly identified as packaged local playback.

| Scenario | Evidence exercised | Result and remaining gap |
| --- | --- | --- |
| Download queue paused during a rate limit or after one send | `test_download_queue.py::test_pause_during_rate_limit_leaves_item_queued_and_resume_sends_once`, `test_pause_after_one_send_leaves_remaining_items_queued` | Remaining entries stay queued; resume does not duplicate the completed send. Browser/desktop walkthrough remains. |
| Process exits after a Torrent Client accepts a queued download | New `test_download_queue.py::test_process_exit_after_handoff_preserves_uncertainty_and_client_scope` | Child exits with `os._exit` inside the simulated handoff, after recording acceptance. Restart preserves an uncertain, non-retryable entry, its client and folder, another client's queued entry and source bytes. Processing does not resend it. Installed remote-client reconciliation remains. |
| Upload POST has an uncertain result | `test_upload_queue.py::test_uncertain_send_is_kept_and_does_not_retry_automatically`, new `test_upload_restart.py` | A child exits inside the simulated POST after recording acceptance. Restart marks the job interrupted, preserves the draft and refuses a repeat send. Reset requires owner approval, increments the revision and invalidates prior send approval. Source bytes remain unchanged. Desktop cancellation/confirmation and Chromium recovery pass; installed-platform and real-site reconciliation remain. |
| Saved Upload Draft and owner approval | `test_upload_queue.py::test_local_draft_survives_restart_and_only_explicit_send_contacts_site`, `test_mcp_automations_queue_locally_and_sending_needs_current_revision_approval` | Saving stays local; sending uses the reviewed revision and owner approval. No real tracker publication was performed. |
| Running job interrupted; browser logs out | `test_web_jobs.py::test_abrupt_restart_records_interruption_without_replaying_mutation`, `test_job_survives_browser_logout_and_is_visible_after_server_restart` | Abrupt restart marks interruption without replay. Logout does not cancel application-owned work. Installed-server termination remains. |
| Reseed interrupted before or during Verification | `test_reseed.py::test_verification_started_before_a_restart_is_settled_after_it`, `test_reseed_interrupted_before_its_check_is_undone_without_a_rejection`, `test_setup_timeout_cleans_up_only_after_successful_removal` | Controlled clients verify recovery and safe cleanup. This pass did not repeat real-client integrations or the supported-version matrix. |
| Approved disk rename, cancellation and restart | `test_disk_rename.py::test_cancel_or_missing_approval_never_renames_or_adds`, `test_recovery_before_add_and_after_interrupted_verification_is_client_specific`, `test_worker_confirmation_and_shutdown` | Approval, client scope, file preservation and consent cancellation are covered. Installed Windows client checks remain. |
| RSS restart, budgets, pause and changed requirements | `test_feed_api.py`, including `test_app_queue_scheduler_never_contacts_clients_and_restart_keeps_rule`, `test_automatic_dispatch_respects_budget_and_schedule_after_restart`, `test_pending_automatic_entry_rechecks_edited_hard_requirements` | Persisted scope and dispatch authorization are checked. User-visible recovery states still need the walkthrough. |
| Plan cancelled before next item or during a wait | `test_send.py::test_stopping_during_a_wait_ends_sending_and_says_so`, `test_stopping_ends_sending_before_the_next_torrent` | No later item is sent after cancellation. Interrupted installed Plan execution remains. |
| Destination changes after work is selected | `test_enqueue_destinations.py`, `test_web_jobs.py::test_selected_download_uses_verified_client_path_and_survives_queue_reload` | Queue/client/folder scope is preserved in controlled API tests. Paired UI selection-change checks remain. |
| Companion disconnect/restart with an outstanding descriptor request | New `test_companion_downloads.py::test_companion_recovery_rejects_late_results_and_requires_a_fresh_request` | Restart does not redispatch the old command. Disconnect revokes the old token. Late results are refused; an explicit fresh request completes. Source bytes are unchanged. These are API/descriptor checks, not extension-tab lifecycle or Torrent Client dispatch tests. |
| Companion refusal and rate limit | `test_companion_downloads.py::test_session_refusal_stops_subsequent_requests`, `test_blocked_or_rate_limited_session_hands_out_no_more_work`; `test_indexer_session.py::test_session_failures_never_fall_back_to_the_api_key` | Refusal/cooldown stops dispatch; session failure does not fall back to API-key downloads. Actual browser extension reconnect remains. |
| Assistant approval across restart | `test_assistant_waits.py::test_approval_resumes_batch_once_after_restart` | Scripted approval/rejection resumes once. Real-provider restart/follow-up is separate from the earlier Radiance acceptance runs. |
| Desktop workers during shutdown | New `test_desktop_shutdown.py`, five subprocess cases | Success, failure, progress, smoke failure and late-dialog paths finish without deleting signal objects early. Queued/follow-up work does not start. Long-running remote calls and installed Windows/macOS shutdown remain. |
| Worker/database cleanup | `test_media_lifecycle.py`, `test_desktop_shutdown.py`; Linux package smoke | Media storage closes on normal and failed server startup; desktop tasks drain before Qt teardown. This is not proof that every database handle and every backend worker has been audited. |

## Linux package evidence

The package smoke test now plays eight generated, muted WAV streams, verifies playback advances, stops each stream and constructs widgets during audio cleanup. It also exercises the existing MCP smoke checks. This checks the actual frozen Qt/QML/FFmpeg dependencies rather than merely importing them.

The final executable and AppImage checks used fresh XDG data/config/cache directories, `keyring.backends.null.Keyring`, and a private network namespace with only loopback enabled. Temporary XDG directories alone do not isolate the system keyring; the initial diagnostic runs used only XDG isolation and are not included in these isolated results.

| Artifact/run | Exit | Duration | Playback, MCP smoke and traceback check |
| --- | --- | --- | --- |
| Frozen Linux executable | 0 | 5.02 s | Passed |
| AppImage, first run | 0 | 6.73 s | Passed |
| AppImage, second run | 0 | 5.67 s | Passed |
| AppImage, third run | 0 | 5.57 s | Passed |

The AppImage contains PulseAudio and the FFmpeg plugin. Its AppDir excludes compiler runtimes that would shadow host graphics drivers. Release smoke checks now have a 120-second deadline on Windows and macOS as well as Linux; those workflow changes have not run remotely.

Local artifact: `/tmp/tl-package-followup/dist/TorrentLinker-x86_64.AppImage`.
SHA-256: `3a43c08a0771a98bb70b02eb8b3b1608de830eb1700c3458e6bb73265efabe33`.
Logs, failure captures, the package runner and JSON results are under `/tmp/tl-package-followup/`.

This was a local Linux/offscreen build using Python 3.13.11 and Qt 6.12.0. It is not the release workflow's Ubuntu 22.04/Python 3.12 build, an installed Windows/macOS test, an upgrade test or a graphical desktop playback check. Nothing was published.

## Remaining audit order

1. Exercise owner reconciliation for uncertain download results through both desktop and browser. Upload reset cancellation and confirmation now pass in both interfaces with controlled transports.
2. Improve interrupted Upload status wording. After abrupt exit, the job is interrupted and sending is blocked, but the draft retains `sending` and both interfaces say "Sending to c411" until the owner reconciles it. Preserve protection against duplicate sends while distinguishing an active send from a result that needs checking.
3. Exercise actual companion-tab disconnect/reconnect during queued work, retaining the no-fallback and no-duplicate checks.
4. Run the package/recovery scenarios on the agreed Windows, Linux and Docker configurations, including source-file preservation and database/worker cleanup after remote calls.

## Upload recovery continuation

The follow-up to the beta.26 release commit adds an abrupt-process-exit test using mocked HTTP and a private in-memory keyring. The recovery test verifies the saved form and revision, refusal to resend, owner approval for reset, invalidation of stale send approval and a fresh approval requirement. No real c411 upload occurs.

The desktop test covers both `sending` and `uncertain` states. Dismissing the confirmation leaves the record unchanged. Confirming resets the revision, clears review and leaves sending disabled. The Chromium test follows the actual Draft actions menu after the process crash and checks the same cancellation and reset behavior against the temporary server. The initial browser test omitted opening that menu; correcting the test navigation produced a passing run without an application change.

Validation: 14 targeted Upload queue/workspace/restart tests passed; the explicit browser run passed both restart tests. Ruff, formatting and diff checks passed. Browser CI now includes the new recovery file. These follow-up tests are separate from the beta.26 release commit.
