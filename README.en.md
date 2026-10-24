# TorrentLinker

[Français](README.md) · English · [Documentation](docs/README.md)

Find torrents matching your existing files and reseed them in **qBittorrent, Deluge or Transmission**, with experimental support for **µTorrent Classic**. TorrentLinker searches a Torznab Indexer such as **c411**, then asks your torrent client to verify the files before seeding.

![TorrentLinker: Zen estimates, categories and torrent notes](docs/guide/images/en/zen.png)

*English interface, dark theme, example data.*

## What you can do

- **Library**: find files no longer seeded, search and check Candidates, then reseed matching torrents.
- **Search**: filter torrents, explore details in tabs and prepare a download queue.
- **Zen**: track estimated earnings and notes, then make a Plan within your space and budget.
- **Torrents**: manage downloads and seeding, grouped by tracker and category.
- **Upload**: prepare files, a description and NFO for a c411 Draft that you review and publish on the website.

With qBittorrent, Deluge and Transmission, reseeding does not rename existing files on disk. µTorrent Classic may require disk renames, with explicit confirmation. API keys and passwords stay in your system keyring. The interface supports French and English, with system, light and dark themes.

## Download 0.6.0

| Platform | Download |
| --- | --- |
| Windows x64 | [TorrentLinker.exe](https://github.com/Vietnoirien/TorrentLinker/releases/download/v0.6.0/TorrentLinker.exe) |
| Linux x86_64 | [TorrentLinker-x86_64.AppImage](https://github.com/Vietnoirien/TorrentLinker/releases/download/v0.6.0/TorrentLinker-x86_64.AppImage) |

On Linux, make the AppImage executable before opening it. See the [release notes](https://github.com/Vietnoirien/TorrentLinker/releases/tag/v0.6.0) for changes.

## Get started

1. Enable your torrent client’s Web UI.
2. Open TorrentLinker and enter the client connection and Indexer API key in Settings. The first launch guides you there.
3. Use **Library → Add folder…** for existing files. Use **Search** or **Zen → Plan** for new downloads.

The [illustrated setup guide](docs/guide/en/getting-started.md) covers connections, Docker and NAS setups.

## Guides and help

[Torrents and client folders](docs/guide/en/torrents.md) · [Library](docs/guide/en/library.md) · [Search and downloads](docs/guide/en/search.md) · [Zen and Plans](docs/guide/en/zen.md) · [Uploads](docs/guide/en/upload.md)

[All documentation](docs/README.md) · [Troubleshooting](docs/guide/en/data.md) · [Report an issue](https://github.com/Vietnoirien/TorrentLinker/issues) · [Contribute](docs/guide/en/development.md)
