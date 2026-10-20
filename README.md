# TorrentLinker

Desktop app that finds which of your files are no longer seeded in qBittorrent, looks them up on a Torznab tracker (c411 first), and reseeds the matching torrents against the data you already have — without moving or renaming your files.

See [CONTEXT.md](CONTEXT.md) for the vocabulary and [docs/adr](docs/adr) for the key decisions.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/torrentlinker
.venv/bin/pytest
```

qBittorrent's Web UI must be enabled (Tools → Options → Web UI).
