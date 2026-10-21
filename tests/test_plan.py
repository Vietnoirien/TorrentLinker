from pathlib import Path

import pytest

from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.plan import (
    PlanCandidate,
    catalogue_candidates,
    disk_budgets,
    make_plan,
)
from torrentlinker.store import CatalogueRow
from torrentlinker.zen import GB, ZenClass, ZenProfile, ZenTorrent, estimate

KEEPER = ZenProfile(ZenClass.SWARM_KEEPER)


def cand(
    name: str, gb: float, seeders: int = 5, disk: str = "A", reseed: bool = False
) -> PlanCandidate:
    return PlanCandidate(name, name, int(gb * GB), seeders, 2000, Path("/dl"), disk, reseed)


def names(plan) -> list[str]:  # type: ignore[no-untyped-def]
    return sorted(i.candidate.title for i in plan.items)


def test_plan_stays_within_each_disk_budget() -> None:
    candidates = [cand("a", 8), cand("b", 8), cand("c", 8, disk="B"), cand("d", 8, disk="B")]

    plan = make_plan(KEEPER, candidates, {"A": int(10 * GB), "B": int(17 * GB)})

    assert names(plan) == ["a", "c", "d"] or names(plan) == ["b", "c", "d"]
    assert plan.download_size == int(24 * GB)


def test_plan_respects_the_torrent_cap() -> None:
    candidates = [cand(str(i), 1) for i in range(10)]

    plan = make_plan(KEEPER, candidates, {"A": 100 * GB}, slots=3)

    assert len(plan.items) == 3


def test_greedy_keeps_the_best_of_several_orderings() -> None:
    # Per GB the small torrent wins, then the big one no longer fits; alone, the big
    # rare torrent pays more.
    candidates = [cand("big", 60, seeders=3), cand("small", 6, 3)]

    plan = make_plan(KEEPER, candidates, {"A": int(60 * GB)})

    assert names(plan) == ["big"]


def test_plan_adds_the_zen_of_its_torrents_to_current_seeding() -> None:
    seeding = [ZenTorrent(4 * GB, 3, 100) for _ in range(4)]
    candidates = [cand("a", 4, 2)]

    plan = make_plan(KEEPER, candidates, {"A": 10 * GB}, seeding)

    after = estimate(KEEPER, [*seeding, ZenTorrent(4 * GB, 3, 0, 2000)]).total
    assert plan.zen_added == pytest.approx(after - estimate(KEEPER, seeding).total)
    assert plan.payback_days == pytest.approx(4 / plan.zen_added)


def test_reseeds_come_first_and_cost_no_download() -> None:
    candidates = [cand("dl", 4, 3), cand("reseed", 30, 3, disk=None, reseed=True)]  # type: ignore[arg-type]

    plan = make_plan(KEEPER, candidates, {"A": 5 * GB}, slots=1)

    assert names(plan) == ["reseed"]
    assert plan.download_size == 0
    assert plan.zen_added > 0


def test_catalogue_torrents_in_qbittorrent_or_without_download_folder_are_skipped() -> None:
    categories = {2000: IndexerCategory("Films"), 7000: IndexerCategory("Ebook")}
    rows = [
        CatalogueRow("aa" * 20, "in client", GB, 5, 2000, "u", "d", 0),
        CatalogueRow("bb" * 20, "no folder", GB, 5, 7000, "u", "d", 0),
        CatalogueRow("cc" * 20, "dead", GB, 0, 2000, "u", "d", 0),
        CatalogueRow("dd" * 20, "ok", GB, 5, 2000, "u", "d", 0),
    ]
    folders = DownloadFolders({2000: "/dl/films"})

    found = catalogue_candidates(rows, folders, categories, {"aa" * 20}, lambda p: "disk")

    assert [c.title for c in found] == ["ok"]
    assert found[0].folder == Path("/dl/films") and found[0].disk == "disk"


def test_a_plan_can_be_limited_to_chosen_categories_parents_including_their_subcategories() -> None:
    categories = {
        2000: IndexerCategory("Films"),
        2030: IndexerCategory("Films étrangers", parent=2000),
        5000: IndexerCategory("Séries"),
        7000: IndexerCategory("Ebook"),
    }
    rows = [
        CatalogueRow("aa" * 20, "film", GB, 5, 2000, "u", "d", 0),
        CatalogueRow("bb" * 20, "foreign film", GB, 5, 2030, "u", "d", 0),
        CatalogueRow("cc" * 20, "series", GB, 5, 5000, "u", "d", 0),
        CatalogueRow("dd" * 20, "ebook", GB, 5, 7000, "u", "d", 0),
    ]
    folders = DownloadFolders(default="/dl")

    def titles(only: set[int] | None) -> list[str]:
        found = catalogue_candidates(rows, folders, categories, set(), lambda p: "d", only)
        return [c.title for c in found]

    assert titles(None) == ["film", "foreign film", "series", "ebook"]
    assert titles({2000, 7000}) == ["film", "foreign film", "ebook"]
    assert titles({2030}) == ["foreign film"]


def test_disk_budget_is_free_space_minus_a_margin_of_the_disk_shared_by_its_folders(
    tmp_path: Path,
) -> None:
    a, b, c = tmp_path / "a", tmp_path / "b" / "not-yet", tmp_path / "c"
    a.mkdir()
    c.mkdir()
    disks = {a: 1, b: 1, c: 2}

    budgets = disk_budgets(
        [a, b, c],
        0.10,
        usage=lambda p: (1000, 400, 600),
        disk=lambda p: disks[p],
    )

    assert budgets == {1: 500, 2: 500}


def test_a_full_disk_gives_no_budget(tmp_path: Path) -> None:
    assert disk_budgets([tmp_path], 0.10, usage=lambda p: (1000, 950, 50)) != {}
    assert set(disk_budgets([tmp_path], 0.10, usage=lambda p: (1000, 950, 50)).values()) == {0}


def test_orphans_with_a_full_match_become_reseed_rows_listed_first(tmp_path: Path) -> None:
    from tests.torrents import make_torrent
    from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
    from torrentlinker.indexer import Candidate
    from torrentlinker.library import LibraryEntry
    from torrentlinker.matching import Match
    from torrentlinker.plan import reseed_candidates
    from torrentlinker.review import CheckedCandidate
    from torrentlinker.torrent_meta import read_torrent

    f = tmp_path / "book.epub"
    f.write_bytes(b"b" * 3000)
    meta = read_torrent(make_torrent(f))
    folder = LibraryFolder(tmp_path)
    full = Match({"book.epub": "book.epub"}, [], [], 1.0)
    partial = Match({"book.epub": "book.epub"}, ["x"], [], 0.6)
    orphan = LibraryEntry(folder, LocalItem(f, {f.name: 3000}), ItemState.ORPHAN)
    other = LibraryEntry(folder, LocalItem(tmp_path / "o"), ItemState.ORPHAN)
    seeded = LibraryEntry(folder, LocalItem(tmp_path / "s"), ItemState.SEEDED)
    checked = CheckedCandidate(Candidate("Book", 3000, "u", 4, meta.infohash), meta, full, full)
    found = [
        (orphan, [checked]),
        (other, [CheckedCandidate(Candidate("P", 3000, "u", 4), meta, partial, partial)]),
        (seeded, [checked]),
    ]

    rows = reseed_candidates(KEEPER, found, in_client=set())
    downloads = [
        cand("dl", 4, 3),
        PlanCandidate(meta.infohash, "Book in catalogue", 3000, 4, 7000, Path("/dl"), "A"),
    ]
    plan = make_plan(KEEPER, rows + downloads, {"A": 10 * GB})

    assert [r.title for r in rows] == ["Book"]
    assert plan.items[0].candidate.reseed
    assert plan.items[0].zen > 0
    assert [i.candidate.title for i in plan.items] == ["Book", "dl"]  # not downloaded twice
    assert plan.download_size == 4 * GB
    assert reseed_candidates(KEEPER, found, in_client={meta.infohash}) == []
