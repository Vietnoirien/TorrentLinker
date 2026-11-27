"""Disk health for Disques: SMART through smartctl, or through a Scrutiny API (#206).

smartctl is run read-only (`-a -j`), only when the server is allowed to, and its absence or
refusal is reported as a hint, never as a failure. Scrutiny is optional: its summary gives
status, temperature and power-on hours for the disks it knows. A failing status or reallocated
sectors raise an alert.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

TIMEOUT = 20.0


def device_of(path: Path, mountinfo: Path = Path("/proc/self/mountinfo")) -> str | None:
    """The whole-disk device a path lives on, read from the mount table: `/dev/sda1` is
    `/dev/sda`, `/dev/nvme0n1p2` is `/dev/nvme0n1`. None when it is no block device."""
    best, source = "", ""
    try:
        lines = mountinfo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    target = str(path.resolve())
    for line in lines:
        left, _, right = line.partition(" - ")
        fields = left.split()
        if len(fields) < 5 or len(right.split()) < 2:
            continue
        mount = fields[4].replace("\\040", " ")
        if (target == mount or target.startswith(mount.rstrip("/") + "/")) and len(mount) > len(
            best
        ):
            best, source = mount, right.split()[1]
    if not source.startswith("/dev/"):
        return None
    name = re.sub(r"(?<=\d)p\d+$|(?<=[a-z])\d+$", "", source[5:]) if "/" not in source[5:] else ""
    return "/dev/" + name if name else None


def parse_smartctl(report: dict[str, Any]) -> dict[str, Any]:
    """Status, temperature, hours, reallocated and pending sectors from `smartctl -j`."""
    passed = (report.get("smart_status") or {}).get("passed")
    realloc = pending = 0
    for attribute in (report.get("ata_smart_attributes") or {}).get("table") or []:
        raw = int((attribute.get("raw") or {}).get("value") or 0)
        if attribute.get("id") == 5:
            realloc = raw
        elif attribute.get("id") == 197:
            pending = raw
    nvme = report.get("nvme_smart_health_information_log") or {}
    status = "ok" if passed is not False and not realloc else "failing"
    return {
        "status": status,
        "passed": passed,
        "temperature": (report.get("temperature") or {}).get("current", nvme.get("temperature")),
        "hours": (report.get("power_on_time") or {}).get("hours"),
        "reallocated": realloc,
        "pending": pending,
        "source": "smartctl",
    }


def smartctl(
    device: str,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """Health of one device, or `{"unavailable": reason}` when smartctl cannot be used."""
    binary = which("smartctl")
    if binary is None:
        return {"unavailable": "missing"}
    try:
        done = run([binary, "-a", "-j", device], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return {"unavailable": "failed"}
    try:
        report = json.loads(done.stdout)
    except ValueError:
        return {"unavailable": "failed"}
    for message in (report.get("smartctl") or {}).get("messages") or []:
        if "Permission denied" in str(message.get("string")) or "Operation not permitted" in str(
            message.get("string")
        ):
            return {"unavailable": "not-allowed"}
    if not (report.get("smart_status") or report.get("ata_smart_attributes")):
        return {"unavailable": "not-allowed" if done.returncode & 2 else "failed"}
    return parse_smartctl(report)


def scrutiny(url: str, client: httpx.Client | None = None) -> dict[str, dict[str, Any]]:
    """Scrutiny's summary by device name (`sda`): status, temperature and hours."""
    http = client or httpx.Client(timeout=TIMEOUT)
    base = url.rstrip("/")
    answer = http.get(f"{base}/api/summary")
    answer.raise_for_status()
    found: dict[str, dict[str, Any]] = {}
    for entry in ((answer.json().get("data") or {}).get("summary") or {}).values():
        device = entry.get("device") or {}
        smart = entry.get("smart") or {}
        name = str(device.get("device_name") or "")
        if name:
            failing = int(device.get("device_status") or 0) != 0
            found[name] = {
                "status": "failing" if failing else "ok",
                "passed": not failing,
                "temperature": smart.get("temp"),
                "hours": smart.get("power_on_hours"),
                "reallocated": 0,
                "pending": 0,
                "source": "scrutiny",
            }
    return found


def alert(health: dict[str, Any]) -> str:
    """The alert a disk's health raises, or an empty string."""
    if health.get("unavailable"):
        return ""
    if health.get("reallocated"):
        return f"{health['reallocated']} reallocated sectors"
    if health.get("status") == "failing":
        return "SMART status failing"
    return ""


def disk_health(
    roots: list[Path], *, allowed: bool = True, scrutiny_url: str = "", **tools: Any
) -> dict[str, Any]:
    """Health for the disk these roots sit on: smartctl when allowed, else Scrutiny."""
    device = device_of(roots[0])
    name = device.removeprefix("/dev/") if device else ""
    if allowed and device:
        found = smartctl(device, **{k: v for k, v in tools.items() if k in {"run", "which"}})
        if not found.get("unavailable"):
            return found
        reason = found["unavailable"]
    else:
        reason = "no-device" if not device else "disabled"
    if scrutiny_url:
        try:
            known = scrutiny(scrutiny_url, tools.get("client"))
        except (httpx.HTTPError, ValueError, OSError):
            return {"unavailable": reason, "scrutiny": "unreachable"}
        if name in known:
            return known[name]
        return {"unavailable": reason, "scrutiny": "unknown-disk"}
    return {"unavailable": reason}
