"""Probe how deep and how finely c411's Torznab feed can be read. Run it yourself:

    .venv/bin/python scripts/probe_c411.py [category]      # default 2030 (Film)

It uses the API key saved in TorrentLinker's Settings (system keyring), goes through
the app's rate limiter (one request every 4.1 s, about 2 minutes in all) and prints
only counts, sizes and dates: never the key, never a URL. Paste the output back.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from torrentlinker.credentials import get_secret
from torrentlinker.gui.settings_dialog import INDEXER_API_KEY
from torrentlinker.indexer import TORZNAB_NS, Indexer

URL = "https://c411.org/api/torznab"
GB = 1_000_000_000


def items(xml: str) -> list[tuple[str, int, str]]:
    """(infohash, size, pubDate) of each result."""
    found = []
    for item in ET.fromstring(xml).iter("item"):
        attrs = {a.get("name"): a.get("value") for a in item.iter(f"{TORZNAB_NS}attr")}
        size = int(item.findtext("size") or attrs.get("size") or 0)
        found.append((str(attrs.get("infohash", "")), size, item.findtext("pubDate") or ""))
    return found


def describe(rows: list[tuple[str, int, str]]) -> str:
    if not rows:
        return "0 results"
    sizes = [s for _, s, _ in rows]
    dates = sorted(parsedate_to_datetime(d) for _, _, d in rows if d)
    span = f"{dates[0]:%Y-%m-%d}..{dates[-1]:%Y-%m-%d}" if dates else "no dates"
    return (
        f"{len(rows):3d} results, size {min(sizes) / GB:.2f}-{max(sizes) / GB:.2f} GB, {span}, "
        f"first {rows[0][0][:8]}"
    )


def main() -> int:
    category = sys.argv[1] if len(sys.argv) > 1 else "2030"
    key = get_secret(INDEXER_API_KEY)
    if not key:
        print("No Indexer API key in Settings.")
        return 1
    indexer = Indexer(URL, key)

    def get(label: str, **params: str) -> list[tuple[str, int, str]]:
        query = {"t": "search", "cat": category, "limit": "100", "extended": "1", **params}
        try:
            rows = items(indexer._get(query))
        except Exception as e:  # noqa: BLE001 - reported, the probe goes on
            print(f"{label:38s} ERROR {type(e).__name__}: {str(e).replace(key, '***')[:120]}")
            return []
        print(f"{label:38s} {describe(rows)}")
        return rows

    print(f"== category {category}")
    print("-- 1. how deep does offset go?")
    seen: set[str] = set()
    for offset in ("0", "100", "500", "600", "700", "1000", "5000"):
        rows = get(f"offset={offset}", offset=offset)
        new = {h for h, _, _ in rows} - seen
        seen |= new
        print(f"{'':38s} new vs earlier pages: {len(new)}")

    print("-- 2. are size filters honoured? (minsize/maxsize in bytes)")
    get("maxsize=1 GB", maxsize=str(GB))
    get("minsize=20 GB", minsize=str(20 * GB))
    get("minsize=2 GB maxsize=3 GB", minsize=str(2 * GB), maxsize=str(3 * GB))

    print("-- 3. is an age filter honoured? (maxage in days)")
    get("maxage=7", maxage="7")
    get("maxage=365", maxage="365")

    print("-- 4. does a query word open another window?")
    get("q=2015", q="2015")
    get("q=2015 offset=600", q="2015", offset="600")

    print("-- 5. sort hints (ignored by most Torznab servers)")
    get("sort=size", sort="size")
    get("order=asc", order="asc")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
