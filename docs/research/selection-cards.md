# Persistent selection cards

Approved scope: category-adapted chat cards in desktop/Web UI, with click-to-open details
without another model turn. Failed tool activity exposes only its concise red summary
while collapsed; expansion contains the complete escaped error. Model error feedback is
unchanged.

## Shared interface

`present_selection(request_id, list_id, expected_revision, selection_id, enrichment_id,
offset=0, limit=12, research=False, title='')` imports exactly one source. A saved list
requires its exact revision. A transient selection must still be valid on first import.
The result includes `presentation_id`, frozen list/revision/client/count, bounded items,
and explicit `has_more`/`next_offset`. `get_presentation` reads subsequent pages.
`get_presentation_item` reads a single exact release's sanitized detail and provenance.
Owner APIs expose these same reads under `/api/assistant/presentations/{id}` and
`/{id}/items/{item_id}`; authenticated desktop methods share the service.

`enrich_selection` prepares the same bounded metadata without displaying cards and
returns `enrichment_id`; `present_selection` can import that snapshot. All calls are
planning/read-only with respect to torrents: no queues, sends, budgets or settings change.
Request IDs are idempotent across planning and action tools. IDs are actor/client scoped;
owner reads still validate the original grant/client. Membership and imported revision
survive selection expiry, list edits and restarts. Items retain ordinal IDs inside that
presentation. Current permissions are checked again when reading it.

## Metadata and safety

The exact release title/hash is distinct from canonical content title/provider ID.
Native c411 detail is fetched by exact release hash. Explicit artwork metadata slots
supply posters/covers/icons/previews; arbitrary description images are never selected as
covers. Unsupported/missing metadata remains visible as release facts and placeholders.
Changing Indexer configuration does not fetch the frozen release from another Indexer.
Descriptions use the existing sanitizer, with all embedded images removed. Main artwork
uses the existing public-URL image proxy/loader. Provider source data remains untrusted.

External research is opt-in and requires the Assistant conversation's Web permission.
Currently only film/series lookups with an explicit native TMDb identity can adopt an
exact single provider match; absent or ambiguous matches never adopt the first title hit.
Books/music/games/software/3D use explicit native artwork or placeholders. Provider keys
are never exposed. A failed metadata lookup leaves the release usable, with an honest
availability note. Observations are cached per persistent presentation; creating a new
presentation explicitly obtains fresh metadata. Pages are bounded to 20, lists remain
bounded by the existing 10,000-row planning limit; pagination never changes membership.

Cards show numeric `torrent_note` and `estimated_zen_per_day`, using the shared Zen
calculation and the configured profile frozen when the presentation is created. Assumptions
are explicit: standalone torrent, saved swarm +1, zero seed age, configured daily seed
hours/tree/badge bonuses, no live portfolio observation. Unknown size/swarm yields null;
Reuploader has no per-torrent seeding payout. These are estimates, not guaranteed payouts.
The string `note` describes metadata availability and is separate from numeric Torrent Note.

No model-authored per-item recommendation scores or notes are invented. An optional
presentation title and verified native facts provide the labels. Desktop/Web UI load
pages, images and details asynchronously and keep expansion/pagination state during
transcript refreshes. Missing images retain usable titles and source links.

## Validation

Public MCP and owner API regressions cover exact membership/revisions, edits after
presentation, request retries/conflicts, ownership, malformed item IDs, bounded pages,
empty/unknown metadata, native artwork vs description banners, sanitized details,
exact content-ID research matching and persistence past source expiry/service recreation.
Desktop and real Chromium tests cover cards/modal/pagination, images and collapsed errors.
Final suite/review outcomes are recorded after combined validation.

Final validation (2026-10-25):

- Full suite: 1,278 passed, 102 skipped, one known existing Upload-view lifecycle
  failure: `test_an_archive_is_unpacked_next_to_it_then_its_folder_is_offered` received
  a delayed `_image_failed` callback after its QLabel was deleted (`upload_view.py:1384`).
  That unrelated callback was left unchanged. The full run took 213.79 seconds.
- Post-review public MCP/list/native-search regressions: 32 passed. Source-binding
  regression checks that changing Indexer before presentation cannot fetch old releases
  from the new source. Legacy unbound sources remain basic-only.
- Final native/real Chromium card tests: 8 passed, including root and mounted Web UI,
  owner modal reads, numeric Note/Zen, plain-text category safety and no duplicate
  gallery for `get_presentation` read receipts.
- Real local Qwen with simulated c411 responses: 3/3 French workflows passed (film,
  ebook, music), 64.88 seconds, correct two-item cards/Note/Zen, no queue or sends.
  Reports: `/tmp/tl-card-model-acceptance/selection-cards-{movie,ebook,music}.json`.
- Ruff checks and formatting pass (269 Python files); mypy passes (144 source files);
  `git diff --check` passes.
- Parallel Standards and Spec reviews against `f8ffd3d` completed. Both findings were
  fixed and independently confirmed: category placeholders are PlainText; original
  Indexer provenance is checked before enrichment. Final read-receipt gallery dedup
  was also independently checked with no remaining finding.

Demo-artwork screenshots, explicitly labeled demo in the preview:
`/tmp/tl-selection-preview/desktop-cards.png` and
`/tmp/tl-cards-browser-fixed/test_browser_cards_open_modal_0/selection-cards-web.png`.
No tracker download, publish, push, release or settings changes were performed for validation.

## Follow-up: avoid duplicate prose and posters

The first local-model acceptance runs all produced a second pair of Markdown images
after displaying cards. The Assistant prompt still explicitly requested Markdown covers.
It now distinguishes standalone images from already displayed cards and asks for a short
summary unless the user explicitly wants textual detail. Successful Assistant presentations
retain complete event data but send the model a compact display acknowledgement; external
MCP responses and ordinary metadata reads retain their full data.

Validation: 76 focused Assistant, presentation, context and tool-activity tests passed. All three local Qwen category workflows
passed the new no-duplicate-image/list checks in 27.16 seconds, using the same isolated
simulated tracker. Reports are in /tmp/tl-cards-no-duplicate. Existing saved replies are
not rewritten.

## Follow-up: preserve metadata through saved-list selections

Materializing a saved list against the Catalogue rebuilt its rows without the original
Indexer binding. Presentations therefore refused metadata lookup, producing empty artwork
and descriptions even when the original live-search presentation had metadata. Materialized
rows now retain their provenance and category details while refreshing the validated fields.
The regression exercises Catalogue selection, saved list, materialization, card and modal,
and verifies that changing the Indexer still prevents fetching from a different source.

Live discovery and size refinements now explicitly require live Indexer search while keeping
the original genre/year constraints. Saved lists can be presented directly by ID and revision.
Catalogue selection remains available for explicitly requested cached ranking and totals.
It now returns an explicit selection_id, matching live search. Local Qwen had repeatedly
mistaken the operation ID for the selection ID without that field.

Validation: 41 focused tests passed. Local Qwen passed film, ebook and music card checks,
including images and modal descriptions, and four native-search cases across the final run
and a focused film rerun. One search assertion was updated to accept the title in rendered
cards instead of requiring duplicate final prose. Reports: /tmp/tl-card-source-model-fixed
and /tmp/tl-card-source-film-check. These simulated-tracker evaluations do not guarantee every
model response is accurate. Existing immutable presentations must be recreated to obtain
metadata with the corrected source binding.

Full regression suite: 1,285 passed, 102 skipped, one failure in the previously observed
Upload image callback race (`upload_view.py:_image_failed` accesses a deleted QLabel).
Ruff, formatting, mypy and both reviews passed. No Upload code was changed.

## Follow-up: distinct films instead of duplicate releases

`deduplicate_selection` is shared by Assistant and MCP. It freezes up to 100 candidates,
reads their native metadata, groups verified TMDb film IDs and saves a new exact selection.
The caller chooses first-ranked, smallest or most-seeded release, with stable ties.
The requested count applies after grouping. The receipt reports removed duplicates,
unknown identities and any shortfall. Cards, durable lists and approved actions consume
the returned selection ID, so displayed counts and queued membership agree.

Original lists stay unchanged. Unknown or malformed identities, other categories and TV
seasons/episodes remain separate. Titles and posters never establish identity. The original
Indexer binding is checked before lookup, and oversized inputs fail before any metadata
fetch. Immutable enrichment observations make retries stable. A list-revision parent marker
keeps list-derived results on the exact-subset action path.

Validation: 12 dedicated public MCP regressions passed, covering release choice, exact
totals, cards/list reuse, original-list preservation, bounded reads, metadata failures,
Indexer changes, malformed IDs, request conflicts and owner-approved queueing. The broader
focused run passed 47 checks before four malformed-ID cases were added. Local Qwen completed
the duplicate-film workflow in seven calls, chose the smaller release and saved/presented
two distinct films with matching totals. The film and music baseline workflows also passed;
the ebook run failed its existing no-duplicate-prose assertion. Reports are in
`/tmp/tl-content-dedup-model`.

Full suite: 1,293 passed, 103 skipped, one known Upload deleted-QLabel callback failure.
The final list-action and malformed-ID fixes were checked with the dedicated regressions
after the full run started. Ruff and mypy passed. No tracker downloads were started.
