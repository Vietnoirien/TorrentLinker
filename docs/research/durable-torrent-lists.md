# Durable torrent lists

## Requested behavior

Keep an exact torrent list across turns, context compaction, snapshot expiry and
application restarts. A user can choose ten films, refine that choice, append fifty
music torrents, refine only the film portion and later act on the saved list.
Models pass list/selection IDs instead of rebuilding hash arrays or doing totals
from chat prose. Lists belong to one agent connection (or Assistant conversation)
and one Torrent Client. Planning requires no queue/download permission or budget.

## Shared tools

- `create_torrent_list(request_id, client_id, name, selection_id="")` saves a named
  list from a completed catalogue/queue snapshot, or creates an empty list.
- `list_torrent_lists(client_id, offset, limit)` rediscovers owned list IDs, names,
  current revisions and full totals after context loss.
- `get_torrent_list(list_id, revision, offset, limit)` reads an immutable revision
  with bounded rows/provenance, full totals and current revision.
- `edit_torrent_list(request_id, list_id, expected_revision, action,
  selection_id="", subset={})` supports add/remove/keep/replace/replace_subset/clear.
  Add and replace require a source selection. Keep/remove accept either a source
  selection or an explicit filter. For example, keep with categories, size order
  and count five retains exactly the five smallest matching rows. Replace_subset
  requires a source and a filter; it replaces that part while preserving the rest.
  Missing arguments never silently clear a list. Clear is an explicit action.
  Irrelevant/ambiguous filters fail without changing a revision.
- `select_torrent_list(request_id, list_id, expected_revision, source, criteria,
  offset, count)` materializes an immutable transient selection for the existing
  compare/preview/enqueue/send tools. It returns `selection_id` directly, not a job.
- `compare_torrent_list_client(list_id, expected_revision, offset, limit)` compares
  the exact revision with a fresh read of that client's torrents. Groups distinguish
  actively seeding, completed paused/stopped, completed other, incomplete and absent.
  An active upload/seeding state does not prove bytes are currently transferring.
  Unknown states stay completed-other; unavailable clients produce an error.

Filters support category descendants, title/excluded terms, byte bounds, saved or
size/title/seeder order, direction and optional count. Equal sort keys retain saved
order. Count zero selects no rows. Unknown/nonpositive sizes stay unknown in totals;
known subtotal and unknown count remain available. Unidentified hashes are rejected
on import. Identical hashes deduplicate, preserving the first saved metadata/order
on add. New replacement rows appear at the first replaced position.

## Persistence, bounds and action safeguards

All writes require stable request IDs. Exact retries return their original receipt,
including its revision, even after later edits or source expiry. Reusing an ID for
another operation fails. Expected revisions prevent lost concurrent updates. Old
revisions and source provenance remain immutable and readable. Identical list names
are allowed; stable IDs distinguish them.

A list holds at most **10,000 rows**. An oversized edit fails atomically; it never
silently truncates. Read pages contain at most 100 rows. Action selections contain
at most 1,000 rows and report full-list totals separately from selected totals,
`has_more` and `next_offset`. Filters and explicit batches do not mutate the list.
Durable list contents do not expire; materialized selections still expire after
15 minutes. A later list edit cannot retarget an existing selection or approval.

Materialization checks current client access and exact identity/title/size/category.
Catalogue mode also checks the saved source where available; volatile seeders and
seen timestamps refresh explicitly while original list metadata/provenance remain
unchanged. Queue mode requires exactly one queued entry per identity and captures
its current key/destination. Ambiguous duplicates fail rather than widening a send.
Normal fresh destination checks, metadata validation, owner review, queue permission,
actual-send permission, budgets, disk checks and uncertain-send safeguards still
apply to subsequent actions. No list operation downloads, starts clients, deletes
files or reserves budget.

## Validation

Deterministic tests use the shared public MCP and owner approval boundaries, with
synthetic catalogue/queue data and simulated clients. They cover incremental mixed
lists, revision conflicts/concurrency, request retries/collisions, restart/expiry,
actor/client isolation, unknown sizes, explicit batches beyond 1,000, atomic storage
bounds, volatile/stable metadata, ambiguous queue identities and live-state groups.
Opt-in local-model tests exercise natural-language multi-turn workflows across eight
categories with all tracker access blocked and no actual downloads.

Working context carries fresh authoritative list IDs/revisions/counts/bytes, separate
from prior model prose. Large current/prior receipts retain structured IDs and
summary fields plus archive pointers; bulk rows are omitted instead of cutting JSON
mid-record. Newest complete prior receipts take priority within the context budget.
List-write revision summaries also survive compaction. A provider-request regression
covers a 1,000-item list with oversized row titles and incorrect prior model prose.
