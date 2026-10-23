# Develop and test

[Documentation](../../README.md) · [Français](../fr/developpement.md)

[Development](#development) · [Translations](#translations) · [Testing against real services](#testing-against-real-services)

## Development

Run the following commands from the repository root.

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

[Documentation](../../README.md) · [Français](../fr/developpement.md)
