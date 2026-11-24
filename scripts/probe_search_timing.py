"""Time what loading the Recherche page costs on c411, request by request. Run it yourself:

    .venv/bin/python scripts/probe_search_timing.py [query] [--config DIR]

It repeats the c411 half of a page load — the category tree, that root's filter options and
the first result page — through the app's own Indexer and rate limiter, and prints how long
each step took. It uses the API key saved in Settings (system keyring), or, with
`--config DIR`, the one in a web deployment's credential vault in that directory. It sends
only GETs and prints no key, URL or torrent name.

It cannot time the tr4ker half: those rows are read through the browser companion, which only
answers while the extension's command loop is awake. See the note it prints at the end.
"""

from __future__ import annotations

import sys
import time

from torrentlinker.credentials import get_secret
from torrentlinker.indexer import Indexer
from torrentlinker.torrent_search import native_search, parse_facets, parse_tree

URL = "https://c411.org/api/torznab"
FILMS = 1  # c411's native Films & Vidéos root, the one the panel opens on


def timed(label: str, call):
    start = time.monotonic()
    try:
        value = call()
    except Exception as error:  # noqa: BLE001 - a failed step is part of the measurement
        print(f"{label:28s} {time.monotonic() - start:6.2f} s  FAILED: {type(error).__name__}")
        raise
    print(f"{label:28s} {time.monotonic() - start:6.2f} s")
    return value


def stored_key(argv: list[str]) -> str:
    """The key Settings saved: the keyring, or a web deployment's vault with `--config DIR`."""
    if "--config" in argv:
        from pathlib import Path

        from torrentlinker.web.security import ServerSecrets

        return ServerSecrets(Path(argv[argv.index("--config") + 1])).get("indexer-api-key")
    return get_secret("indexer-api-key") or ""


def main() -> int:
    argv = sys.argv[1:]
    query = argv[0] if argv and not argv[0].startswith("--") else ""
    key = stored_key(argv).strip()
    if len(key) < 16:
        print(
            f"No usable c411 API key here (found {len(key)} characters). Save the key in "
            "Settings, or point this at the instance that holds it with "
            "--config <its configuration directory>."
        )
        return 1
    indexer = Indexer(URL, key)
    print(f"query {query!r} · root {FILMS} · one key\n")

    whole = time.monotonic()
    tree = timed("search_categories", lambda: parse_tree(indexer.search_categories()))
    timed("search_filter_options", lambda: parse_facets(indexer.search_filter_options(FILMS)))
    page = timed(
        "first result page",
        lambda: native_search(
            indexer,
            {"sortBy": "createdAt", "sortOrder": "desc", "name": query, "category": str(FILMS)},
            1,
        ),
    )
    print(f"\n{'c411 total':28s} {time.monotonic() - whole:6.2f} s")
    print(
        f"{len(tree.categories)} categories · {len(page.rows)} rows · "
        f"{len(page.root_counts)} root counts · {len(page.details)} listing details"
    )
    print(
        "\nThe rows, their listing facts and the per-category counts all come from that one "
        "result page.\nThe tr4ker half runs after this one, in the same job, and waits on the "
        "browser companion:\nits command loop stays awake for 10 s, then sleeps until the next "
        "alarm (30-60 s), and the\nread has a 60 s timeout. Nothing is painted until it returns."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
