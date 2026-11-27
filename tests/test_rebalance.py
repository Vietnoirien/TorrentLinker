"""Disques' rebalance proposal: films from a disk under the margin to the disk with room."""

from __future__ import annotations

from pathlib import Path

from torrentlinker.rebalance import destination, proposal


def card(name: str, root: str, *, below: bool, usable: int = 100, writable: bool = True):
    return {
        "id": name, "name": name, "roots": [root], "below_margin": below, "writable": writable,
        "free": 5, "margin": 10, "usable": usable,
    }  # fmt: skip


def test_films_move_from_a_disk_under_the_margin_to_the_one_with_most_room(tmp_path: Path):
    full, roomy = tmp_path / "saves", tmp_path / "library"
    (full / "Films" / "Big (2020)").mkdir(parents=True)
    (full / "Films" / "Big (2020)" / "big.mkv").write_bytes(b"x" * 500)
    (full / "Films" / "Small.mkv").write_bytes(b"x" * 50)
    (roomy / "Films").mkdir(parents=True)
    films = [
        {"id": "1", "path": str(full / "Films" / "Big (2020)" / "big.mkv"), "title": "Big"},
        {"id": "2", "path": str(full / "Films" / "Small.mkv"), "title": "Small"},
    ]
    found = proposal(
        [card("saves", str(full), below=True), card("library", str(roomy), below=False)],
        [full / "Films", roomy / "Films"],
        lambda folder: films if folder == full / "Films" else [],
        [],
    )
    assert found["state"] == "proposal" and found["target"]["folder"] == str(roomy / "Films")
    [source] = found["sources"]
    assert [f["title"] for f in source["films"]] == ["Big", "Small"]  # the biggest first
    assert source["films"][0]["size"] == 500
    folder, chosen = destination(found, [str(full / "Films" / "Small.mkv"), "/etc/passwd"])
    assert folder == str(roomy / "Films") and chosen == [str(full / "Films" / "Small.mkv")]


def test_nothing_is_proposed_when_no_disk_is_under_the_margin_or_none_has_room(tmp_path: Path):
    ok = card("a", "/a", below=False)
    assert proposal([ok], [], lambda _: [], [])["state"] == "balanced"
    assert proposal([card("b", "/b", below=True)], [], lambda _: [], [])["state"] == "no-room"
    assert proposal([card("b", "/b", below=True), ok], [], lambda _: [], [])["state"] == "no-folder"
