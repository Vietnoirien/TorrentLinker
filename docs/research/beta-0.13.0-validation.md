# 0.13.0-beta.1 validation

Validation performed on 2026-10-26, on main after abfad2a plus the fixes committed with this report. Tests used isolated configuration folders. Source files were not changed, and no torrents were published or sent to a real Torrent Client.

## Automated and packaging checks

- Full suite with browser tests enabled: 1,472 passed, 99 skipped in 303 seconds. Live-provider tests are opt-in and were run separately below.
- Ruff and mypy passed, covering 158 Python source files.
- The installed 0.13.0b1 package passed the desktop smoke test, including local MCP startup. The wheel includes the RSS guide and web assets.
- An isolated upgrade from the actual v0.12.2 sources preserved settings, an Upload draft and its files, a conversation and an app queue entry. RSS initialized without changing them.
- Windows and AppImage packaging and smoke checks run in the release workflow. Local Linux success alone is not evidence for those packaged binaries.

## Local model

Provider: Qwen3.8-27B-MXFP4-off, using its configured local OpenAI-compatible endpoint.

Generated Upload fixtures passed four live tests: French ebook with same-draft refinement, audio, a 3D mesh, and rejection of a foreign-language ebook. Complete cards matched the saved draft preview; drafts remained unreviewed and files unchanged.

Real-file checks:

- A feature-film MKV produced a complete local review card after file inspection and metadata research.
- A French EPUB produced a complete local review card.
- A complete FLAC album preserved all 19 files, including 18 tracks and artwork. The model initially embellished technical values, which strict fact comparison rejected. A follow-up corrected those fields in the same draft using exact extracted facts. Only the unknown rip source remained incomplete in the description and NFO, correctly preventing a complete card. Public image hosting was still required before sending.
- An earlier album attempt used a Library Folder at the wrong scan level and selected one track. That attempt is not counted as full-album coverage; the test was rerun with the parent folder and explicit path/file-count assertions.

The tests found and fixed a crash when documentation text was interpreted as image blocks. They also exposed unknown source values followed by explanations being accepted as filled fields. Regression tests now reject these source placeholders. All 58 focused Upload completeness, file-fact, card and queue tests passed after this final fix.

No claim is made that the local endpoint supports vision, or that real publishing credentials and tracker moderation were exercised. Large multi-piece 3D rendering remains subject to the documented resource limits.

## RSS

A live-model test against controlled feeds created three subscriptions, then edited a polling interval and paused another feed. IDs, preferences and unrelated fields survived the edits and database reopening. No downloads occurred.

A separate run used the actual c411 endpoint. The model created and refreshed three review-only subscriptions: Films à découvrir, Livres et lectures, and Atelier 3D. The stored Torznab categories were 2030, 7020 and 8010. Film preferences retained the 8 GB ceiling, resolution and codec ordering, seeders and smaller-size preferences. Books preferred EPUB. The database contained 900 real release rows and all three subscriptions recorded a successful refresh.

A redundant verification refresh encountered HTTP 429. The successful initial results were retained; the test stopped redundant polling and respected backoff. Feed discovery is bounded and does not establish complete history or gap-free polling.

The model tests found that an untyped subscription object made settings harder to discover, and that preferred format keys could be omitted from ranking priorities. Typed MCP schemas now expose the fields and allowed metadata keys; missing preferred keys and the smaller-size preference are added to the ranking order. Regression tests cover the resulting ranking.

The screenshots were captured from the real web application using this isolated RSS database. They are not mockups. The upload and RSS tests guard Torrent Client mutations; automatic download rules are covered by controlled tests rather than a real download.

## Review

Standards and spec reviews were performed independently. The standards review caught a beta-version packaging smoke-check failure, fixed by validating installed versions with packaging.Version while retaining stable-only update discovery. No unresolved release blocker remained from those reviews. The final source-placeholder fix received an additional review and regression coverage.

## Packaging follow-up: beta.2

The beta.1 tag was pushed, but its release job did not publish a release. Linux packaging and smoke passed. Windows built successfully, then its smoke check failed. The MCP smoke test left feeds.sqlite open at temporary-directory removal. Linux permits that unlink, while Windows rejects it. An open-file check reproduced the leak; a regression verifies the database connection is closed. The smoke cleanup now closes this owned connection, and Windows failure output includes the application log. The corrected release uses v0.13.0-beta.2 rather than moving the existing tag.

CI also found four unformatted RSS integration files. They were formatted in follow-up commit 568210b; AST comparison verified no Python behavior changed. Ruff check and format checks both pass.

## Published result

v0.13.0-beta.2 was published from b9d41cc. Its exact-tag CI passed with 1,462 tests passed and 115 skipped; browser and live-model coverage was run separately as described above. All client integration jobs passed: qBittorrent 4.6 and 5.2.4, qBittorrent Docker Path Mappings, Deluge 2.1.1 and 2.2.0, and Transmission 4.1.3. Both packaged Windows and Linux smoke tests passed, and both binaries are attached to the public prerelease. The stable latest release remains v0.12.2.

An earlier CI run timed out while waiting for the 1,100-torrent test action. Follow-up main commit 2d18aa8 adds a bounded wall-clock wait and permits 30 seconds for this bulk case without changing its outcome assertions or application code. All 30 affected local job/selection tests passed. The exact beta.2 tag also passed CI independently.

- Release workflow: https://github.com/Vietnoirien/TorrentLinker/actions/runs/40371985744
- Exact-tag CI: https://github.com/Vietnoirien/TorrentLinker/actions/runs/40371985355
- Public prerelease: https://github.com/Vietnoirien/TorrentLinker/releases/tag/v0.13.0-beta.2
