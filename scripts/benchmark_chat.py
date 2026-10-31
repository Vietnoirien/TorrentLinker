"""Isolated native chat-history rendering timings, without a model or saved chats."""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import tempfile
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.count <= 100:
        parser.error("count must be between 1 and the current history limit of 100 runs")
    with tempfile.TemporaryDirectory(prefix="tl-chat-benchmark-") as temporary:
        for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
            os.environ[name] = str(Path(temporary) / name)
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QCoreApplication, QEvent, QTimer, qVersion
        from PySide6.QtWidgets import QApplication

        from torrentlinker.gui.chat_transcript import ChatTranscript, MessageText

        app = QApplication([])
        app.setOrganizationName("TorrentLinkerBenchmark")
        app.setApplicationName("IsolatedChat")
        view = ChatTranscript()
        view.resize(1100, 850)
        view.show()
        rows = [
            {
                "id": f"fixture-{i}",
                "status": "finished",
                "calls": 1,
                "tokens": 500,
                "error": "",
                "messages": [
                    {"role": "user", "content": f"Fixture question {i}: explain these results."},
                    {
                        "role": "assistant",
                        "content": f"Fixture response {i}.\n\n"
                        + "The catalogue contains these synthetic results. " * 12
                        + "\n\n- First item\n- Second item\n\nNo download was requested.",
                    },
                ],
                "events": [
                    {
                        "tool": "search",
                        "status": "finished",
                        "after_message_index": 0,
                        "arguments": {"query": "fixture"},
                        "result": {"count": 2},
                    }
                ],
            }
            for i in range(args.count)
        ]
        ticks = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
        timer.start()

        def measure(action):
            ticks.clear()
            start = time.perf_counter()
            ticks.append(start)
            action()
            until = time.perf_counter() + 0.02
            while time.perf_counter() < until:
                app.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                time.sleep(0.001)
            return {
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                "max_heartbeat_gap_ms": round(
                    max((b - a for a, b in zip(ticks, ticks[1:], strict=False)), default=0) * 1000,
                    2,
                ),
            }

        try:
            measurements = {"first_render": measure(lambda: view.set_runs(rows, str))}
            for i in range(3):
                rows[0]["messages"][-1]["content"] += f"\n\nAdditional response {i}."
                measurements.setdefault("one_run_changed", []).append(
                    measure(lambda: view.set_runs(rows, str))
                )
                assert len(view.findChildren(MessageText)) == 2 * args.count
                assert f"Additional response {i}." in view.toPlainText()
            result = {
                "runs": args.count,
                "messages": 2 * args.count,
                "python": platform.python_version(),
                "qt": qVersion(),
                "qt_platform": app.platformName(),
                "measurements": measurements,
                "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            }
            text = json.dumps(result, indent=2)
            if args.output:
                args.output.write_text(text + "\n", encoding="utf-8")
            print(text)
        finally:
            timer.stop()
            view.close()


if __name__ == "__main__":
    main()
