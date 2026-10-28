# Library evidence, provenance, compatible discovery and protected repair

Implementation baseline: `7ebce0c4bc6c581ccb6313c226b4568cefb7f0eb`.

The user approved the seven-step implementation plan on 28 October 2026 and requested implementation with the implement skill. Public Library APIs and visible desktop/WebUI workflows are the agreed test boundaries.

## Required behavior

- Share evidence rules and persisted results between desktop and WebUI. Show claims, measured observations, provenance and confidence. No automatic authorship accusation or team replacement.
- Compare filename, embedded title and matching sidecar NFO claims with MediaInfo. Account for cropped video, multiple audio tracks and missing data. HandBrake is only a processing clue. Surface warnings in upload preparation too.
- Import historical torrents offline, without adding them to a client or retaining announce secrets. Distinguish ambiguous, unverified, partial and verified associations. Invalidate saved evidence when source files change. Offer verified original release names explicitly during upload preparation. Do not physically rename media.
- Discover compatible torrents for already seeded items across series, season and episode scopes. Deduplicate, respect supported search parameters and bound requests. A smaller target must not be discarded by the source pack's total size. Clearly disclose bounded coverage.
- Combine selected Local Items into a relative manifest without copying data. Require a consistent mapping from their common parent; initially support qBittorrent. Verify every target file before seeding and do not download missing content.
- Provide a read-only near-match diagnostic using exact target piece hashes. Initial defaults use binary MiB: size difference <= min(1%, 50 MiB), >=90% verified target bytes, <=500 MiB missing and >=2 advertised seeders. Missing payload is not a network traffic cap. Metadata and availability claims remain uncertain; no automatic candidate-to-repair action.
- Experimental repair supports single-file v1 torrents and qBittorrent. It creates an independent copy in a new exclusive directory, adds the target stopped and rechecks. It requires a separate confirmation after completed client verification to download into that copy. Never modify originals, use hardlinks, overwrite destinations, auto-start after restart or replay uncertain sends.
- Include English/French wording, documentation, screenshots, focused checks, typechecking, the full test suite and separate Standards/Spec reviews. Commit only this work to the existing branch.

## Validation limits

The current authenticated C411 metadata contract and current member-only reupload rules were not available during the preceding research. Discovery therefore uses the existing Torznab adapter and does not depend on unverified by-tmdb technical attributes. Original names are optional suggestions; publication remains the user's existing draft review workflow.

Synthetic fixtures can validate hash arithmetic, file preservation and state transitions. They cannot establish the success rate of repair on real media libraries. The repair feature remains explicitly experimental. NAS-specific mapping and filesystem combinations require additional environment-specific validation; unsupported layouts must explain why they are refused.
