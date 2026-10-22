# TorrentLinker

TorrentLinker finds files that are no longer seeded in qBittorrent or Deluge, searches a Torznab Indexer such as c411, and reseeds matching torrents against the data already on disk. It also estimates your Zen earnings and plans which new torrents to download and seed. The interface is available in English and French.

## Download 0.2.9

| Platform | Download |
| --- | --- |
| Windows x64 | [TorrentLinker.exe](https://github.com/Vietnoirien/TorrentLinker/releases/download/v0.2.9/TorrentLinker.exe) |
| Linux x86_64 | [TorrentLinker-x86_64.AppImage](https://github.com/Vietnoirien/TorrentLinker/releases/download/v0.2.9/TorrentLinker-x86_64.AppImage) |

On Linux, make the AppImage executable before opening it. See the [release notes](https://github.com/Vietnoirien/TorrentLinker/releases/tag/v0.2.9) for changes and assets.

## Set up

1. Enable your torrent client's Web UI:
   - **qBittorrent**: **Tools → Options → Web UI**.
   - **Deluge** 2.x: run its Web UI (`deluge-web`, port 8112 by default) connected to its daemon, and turn on the **Label** plugin in **Preferences → Plugins**. TorrentLinker labels the torrents it adds (`torrentlinker`, `torrentlinker-verifying`, `torrentlinker-partial`, `torrentlinker-zen`) to follow their Verification, as it tags them in qBittorrent.
2. Open TorrentLinker's **Settings → Connections**, choose your **Client** and enter its connection, then the Indexer URL/API key. qBittorrent takes a username/password or a Web UI API key where available; Deluge takes its Web UI address and password.
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

## Reseed existing files

Scan the Library, then search the Orphans: Local Items that no c411 torrent in your torrent client covers. Files seeded only for other trackers are Orphans too, so you can cross-seed them on c411. A torrent counts as c411's by its tracker, by its infohash in the Catalogue (a torrent that has not announced yet may report none), or by TorrentLinker's tag; only these torrents' file lists are read. TorrentLinker compares each Candidate's file tree with the local files. Full Matches can be Reseeded without downloading their data. Partial Matches skip missing files and stay stopped after Verification.

Reseeds rename paths inside the torrent client, leaving local filenames and contents untouched. A hash check must pass before seeding starts. Verification failures remove the torrent from the client without deleting local files. Deluge resumes a stopped torrent while it checks it, so until a Reseed is started or its Verification ends TorrentLinker holds its download speed at 1 byte/s: nothing can be written into your files meanwhile (see [ADR-0009](docs/adr/0009-deluge-through-its-web-ui-with-labels-and-a-speed-guard.md)). Previous searches and rejections are remembered across restarts.

### Archives

A Local Item that is a .zip, .rar or .7z archive is also compared by what it holds, since torrents usually share the same files unpacked. A Candidate matching the archive's contents shows as **Full match inside the archive**. **Unpack and Reseed…** then unpacks it into a new folder next to the archive, after showing the size and the free space, and Reseeds the torrent against the unpacked files with the usual Verification. Nothing is overwritten. Once the client has verified every unpacked file and the torrent seeds, TorrentLinker offers to move the archive to the trash, or to keep it. Plans never unpack archives.

Zip archives need nothing more. Rar and 7z archives need [7-Zip](https://www.7-zip.org/) (or unrar for rar); without it they are compared as plain files.

## Zen integration

The Zen tab brings together c411's reported balance and TorrentLinker's earnings estimates:

- Read your Zen Balance, Class, unlocked progression-tree bonus, and download eligibility from your c411 profile. The Indexer API key needs the `profile:read` scope for this, in addition to catalog/download access.
- Estimate Zen/day for each torrent currently seeding in your torrent client and for Matches found in the Library, using size, seeders, seed age, category, Class bonuses, and the configured seed hours per day.
- Compare Tanker, Swarm Keeper, and Reuploader. Reuploader estimates use the upload count entered in the Zen tab and are approximate.
- Set Class, unlocked tree bonus, seed hours per day, and an overall torrent cap in **Settings → Zen**. Values supplied by c411 fill the Class and tree bonus automatically when profile access is available.

Without profile permission, you can enter the Zen Profile by hand and use estimates and planning. The displayed balance comes from c411; projected earnings and payback are local estimates. The client's seed age is a lower bound when a torrent has been removed and added again.

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

Each Plan shows two estimated times. **Sending** to the client takes about 4 seconds per torrent, the pace c411 allows for `.torrent` downloads. **Downloading** the data is the Plan's size divided by your download speed. **Test speed** measures that speed for about 8 seconds with Cloudflare's public speed test, anonymously, and remembers it. The download time is a lower bound: torrents with few seeders download slower than your connection. Run the test while your torrent client is idle.

Sending a Plan downloads each `.torrent` directly from c411 and adds it to its Download Folder. TorrentLinker refuses downloads that would overwrite existing files. Normal Reseeds still go through hash Verification.

A progress bar shows how many torrents have been sent, added, refused, or failed, with an estimate of the time left. **Stop sending** ends after the current torrent. If c411 refuses downloads (HTTP 429), sending waits and retries the same torrent, waiting longer each time up to 15 minutes, and shows the next try time.

The Plan and each torrent's result are saved as sending goes. After you stop sending, close the app, or after a crash, the Plan comes back with only the torrents left to send; failed ones are tried again. Click **Send to the torrent client** to continue. Making a new Plan or changing its options replaces the saved one. Reseeds are not saved, but sending always starts with them.

### Catalog updates and provisional estimates

The first Plan imports Zen Lab's public metadata snapshot anonymously. Your c411 API key and all `.torrent` requests go directly to c411.

c411 limits each API key to 1,200 searches and Catalogue requests an hour, and limits `.torrent` downloads separately. TorrentLinker keeps the two apart: searches go up to two a second while the hour's budget lasts, then slow down, even while a Plan is being sent; downloads keep their own pace of one every 4 seconds. Your own searches, file checks and Reseeds always go before a Plan being sent or a Catalogue update. If c411 asks every key to wait more than half a minute, they stop at once and tell you when to try again, instead of hanging. You can add up to 4 more keys of the same c411 account in **Settings → Connections → More API keys**: each keeps within its own limits, and requests go to whichever is free soonest (see [ADR-0008](docs/adr/0008-several-c411-keys-each-within-its-own-limits.md)). See [the measurements](docs/research/rate-limits.md).

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
- `state.db`: the Catalogue, remembered searches, Rejections, Verifications in progress and the saved Plan.
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

Search c411 for a real file (enter the API key in Settings → Connections first):

```bash
TL_LIVE=1 .venv/bin/pytest tests/test_live.py -s
```
