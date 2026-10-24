# Uploads start as c411 drafts, 3D models first

An Orphan that no Candidate matches may be something c411 does not have yet. The app can make it an Upload: create a new private torrent from the Local Item with the user's own announce URL, write its NFO, and send both to c411 with a title, a description and the category. The rules it follows are in docs/research/upload-rules.md.

c411's API can create a torrent outright (`POST /api/torrents`, scope `upload:write`) or save an upload draft (`/api/user/drafts`, scope `drafts:rw`, at most 15). The app saves drafts only: the user reviews and publishes each one on c411. A rejected upload counts against the user, and a new uploader may have only one upload waiting for Team Pending per category, so the user stays the one who publishes. Publishing directly can come later, once the drafts prove compliant. Draft access calls for a key with `drafts:rw`, which the user may keep apart from the search keys (ADR-0008).

Every category will be covered. 3D models come first: the user has some, their NFO is a file list (name, file count, total size, formats) that needs no MediaInfo, and their rules are the simplest. Video, which needs MediaInfo for its NFO and name, and audio, eBooks, games and applications follow, each with its own naming and checks.

The torrent's name follows c411's naming rules, even when the Local Item's own name does not. The files on disk are never renamed (ADR-0004): the torrent is added to the Torrent Client with its paths renamed onto the local files, as a Reseed does (ADR-0002, ADR-0010), and must pass Verification. c411 refuses an upload whose uploader is not seeding, so the torrent is seeding before the draft is published. The .torrent and .nfo the app creates are kept in the app's own data folder, never in a Library Folder.

The announce URL holds the user's passkey and is stored in the system keyring like the API keys.

Publication was checked on 2026-10-23 with a real 3D Upload. c411 adds `info.source = "C411"`; the original was already private. Including this source tag when creating the torrent reproduces the published info-hash exactly, so the torrent added before publication remains valid afterward. File names and piece hashes are unchanged. Announce URLs are outside the info dictionary and do not affect the info-hash. Previously generated torrents need c411's published copy, mapped to the original files inside the Torrent Client.

c411's own upload checks and image upload accept only a logged-in browser, not an API key. The app applies the rules itself. The user can add an image on c411 or provide an externally hosted image URL; the app includes that image in the Draft description while preserving edited text (docs/research/upload-rules.md).

## Local review queue, 0.10.0

Uploads can now be saved as Local Drafts before creating a c411 Draft. The Local Draft Queue persists the form, file sizes and modification times, category fields and review findings for one Torrent Client. Saving requires neither an announce URL nor a remote upload, and does not hash files or start seeding.

Desktop and web users can review, edit, remove or explicitly send a saved revision. Sending rechecks files and category requirements, creates the torrent and saves the c411 Draft. Editing increments the revision and invalidates older approvals. A changed local file requires saving and reviewing again. Sent records are retained; retrying the same completed revision does not send it twice. Failed or interrupted sends remain uncertain until the owner checks c411 and permits another attempt.

MCP and built-in Assistant upload creation now saves locally. The legacy agent `upload-draft` action maps to `upload-queue`. `upload-send` always requires owner approval, including for execute-enabled connections. Scheduled upload tasks stop at local review. Publication still belongs to the user on c411. The existing manual direct-to-c411 action remains available.
