"""How fast the app may ask c411: two queues, one per limit c411 applies.

Measured on 2026-10-22 with one key (docs/research/rate-limits.md):

- Searches, Catalogue pages and the profile share a budget of 1,200 requests per
  rolling hour per key, which c411's JSON API reports in `x-ratelimit-*` headers; its
  guide also documents 120 requests a minute.
- .torrent downloads do not count in that budget. They have their own limit, which
  c411 does not report; past it, it answers 429 for a while.

So a Library search never waits behind a Plan's downloads, and goes as fast as c411
allows while the budget lasts.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping

DOWNLOAD_INTERVAL = 4.1  # seconds between .torrent downloads
API_INTERVAL = 0.5  # 120 requests a minute, as c411's guide documents
API_BUDGET = 1200  # requests per rolling hour on searches, listings and the profile
API_WINDOW = 3600.0
LOW_BUDGET = 100  # below this, slow down to what the hour can sustain (3 s a request)


class Queue:
    """One request at a time, at least `interval` seconds apart."""

    def __init__(
        self,
        interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self.lock = threading.Lock()  # held for a whole request, retries included
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def next_in(self) -> float:
        """Seconds before the next request may go."""
        if self._last is None:
            return 0.0
        return max(0.0, self._last + self._interval() - self._clock())

    def wait_turn(self) -> None:
        """Call with the lock held, just before sending."""
        if (wait := self.next_in()) > 0:
            self._sleep(wait)
        self._last = self._clock()
        self._sent()

    def _interval(self) -> float:
        return self.interval

    def _sent(self) -> None:
        pass

    def observe(self, headers: Mapping[str, str]) -> None:
        """What c411 said about the budget in a response; plain queues ignore it."""


class BudgetQueue(Queue):
    """A queue drawing on a budget of requests per rolling window.

    It counts its own requests over the window, and trusts `x-ratelimit-remaining` and
    `x-ratelimit-reset` whenever c411 sends them (other apps may use the same key).
    """

    def __init__(
        self,
        interval: float = API_INTERVAL,
        budget: int = API_BUDGET,
        window: float = API_WINDOW,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wall: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(interval, clock, sleep)
        self.budget = budget
        self.window = window
        self._wall = wall
        self._sent_at: deque[float] = deque()
        self._reported: int | None = None  # remaining, as c411 last said
        self._since_report = 0
        self._reset: float | None = None  # on this queue's clock

    def left(self) -> int:
        """Requests left in the budget, by our count or c411's, whichever is lower."""
        now = self._clock()
        while self._sent_at and self._sent_at[0] <= now - self.window:
            self._sent_at.popleft()
        left = self.budget - len(self._sent_at)
        if self._reported is not None and self._reset is not None and now < self._reset:
            left = min(left, self._reported - self._since_report)
        return left

    def _interval(self) -> float:
        left = self.left()
        if left > LOW_BUDGET:
            return self.interval
        if left > 0:
            return max(self.interval, self.window / self.budget)
        return self._until_refill()

    def _until_refill(self) -> float:
        """Seconds from the last request until the budget gives one back."""
        assert self._last is not None
        ends = [t + self.window for t in list(self._sent_at)[:1]]
        if self._reset is not None:
            ends.append(self._reset)
        refill = min(ends) if ends else self._clock() + self.interval
        return max(self.interval, refill - self._last)

    def _sent(self) -> None:
        self._sent_at.append(self._clock())
        self._since_report += 1

    def observe(self, headers: Mapping[str, str]) -> None:
        try:
            remaining = int(headers["x-ratelimit-remaining"])
            reset = float(headers["x-ratelimit-reset"])
        except (KeyError, ValueError):
            return
        if limit := headers.get("x-ratelimit-limit"):
            try:
                self.budget = int(limit)
            except ValueError:
                pass
        self._reported, self._since_report = remaining, 0
        self._reset = self._clock() + max(0.0, reset - self._wall())
