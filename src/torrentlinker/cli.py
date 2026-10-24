"""Choose desktop or server before importing optional UI dependencies."""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        del sys.argv[1]
        from torrentlinker.web.server import main as serve

        return serve()
    from torrentlinker.app import main as desktop

    return desktop()
