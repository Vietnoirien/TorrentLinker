"""Build real .torrent files for tests."""

from pathlib import Path

import torf


def make_torrent(content: Path) -> bytes:
    t = torf.Torrent(path=content, trackers=["https://tracker.example/announce"], private=True)
    t.generate()
    return bytes(t.dump())
