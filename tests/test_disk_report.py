"""Disques: real statvfs figures, the 10 % margin, and the placement rule."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_web_jobs import login
from torrentlinker import disk_report
from torrentlinker.disk_report import Usage, disk_cards, place
from torrentlinker.file_storage import FileStorage
from torrentlinker.web.app import create_app


def card(name, usable, roots=None, writable=True):
    return {"id": name, "name": name, "roots": roots or [f"/{name}"], "usable": usable,
            "writable": writable}  # fmt: skip


def test_usage_keeps_a_margin_of_ten_percent():
    u = Usage(total=1000, used=900, free=100)
    assert u.margin == 100 and u.usable == 0
    assert Usage(1000, 500, 500).usable == 400


def test_a_card_shows_real_figures_and_what_fills_the_disk(tmp_path: Path):
    library, downloads = tmp_path / "library", tmp_path / "downloads"
    (library / "Films" / "Dune").mkdir(parents=True)
    (library / "Films" / "Dune" / "Dune.mkv").write_bytes(b"x" * 4096)
    downloads.mkdir()
    (downloads / "new.mkv").write_bytes(b"y" * 1024)
    storage = FileStorage(tmp_path, (library, downloads))
    storage.trash(library / "Films" / "Dune", "owner")
    disk_report._walked.clear()
    report = disk_cards(storage, [library / "Films"], [downloads], lambda f: 1)
    [one] = report["disks"]  # both roots are on the same device
    real = disk_report.usage(tmp_path)
    assert one["total"] == real.total and one["margin"] == real.total // 10
    assert one["downloads"] == 1024 and one["trash"] == 4096 and one["library"] == 0
    assert one["films"] == 1 and one["below_margin"] is (real.free < real.margin)
    assert report["missing"] == []


def test_a_configured_folder_the_application_cannot_see_is_reported(tmp_path: Path):
    storage = FileStorage(tmp_path, (tmp_path,))
    report = disk_cards(storage, [Path("/library/Films")], [])
    assert report["missing"] == ["/library/Films"]


def test_together_wins_then_the_disk_with_most_free_space_above_the_margin():
    cards = [
        card("saves", 50, ["/saves"]),
        card("windocs", 0, ["/windocs"]),
        card("library", 9000, ["/library"]),
    ]
    assert place(cards, 100)["name"] == "library" and place(cards, 100)["why"] == "most-free"
    together = place(cards, 40, Path("/saves/Films/Dune"))
    assert together["name"] == "saves" and together["why"] == "together"
    # The disk the film already sits on has no room: the free-space rule applies.
    full = place(cards, 100, Path("/saves/Films/Dune"))
    assert full["name"] == "library" and full["why"] == "together-full"
    assert place(cards, 10**6)["disk"] is None
    assert place([card("ro", 9000, writable=False)], 1)["disk"] is None


@pytest.fixture
def browser(tmp_path: Path):
    library = tmp_path / "lib"
    library.mkdir()
    app = create_app(tmp_path / "app", password="test-password-long", roots=(library,),
                     monitor_verifications=False)  # fmt: skip
    with TestClient(app) as b:
        login(b)
        yield b


def test_the_routes_serve_the_cards_and_the_placement(browser):
    cards = browser.get("/api/files/disks").json()
    assert len(cards["disks"]) == 1 and cards["disks"][0]["total"] > 0
    chosen = browser.post("/api/files/disks/placement", json={"size": 1}).json()
    assert chosen["disk"] == cards["disks"][0]["id"]
