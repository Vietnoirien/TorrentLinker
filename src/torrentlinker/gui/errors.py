"""Errors as the user reads them."""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication

from torrentlinker.indexer import KeyRefused, RateLimited


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
