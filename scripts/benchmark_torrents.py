"""Isolated Linux native Torrents baseline; no Torrent Client or Indexer is contacted.

Run one size per process for useful peak-RSS comparisons, for example:
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark_torrents.py --count 12000
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import tempfile
import time
from dataclasses import replace
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--tags", type=int, default=32)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    if min(args.count, args.tags, args.repeats) < 1:
        parser.error("count, tags and repeats must be positive")

    with tempfile.TemporaryDirectory(prefix="tl-torrents-benchmark-") as temporary:
        for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            os.environ[name] = str(Path(temporary) / name)
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QTimer, qVersion
        from PySide6.QtWidgets import QApplication

        from torrentlinker.domain import Torrent
        from torrentlinker.gui import tasks
        from torrentlinker.gui.torrents_view import TorrentsTab

        rows = [
            Torrent(
                f"{i:040x}",
                f"Fixture {i:06d} with a moderately long release name",
                Path("/benchmark/downloads"),
                tags=frozenset({f"tag-{i % args.tags:05d}", "benchmark"}),
                category=f"Category {i % 8}/Subcategory {i % 24}",
                trackers=(f"https://tracker-{i % 4}.example/announce",),
                state="uploading" if i % 4 else "downloading",
                progress=1.0 if i % 4 else 0.4,
                size=(i + 1) * 1024 * 1024,
                upload_rate=i % 1000,
            )
            for i in range(args.count)
        ]

        class Client:
            def torrents(self, **kwargs):
                return rows

            def file_listing(self, hash):
                return []

        app = QApplication([])
        app.setOrganizationName("TorrentLinkerBenchmark")
        app.setApplicationName("IsolatedTorrents")
        view = TorrentsTab(lambda: Client())
        view.resize(1280, 850)
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        ticks = []
        heartbeat.timeout.connect(lambda: ticks.append(time.perf_counter()))
        heartbeat.start()

        def wait_idle():
            deadline = time.perf_counter() + 60
            while view._loading or tasks._alive:
                app.processEvents()
                if time.perf_counter() > deadline:
                    raise TimeoutError("Refresh did not finish within 60 seconds")
                time.sleep(0.001)
            view.timer.stop()
            app.processEvents()
            # Deliver a heartbeat after the operation to include its final GUI stall.
            until = time.perf_counter() + 0.02
            while time.perf_counter() < until:
                app.processEvents()
                time.sleep(0.001)

        def measure(action):
            ticks.clear()
            start = time.perf_counter()
            ticks.append(start)
            action()
            wait_idle()
            return {
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                "max_heartbeat_gap_ms": round(
                    max((b - a for a, b in zip(ticks, ticks[1:], strict=False)), default=0) * 1000,
                    2,
                ),
            }

        try:
            measurements = {"first_display": measure(view.show)}
            assert view.model.rowCount() == args.count
            measurements["unchanged_refresh"] = [measure(view.refresh) for _ in range(args.repeats)]
            for i in range(args.repeats):
                rows = [
                    replace(row, upload_rate=row.upload_rate + 1, ratio=i + 1.5) for row in rows
                ]
                measurements.setdefault("changing_refresh", []).append(measure(view.refresh))
            selected = rows[-1].hash
            view._restore_selection({selected})
            measurements["selected_refresh"] = measure(view.refresh)
            assert {row.hash for row in view.selected()} == {selected}
            measurements["filter"] = measure(lambda: view.search.setText(f"{args.count - 1:06d}"))
            assert view.proxy.rowCount() == 1
            measurements["clear_filter"] = measure(view.search.clear)
            assert view.proxy.rowCount() == args.count
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                assert view.grab().save(str(args.screenshot))
            result = {
                "count": args.count,
                "distinct_tags": min(args.tags, args.count) + 1,
                "python": platform.python_version(),
                "qt": qVersion(),
                "qt_platform": app.platformName(),
                "platform": platform.platform(),
                "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
                "measurements": measurements,
                "limits": "Synthetic client; excludes real RPC and disk/network IO. "
                "Timings include a 20 ms heartbeat drain. No cancellation scenario is exercised.",
            }
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result))
        finally:
            heartbeat.stop()
            view.close()
            tasks.shutdown()
            app.processEvents()


if __name__ == "__main__":
    main()
