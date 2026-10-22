# Uploads start as c411 drafts, 3D models first

An Orphan that no Candidate matches may be something c411 does not have yet. The app can make it an Upload: create a new private torrent from the Local Item with the user's own announce URL, write its NFO, and send both to c411 with a title, a description and the category. The rules it follows are in docs/research/upload-rules.md.

c411's API can create a torrent outright (`POST /api/torrents`, scope `upload:write`) or save an upload draft (`/api/user/drafts`, scope `drafts:rw`, at most 15). The app saves drafts only: the user reviews and publishes each one on c411. A rejected upload counts against the user, and a new uploader may have only one upload waiting for Team Pending per category, so the user stays the one who publishes. Publishing directly can come later, once the drafts prove compliant. Draft access calls for a key with `drafts:rw`, which the user may keep apart from the search keys (ADR-0008).

Every category will be covered. 3D models come first: the user has some, their NFO is a file list (name, file count, total size, formats) that needs no MediaInfo, and their rules are the simplest. Video, which needs MediaInfo for its NFO and name, and audio, eBooks, games and applications follow, each with its own naming and checks.

The torrent's name follows c411's naming rules, even when the Local Item's own name does not. The files on disk are never renamed (ADR-0004): the torrent is added to the Torrent Client with its paths renamed onto the local files, as a Reseed does (ADR-0002, ADR-0010), and must pass Verification. c411 refuses an upload whose uploader is not seeding, so the torrent is seeding before the draft is published. The .torrent and .nfo the app creates are kept in the app's own data folder, never in a Library Folder.

The announce URL holds the user's passkey and is stored in the system keyring like the API keys.

Open: whether c411 changes the torrent when the draft is published (a source tag, its own announce URL), which would change its info hash and mean seeding c411's copy instead. c411's own upload checks and image upload accept only a logged-in browser, not an API key: the app applies the rules itself, and the user adds the description's image while reviewing the draft on c411 (docs/research/upload-rules.md).
