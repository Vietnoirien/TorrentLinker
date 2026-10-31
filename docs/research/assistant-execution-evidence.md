# Assistant replies without execution evidence

Reported on 2026-10-30 during 1.0 polish, tracked with #46.

## Reproduction

The restarted desktop app's saved responses claimed a film was queued and sent, but each affected run contained only a user message and an assistant message: zero tool calls and zero tool events. The companion/session-download code was never reached. Earlier turns had invented disk-space rejection messages in the same way.

The discussion's actual grant allowed media control, not automatic downloads. A correct send request should therefore create an owner-approval proposal, not bypass the grant or treat a conversational "yes" as approval.

The controlled replay is `tests/test_assistant_execution_live.py::test_live_send_after_unexecuted_retry_claims_requires_real_proposal`. It uses a temporary media-only discussion, a fake queued film, simulated clients and blocked tracker/client connections. Three previous assistant replies claim actions without any recorded events. The current request is "lance le telechargement".

Before the change, Radiance returned a completed answer in one model call with zero tool events. It invented another disk-space rejection and a queue limit. The replay failed in 4.25 seconds. The native transcript regression also failed because it displayed `1 calls · 100 tokens · completed`, without explaining that no application action occurred.

## Cause and correction

Recent assistant prose was replayed as ordinary conversation history. Only previous tool receipts were added; tool-free turns had no explicit execution record contradicting their claims. The loop treated a final text answer as a completed model run, and the UI's "calls" count described model calls without distinguishing tool calls.

The model now receives an authoritative execution ledger for recent replies. It records the actual tool-call count, bounds the tool-name preview, and explains that a zero-tool reply did not queue, send, retry, edit or measure disk space. Completed reply status is explicitly separate from action completion. Compacted history keeps the same distinction. Existing receipts, client observations and approval rules remain authoritative.

Desktop and browser activity now distinguish model calls from tool calls. Completed zero-tool replies show "Reply only", "No tools called", and a visible statement that no application action was performed. Writing-only replies remain supported. The notice derives from recorded events, not from trusting the model's text.

This does not attempt to prove every natural-language claim made after arbitrary tool calls. A successful read or search is still not evidence of a download. Actual operation receipts must establish the requested outcome.

## Validation

- The controlled Radiance replay passed twice with server-default sampling, matching the reported provider setting. It reached owner approval in seven and five model calls. The second run also checked the proposal was `send-queue` for exactly the one fixture hash.
- No owner approval was granted during those runs, no tracker was contacted and the queue remained unchanged.
- The native, Chromium, assistant/provider/context and translation regression suite passed 80 tests. A follow-up check covers the bounded ledger representation.
- Companion-download and queue-capability regressions passed 45 tests. Ruff and mypy also passed.
- The real user's download was not retried, their permissions were not broadened, and disk-space limits were not changed.

This fix follows the published beta.27 artifact.

Full CI subsequently exposed eight assistant regressions: the history-evidence note was also sent with an empty history, pushing fresh chats over the fallback context budget. Early compaction replaced raw tool receipts with archived memory, which the scripted approval/recovery providers did not understand. The note is now added only when previous replies exist. Fresh chats avoid the unnecessary context cost, while follow-ups retain the recorded execution ledger. The original failures reproduced locally; the affected folder, tool-error, guard and context suite then passed all 53 tests. A ninth CI failure was a stale assertion expecting a reserve error when the disk was actually full; it now checks the insufficient-space explanation while retaining the no-client-add assertion.

## Optional reserve for direct downloads

The next report contained a real `send_selection` receipt refusing the download because of the free-space reserve. The owner requested an opt-in reserve and explicitly approved disabling it for the current Media discussion. Its saved grant kept 10 GiB free; the Plan margin was already zero.

New discussions and agent connections now default to zero extra reserve. Desktop controls label zero as "No extra reserve", and browser controls explain that zero disables it. Existing saved nonzero reserves remain in effect until their owner changes them. The Plan's percentage margin applies to Plan generation, not to direct sends. RSS feeds retain their separately configured reserve.

Preview, approval and the final send guard still account for selected downloads, unfinished client downloads and unresolved send reservations. A zero reserve does not permit a download that exceeds actual available space. Errors distinguish insufficient space from an optional reserve, with directions to change the latter.

The regression first failed for the default 10 GiB reserve and the inherited Plan percentage. Four cases now cover a successful direct send, an explicitly chosen reserve, pending downloads exhausting space, and space disappearing before the client receives the torrent. The related agent, catalogue, native/browser and translation suite passed 71 tests; the focused cases and Plan checks passed 78 tests.

## Workstation acceptance replay, 2026-10-31

At `e054892`, Radiance at the previously configured local endpoint still advertised
`Qwen3.8-27B-MXFP4-off`. Both controlled scenarios passed with server-default sampling
in 44.96 seconds. The retry-claim replay reached an exact one-film `send-queue` approval
proposal in four model calls. Queue preview prepared the bounded batch without sending;
the removal follow-up required approval of Film 01 and Film 02 and left Film 03 through
Film 10 intact. Simulated clients recorded no downloads or removals, and no send
reservations remained. No real tracker, user queue or Torrent Client was used.

These are two focused replays after the workstation changes, not a new complete
16-scenario acceptance pass or proof that every model selection is correct.
