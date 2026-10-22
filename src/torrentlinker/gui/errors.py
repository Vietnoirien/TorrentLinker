"""Errors as the user reads them."""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox, QWidget

from torrentlinker.gui.tasks import run_in_background
from torrentlinker.indexer import KeyRefused, RateLimited
from torrentlinker.transmission import PartialNamesOn


def error_text(error: Exception) -> str:
    if isinstance(error, KeyRefused) and error.key_number > 1:
        return QCoreApplication.translate(
            "Errors",
            "c411 refused API key {1} (HTTP {0}). Check it in Settings → Connections, under "
            "More API keys: it needs the torznab:read scope.",
        ).format(error.status, error.key_number)
    if isinstance(error, KeyRefused):
        return QCoreApplication.translate(
            "Errors",
            "c411 refused your API key (HTTP {0}). Check it in Settings → Connections: "
            "create one at https://c411.org/user/integrations with the torznab:read scope "
            "(add profile:read to see your Zen Balance).",
        ).format(error.status)
    if isinstance(error, RateLimited):
        return QCoreApplication.translate(
            "Errors",
            "c411 is asking to wait before more requests: try again at {0}. A Plan being "
            "sent waits on its own.",
        ).format(time.strftime("%H:%M", time.localtime(time.time() + error.retry_after)))
    return str(error) or type(error).__name__


def offer_whole_names(parent: QWidget, error: Exception, then: Callable[[], object]) -> bool:
    """When Transmission would rename files to .part, offer to turn that off, then run
    `then`. Whether `error` was that refusal (ADR-0010)."""
    if not isinstance(error, PartialNamesOn):
        return False
    answer = QMessageBox.question(
        parent,
        "Transmission",
        QCoreApplication.translate(
            "Errors",
            "Transmission appends .part to the names of incomplete files: during a Reseed "
            "that would rename your own files.\n\nTurn off “Append .part to incomplete "
            "files' names” in Transmission? It applies to all its torrents. Your files are "
            "left as they are either way.",
        ),
    )
    if answer == QMessageBox.StandardButton.Yes:
        run_in_background(
            error.turn_off,
            lambda _: then(),
            lambda e: QMessageBox.warning(parent, "Transmission", error_text(e)),
        )
    return True
