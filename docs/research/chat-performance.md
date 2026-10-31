# Native chat-history performance, 2026-10-31

Workstation continuation for [#49](https://github.com/Vietnoirien/TorrentLinker/issues/49).
Baseline source was `56745c9`. [Raw measurements](chat-performance-2026-10-31.json).

## Reproduction

`scripts/benchmark_chat.py --count 100` renders 100 synthetic runs, the current
Assistant history limit. Each has a user message, an assistant response of about
700 characters with a short list, and one collapsed tool receipt. There are no
images, model requests, application actions or reads from saved conversations.

The benchmark runs in a fresh process with temporary Qt preferences, Python 3.13.11,
Qt 6.12.0 and the offscreen platform. It measures first rendering and three changes
to the newest response. A 10 ms heartbeat records GUI stalls. Each measurement
includes a 20 ms event-loop drain and processes deferred widget deletions, as the
normal application event loop would.

| Measurement | Before | After |
| --- | ---: | ---: |
| First render, 100 runs / 200 messages | 749 ms | 808 ms |
| One changed run, median of three | 825 ms | 28 ms |
| Peak RSS | 225 MiB | 182 MiB |

First rendering has not improved. The update time is now near the benchmark's
20 ms event-loop drain. These are local observations, not cross-platform timing
guarantees or CI thresholds.

## Change and verification

Previously, any changed run recreated the entire transcript, including completed
messages and expanded receipts. The regression reproduced that replacement before
the fix. The transcript now retains unchanged run widgets and their containing
layout. It replaces changed runs, removes missing ones, and inserts new ones in
chronological order. A copied run snapshot detects nested message or receipt edits
even when the caller mutates its existing dictionary.

Reuse also checks language, light/dark appearance, status formatter and the rendered
discussion heading. Changed approval receipts replace their previous controls.
Expanded receipts and presentation pagination survive unrelated response updates.
The 64 focused native Assistant, receipt, approval, image, presentation and discussion
checks pass, with 11 optional browser cases skipped. Lint, formatting and typechecking
pass. The expanded-receipt screenshot was inspected for layout and message order.

The benchmark covers native transcript rendering. It does not measure history SQL
reads, JSON comparison in the Assistant poll, remote images, large presentation
payloads, browser chat, or model latency. Reopening a long history still creates all
its widgets. Those costs and installed Windows measurements remain open.
