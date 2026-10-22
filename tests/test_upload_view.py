from pathlib import Path
from typing import Any

from tests.fake_qbit import FakeQbit
from torrentlinker.domain import ContentKind, ItemState, LibraryFolder
from torrentlinker.gui.upload_view import UploadTab
from torrentlinker.library import LibraryEntry
from torrentlinker.matching import IgnoreList
from torrentlinker.scan import scan_item
from torrentlinker.store import Store

ANNOUNCE = "https://c411.org/announce/secret"


class StubIndexer:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def save_draft(self, body: dict[str, Any]) -> int:
        self.saved.append(body)
        return 7

    def drafts(self) -> list[dict[str, Any]]:
        return [{"name": b["title"], "subcategory": {"name": "Objets"}} for b in self.saved]


def model(tmp_path: Path, name: str = "Petit étau de bureau.3mf") -> LibraryEntry:
    folder = LibraryFolder(tmp_path / "STL", 1, ContentKind.MODEL_3D)
    folder.path.mkdir(exist_ok=True)
    (folder.path / name).write_bytes(b"m" * 3000)
    return LibraryEntry(folder, scan_item(folder.path / name), ItemState.ORPHAN)


def tab(qtbot, tmp_path: Path, announce: str = ANNOUNCE) -> tuple[UploadTab, StubIndexer, FakeQbit]:  # type: ignore[no-untyped-def]
    indexer, qbit = StubIndexer(), FakeQbit()
    view = UploadTab(
        Store(tmp_path / "s.db"),
        lambda: indexer,  # type: ignore[arg-type,return-value]
        lambda: qbit,
        IgnoreList.default,
        lambda: announce,
        tmp_path / "uploads",
    )
    qtbot.addWidget(view)
    return view, indexer, qbit


def test_only_searched_3d_orphans_without_a_match_may_be_uploaded(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    vise, archive = model(tmp_path), model(tmp_path, "Dragon.rar")
    other = LibraryEntry(LibraryFolder(tmp_path, 1, ContentKind.MOVIE), vise.item, ItemState.ORPHAN)
    view.set_entries([vise, archive, other])

    assert view.candidates() == [vise, archive]
    assert "Search it first" in (view.why_not(vise) or "")
    view.remember(vise, [])
    view.remember(archive, [])
    assert view.why_not(vise) is None
    assert "Archives are refused" in (view.why_not(archive) or "")


def test_selecting_an_orphan_suggests_a_compliant_name_and_previews_the_nfo(
    qtbot, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    view.set_entries([vise])
    view.remember(vise, [])

    view.items.selectRow(0)
    assert view.name.text() == "Petit.Etau.De.Bureau.NOTAG.3MF"
    view.source.setText("Printables")
    assert view.name.text() == "Petit.Etau.De.Bureau.Printables.3MF"
    assert "Petit.Etau.De.Bureau.Printables.3MF.3mf" in view.preview.toPlainText()
    assert view.create_button.isEnabled()

    view.name.setText("Petit étau")
    assert not view.create_button.isEnabled()


def test_no_announce_url_says_where_to_enter_it(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path, announce="")
    vise = model(tmp_path)
    view.set_entries([vise])
    view.remember(vise, [])
    view.items.selectRow(0)

    assert "Announce URL" in view.notice.text()
    assert not view.create_button.isEnabled()


def test_creating_a_draft_saves_it_and_seeds_from_the_local_file(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: shown.append(a[2]))
    view, indexer, qbit = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    view.set_entries([vise])
    view.remember(vise, [])
    view.items.selectRow(0)
    started: list[Path] = []
    view.upload_started.connect(started.append)

    view.create_button.click()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    assert "saved as a Draft" in shown[0], shown
    assert indexer.saved[0]["title"] == "Petit.Etau.De.Bureau.NOTAG.3MF"
    [t] = qbit.torrents()
    assert set(t.files) == {"Petit étau de bureau.3mf"}
    assert started == [vise.item.path]
    qtbot.waitUntil(lambda: view.drafts.rowCount() == 1, timeout=5000)
