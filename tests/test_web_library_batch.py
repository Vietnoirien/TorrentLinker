"""The web Library's batch actions follow the desktop's: remembered Candidates only."""

import threading
from types import SimpleNamespace

from torrentlinker.domain import ItemState
from torrentlinker.reseed import AlreadyInClient
from torrentlinker.web import library as web_library


def candidate(name):
    return SimpleNamespace(title=name, infohash=name * 40, details_url="", download_url=name)


def checked(match, *, unpack=None, infohash=None):
    full = SimpleNamespace(is_full=True, renames=[])
    partial = SimpleNamespace(is_full=False, renames=[])
    return SimpleNamespace(
        match={"full": full, "partial": partial, "none": None}[match],
        unpack=unpack,
        meta=SimpleNamespace(infohash=infohash or "f" * 40) if match != "none" else None,
    )


def make_library(tmp_path, monkeypatch):
    items = {name: tmp_path / name for name in ("orphan", "partial", "seeded", "unsearched")}
    remembered = {
        items["orphan"]: [candidate("a"), candidate("b"), candidate("c")],
        items["partial"]: [candidate("d"), candidate("e")],
        items["seeded"]: [candidate("x")],
    }
    results = {
        "a": checked("full", infohash="1" * 40),
        "b": checked("full", unpack=object()),  # an archive: left for the item's review
        "c": checked("none"),
        "d": checked("full", infohash="1" * 40),  # the same torrent as "a": once only
        "e": checked("partial"),
        "x": checked("full"),
    }
    monkeypatch.setattr(
        web_library, "remembered_candidates", lambda store, indexer, path: remembered.get(path)
    )
    monkeypatch.setattr(web_library, "scan_item", lambda path: SimpleNamespace(path=path))
    monkeypatch.setattr(
        web_library, "check_candidate", lambda indexer, item, c, rules: results[c.title]
    )
    started = []

    def start_reseed(client, store, item, meta, match, key):
        if key == "d" * 40:
            raise AlreadyInClient("already there")
        started.append(item.path.name)
        return meta.infohash

    monkeypatch.setattr(web_library, "start_reseed", start_reseed)
    setup = SimpleNamespace(
        indexer=lambda: object(),
        store=SimpleNamespace(
            rejections=lambda path: {"e" * 40} if path == items["partial"] else {}
        ),
        settings=SimpleNamespace(matching=SimpleNamespace(rules=lambda: None)),
        path_under_root=lambda *args, **kwargs: None,
    )
    library = web_library.Library(setup)
    library.client = lambda: SimpleNamespace(requires_disk_renames=False)
    states = {
        "orphan": ItemState.ORPHAN,
        "partial": ItemState.PARTIALLY_SEEDED,
        "seeded": ItemState.SEEDED,
        "unsearched": ItemState.ORPHAN,
    }
    library.entries = [
        SimpleNamespace(item=SimpleNamespace(path=path), state=states[name])
        for name, path in items.items()
    ]
    return library, started


def test_check_all_checks_remembered_candidates_of_unseeded_items(tmp_path, monkeypatch):
    library, _ = make_library(tmp_path, monkeypatch)
    result = library.check_all(threading.Event(), lambda _p: None)
    assert result["items"] == 2  # seeded and never-searched items are left out
    assert (result["full"], result["partial"], result["none"], result["archive"]) == (2, 0, 1, 1)
    names = {item["name"]: [row["match"] for row in item["rows"]] for item in result["results"]}
    assert names == {"orphan": ["full", "full", "none"], "partial": ["full"]}  # "e" rejected


def test_reseed_all_starts_each_full_match_once_and_leaves_archives(tmp_path, monkeypatch):
    library, started = make_library(tmp_path, monkeypatch)
    result = library.reseed_all(threading.Event(), lambda _p: None)
    assert started == ["orphan"]
    assert result == {"started": 1, "already_present": 0, "skipped": 1, "errors": []}


def test_a_torrent_already_in_the_client_is_counted_not_failed(tmp_path, monkeypatch):
    library, started = make_library(tmp_path, monkeypatch)
    # Without the first item, "d" is the only Full Match, and the client has it.
    library.entries = library.entries[1:]
    result = library.reseed_all(threading.Event(), lambda _p: None)
    assert started == [] and result["already_present"] == 1 and result["errors"] == []
