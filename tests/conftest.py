"""Tests never touch the user's real keyring, except the opt-in live tests."""

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
