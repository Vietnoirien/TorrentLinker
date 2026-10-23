# Search and download

[Documentation](../../README.md) · [Français](../fr/recherche.md)

1. Enter a title, choose a category and adjust its filters.
2. Double-click a result to open its details in a tab.
3. Choose a download folder and add the torrent to the queue.
4. ### Start and manage the queue

![File de téléchargement](../images/file.png)

The queue also shows **≈ Zen/day** and **≈ Note** for each torrent. Click their headers to sort numerically. Estimates use the same calculation as search results and refresh when the Zen Profile or seeding torrents change. They remain available after restarting the app.

Open **Download queue** and start it. **Download now** sends only the selected torrent immediately.

Screenshots use the French interface, dark theme and example data.

![Recherche et filtres par catégorie](../images/recherche.png)

## Search and download queue

In **Search**, enter a title and optionally choose a category from the expandable tree. Click an arrow to show subcategories, select a parent or child to filter, or choose **All categories** to clear the filter. Results come directly from your Indexer, with previous/next paging. Select one or more torrents, choose a Download Folder or leave it blank to use the category folders from Settings, then click **Add selected to queue**.

### Category filters

For c411, the category tree and available search options come from its native API. Select a category to see its multi-select filters. Films & Vidéos adds resolution, source, HDR, codec, audio, channels, language and profile; series also offer season and episode choices. Year, uploader, exclusivity and sorting apply across categories. **Clear filters** resets the selection. Changing categories clears incompatible filters. Other Indexers keep their Torznab search.

### Soins palliatifs

The revival selector offers available torrents, inclusion of **soins palliatifs**, or revival torrents only. Results identified by c411 as soins palliatifs carry a label; zero seeders alone does not establish that status. This is discovery support, not personal reward tracking. Previous/next paging keeps the submitted search criteria. If c411 exposes only part of a large result set, the app shows its accessible limit and asks you to narrow the filters.

### Estimates and publication age

Search results include sortable **≈ Zen/day** and **≈ Note** previews for c411, also shown in torrent details. Note is the estimated contribution score for your Class, category, swarm and seed age. New torrents use your Zen Profile, planned seed hours and current seeding count, starting at zero seed age and including you in the swarm. Already seeded torrents keep their current estimate and seed age. Hover over the estimate to see its assumptions. Revival payouts remain separate.

The **Age** column shows time since publication, such as **2 hours** or **3 days**, and refreshes every minute while Search is visible. Hover to see the exact local date and time, using c411's creation date or Torznab's publication date. Missing dates display as **–**. The header sorts the current page by the underlying timestamp; use **Newest** with ascending or descending order to sort the search across pages.

### Torrent details

Select a result and click **Open on website**, or double-click it to open its description, images, NFO and file list in a torrent tab. **Open in tabs** opens all selected results. Details load only when opened; no `.torrent` is downloaded. The NFO is plain text, and images load through the configured proxy without Indexer credentials. Descriptions are centered, with explicit text alignment preserved. Images up to 32 MiB are decoded within a pixel limit and scaled for display. Failed images show compact links; **Retry images** retries them without reloading the torrent metadata and respects a host's rate-limit cooldown. Unsupported details and unavailable images can still be viewed on the website.

Each torrent tab also offers **Add to queue** and **Download now**, with an editable Download Folder. Download now sends only that torrent, leaving other queued items waiting. Both actions use the queue's duplicate and overwrite protections; a torrent already queued to a different folder must be removed before changing its destination.

### Manage tabs

Torrent tabs stay open while you run other searches. Opening the same torrent switches to its existing tab. Drag tabs to reorder them, use **Open tabs** to jump to one, or close them with the × button, middle-click, **Ctrl+W**, or the tab's right-click menu. **Ctrl+Tab** and **Ctrl+Shift+Tab** switch tabs; **Ctrl+F** returns to the search field. Closing a tab does not remove or stop a queued download.

On the main Search page, **Queue all tabs** adds the open torrent tabs and opens the queue without starting downloads. The **Download queue** button above the tabs stays accessible while browsing torrent details. **Download all tabs** queues and starts that set in one click, leaving unrelated queued torrents waiting. Each tab keeps its own Download Folder. All destinations are checked before queuing the batch; if one needs attention, that tab opens and an error appears above the tabs. Torrent tabs last for the current app session; the download queue persists across restarts.

Open **Download queue** and click **Start queue** to send the selected torrents to your torrent client in order. The queue respects the Indexer's download limits and waits when asked. **Pause** stops further sends after the current request; downloads already started continue in the torrent client. Queue entries and outcomes survive restarts, and the queue waits for Start after reopening. Failed entries can be retried; sent entries can be cleared without removing torrents from the client. Existing client torrents and files at the destination are protected against duplicate downloads or overwrites.

### Unavailable torrents

When c411 explicitly reports that a torrent is unavailable for download, TorrentLinker removes it from the local Catalogue and remembers its hash across restarts. Catalogue refreshes and snapshot imports cannot add it back, so future Plans stop proposing it. Authentication errors, rate limits and server errors do not remove torrents.

[Documentation](../../README.md) · [Français](../fr/recherche.md)
