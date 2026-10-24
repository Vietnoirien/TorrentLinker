"""Keep desktop workers concurrent, but give agent jobs exclusive application access."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from functools import wraps


class Coordinator:
    def __init__(self):
        self.condition = threading.Condition()
        self.desktop_workers = 0
        self.agent_waiting = 0
        self.agent_active = False

    @contextmanager
    def desktop(self):
        with self.condition:
            while self.agent_active or self.agent_waiting:
                self.condition.wait()
            self.desktop_workers += 1
        try:
            yield
        finally:
            with self.condition:
                self.desktop_workers -= 1
                self.condition.notify_all()

    @contextmanager
    def agent(self, stop):
        with self.condition:
            self.agent_waiting += 1
            try:
                while self.desktop_workers or self.agent_active:
                    if stop.is_set():
                        raise ValueError("Agent job cancelled while waiting for desktop work.")
                    self.condition.wait(0.2)
                self.agent_active = True
            finally:
                self.agent_waiting -= 1
                self.condition.notify_all()
        try:
            yield
        finally:
            with self.condition:
                self.agent_active = False
                self.condition.notify_all()


coordinator = Coordinator()


def desktop_worker(fn):
    @wraps(fn)
    def work(*args, **kwargs):
        with coordinator.desktop():
            return fn(*args, **kwargs)

    return work
