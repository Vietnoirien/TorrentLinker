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

Search c411 for a real file (enter the API key in Settings → Connections first):

```bash
TL_LIVE=1 .venv/bin/pytest tests/test_live.py -s
```
