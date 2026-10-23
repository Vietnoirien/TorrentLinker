# TorrentLinker

TorrentLinker finds files that are no longer seeded in qBittorrent, Deluge or Transmission, searches a Torznab Indexer such as c411, and reseeds matching torrents against the data already on disk. It also estimates your Zen earnings, plans which new torrents to download and seed, and prepares c411 uploads of what the tracker does not have yet. The interface is available in English and French.

## Download 0.5.1

| Platform | Download |
| --- | --- |
| Windows x64 | [TorrentLinker.exe](https://github.com/Vietnoirien/TorrentLinker/releases/download/v0.5.1/TorrentLinker.exe) |
| Linux x86_64 | [TorrentLinker-x86_64.AppImage](https://github.com/Vietnoirien/TorrentLinker/releases/download/v0.5.1/TorrentLinker-x86_64.AppImage) |

On Linux, make the AppImage executable before opening it. See the [release notes](https://github.com/Vietnoirien/TorrentLinker/releases/tag/v0.5.1) for changes and assets.

TorrentLinker checks GitHub for a newer stable release at startup and daily while running, reusing successful checks for 24 hours. A small, dismissible notice links to the release page when an update is available. Downloads and installation remain manual. The check uses your configured internet proxy, sends no account or torrent information, and stays silent when GitHub is unreachable.

## Finding your way around

The 0.5.0 interface adds **Search** alongside **Zen**, **Library**, **Upload** and **Settings**. Zen separates **Seeding**, **Plan** and **Catalogue**; Upload separates preparing an Upload from reviewing your **Drafts**. **Settings → General → Theme** offers System, Light and Dark. System follows the desktop preference, including GNOME's explicit dark-mode setting; a saved theme change applies immediately.

Click a results table's column header to sort, then click again to reverse it. Drag the divider between column headers to resize a column, or double-click it to fit its contents. Sizes, seeder counts and Zen estimates sort numerically. The Library and Seeding lists also have text filters. Library actions stay above the Library, with **Rescan everything** in the **Scan** menu. Use **Ctrl+1/2/3/4** to switch workspaces, **Ctrl+F** to focus Search or the Library filter, and **Ctrl+,** to open Settings.

## Search and download queue

In **Search**, enter a title and optionally choose a category from the expandable tree. Click an arrow to show subcategories, select a parent or child to filter, or choose **All categories** to clear the filter. Results come directly from your Indexer, with previous/next paging. Select one or more torrents, choose a Download Folder or leave it blank to use the category folders from Settings, then click **Add selected to queue**.

For c411, the category tree and available search options come from its native API. Select a category to see its multi-select filters. Films & Vidéos adds resolution, source, HDR, codec, audio, channels, language and profile; series also offer season and episode choices. Year, uploader, exclusivity and sorting apply across categories. **Clear filters** resets the selection. Changing categories clears incompatible filters. Other Indexers keep their Torznab search.

The revival selector offers available torrents, inclusion of **soins palliatifs**, or revival torrents only. Results identified by c411 as soins palliatifs carry a label; zero seeders alone does not establish that status. This is discovery support, not personal reward tracking. Previous/next paging keeps the submitted search criteria. If c411 exposes only part of a large result set, the app shows its accessible limit and asks you to narrow the filters.

Search results include sortable **≈ Zen/day** and **≈ Note** previews for c411, also shown in torrent details. Note is the estimated contribution score for your Class, category, swarm and seed age. New torrents use your Zen Profile, planned seed hours and current seeding count, starting at zero seed age and including you in the swarm. Already seeded torrents keep their current estimate and seed age. Hover over the estimate to see its assumptions. Revival payouts remain separate.

The **Age** column shows time since publication, such as **2 hours** or **3 days**, and refreshes every minute while Search is visible. Hover to see the exact local date and time, using c411's creation date or Torznab's publication date. Missing dates display as **–**. The header sorts the current page by the underlying timestamp; use **Newest** with ascending or descending order to sort the search across pages.

Select a result and click **Open on website**, or double-click it to open its description, images, NFO and file list in a torrent tab. **Open in tabs** opens all selected results. Details load only when opened; no `.torrent` is downloaded. The NFO is plain text, and images load through the configured proxy without Indexer credentials. Descriptions are centered, with explicit text alignment preserved. Images up to 32 MiB are decoded within a pixel limit and scaled for display. Failed images show compact links; **Retry images** retries them without reloading the torrent metadata and respects a host's rate-limit cooldown. Unsupported details and unavailable images can still be viewed on the website.

Each torrent tab also offers **Add to queue** and **Download now**, with an editable Download Folder. Download now sends only that torrent, leaving other queued items waiting. Both actions use the queue's duplicate and overwrite protections; a torrent already queued to a different folder must be removed before changing its destination.

Torrent tabs stay open while you run other searches. Opening the same torrent switches to its existing tab. Drag tabs to reorder them, use **Open tabs** to jump to one, or close them with the × button, middle-click, **Ctrl+W**, or the tab's right-click menu. **Ctrl+Tab** and **Ctrl+Shift+Tab** switch tabs; **Ctrl+F** returns to the search field. Closing a tab does not remove or stop a queued download.

On the main Search page, **Queue all tabs** adds the open torrent tabs and opens the queue without starting downloads. The **Download queue** button above the tabs stays accessible while browsing torrent details. **Download all tabs** queues and starts that set in one click, leaving unrelated queued torrents waiting. Each tab keeps its own Download Folder. All destinations are checked before queuing the batch; if one needs attention, that tab opens and an error appears above the tabs. Torrent tabs last for the current app session; the download queue persists across restarts.

Open **Download queue** and click **Start queue** to send the selected torrents to your torrent client in order. The queue respects the Indexer's download limits and waits when asked. **Pause** stops further sends after the current request; downloads already started continue in the torrent client. Queue entries and outcomes survive restarts, and the queue waits for Start after reopening. Failed entries can be retried; sent entries can be cleared without removing torrents from the client. Existing client torrents and files at the destination are protected against duplicate downloads or overwrites.

## Set up

1. Enable your torrent client's Web UI:
   - **qBittorrent**: **Tools → Options → Web UI**.
   - **Transmission** 4.x: turn on remote access in **Preferences → Remote**. Reseeds need **Append .part to incomplete files' names** off, or Transmission would rename your own files during a check: TorrentLinker offers to turn it off for you. Transmission renames file and folder names in place only, so a Match that needs other folders (a flattened folder, for example) cannot be Reseeded with it (see [ADR-0010](docs/adr/0010-transmission-with-whole-file-names-and-in-place-renames.md)).
   - **Deluge** 2.x: run its Web UI (`deluge-web`, port 8112 by default) connected to its daemon, and turn on the **Label** plugin in **Preferences → Plugins**. TorrentLinker labels the torrents it adds (`torrentlinker`, `torrentlinker-verifying`, `torrentlinker-partial`, `torrentlinker-zen`) to follow their Verification, as it tags them in qBittorrent.
2. Open TorrentLinker's **Settings → Connections**, choose your **Client** and enter its connection, then the Indexer URL/API key (and your Announce URL, for Uploads). qBittorrent takes a username/password or a Web UI API key where available; Deluge takes its Web UI address and password; Transmission its remote address, and a username and password if you set them.
3. Register Library Folders to find files you can Reseed.
4. Set Download Folders for the categories you want to plan, or choose a default folder. Categories without a resolved folder are excluded.
5. If your torrent client runs in Docker, on a NAS or on another computer, set its paths in **Settings → Client Paths** (see below).

## Your torrent client in Docker, on a NAS or on another computer

The client then sees your folders under other paths than this computer does. For example, a Docker container sees `/data`, while this computer reaches the same files as `/mnt/nas` or `Z:\`. TorrentLinker needs to know the correspondence to find the client's torrents in your folders, to Reseed, and to send a Plan's downloads where the client can write them.

In **Settings → Client Paths**:

1. Fill in the client connection and your Library or Download Folders first.
2. Click **Detect**. TorrentLinker reads a few torrents of each folder the client uses and looks for their files, by name and size, in your folders and the folders above them. It adds the paths that lead there, for example `/mnt/nas` ↔ `/data`, and says how many torrents each one found.
3. **Check** counts, for each path, the client's torrents whose folder exists on this computer. It also warns about Download Folders that the client probably cannot reach.
4. Save.

You can also add a path by hand with **Add folder…**: choose the folder on this computer, then type how the client sees it. One path covers everything below it, and the longest matching path wins. Typical cases:

| Setup | On this computer | In the client |
| --- | --- | --- |
| Docker on this computer, volume `-v /srv/media:/data` | `/srv/media` | `/data` |
| Client on a NAS, share mounted on Linux | `/mnt/nas/media` | `/volume1/media` |
| Client on a NAS, share mapped as a Windows drive | `Z:\` | `/volume1/media` |
| Docker on a NAS, share mounted here | `/mnt/nas/media` | `/data` |

Detection and checks only talk to your torrent client.

## Proxy

To reach the internet through a proxy, enter it in **Settings → Connections → Proxy**: `http://host:port`, `https://…`, `socks5://host:port`, or `socks5h://…` to resolve names through the proxy too, with a username and password if it needs them (the password stays in the system keyring). Every connection to c411, TMDb, the Zen Lab snapshot, images and the speed test then goes through it. Your torrent client is reached directly, as it usually runs on this computer or your network, unless you tick **Also for the torrent client**. **Test proxy** shows the address c411 sees. A new proxy applies as soon as you save.

## Reseed existing files

Scan the Library, then search the Orphans: Local Items that no c411 torrent in your torrent client covers. Files seeded only for other trackers are Orphans too, so you can cross-seed them on c411. A torrent counts as c411's by its tracker, by its infohash in the Catalogue (a torrent that has not announced yet may report none), or by TorrentLinker's tag; only these torrents' file lists are read. TorrentLinker compares each Candidate's file tree with the local files. Full Matches can be Reseeded without downloading their data. Partial Matches skip missing files and stay stopped after Verification.

Reseeds rename paths inside the torrent client, leaving local filenames and contents untouched. A hash check must pass before seeding starts. Verification failures remove the torrent from the client without deleting local files. Deluge resumes a stopped torrent while it checks it, so until a Reseed is started or its Verification ends TorrentLinker holds its download speed at 1 byte/s: nothing can be written into your files meanwhile (see [ADR-0009](docs/adr/0009-deluge-through-its-web-ui-with-labels-and-a-speed-guard.md)). Previous searches and rejections are remembered across restarts.

### Archives

A Local Item that is a .zip, .rar or .7z archive is also compared by what it holds, since torrents usually share the same files unpacked. A Candidate matching the archive's contents shows as **Full match inside the archive**. **Unpack and Reseed…** then unpacks it into a new folder next to the archive, after showing the size and the free space, and Reseeds the torrent against the unpacked files with the usual Verification. Nothing is overwritten. Once the client has verified every unpacked file and the torrent seeds, TorrentLinker offers to move the archive to the trash, or to keep it. Plans never unpack archives.

Zip archives need nothing more. Rar and 7z archives need [7-Zip](https://www.7-zip.org/) (or unrar for rar); without it they are compared as plain files.

## Upload 3D models as c411 Drafts

The **Upload** tab lists Orphans from every Library Folder that a search found no Match for: c411 may not have them yet. Each is made for one c411 **category**, picked in the form: the Library Folder's Content Kind proposes it (3D models → Imprimante 3D; movies and series, ebooks, music and games propose theirs), and an item of kind *Other* asks you to choose. **Imprimante 3D**, **Ebook**, **Audio**, **Films & Vidéos**, **GPS**, **Emulation**, **Applications** and **Jeux Vidéo** can be uploaded so far; the other categories show "not supported yet" until their rules are added. Changing the category redoes the checks, subcategory, name, NFO and description. Enter your **Announce URL** (from your c411 profile) in **Settings → Connections**, and use a main API key with the **Brouillons d'upload** (`drafts:rw`) scope.

Use the search bar above the Upload list to filter Local Items by filename. It works alongside the Content Kind and **Show all** filters.

Selecting an item also searches c411 for what it **already has** of it (the item's title words, within its category) and lists the releases found, with size, seeders and a link, in a collapsible **Already on c411** box; "Nothing found on c411" when there are none. It is information only: Team Pending refuses duplicates, and the app does not decide them. Each item is searched once per session, only when you select it, through the same key budget as every search.

For the chosen item, TorrentLinker checks c411's 3D rules: those a program can check (accepted formats, no archives) are red **Refusals** that stop the Draft, while those only you can judge (no files from independent creators who live off them, one coherent theme for a pack) are amber **Warnings** that leave the Draft available. It suggests a release name such as `Petit.Etau.De.Bureau.NOTAG.3MF` (dots between words, no accents, `NOTAG` when the source is unknown), makes a private torrent with c411's piece size and `source = C411` tag so its info-hash stays the same when published and an NFO listing every file, and saves them as a Draft on c411. The torrent then joins your torrent client against your own files, renamed inside the client as a Reseed is, so your files keep their names; it seeds once Verification passes. Below the subcategory, the **Options** c411 asks for in that subcategory (language, genre, format…) show as selectors: a list to tick for several values, a drop-down for one, required ones marked with an asterisk. TorrentLinker reads them from c411 the first time a subcategory needs them, keeps them for a week (**Refresh options** reads them again), and a category's rules can pre-fill them; what you choose wins. A required option left empty blocks the Draft, and Imprimante 3D has none. Open c411's upload page, load the Draft, add the image the rules ask for (see below), and publish it there. See [ADR-0011](docs/adr/0011-uploads-start-as-c411-drafts.md) and the [rules summary](docs/research/upload-rules.md).

### The image for the description

c411's image upload only accepts a logged-in browser, so TorrentLinker renders the model itself. The **3D view** page of the Upload tab shows the chosen item's model (STL, binary or ASCII; OBJ; 3MF) at an isometric angle, framed on its bounding box: drag to rotate, scroll to zoom, double-click or **Reset the view** to start over. A folder with several models offers each in a list. Big meshes are read off the interface thread and thinned for display only.

- **Capture** saves the current view as a PNG at least 1000 px wide.
- For a **Pack**, **Capture the Pack sheet** saves a grid of up to 9 models, each seen from the isometric angle with its file name below.
- **Open the folder** shows the images, which are in `uploads/<release name>/` (never in your Library). Add the one you choose on c411's upload page while reviewing the Draft; the description keeps an `[img]…[/img]` placeholder for it.

If you host the image elsewhere, paste its direct URL into **Image URL**. **Host image…** opens Postimages. The image is included in the Draft description even after you edit the text; changing the URL updates the image without resetting your presentation.

STEP, GCODE, BLEND, F3D, SLDPRT and FCStd items show no preview and say so: make that image yourself. Rendering needs OpenGL; without it the view and captures are unavailable and the message says why.

For **Ebook** (Livres, BDs, Comics, Manga, Presse, Audio, Partitions, Revues & Manuels), the subcategory defaults to BDs for CBR/CBZ or page-image folders, Audio for MP3/M4A/M4B/FLAC and Livres otherwise. Refusals: no file, archives (RAR/ZIP/7z), no accepted format (PDF, EPUB, MOBI, DjVu, CBR, CBZ, JPG/PNG, audiobooks). Warnings: French only, no duplicates, no more than two formats of a book, whole volumes in a BD/Comics/Manga pack (every volume for a BD). The name is `Titre.Auteur.FRENCH.EPUB-NOTAG` (title and author guessed from `Auteur - Titre`; the Source field is the team tag; a pack adds `[T01.a.T07]`; press is `Titre.Date.FRENCH.PDF-NOTAG`), and the file format and French language options are pre-filled. An audiobook under 64 kbps (read from its tags) is refused. Open c411's upload page, load the Draft, add the image the rules ask for, and publish it there. See [ADR-0011](docs/adr/0011-uploads-start-as-c411-drafts.md) and the [rules summary](docs/research/upload-rules.md).

For **Audio** (Karaoké, Musique, Podcast Radio, Samples), the subcategory defaults to Musique. TorrentLinker reads each file's tags (artist, album, year, titles, durations, codec, bitrate, sample rate, bit depth) with [mutagen](https://mutagen.readthedocs.io), off the GUI thread, when you select an item; the checks that need them appear a moment later. Refusals: no audio file, archives, formats c411 does not list (APE, Opus, AAC files…; FLAC, ALAC, WAV, WV, AIF, MP3, M4A, OGG, WMA and ISO are accepted), MP3 under 320 kbps constant bitrate (VBR accepted) and AAC under 256 (128 for podcasts and radio), a one-file album without a `.cue`, and formats or bitrates mixed in one album. Warnings: no transcodes, singles only from 20 minutes, discographies only for inactive artists, and for a CD-Rip (lossless 16 bit 44.1 kHz with a `.cue` or `.log`) what is missing among `cover.jpg` (500×500 or more), the `.cue` and the EAC `.log`, plus the catalogue number and Discogs or MusicBrainz link the description must give. The name is built from the tags and editable: music `Daft.Punk.Discovery.2001.FLAC.16bit.44.1kHz-NOTAG` (`CD-Rip` after the year for a CD-Rip, `MP3.320kbps` for a lossy one), podcast `Emission.2024.05.12.INTEGRALE.MP3.128kbps-NOTAG`, samples `Nom.2023.wav.1411kbps`. The NFO states artist, album, year, source, codec, bitrate or bit depth, sample rate, track count, size and the tracklist with durations; the format, source (CD) and type (Album or Discographie) options are pre-filled.

For **Films & Vidéos** (Animation, Animation Série, Concert, Documentaire, Série Documentaire, Émission TV, Film, Série TV, Spectacle, Sport, Vidéo-clips, Collection), the subcategory defaults to Film, or Série TV when the name has a season or episode. Each video is read with [MediaInfo](https://mediaarea.net/en/MediaInfo) (through `pymediainfo`, [ADR-0012](docs/adr/0012-mediainfo-through-pymediainfo.md)) off the GUI thread; where libmediainfo cannot be loaded, every video item is refused with a message to install it. With a TMDb key in Settings, the item is identified (an id in its name or `.nfo`, else a title search) and the release name carries TMDb's French title, the synopsis goes in the description, the Draft carries `tmdbData`, and the releases c411 already has are looked up by TMDb id. Refusals: archives, containers other than MKV, MP4, M4V, AVI, TS, M2TS or a disc (ISO, BDMV, VIDEO_TS), GPU encoders (NVENC, QSV, AMF), an encode under c411's minimum bitrate (not a WEB-DL or a remux), banned teams (Wawacity, kORE, RARBG…), no French audio and no full French subtitles, and a pack whose files differ in specs or team. Warnings: the French title, forbidden sources, WEB needing its VOD platform in the description, the MICKEY detag, missing episodes of a season, and the 28-slot duplicate rule (not computed: see the existing releases). The name follows c411's templates, from the file name and MediaInfo: `Le.Film.2020.VFF.1080p.BluRay.AC3.5.1.x264-TFA` (language, resolution, source, REMUX/BDMV/ISO, HDR, audio, video codec; `x264`/`x265` for encodes, `H264`/`H265` for a WEB-DL, `AVC`/`HEVC` for remuxes and discs; the team tag kept with its special characters dropped, `NOTAG` when none). The one video file of a folder is named exactly the release title inside the torrent. The NFO is MediaInfo's full text of each file (the first one only for a pack of more than ten), also sent as the Draft's `mediainfo`, and the language, quality, source and codec options are pre-filled where c411's values name them.

For **GPS** (Applications, Cartes, Divers) and **Emulation** (Émulateur, ROM/ISO), which no Content Kind proposes (pick the category in the form), the release name keeps spaces and accents where c411 allows them. GPS refuses an empty item, archives (RAR/ZIP/7z; install `.cab` and text files are fine) and downloader executables, warns that the version and activation must be stated and that alpha or early-access versions are banned, and suggests `Marque.Zone.Année.Support` (the support is the system its files run on). Emulation refuses archives unless the pack holds more than 50 files, a password-protected zip in such a pack (detected for zip only), a `.bin` without a `.cue` and a CloneCD image without its `.ccd`, `.img` and `.sub`; it warns about retro platforms only and about machines mixed in a pack (except MAME), and names a game `[SNES]Zelda [EU - MULTI] SFC` (console from the ROM extension, region and languages from the `(Europe) (Fr,En)` tags). Both have an NFO with the facts, a place for the install instructions in French, and every file listed.

For **Applications** (Autre, Formation, Linux, MacOS, Smartphone, Tablette, Windows), which no Content Kind proposes, the subcategory defaults from the files (`.exe`/`.msi` Windows, `.dmg`/`.pkg`/`.app` MacOS, `.deb`/`.rpm`/`.AppImage` Linux, `.apk`/`.ipa` Smartphone, else Autre) and the **release type** (keygen, crack, patch, installer or portable) is decided from the files and shown as a note you can override by editing the name. The decision table is TorrentLinker's own reading of c411's rules and is **not verified** against c411's wiki page (see [the rules summary](docs/research/upload-rules.md)). Refusals: archives (install `.cab` and text files are fine) and downloader executables. Warnings: the install note (not for a portable release), no alpha or early access, no IPTV software, an older version of the same generation is removed. The name is `Nom Version [OS Langue Type]` (`[OS] Nom Version Langue [EXT]` for a phone or tablet), and the NFO and description state the version, system, year, size, languages, activation and requirements, with a place for the install instructions in French.

For **Jeux Vidéo** (Autre, Linux, MacOS, Microsoft, Nintendo, Smartphone, Sony, Tablette, Windows, VR), proposed for the *game* kind, the subcategory defaults from the files (`.nsp`/`.xci` Nintendo, `.pkg` Sony, `.xex` Microsoft, `.apk` Smartphone, `.dmg` MacOS, `.AppImage` Linux, `.exe` Windows, VR when the name says so). For a PC game the **release type** (scene, repack, portable, GOG, DRM-free, preactivated) is decided from the files (crack files, `.iso`, `setup.exe` with `.bin` data, `steam_api`, GOG in the `.nfo`) and shown as a note; the decision table is TorrentLinker's own reading of c411's rules and is **not verified** against c411's wiki page ([rules summary](docs/research/upload-rules.md)). Refusals: archives (except console packs, one archive per game), downloader executables, and for a console, files outside its accepted containers. Warnings: one scene release plus one repack, one repacker release and one portable per scene release, one GOG version, one version per console game, the region (PAL/EU, NTSC/US, NTSC-J/JP, HK). Names keep spaces and accents: scene and repack names as they are, portable `Nom - 1.2 [Windows - FR - PORTABLE]`, GOG `Nom (4.04) [MULTI - Windows][GOG]`, VR prefixed `[VR]`, console `[Switch]Zelda [EU - FR] NSP` (PS4 and PS5 add `-CUSA…` or `-PPSA…`). A scene release's own `.nfo` is sent as the NFO (decoded from the DOS code page, so its bytes are not strictly unaltered); otherwise the NFO states the version, system, year, size, languages, region, crack or loader and requirements, with room for the install instructions in French. The language option is pre-filled from the name.

## Zen integration

The Zen tab brings together c411's reported balance and TorrentLinker's earnings estimates:

- Read your Zen Balance, Class, unlocked progression-tree bonus, and download eligibility from your c411 profile. The Indexer API key needs the `profile:read` scope for this, in addition to catalog/download access.
- Estimate Zen/day for each torrent currently seeding in your torrent client and for Matches found in the Library, using size, seeders, seed age, category, Class bonuses, and the configured seed hours per day.
- Compare Tanker, Swarm Keeper, and Reuploader. Reuploader estimates use the upload count entered in the Zen tab and are approximate.
- Set Class, unlocked tree bonus, seed hours per day, and an overall torrent cap in **Settings → Zen**. Values supplied by c411 fill the Class and tree bonus automatically when profile access is available.

Without profile permission, you can enter the Zen Profile by hand and use estimates and planning. The displayed balance comes from c411; projected earnings and payback are local estimates. The client's seed age is a lower bound when a torrent has been removed and added again.

### Browse seeding torrents by category

**Zen → Seeding** groups torrents under their Catalogue category and subcategory. Expand a branch to see its torrents, size and estimated Zen/day. Search matches both torrent names and category names. Sorting, resized columns, selection and collapsed branches survive refreshes. Torrents without a known category appear under **Unknown category**; broad snapshot categories stay at the parent level until confirmed.

Each Seeding refresh also synchronizes category tags in qBittorrent and labels in Transmission, for example `torrentlinker:category:Books / Comics`. It adds missing tags and replaces only older tags in that namespace, preserving personal tags, Verification tags, download folders and the client's native category. Unknown category names are left untagged. Deluge's single label is preserved because it carries Verification state; its torrents still appear in the category tree. The Seeding view reports tag updates and failures.

## Make a Zen Plan

Choose categories, then configure the Plan:

| Control | Effect |
| --- | --- |
| Optimize for **Zen/day** | Tries several greedy orderings and keeps the Plan with the largest estimated Zen gain. |
| Optimize for **Note** | Selects the highest-note torrents first for your Class. |
| Download limit | Maximum total download size in decimal GB. Zero means no additional size limit. |
| Limit torrents | Optional maximum number of torrents added by this Plan. |
| Low seeders only | Optional maximum current seeder count, initially 10, before you join the swarm. |
| Torrent size from … to | Optional minimum and maximum size of each torrent, in decimal GB. Zero leaves that side open. Applies to downloads and Reseeds. |

Reseeds come first. They count toward the torrent limit and consume no download budget. The overall torrent cap and disk-space reserve also apply. The results show each torrent's note, the size-weighted average note, estimated Zen gain and payback, and free disk space before and after the Plan. Download Folders sharing a physical disk are counted once. Plan options are saved across restarts.

A Plan leaves out every torrent already in your torrent client, whatever its tracker or state. It also leaves out Catalogue torrents that seem to be in your Library or in the Plan's Download Folders already, such as files kept after their torrent left the client: a Local Item, or one of its files, of the torrent's size (or up to 64 KiB smaller, for an .nfo or cover) whose name shares most of its significant words, with no other volume number. The Plan says how many it left out; hover over its summary to see them. No request is made for this, so only a search in the Library confirms a Match, which you can then Reseed instead of downloading.

Each Plan shows two estimated times. **Sending** to the client follows c411's limit on `.torrent` downloads: 30 a minute per API key, and about 280 in 20 minutes, so more keys send faster (1,000 torrents take about an hour with one key, 7 minutes with five). **Downloading** the data is the Plan's size divided by your download speed. **Test speed** measures that speed for about 8 seconds with Cloudflare's public speed test, anonymously, and remembers it. The download time is a lower bound: torrents with few seeders download slower than your connection. Run the test while your torrent client is idle.

Sending a Plan downloads each `.torrent` directly from c411 and adds it to its Download Folder. TorrentLinker refuses downloads that would overwrite existing files. Normal Reseeds still go through hash Verification.

A progress bar shows how many torrents have been sent, added, refused, or failed, with an estimate of the time left. **Stop sending** ends after the current torrent. If c411 refuses downloads (HTTP 429), sending waits and retries the same torrent, waiting longer each time up to 15 minutes, and shows the next try time.

The Plan and each torrent's result are saved as sending goes. After you stop sending, close the app, or after a crash, the Plan comes back with only the torrents left to send; failed ones are tried again. Click **Send to the torrent client** to continue. Making a new Plan or changing its options replaces the saved one. Reseeds are not saved, but sending always starts with them.

### Catalog updates and provisional estimates

The first Plan imports Zen Lab's public metadata snapshot anonymously. Your c411 API key and all `.torrent` requests go directly to c411.

c411 allows your account 1,200 searches and Catalogue requests an hour, whatever the key, and limits each key's `.torrent` downloads to 30 a minute. TorrentLinker keeps the two apart: searches go up to two a second while the hour's budget lasts, then slow down, even while a Plan is being sent; each key's downloads keep to 30 a minute and about 280 in 20 minutes. Your own searches, file checks and Reseeds always go before a Plan being sent or a Catalogue update. If c411 asks every key to wait more than half a minute, they stop at once and tell you when to try again, instead of hanging. You can add up to 4 more keys of the same c411 account in **Settings → Connections → More API keys**: each adds its own download allowance, and requests go to whichever is free soonest (see [ADR-0008](docs/adr/0008-several-c411-keys-each-within-its-own-limits.md)). See [the measurements](docs/research/rate-limits.md).

Planning and startup refresh c411 newest-first, stopping at the previous successful update's checkpoint, or an already known page on the first update. Historical scans and their saved page positions are reserved for the explicit Catalogue fetch action. Interrupted updates retain their checkpoint and check for new arrivals when resumed.

Plans use cached metadata and show provisional estimates. There are no per-torrent c411 metadata checks before planning or sending. The torrent client is read every 30 seconds to update Seeding estimates as tracker responses arrive. Its known swarm counts also update the local Catalogue for future Plans; unknown counts retain the cached estimate.

If another Catalogue refresh is running, the Plan waits for it and then refreshes its selected categories. A failed refresh stops Plan creation. You can stop fetching and make a Plan from the data already available.

The snapshot has coarse categories and unknown upstream age. Broad entries are excluded from narrower subcategory selections until the local Catalogue has a specific category from c411. Selecting the parent category allows the broader set. Seeder updates from the client preserve that category uncertainty. c411's paging limits and the snapshot do not establish complete tracker coverage, and the app reports known limits. Zen values remain estimates.

See [CONTEXT.md](CONTEXT.md) for the vocabulary and [docs/adr](docs/adr) for the design decisions.

## Where TorrentLinker keeps its data

| System | Folder |
| --- | --- |
| Linux | `~/.local/share/TorrentLinker/TorrentLinker/` |
| Windows | `%APPDATA%\TorrentLinker\TorrentLinker\` (`C:\Users\<you>\AppData\Roaming\TorrentLinker\TorrentLinker\`) |

It holds:

- `torrents/`: every `.torrent` downloaded from c411, so none is requested twice, even after a restart or when a saved Plan is sent again. Files are named after a fingerprint of their download address, without your key. Deleting the folder is harmless: the files are fetched again when needed.
- `uploads/`: the `.torrent` and `.nfo` of each Upload, as sent in its Draft, and a folder per Upload with the images captured for its description.
- `state.db`: the Catalogue, remembered searches, Rejections, Verifications in progress, the saved Plan, the Uploads made and c411's Category Options.
- `settings.json`: your settings. API keys and passwords are not in it: they stay in the system keyring.
- `torrentlinker.log`: the log, useful when reporting a problem.

Your torrent client keeps its own copy of every torrent added to it, in its own profile folder.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/torrentlinker
.venv/bin/pytest
```

Requires Python 3.11 or newer. Run the local checks with:

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q
```

## Translations

UI strings are English in the code; French lives in `src/torrentlinker/i18n/`. After changing UI text:

```bash
.venv/bin/pyside6-lupdate $(find src/torrentlinker -name "*.py") -ts src/torrentlinker/i18n/torrentlinker_fr.ts -no-obsolete
.venv/bin/pyside6-linguist src/torrentlinker/i18n/torrentlinker_fr.ts
.venv/bin/pyside6-lrelease src/torrentlinker/i18n/torrentlinker_fr.ts -qm src/torrentlinker/i18n/torrentlinker_fr.qm
```

## Testing against real services

Reseed against a real qBittorrent, using a throwaway localhost-only instance (never your own client):

```bash
python scripts/qbit_sandbox.py /tmp/qbt-sandbox
qbittorrent-nox --profile=/tmp/qbt-sandbox &
TL_QBIT_SANDBOX=http://127.0.0.1:18080 .venv/bin/pytest tests/test_qbit_integration.py
```

Reseed against a real Deluge in a throwaway Docker container that sees a temporary folder at the same path:

```bash
data=$(mktemp -d)
docker run -d --rm --name tl-deluge -p 127.0.0.1:18112:8112 -e PUID=$(id -u) -e PGID=$(id -g) -v "$data:$data" lscr.io/linuxserver/deluge:2.2.0
python scripts/deluge_sandbox.py http://127.0.0.1:18112
TL_DELUGE_SANDBOX=http://127.0.0.1:18112 TL_DELUGE_DATA="$data" .venv/bin/pytest tests/test_deluge_integration.py
docker stop tl-deluge
```

`tests/test_deluge_docker_paths.py` does the same with Deluge seeing the folder as `/data`, to test Path Mappings; its docstring has the commands.

Transmission works the same way, with `scripts/transmission_sandbox.py`, `tests/test_transmission_integration.py` and `tests/test_transmission_docker_paths.py`: their docstrings have the commands.

Search c411 for a real file (enter the API key in Settings → Connections first):

```bash
TL_LIVE=1 .venv/bin/pytest tests/test_live.py -s
```
