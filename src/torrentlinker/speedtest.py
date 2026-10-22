"""Measure the line's download speed, to estimate how long a Plan's data takes.

Downloads Cloudflare's public speed-test file over a few parallel connections for a few
seconds. The request is anonymous: no key or cookie is sent. A torrent with few seeders
downloads slower than the line, so an estimate from this speed is a lower bound.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import httpx

SPEED_TEST_URL = "https://speed.cloudflare.com/__down"
CHUNK = 25_000_000  # bytes per request; Cloudflare refuses 100 MB
STREAMS = 4
DURATION = 8.0  # seconds


def measure_download_speed(
    http: httpx.Client | None = None,
    *,
    streams: int = STREAMS,
    duration: float = DURATION,
    clock: Callable[[], float] = time.monotonic,
) -> float:
    """Bytes per second received over `streams` connections during about `duration` s."""
    client = http or httpx.Client(timeout=30, follow_redirects=True)
    lock = threading.Lock()
    received = 0
    start = clock()
    deadline = start + duration

    def stream() -> None:
        nonlocal received
        while clock() < deadline:
            with client.stream("GET", SPEED_TEST_URL, params={"bytes": str(CHUNK)}) as r:
                r.raise_for_status()
                for chunk in r.iter_bytes():
                    with lock:
                        received += len(chunk)
                    if clock() >= deadline:
                        return

    try:
        with ThreadPoolExecutor(streams) as pool:
            for future in [pool.submit(stream) for _ in range(streams)]:
                future.result()
    finally:
        if http is None:
            client.close()
    elapsed = clock() - start
    if received == 0 or elapsed <= 0:
        raise RuntimeError("the speed test received nothing")
    return received / elapsed
