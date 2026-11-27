"""Disk health: smartctl when the server may run it, Scrutiny otherwise, alerts on failures."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from torrentlinker.disk_health import (
    alert,
    device_of,
    disk_health,
    parse_smartctl,
    scrutiny,
    smartctl,
)

OK = {
    "smart_status": {"passed": True},
    "temperature": {"current": 34},
    "power_on_time": {"hours": 12345},
    "ata_smart_attributes": {
        "table": [{"id": 5, "raw": {"value": 0}}, {"id": 197, "raw": {"value": 0}}]
    },
}
BAD = {**OK, "ata_smart_attributes": {"table": [{"id": 5, "raw": {"value": 48}}]}}


def runner(payload, returncode=0):
    def run(command, **kwargs):
        assert command[0] == "/usr/sbin/smartctl" and command[1:3] == ["-a", "-j"]  # read-only
        return subprocess.CompletedProcess(command, returncode, json.dumps(payload), "")

    return run


def which(name):
    return "/usr/sbin/smartctl"


def test_device_of_reads_the_mount_table(tmp_path: Path):
    table = tmp_path / "mountinfo"
    table.write_text(
        "30 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
        "41 30 259:2 / /library rw - ext4 /dev/nvme0n1p2 rw\n"
        "52 30 0:50 / /saves rw - overlay overlay rw\n",
        encoding="utf-8",
    )
    assert device_of(Path("/"), table) == "/dev/sda"
    assert device_of(Path("/library"), table) == "/dev/nvme0n1"
    assert device_of(Path("/saves"), table) is None


def test_smartctl_status_temperature_hours_and_reallocated_sectors():
    good = parse_smartctl(OK)
    assert (good["status"], good["temperature"], good["hours"]) == ("ok", 34, 12345)
    bad = parse_smartctl(BAD)
    assert bad["status"] == "failing" and bad["reallocated"] == 48


def test_smartctl_is_read_when_allowed_and_a_hint_is_given_when_it_is_not():
    assert smartctl("/dev/sda", runner(OK), which)["status"] == "ok"
    assert smartctl("/dev/sda", runner({}, 2), which) == {"unavailable": "not-allowed"}
    assert smartctl("/dev/sda", runner(OK), lambda n: None) == {"unavailable": "missing"}
    denied = {"smartctl": {"messages": [{"string": "Smartctl open device: Permission denied"}]}}
    assert smartctl("/dev/sda", runner(denied, 2), which) == {"unavailable": "not-allowed"}


def scrutiny_client(status=200):
    def disk(name, status, temp, hours):
        return {"device": {"device_name": name, "device_status": status},
                "smart": {"temp": temp, "power_on_hours": hours}}  # fmt: skip

    summary = {"data": {"summary": {"w1": disk("sda", 0, 31, 900), "w2": disk("sdb", 2, 40, 5)}}}
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=summary))
    )


def test_scrutiny_gives_status_temperature_and_hours_by_device():
    found = scrutiny("http://scrutiny:8080", scrutiny_client())
    assert found["sda"]["status"] == "ok" and found["sda"]["temperature"] == 31
    assert found["sdb"]["status"] == "failing"
    with pytest.raises(httpx.HTTPStatusError):
        scrutiny("http://scrutiny:8080", scrutiny_client(500))


def test_scrutiny_stands_in_when_smartctl_cannot_be_used(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("torrentlinker.disk_health.device_of", lambda path: "/dev/sdb")
    health = disk_health(
        [tmp_path],
        scrutiny_url="http://s",
        run=runner({}, 2),
        which=which,
        client=scrutiny_client(),
    )
    assert health["source"] == "scrutiny" and alert(health) == "SMART status failing"
    unknown = disk_health(
        [tmp_path],
        scrutiny_url="http://s",
        run=runner({}, 2),
        which=which,
        client=scrutiny_client(),
    )
    monkeypatch.setattr("torrentlinker.disk_health.device_of", lambda path: "/dev/sdz")
    assert disk_health(
        [tmp_path],
        scrutiny_url="http://s",
        run=runner({}, 2),
        which=which,
        client=scrutiny_client(),
    ) == {"unavailable": "not-allowed", "scrutiny": "unknown-disk"}
    assert unknown["source"] == "scrutiny"


def test_alerts_come_from_failing_status_or_reallocated_sectors_only():
    assert alert(parse_smartctl(BAD)) == "48 reallocated sectors"
    assert alert(parse_smartctl(OK)) == ""
    assert alert({"unavailable": "missing"}) == ""
    assert alert({"status": "failing", "reallocated": 0}) == "SMART status failing"


def test_the_scrutiny_address_is_checked_and_kept_beside_the_retention(tmp_path: Path):
    from torrentlinker.file_storage import FileStorage, StorageError

    storage = FileStorage(tmp_path, (tmp_path,))
    storage.set_retention_days(14)
    storage.set_scrutiny_url("http://scrutiny:8080")
    assert storage.retention_days() == 14 and storage.scrutiny_url() == "http://scrutiny:8080"
    with pytest.raises(StorageError):
        storage.set_scrutiny_url("not a url")
