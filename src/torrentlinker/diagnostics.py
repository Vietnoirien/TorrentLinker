"""Allowlisted support metadata. Never serialize settings, logs, or job payloads."""

from __future__ import annotations

import copy
import json
import platform
import sys
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, get_args
from urllib.parse import urlsplit

from torrentlinker.config import Settings
from torrentlinker.domain import ContentKind, TorrentClient
from torrentlinker.store import Store

if TYPE_CHECKING:
    from torrentlinker.web.jobs import Jobs


QUEUE_STATES = {"queued", "sending", "sent", "uncertain", "refused", "failed"}
JOB_STATES = {"queued", "running", "completed", "partial", "cancelled", "failed", "interrupted"}


def _choice(value: str, allowed: set[str]) -> str:
    return value if value in allowed else "other"


def _version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unavailable"


def _path_style(value: str) -> str:
    if not value.strip():
        return "unset"
    if PureWindowsPath(value).is_absolute():
        return "windows-absolute"
    if PurePosixPath(value).is_absolute():
        return "posix-absolute"
    return "relative"


def _connection(value: str) -> dict[str, str]:
    if not value.strip():
        return {"scheme": "unset", "scope": "unset"}
    try:
        url = urlsplit(value)
        if not url.hostname or url.scheme not in {"http", "https"}:
            raise ValueError
        return {
            "scheme": url.scheme,
            "scope": "local" if url.hostname in {"localhost", "127.0.0.1", "::1"} else "remote",
        }
    except ValueError:
        return {"scheme": "invalid", "scope": "unknown"}


def build_report(settings: Settings, store: Store, jobs: Jobs | None = None) -> dict:
    """Read current state without probes, secret lookups, or startup reconciliation.

    Client aliases are report-local and carry no persisted IDs. Counts cover all
    clients. Job records contain only an operation kind, outcome and client alias.
    """
    snapshot = copy.deepcopy(settings)
    snapshot.capture_client()
    aliases = {p.id: f"client-{i}" for i, p in enumerate(snapshot.client_profiles, 1)}
    clients = []
    for profile in snapshot.client_profiles:
        clients.append(
            {
                "alias": aliases[profile.id],
                "type": _choice(profile.client, set(TorrentClient)),
                "enabled": bool(profile.enabled),
                "active": profile.id == snapshot.active_client_id,
                "default": profile.id == snapshot.default_client_id,
                "connection": _connection(profile.host),
                "path_mappings": dict(
                    Counter(
                        f"{_path_style(m.local)} -> {_path_style(m.qbit)}"
                        for m in profile.path_mappings
                    )
                ),
                "download_folders": {
                    "default": _path_style(profile.download_folders.default),
                    "category_overrides": sum(
                        bool(p.strip()) for p in profile.download_folders.by_category.values()
                    ),
                },
            }
        )
    state = store.diagnostic_counts()
    for key in ("download_queue", "local_draft"):
        counts: Counter[str] = Counter()
        for status, count in state[key].items():
            counts[_choice(status, QUEUE_STATES)] += count
        state[key] = dict(counts)
    recent_jobs = None
    if jobs is not None:
        from torrentlinker.web.operations import JobRequest

        kinds = set(get_args(JobRequest.model_fields["kind"].annotation))
        recent_jobs = [
            {
                "kind": _choice(row["kind"], kinds),
                "status": _choice(row["status"], JOB_STATES),
                "client": aliases.get(row["client_id"], "removed-or-unknown"),
            }
            for row in jobs.diagnostic_rows()
        ]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "runtime": {
            "app_version": _version("torrentlinker"),
            "python": platform.python_version(),
            "pyside": _version("PySide6"),
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "packaged": bool(getattr(sys, "frozen", False)),
        },
        "preferences": {
            "language": _choice(snapshot.language, {"auto", "en", "fr"}),
            "theme": _choice(snapshot.theme, {"auto", "light", "dark"}),
            "proxy_configured": bool(snapshot.proxy.address.strip()),
            "proxy_for_client": bool(snapshot.proxy.torrent_client),
        },
        "clients": clients,
        "library_folders": dict(
            Counter(_choice(folder.kind, set(ContentKind)) for folder in snapshot.library_folders)
        ),
        "state": state,
        "recent_jobs": recent_jobs,
    }


def report_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"
