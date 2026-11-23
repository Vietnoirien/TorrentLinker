"""Add the owner's genre subscriptions (review only) to a configuration directory.

Usage: .venv/bin/python scripts/add_rss_subscriptions.py CONFIG_DIR

Goes through the app's own feed workspace (preview, then save), never the HTTP API. A
subscription of the same name and Tracker is skipped, so a second run adds nothing. Stop the
app that uses CONFIG_DIR first. Each preview reads its source once: c411's Indexer or
tr4ker's passkey feed, as saving in the editor does.
"""

from __future__ import annotations

import argparse
import sys
from ipaddress import ip_network
from pathlib import Path

from torrentlinker.feed_workspace import FeedWorkspace

HORROR, SCIENCE_FICTION = "27", "878"  # TMDb genre ids
GIB = 1024**3
UHD_FILMS = 2045  # Torznab "Movies/UHD", when the Indexer's own list names none


def genre_subscription(name: str, tracker: str, genre: str, uhd: int) -> dict:
    video = [uhd] if tracker == "c411" else [2000, 2040, 2045]
    return {
        "name": name,
        "tracker": tracker,
        "mode": "review_only",
        **({"categories": [uhd]} if tracker == "c411" else {"feed_category": "films-film"}),
        "preferences": {
            "min_size": 4 * GIB,
            "max_size": 8 * GIB,
            "required": {"quality": ["2160p"], "genre": [genre]},
            "category_scopes": {"quality": video, "genre": video},
        },
    }


def subscriptions(uhd: int = UHD_FILMS) -> list[dict]:
    return [
        genre_subscription("Horreur 4K", "c411", HORROR, uhd),
        genre_subscription("Horreur 4K", "tr4ker", HORROR, uhd),
        genre_subscription("Science-fiction 4K", "c411", SCIENCE_FICTION, uhd),
        genre_subscription("Science-fiction 4K", "tr4ker", SCIENCE_FICTION, uhd),
        {"name": "tr4ker freeleech", "tracker": "tr4ker", "mode": "review_only", "freeleech": True},
    ]


def add(directory: Path) -> tuple[list[str], list[str]]:
    """Add what is missing; returns the names added and the names skipped."""
    from torrentlinker.web.app import create_app

    # The app is built, not served: no loop starts and nothing listens.
    app = create_app(directory, password=None, trusted_proxies=(ip_network("127.0.0.1/32"),))
    control = app.state.agent_service.feed_control
    workspace = FeedWorkspace(control)
    categories = control.service.setup.settings.indexer_categories
    uhd = next(
        (
            identifier
            for identifier, category in categories.items()
            if category.parent == 2000 and any(w in category.name.upper() for w in ("UHD", "4K"))
        ),
        UHD_FILMS,
    )
    existing = {(row["name"], row["tracker"]) for row in workspace.request("feeds")}
    added, skipped = [], []
    for definition in subscriptions(uhd):
        label = f"{definition['name']} ({definition['tracker']})"
        if (definition["name"], definition["tracker"]) in existing:
            skipped.append(label)
            continue
        workspace.request("feeds/preview", definition, "POST")
        workspace.request("feeds", {"subscription": definition}, "POST")
        added.append(label)
    return added, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path, help="the configuration directory")
    args = parser.parse_args()
    if not args.directory.is_dir():
        sys.exit(f"No configuration directory at {args.directory}")
    added, skipped = add(args.directory)
    print("Added: " + (", ".join(added) or "none"))
    print("Skipped (already there): " + (", ".join(skipped) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
