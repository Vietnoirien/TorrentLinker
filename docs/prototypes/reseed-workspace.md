# Reseed workspace preview

Question: how should desktop and Web UI expose the same guided Reseed workflow while keeping original file names and paths unchanged?

This is a standalone HTML design prototype, including an HTML representation of the desktop window. It is not a PySide implementation or an operational symlink feature. No backend, filesystem, torrent-client or indexer calls are made. All titles and actions are demonstration data. Reloading resets the session; changing layout or interface preserves it.

## Open it

Double-click `src/torrentlinker/web/static/reseed-prototype.html`, or serve this branch:

```sh
python3 -m http.server 18768 --bind 127.0.0.1 --directory src/torrentlinker/web/static
```

Open `http://127.0.0.1:18768/reseed-prototype.html?variant=A&mode=web`.

- A, Columns: closest to the supplied reference, with selection per stage and batch actions.
- B, Guided: a stage list, Local Items and an adjacent file-path review.
- C, Table: denser review of larger libraries with explicit status and next action.

Use the bottom switcher or Left/Right keys. Inputs, selects and dialogs retain their own key handling. `mode=desktop` shows the application frame; `mode=web` shows the browser frame. The workflow, statuses, selection and dialogs are shared deliberately. Surrounding navigation is contextual decoration.

## Try the workflow

Open “Un été ailleurs”, prepare its links, confirm that they remain during seeding, verify the content, then start sharing. Counts and stages update after each action. Select several Local Items to review links as a batch. Use the scenario selector for an inaccessible target or an incorrect hash. Failed verification returns the item for candidate review; inaccessible targets remain blocked in preparation.

Incomplete Matches are an exception branch. Their review shows the missing file and explains a separate decision for partial seeding or a Repair Copy. That decision is intentionally not implemented in this preview. A search with no retained Candidate is called “À retrouver”, not “absent from the site”.

## Proposed behavior for implementation

- Use a dedicated link tree per torrent, with its expected names and links targeting the unchanged Local Item files. Keep the links for as long as the torrent seeds.
- Preflight both the link directory and every target as seen by the Torrent Client. A successful local filesystem check does not establish access from a NAS, container or remote client.
- Refuse destination conflicts, including dangling links; do not overwrite existing paths. Keep an ownership record for created directories and links, and recover interrupted preparation.
- Add stopped, check the actual pieces, and only seed fully verified content. Removing a failed torrent must preserve original files. Validate the cleanup behavior of each adapter before enabling it.
- A symlink does not prevent writes to its target. Download suppression and existing-file protection still need verification with each supported client. Missing pieces must never be repaired through a link to an original; an explicitly approved Repair Copy is independent.
- Moving an original invalidates its links. Surface this failure and provide a recheck/relink path. Define safe cleanup of app-owned links after torrent removal.
- Preserve existing candidate rejection, archive review and partial-match protections. Reconcile these with the new flow rather than treating compatible sizes as verified content.
- Check Windows link privileges, Unicode paths and client-specific behavior before advertising support. No compatibility claim follows from this HTML prototype.

The proposal reopens ADR-0002, which intentionally avoided links, and the disk-rename exceptions in ADR-0013 and ADR-0017. Those decisions remain unchanged in production until a design is selected and the replacement is implemented and tested.

## Preview checks

Manually exercised in the browser: prepare → verify → seed, retained links after sharing, inaccessible target, failed hash, batch preparation, layout switching and desktop/Web UI switching. Inspected the Web UI at phone width and corrected page overflow. All checks use simulated operations; no real links or torrent changes were made.

No variant has been selected yet. Keep this prototype on `prototype/reseed-workspace` until review.
