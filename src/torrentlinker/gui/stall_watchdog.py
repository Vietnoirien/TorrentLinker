"""Opt-in diagnosis of a frozen interface: log what the GUI thread was doing when it stalled.

Set TORRENTLINKER_STALL_MS to a threshold in milliseconds (for example 25). Every time the
GUI thread fails to run its heartbeat for longer than that, the watchdog logs the Python
stack the GUI thread was in, and how long the stall lasted. A stall with no TorrentLinker
frame on top means the time went into Qt or the platform (painting, decoding, compositing).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback

from PySide6.QtCore import QObject, QTimer

log = logging.getLogger("torrentlinker.stall")
BEAT_MS = 4


class StallWatchdog(QObject):
    def __init__(self, threshold_ms: float, parent: QObject | None = None):
        super().__init__(parent)
        self.threshold = threshold_ms / 1000
        self.main_id = threading.get_ident()
        self.beat = time.perf_counter()
        self.running = True
        self.timer = QTimer(self)
        self.timer.setInterval(BEAT_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.worker = threading.Thread(target=self.watch, name="stall-watchdog", daemon=True)
        self.worker.start()

    def tick(self) -> None:
        self.beat = time.perf_counter()

    def stack(self) -> str:
        frame = sys._current_frames().get(self.main_id)
        return "".join(traceback.format_stack(frame, limit=14)) if frame else "(no stack)"

    def watch(self) -> None:
        stalled_at = 0.0
        sampled: list[tuple[float, str]] = []
        while self.running:
            time.sleep(BEAT_MS / 1000)
            beat = self.beat
            gap = time.perf_counter() - beat
            if gap > self.threshold:
                if stalled_at != beat:
                    stalled_at, sampled = beat, []
                # Sample at the threshold and again each time the stall doubles.
                if not sampled or gap > 2 * sampled[-1][0]:
                    sampled.append((gap, self.stack()))
            elif sampled:
                total = time.perf_counter() - stalled_at
                shown = "\n".join(f"--- at {g * 1000:.0f} ms ---\n{s}" for g, s in sampled)
                log.warning("GUI thread stalled about %.0f ms\n%s", total * 1000, shown)
                sampled = []


def install(parent: QObject) -> StallWatchdog | None:
    """Start the watchdog when TORRENTLINKER_STALL_MS asks for it."""
    value = os.environ.get("TORRENTLINKER_STALL_MS", "")
    try:
        threshold = float(value)
    except ValueError:
        return None
    if threshold <= 0:
        return None
    log.warning("Stall watchdog on: logging GUI stalls longer than %.0f ms", threshold)
    return StallWatchdog(threshold, parent)
