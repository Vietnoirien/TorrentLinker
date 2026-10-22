"""Secrets live in the OS keyring (Secret Service, Windows Credential Manager)."""

from __future__ import annotations

import keyring
import keyring.errors

SERVICE = "torrentlinker"
TMDB_API_KEY = "tmdb-api-key"  # the video profile identifies releases with it


def get_secret(name: str) -> str:
    try:
        return keyring.get_password(SERVICE, name) or ""
    except keyring.errors.KeyringError:
        return ""


def set_secret(name: str, value: str) -> None:
    if value:
        keyring.set_password(SERVICE, name, value)
    else:
        try:
            keyring.delete_password(SERVICE, name)
        except keyring.errors.PasswordDeleteError:
            pass
