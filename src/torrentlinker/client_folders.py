"""Read-only folder settings reported by Torrent Clients, before Path Mapping."""

from __future__ import annotations

import ntpath
import posixpath
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ClientFolder:
    name: str
    path: str
    kind: Literal["default", "category", "completed", "incomplete"] = "category"


def client_path(path: str, base: str = "") -> str:
    """Resolve using the server's path syntax, even when it differs from this computer."""
    module = ntpath if (len(base) > 1 and base[1] == ":") or "\\" in base else posixpath
    if ntpath.isabs(path) and (ntpath.splitdrive(path)[0] or "\\" in path):
        module = ntpath
    return module.normpath(module.join(base, path)) if path or base else ""


def qbit_folders(
    default: str,
    categories: Mapping[str, Any],
    subcategories: bool,
) -> list[ClientFolder]:
    """Explicit relative category paths use the default; implicit children inherit parents."""

    def resolve(name: str) -> str:
        if not name:
            return default
        raw = str((categories.get(name) or {}).get("savePath") or "")
        if raw:
            return client_path(raw, default)
        parent, _, leaf = name.rpartition("/")
        implicit = leaf if subcategories else name
        # Sanitizing unusual names differs between server versions and platforms.
        # Do not guess a destination in those cases; the preview leaves it unselected.
        windows = "\\" in default or (len(default) > 1 and default[1] == ":")
        parts = implicit.split("/")
        reserved = {"CON", "PRN", "AUX", "NUL"} | {
            f"{prefix}{n}" for prefix in ("COM", "LPT") for n in "123456789¹²³"
        }
        for part in parts:
            if (
                not part
                or part != part.strip()
                or part in {".", ".."}
                or any(ord(c) < 32 or ord(c) == 127 or c == ":" for c in part)
                or len(part.encode("utf-8")) > 255
                or (
                    windows
                    and (
                        any(c in '<>"|?*\\' for c in part)
                        or part.endswith(".")
                        or part.split(".")[0].upper() in reserved
                    )
                )
            ):
                return ""
        base = resolve(parent) if subcategories else default
        return client_path(implicit, base) if base else ""

    rows = [ClientFolder("", default, "default")] if default else []
    rows.extend(ClientFolder(name, resolve(name)) for name in sorted(categories))
    return rows
