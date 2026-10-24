# The app downloads, but never writes files it did not create

TorrentLinker began as a reseeder that never downloads (ADR-0002). With Zen Plans it also downloads new torrents chosen to earn Zen. The invariant becomes: the app never writes to a file it did not create. Plan torrents download into Download Folders set per Indexer category or subcategory (falling back to the category's folder, then a default; a category with none is left out of the Plan). A Download Folder may sit inside a Library Folder, since a new torrent only creates its own files, so downloads appear in the Library after the next Scan. Reseeds keep every rule of ADR-0002, and a Plan proposes Reseeds (0 Go to download) before any download.

## Explicit deletion in the torrent manager

At the user's request, the Torrents tab offers a separate “Delete torrent and files…” action. It requires confirmation for the selected torrents, lists their names and folders, and defaults to Cancel. The confirmation warns that files are deleted on the Torrent Client's machine and may be shared with other torrents. Deletion is delegated to the client's API; TorrentLinker does not recursively delete a Download Folder itself.

Ordinary removal, failed Reseed cleanup and Upload cleanup still keep files. Data deletion requires the explicit `delete_files=True` argument, used only by the torrent manager's delete action. Torrents undergoing Reseed Verification remain protected from both removal actions.
