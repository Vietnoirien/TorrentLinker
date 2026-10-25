# Agent edge cases and capability priorities

Assessment: 2026-10-25. Scope: the built-in Assistant and its shared MCP server.
The Docker support conversation is outside this assessment.

Initial validation: 166 related tests passed, 4 opt-in tests skipped; all three new live
Qwen scenarios passed after the reporting correction. Ruff, formatting, mypy and
`git diff --check` passed. The new deterministic edge-case file contains 21 cases.

## Findings fixed locally

1. **Rejected job submission reserved download budget.** Approving a send when the
   worker queue was full or closed changed the proposal to `submitting` and recorded
   a reservation before job submission failed. The proposal had no running job.
   Submission capacity is now checked while holding the same job lock, before
   reserving budget or changing proposal state. This covers known capacity and
   shutdown rejection; uncertain failures after acceptance remain conservative.
2. **Invalid later entries partially changed the queue.** A batch containing a
   valid first item and a later item without a download link queued the first item,
   then failed. Candidates and download links are now validated for the whole batch
   before insertion. This is prevalidation, not a promise of transactional recovery
   from arbitrary storage failures.
3. **The local model invented numeric explanations.** In the first oversized-queue
   run, Qwen correctly queued 500 films without downloading, but its explanation
   invented disk capacity and a positive daily budget. The tool had reported zero.
   The Assistant now requires observed figures, distinguishes capacity from free
   space, and treats zero as zero. Catalogue selection also returns a computed
   `total_size_display` with both GiB and GB, alongside exact `total_size_bytes`.
   The repeated live run reported the correct total and zero budget. This is evidence
   for that run, not a guarantee that all future model prose is correct.

## Additional deterministic coverage

`tests/test_agent_edge_cases.py` exercises:

- Empty results from an unknown category, unmatched title or offset beyond the end.
  None may turn into an unfiltered queue or download action.
- Repeated request IDs, new request IDs for already-queued items, and reuse of one
  request ID for a different action.
- Entries removed, sent, sending, refused or failed after a proposal was created.
- Queued size, title or category changed before approval.
- Full and closed job queues, with no stranded proposal or budget charge.
- A missing download link late in a batch, with no partial queue insertion.
- Disk space disappearing after reservation, a larger-than-declared torrent,
  a different infohash, revoked access and cancellation before the client add.
  These use a real generated `.torrent` and a simulated client through the send path.
- Decimal and binary size formatting without changing the exact byte total.

Earlier tests also cover oversized queues with byte, torrent and free-space limits,
selection ownership and expiry, missing-folder recovery, changed catalogue rankings,
category isolation, and approval rendering in desktop and browser views.

## Real-model checks

The opt-in tests in `tests/test_assistant_live.py` use local
`Qwen3.8-27B-MXFP4-off`, temporary settings, synthetic Catalogue rows and simulated
Torrent Clients. Tracker access is blocked; no real downloads or user settings are
changed.

- Queue 500 films totalling 536,871,037,250 bytes against a simulated 100 GiB disk,
  with zero daily bytes and zero daily torrents allowed. Expected: queue all 500,
  no download, no reservation, no settings edit, exact reported byte total.
- Ask for the weight of 500 films when only three films exist. Expected: report
  those three and 24,000,000 bytes, with no extrapolation or mutation.
- Ask the same question when only an ebook exists. Expected: report no available
  films, without replacing the category or creating a queue.

Live evaluations are opt-in and should be rerun when changing model, prompt or
schemas. Deterministic tests remain the reproducible gate.

## Shared capabilities implemented

The six capabilities below now run through the shared application service and MCP.
The built-in Assistant and external agents use the same tools, snapshots and approvals.

| Priority | Capability | Why it is needed | Example acceptance case |
| --- | --- | --- | --- |
| 1 | `select_queue` with filters, sorting, counts and exact totals | `list_items(collection="queue")` only offers title search and pagination. Catalogue selections expire after 15 minutes, but queues are persistent. | Select the oldest 20 queued films from yesterday, excluding sent/refused entries, without reselecting the current Catalogue. |
| 1 | `preview_download` returning per-item blockers and remaining budget/space | `overview` exposes configured limits, not today's usage, remaining allowance or measured disk capacity. Current checks often surface one error after approval. | Explain that 500 items remain queued, 17 fit now, which folders are missing, and how pending client downloads reduce available space. Return unknown values explicitly when a client is unavailable. |
| 2 | `prepare_download_batch` with byte/count caps and ordering | Starting a whole saved selection is currently all-or-nothing at the budget check. The agent cannot conveniently prepare a smaller exact subset of the persistent queue. | Keep a 500 GiB queue intact; prepare an explicit 20 GiB batch, show exclusions and request approval for precisely that batch. Recheck constraints at send time. |
| 2 | `edit_queue_selection` for remove, retry and priority changes | The owner UI can remove queue entries; there is no equivalent MCP queue-edit tool. Client torrent controls affect a different collection. | Remove only three unsent queue entries without deleting files or torrents from the client. Retry failed entries after validating their destinations; never blindly retry an uncertain send. Priority changes require a persistent priority/order model first. |
| 3 | `refine_selection` and explicit exclusions | Current category/title/size/seeder criteria cannot exclude already-queued or already-seeded items, or compute a set difference between saved selections. | Select 500 smallest films not already queued or seeded on the chosen client; report whether fewer than 500 remain. Return a new snapshot instead of editing an approved one. |
| 3 | `compare_selections` / grouped statistics | The model still has to perform arithmetic across paginated results for category breakdowns and comparisons. | Return exact counts and byte totals by category, intersection and difference between two selections, without changing either selection. |

Queue selection and preview inspect the persistent queue without Catalogue reselection.
Snapshots belong to one connection and Torrent Client and expire after 15 minutes.
`prepare_download_batch` preserves the saved order and chooses only rows that fit both
explicit caps and observed constraints. It keeps the larger queue intact. Zero caps
and budgets remain zero. All actual sends recheck approval bindings, destinations,
daily budgets, available space and torrent identity/size.

`edit_queue_selection` supports removal, safe retry and persistent priority. Larger
priority values send first, with insertion order for ties. A saved queue selection
may explicitly choose a different order; its sends preserve that reviewed order.
Queue edits and enqueueing use the new `queue` permission; starting downloads uses
`downloads`. Existing persisted grants and Assistant policies migrate once to retain
their previous queue rights. New download-only grants do not receive queue rights.

`refine_selection` filters only the saved rows and returns a new snapshot. To fill a
Catalogue count after exclusions, use `exclude_queued`, `exclude_seeded` or explicit
`exclude_hashes` in `select_catalogue`; these apply before sorting, offset and count.
`compare_selections` compares saved Catalogue/queue snapshots by torrent hash,
deduplicates repeated identities and returns exact category counts and bytes. Its
intersection totals use the left snapshot's metadata.

A preview makes no budget reservation and does not reconcile storage ledger rows.
It reports measured capacity, free space, pending allocations and reserve with an
observation time. Unavailable clients or unverified/missing mounts leave capacity
unknown. Batch preparation observes each destination once, then applies caps in
one ordered pass instead of recontacting clients for every item.

Failures before a client add are explicitly marked safe to retry. An add timeout,
post-add bookkeeping failure or interrupted send remains uncertain. Legacy failed
rows without safe-send evidence cannot be retried or removed by an agent. The owner
must inspect the Torrent Client first, then may remove the local queue record and
queue it again manually if no torrent was accepted. This never deletes client data.

## Design constraints for those additions

- Separate permission to prepare/edit a queue from permission to start downloads.
  The current `downloads` permission covers both. Queue-only execution should not
  grant the ability to send torrents.
- Keep queues independent of capacity and daily download budgets. Apply those
  limits to actual sends and recheck just before adding a torrent to the client.
- A preview is read-only and makes no reservation. Approval binds an explicit set
  of hashes, client and destinations; later changes require a fresh review.
- Report results per item: queued, already present, excluded, blocked, sent, failed
  or uncertain. Include totals over the whole selection, not merely one page.
- Use stable request IDs, connection ownership and existing folder validation.
- Report both total capacity and free space only when measured. Include observation
  time, pending allocations, required reserve and uncertainty. Do not replace an
  unavailable remote disk measurement with container disk space.
- Retain existing safeguards for uncertain sends and shared disks. Do not add
  automatic deletion, budget increases or unlimited background downloading as a
  side effect of preparing a queue.


## Implementation validation

The new deterministic capability suite exercises shared MCP and owner approval with
simulated clients: queue filtering and exact totals, read-only previews and ledgers,
explicit/zero batch caps, queue-only permissions, one-time migration, immutable
refinement, category comparisons, stale/foreign snapshots, missing mounts,
nonfinite date filters, unknown identity/size, repeated Indexer hashes, persistent
priority and reviewed send ordering, definitive fetch failure, accepted-but-timeout
and post-add bookkeeping failures. A 500-item batch bounds client observations per
destination instead of per item. Native and browser approval summaries identify
queue removal, retry and priority without hiding the action in JSON.

The new local Qwen workflow passed using temporary settings and a simulated Torrent
Client. It selected the queue, previewed current blockers/allowances, prepared a
2-torrent/20-byte batch while keeping all 10 entries, then removed only two named
queue entries using queue-only permission. It created no downloads, client removals
or budget reservations. Its two phases completed in 29.49 seconds in the recorded
run. Model prose remains an opt-in evaluation, not a deterministic guarantee.

Known limits: snapshots contain at most 1,000 rows and expire after 15 minutes;
queues persist across restarts. Batch feasibility is provisional and handles one
physical disk per send. Size totals describe cached metadata. Unknown remote space
is not replaced with container disk capacity. Refinement does not widen a saved set.


## Installed documentation guidance

Two additional read-only shared MCP tools, `search_documentation` and
`read_documentation`, let the Assistant and external agents consult installed
English/French guides without network access. They accept allowlisted guide IDs,
return bounded snippets/sections and continuation offsets, and report missing
bundled files explicitly. Results identify the app version, exact document SHA256,
source checkout versus bundled installation, heading and local citation URL.
Checkout content does not claim to match an online release tag. Citation links open
a standalone guide on the web or a nonmodal guide reader in the native chat.
The Assistant prompt asks it to consult these tools for setup/how-to questions.


## Chat presentation and repository links

Actual model commentary now retains its place before the calls it accompanies.
Persisted event anchors let desktop/browser chats show commentary, compact readable
tool groups and the final answer in order. Expanding a tool shows exact highlighted
JSON arguments/results/reviews; approval cards and questions remain visible.
Descriptions are deterministic tool-action labels when the model supplies no note.
They do not fabricate hidden reasoning.

Public HTTP(S) poster/cover images may be displayed with observed Markdown image
URLs and clickable originals. The browser uses the authenticated same-origin image
proxy; native thumbnails load asynchronously and retain unavailable-image links.
The English and French README files include the repository mirror at
https://git.mma.dev/Vietnoirien/TorrentLinker. Future release/chat announcements
should include that mirror as requested; this implementation does not publish a
release, push or restart the running app.


## Conversation folders

Native and web sidebars group conversations in collapsible built-in or bounded custom folders. Owner moves persist independently of ordinary discussion settings edits. The internal `classify_conversation` tool derives the current conversation from the active run, accepts no other conversation ID and respects manual owner placement. Re-enabling automatic classification is an explicit owner action. This tool changes neither settings nor permissions. Public owner API and simulated-provider tests cover restart persistence, manual protection and rejection of foreign conversation IDs.
