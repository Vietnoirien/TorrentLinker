# Library and reseeding

## Folder explorer and Candidate review

Desktop and WebUI use the same Library layout: **Local Items**, **Folders**, and **Activity**. Choose a Library Folder in the left rail, filter the Local Items, then select an item to open its Candidate review below the table. **Expand review** gives the Candidates more room; **Back to Local Items** restores the table without losing the selected Candidate.

Review **Summary**, **Files**, **Description**, and **NFO** before acting. Files shows local counterparts, renamed paths and absent files. A Full Match compares file names and sizes; **Verify & reseed** still requires the Torrent Client's hash Verification. **Reject Candidate** remembers your decision for this Local Item. Searching, checking and rejecting never start a Reseed.

Use **Folders → Add folder** to register several folders and edit their Content Kind and scan grouping. Depth 1 treats each direct child as one Local Item. Removing a registration leaves files on disk. Settings opens the same folder editor. Download destinations and Path Mappings remain separate, per Torrent Client.

In the WebUI, Browse lists folders on the **TorrentLinker server**, within its configured storage roots. It cannot browse the computer running your browser. Registering a readable Library Folder does not require a Torrent Client mapping. If the client is unavailable, a scan can still list files with **Seeding status unknown**; they are not automatically classified as Orphans. The desktop also scans readable folders while the client is offline and labels their seeding status unknown. Unreadable paths retain their previous scanned items.

The WebUI now supports selected-item searches, remembered Candidate review, file comparison and rejection. **Activity** lists server jobs and allows cancelling active work. Archive extraction and µTorrent disk-rename approval still require the desktop application's individual review.

Settings also lists the selected client's default and category Download Folders. Choose a category to see its effective destination. Saving a destination verifies an existing Path Mapping against a seeded file and preserves the other category rules.

[Documentation](../../README.md) · [Français](../fr/bibliotheque.md)

1. Click **Add folder…** and choose its content kind and scan depth.
2. After scanning, search a selected Orphan or all Orphans.
3. Check the Candidates. A size match must still pass the torrent client’s hash Verification.
4. Reseed Full Matches. The summary separates new additions from torrents already in the client.

Screenshots use the English interface, dark theme and example data.

![Library and Reseed actions](../images/en/bibliotheque.png)

![Add a Library Folder](../images/en/ajouter-dossier.png)

## Add folders and use batch actions

The **≈ Zen/day** column shows the current estimate from Zen for torrents linked to Seeded or Partially Seeded Items. For Orphans, it shows the estimate for the best checked Match. Paused torrents contribute zero; unavailable estimates stay blank. If one torrent covers several Local Items, its estimate appears on each, so this column should not be summed as a library-wide total.

In the Library, **Add folder…** lets you choose a folder, its Content Kind and scan depth without opening Settings. Depth 1 treats each immediate file or folder as one Local Item. Saving scans the Library and selects the new folder in its filter; a folder already registered is not added twice.

In the Library, **Check all Candidates** checks every untested Candidate already found, including items hidden by filters, without repeating searches or successful checks. **Reseed all Full Matches** sends confirmed Full Matches through the usual hash Verification before seeding. Both actions run in the background with progress and **Cancel batch**; errors are collected so other Candidates can continue. Torrents already in the client are labelled and counted separately from new Reseeds.

If Full Matches are inside archives, a preflight lists their unpacked sizes. Choose **Unpack and reseed selected…** to review one archive’s destination and free space in the existing confirmation dialog, or **Reseed ready Matches** to process only files already on disk. Archives are never unpacked automatically by the batch.

## Reseed existing files

Scan the Library, then search the Orphans: Local Items that no c411 torrent in your torrent client covers. Files seeded only for other trackers are Orphans too, so you can cross-seed them on c411. A torrent counts as c411's by its tracker, by its infohash in the Catalogue (a torrent that has not announced yet may report none), or by TorrentLinker's tag; only these torrents' file lists are read. TorrentLinker compares each Candidate's file tree with the local files. Full Matches can be Reseeded without downloading their data. Partial Matches skip missing files and stay stopped after Verification.

Reseeds rename paths inside the torrent client, leaving local filenames and contents untouched. A hash check must pass before seeding starts. Verification failures remove the torrent from the client without deleting local files. Deluge resumes a stopped torrent while it checks it, so until a Reseed is started or its Verification ends TorrentLinker holds its download speed at 1 byte/s: nothing can be written into your files meanwhile (see [ADR-0009](../../adr/0009-deluge-through-its-web-ui-with-labels-and-a-speed-guard.md)). Previous searches and rejections are remembered across restarts.

### Archives

A Local Item that is a .zip, .rar or .7z archive is also compared by what it holds, since torrents usually share the same files unpacked. A Candidate matching the archive's contents shows as **Full match inside the archive**. **Unpack and Reseed…** then unpacks it into a new folder next to the archive, after showing the size and the free space, and Reseeds the torrent against the unpacked files with the usual Verification. Nothing is overwritten. Once the client has verified every unpacked file and the torrent seeds, TorrentLinker offers to move the archive to the trash, or to keep it. Plans never unpack archives.

Zip archives need nothing more. Rar and 7z archives need [7-Zip](https://www.7-zip.org/) (or unrar for rar); without it they are compared as plain files.

[Documentation](../../README.md) · [Français](../fr/bibliotheque.md)
