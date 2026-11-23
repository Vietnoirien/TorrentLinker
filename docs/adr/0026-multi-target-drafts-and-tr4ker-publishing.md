# Multi-target Drafts, and tr4ker publishes directly

ADR-0011 has Uploads stop as c411 Drafts that the user publishes on c411. tr4ker has no draft API. Its frontend runs `POST /api/torrents/preflight`, which reports `hash_conflict` and `nfo_conflict`, then `POST /api/torrents` with a multipart form, which publishes at once (docs/research/tr4ker-integration.md). The Owner also wants one Upload sent to both Trackers without preparing it twice.

A Local Draft now carries a list of target Trackers. Each target has its own Upload Category, Category Options, title, NFO and Refusals, checked against that Tracker's rules. The files and their Inspection are shared. The Owner approves one revision together with its target list. Editing either target makes a new revision and voids the approval, as before.

Each target then has its own send state. c411 still gets a remote Draft that the Owner publishes there. tr4ker runs the preflight first. A conflict stops that target, and otherwise it publishes. A failure or uncertain send on one target never blocks, repeats or rolls back the other. An uncertain target needs the Owner to check that Tracker before it can be retried. Agents still need owner approval to send, and scheduled tasks still stop at review.

Each Tracker gets its own torrent. tr4ker's is private with `info.source = "TR4KER"` and the announce `https://tr4ker.net/announce/<passkey>`. c411's keeps `C411`. Both are added to the Torrent Client with paths renamed onto the same files, and both must pass Verification before publication. Files on disk are never renamed (ADR-0004). After a tr4ker publication the app downloads the personalised torrent that tr4ker returns. An Upload can name a tr4ker request it fills (`request_id`).

tr4ker's upload rules (docs/research/tr4ker-integration.md, wiki `regles-*`) contradict each other in places: the VirusTotal size threshold, watermarks, and the emulation region. The app shows these as Warnings and does not pick one as a Refusal.

## Considered Options

- **The app prepares the files and the Owner publishes by hand on tr4ker**: rejected; the Local Draft Queue already provides the review that the c411 Draft step gave.
- **One Tracker per Draft, with a copy action**: rejected; the Owner wants a single approval.
- **Approve each target separately**: rejected; the approval names its targets, and per-target send state handles partial failure.

## Consequences

This amends ADR-0011 for tr4ker only. Publishing directly on c411 stays deferred there. The Local Draft schema, its review views and the agent `upload-send` action become per-target. The tr4ker publish test is a human step on an item the Owner designates.
