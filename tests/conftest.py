"""Tests never touch the user's real keyring, except the opt-in live tests."""

import gc
import os

import keyring
import pytest
from keyring.backend import KeyringBackend


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.secrets: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.secrets.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.secrets[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.secrets.pop((service, username), None)


@pytest.fixture(autouse=True)
def memory_keyring():  # type: ignore[no-untyped-def]
    if os.environ.get("TL_LIVE"):
        yield None
        return
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def collect_garbage_on_the_gui_thread(request):  # type: ignore[no-untyped-def]
    """Free each test's leftover windows here, on the GUI thread.

    A window caught in a reference cycle is otherwise freed whenever the garbage
    collector next runs, possibly on a later test's worker thread, and destroying Qt
    widgets off the GUI thread crashes Python.
    """
    yield
    if "qtbot" in request.fixturenames:
        gc.collect()


# The app's default client addresses are the user's own clients on this machine: a test
# must never log in to them (a wrong password gets localhost banned by qBittorrent).
USER_CLIENTS = {
    f"{scheme}://{host}:{port}"
    for scheme in ("http", "https")
    for host in ("localhost", "127.0.0.1")
    for port in (8080, 8112, 9091)
}
NOWHERE = "http://127.0.0.1:9"  # discard port: refused at once


@pytest.fixture(autouse=True)
def never_reach_the_users_own_clients(monkeypatch):  # type: ignore[no-untyped-def]
    from torrentlinker.deluge import DelugeApi
    from torrentlinker.qbit import QbitApi
    from torrentlinker.transmission import TransmissionApi

    for cls in (QbitApi, DelugeApi, TransmissionApi):
        original = cls.__init__

        def guarded(self, host, *args, __original=original, **kwargs):  # type: ignore[no-untyped-def]
            if host.strip().rstrip("/") in USER_CLIENTS:
                host = NOWHERE
            __original(self, host, *args, **kwargs)

        monkeypatch.setattr(cls, "__init__", guarded)
