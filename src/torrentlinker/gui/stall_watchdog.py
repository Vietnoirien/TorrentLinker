"""Opt-in diagnosis of a frozen interface: log what the GUI thread was doing when it stalled.

Set TORRENTLINKER_STALL_MS to a threshold in milliseconds (for example 25). Every time the
GUI thread fails to run its heartbeat for longer than that, the watchdog immediately logs
Python thread stacks, then samples again as the stall doubles. Logging does not require
the GUI to recover. Stacks contain code locations, not local-variable values.
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
        names = {thread.ident: thread.name for thread in threading.enumerate()}
        frames = sys._current_frames()
        sections = []
        for identifier in sorted(frames, key=lambda identifier: identifier != self.main_id):
            if identifier == threading.get_ident():
                continue
            label = "GUI thread" if identifier == self.main_id else names.get(identifier, "worker")
            sections.append(
                f"--- {label} ({identifier}) ---\n"
                + "".join(traceback.format_stack(frames[identifier], limit=14))
            )
        return "\n".join(sections) or "(no stack)"

    def watch(self) -> None:
        stalled_at = 0.0
        last_sample = 0.0
        while self.running:
            time.sleep(BEAT_MS / 1000)
            beat = self.beat
            gap = time.perf_counter() - beat
            if gap > self.threshold:
                if stalled_at != beat:
                    stalled_at, last_sample = beat, 0.0
                # Sample at the threshold and again each time the stall doubles.
                if not last_sample or gap > 2 * last_sample:
                    log.warning(
                        "GUI thread stalled for %.0f ms (still blocked)\n%s",
                        gap * 1000,
                        self.stack(),
                    )
                    last_sample = gap
            elif last_sample:
                total = time.perf_counter() - stalled_at
                log.warning("GUI thread recovered after about %.0f ms", total * 1000)
                last_sample = 0.0


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
