from pathlib import Path

from torrentlinker.batch import run_batch
from torrentlinker.domain import ItemState, LibraryFolder, LocalItem
from torrentlinker.library import LibraryEntry

FOLDER = LibraryFolder(Path("/lib"))


def entry(name: str, state: ItemState = ItemState.ORPHAN) -> LibraryEntry:
    return LibraryEntry(FOLDER, LocalItem(Path("/lib") / name), state)


def test_batch_searches_each_orphan_and_reports_progress() -> None:
    entries = [entry("a"), entry("b", ItemState.PARTIALLY_SEEDED), entry("c")]
    progress: list[tuple[int, int, str]] = []

    done = run_batch(
        entries,
        search=lambda e: [e.item.path.name.upper()],
        on_searched=lambda i, n, e, r: progress.append((i, n, r[0])),
        cancelled=lambda: False,
    )

    assert done == 2
    assert progress == [(1, 2, "A"), (2, 2, "C")]


def test_cancelling_stops_before_the_next_item() -> None:
    searched: list[str] = []
    entries = [entry("a"), entry("b"), entry("c")]

    done = run_batch(
        entries,
        search=lambda e: searched.append(e.item.path.name) or [],
        on_searched=lambda *_: None,
        cancelled=lambda: len(searched) >= 1,
    )

    assert searched == ["a"]
    assert done == 1


def test_a_failing_item_is_reported_and_the_batch_goes_on() -> None:
    errors: list[str] = []

    def search(e: LibraryEntry) -> list[str]:
        if e.item.path.name == "a":
            raise RuntimeError("boom")
        return ["ok"]

    done = run_batch(
        [entry("a"), entry("b")],
        search=search,
        on_searched=lambda *_: None,
        cancelled=lambda: False,
        on_error=lambda e, err: errors.append(f"{e.item.path.name}: {err}"),
    )

    assert done == 2
    assert errors == ["a: boom"]
