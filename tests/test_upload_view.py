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

    assert view.candidates() == [vise, archive, other]
    assert "Search it first" in (view.why_not(vise) or "")
    assert "Films & Vidéos" in (view.why_not(other) or "")
    assert "not supported yet" in (view.why_not(other) or "")
    assert view.items.rowCount() == 0  # nothing ready: the rest hides behind Show all
    view.show_all.setChecked(True)
    assert view.items.rowCount() == 3
    view.show_all.setChecked(False)

    view.remember(vise, [])
    view.remember(archive, [])
    assert view.why_not(vise) is None
    assert view.why_not(archive) is None and view.needs_unpacking(archive)  # unpacked first
    assert view.items.rowCount() == 2
    assert view.items.item(0, 3).text() == "Archive: unpack it to upload"


def test_the_category_picker_defaults_from_the_kind_and_reruns_the_profile(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path
) -> None:
    view, _, _ = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    loose = LibraryEntry(
        LibraryFolder(tmp_path / "STL", 2, ContentKind.OTHER), vise.item, ItemState.ORPHAN
    )
    view.set_entries([loose])
    view.remember(loose, [])

    assert view.items.rowCount() == 0  # no category: not ready, hidden behind Show all
    view.show_all.setChecked(True)
    assert view.why_not(loose) == "Choose a category"
    assert view.items.item(0, 3).text() == "Choose a category"
    view.items.selectRow(0)
    assert (
        view.category.currentData() is None and view.category.currentText() == "Choose a category"
    )
    assert not view.name.isEnabled() and not view.create_button.isEnabled()

    view.category.setCurrentIndex(view.category.findData(10))
    assert view.why_not(loose) is None and view.items.item(0, 3).text() == "Ready"
    assert view.name.text() == "Petit.Etau.De.Bureau.NOTAG.3MF"
    assert view.subcategory.count() == 3 and view.name.isEnabled()
    assert view.create_button.isEnabled()

    view.set_entries([loose, model(tmp_path)])  # a 3D folder defaults to Imprimante 3D
    view.remember(view.candidates()[1], [])
    view.items.selectRow(1 if view.shown[0] is loose else 0)
    assert view.category.currentData() == 10


def test_a_kind_whose_category_has_no_profile_yet_says_so(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    game = LibraryEntry(LibraryFolder(tmp_path, 1, ContentKind.GAME), vise.item, ItemState.ORPHAN)
    view.set_entries([game])
    view.remember(game, [])
    view.show_all.setChecked(True)
    view.items.selectRow(0)

    assert (
        "Jeux Vidéo" in (view.why_not(game) or "") and "not supported yet" in view.problems.text()
    )
    assert view.category.currentText() == "Jeux Vidéo"
    view.category.setCurrentIndex(view.category.findData(10))  # the user can still pick 3D
    assert view.why_not(game) is None


def test_an_archive_that_cannot_be_read_cannot_be_unpacked(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    broken = model(tmp_path, "Dragon.zip")  # not a zip inside
    view.set_entries([broken])
    view.remember(broken, [])
    view.items.selectRow(0)

    qtbot.waitUntil(lambda: "cannot be read" in view.problems.text(), timeout=5000)
    assert view.create_button.text() == "Unpack…"
    assert not view.create_button.isEnabled()


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
    assert "Petit.Etau.De.Bureau.Printables.3MF.3mf" in view.nfo.toPlainText()
    assert view.file_table.item(0, 0).text() == "Petit.Etau.De.Bureau.Printables.3MF.3mf"
    assert view.file_table.item(0, 1).text() == "Petit étau de bureau.3mf"
    assert "Printables" in view.description.toPlainText()
    assert "Informations" in view.preview.toPlainText()  # rendered, without BBCode
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
    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a: asked.append(a[2]) or QMessageBox.StandardButton.Yes,
    )
    view, indexer, qbit = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    view.set_entries([vise])
    view.remember(vise, [])
    view.items.selectRow(0)
    started: list[Path] = []
    view.upload_started.connect(started.append)

    view.create_button.click()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    assert "requires an image" in asked[0]
    assert "saved as a Draft" in shown[0], shown
    assert indexer.saved[0]["title"] == "Petit.Etau.De.Bureau.NOTAG.3MF"
    [t] = qbit.torrents()
    assert set(t.files) == {"Petit étau de bureau.3mf"}
    assert started == [vise.item.path]
    qtbot.waitUntil(lambda: view.drafts.rowCount() == 1, timeout=5000)


def test_the_library_offers_an_upload_once_searched_without_a_match(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from torrentlinker.config import Settings
    from torrentlinker.gui.main_window import MainWindow

    vise = model(tmp_path)
    window = MainWindow(
        Settings(library_folders=[vise.folder]),
        tmp_path / "settings.json",
        Store(tmp_path / "s.db"),
    )
    qtbot.addWidget(window)
    window.upload_tab.set_entries([vise])
    window.review.set_entry(vise)
    button = window.review.upload_button
    assert not button.isHidden() and not button.isEnabled()  # not searched yet

    window.review.remember(vise, [])
    assert button.isEnabled()
    button.click()

    assert window.tabs.currentWidget() is window.upload_tab
    assert window.upload_tab.entry == vise


def test_changing_library_folders_scans_again(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from dataclasses import replace

    from torrentlinker.config import Settings
    from torrentlinker.gui import main_window
    from torrentlinker.gui.main_window import MainWindow

    folder = LibraryFolder(tmp_path, 1, ContentKind.OTHER)
    window = MainWindow(
        Settings(library_folders=[folder]), tmp_path / "settings.json", Store(tmp_path / "s.db")
    )
    qtbot.addWidget(window)
    scans: list[bool] = []
    window.scan = lambda refresh=False: scans.append(refresh)  # type: ignore[method-assign]
    window.zen_tab.seeding_view.refresh = lambda quiet=False: None  # type: ignore[method-assign]

    class Dialog:
        def __init__(self, settings: Settings, parent: object) -> None:
            self.settings = settings

        def exec(self) -> bool:
            self.settings.library_folders = [replace(folder, kind=ContentKind.MODEL_3D)]
            return True

    monkeypatch.setattr(main_window, "SettingsDialog", Dialog)
    window.open_settings()
    assert scans == [False]
    window.open_settings()  # nothing changed this time
    assert scans == [False]


def test_edits_to_the_description_survive_other_changes_until_reset(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, _, _ = tab(qtbot, tmp_path)
    vise = model(tmp_path)
    view.set_entries([vise])
    view.remember(vise, [])
    view.items.selectRow(0)

    view.description.setPlainText("[b]Mine[/b]")
    view.source.setText("Printables")
    assert view.description.toPlainText() == "[b]Mine[/b]"
    view.image_url.setText("https://i.example/v.png")
    assert view.description.toPlainText() == "[b]Mine[/b]"

    view._reset("description")
    assert "[img]https://i.example/v.png[/img]" in view.description.toPlainText()


def test_an_archive_is_unpacked_next_to_it_then_its_folder_is_offered(  # type: ignore[no-untyped-def]
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    import zipfile

    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    folder = LibraryFolder(tmp_path / "STL", 1, ContentKind.MODEL_3D)
    folder.path.mkdir()
    archive = folder.path / "Dragon.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("Dragon/Corps.stl", b"c" * 1500)
        z.writestr("Dragon/Tete.stl", b"t" * 700)
    entry = LibraryEntry(folder, scan_item(archive), ItemState.ORPHAN)
    view, _, _ = tab(qtbot, tmp_path)
    view.set_entries([entry])
    view.remember(entry, [])
    view.items.selectRow(0)
    qtbot.waitUntil(lambda: view.file_table.rowCount() == 2, timeout=5000)
    assert view.create_button.text() == "Unpack…" and view.create_button.isEnabled()
    assert view.name.text() == "Dragon.NOTAG.[PACK].STL"
    new: list[Path] = []
    view.unpacked.connect(new.append)

    view.create_button.click()
    qtbot.waitUntil(lambda: bool(new), timeout=5000)

    unpacked_folder = new[0]
    assert (unpacked_folder / "Dragon" / "Corps.stl").exists() or (
        unpacked_folder / "Corps.stl"
    ).exists()
    assert archive.exists()  # the archive stays until the Upload seeds
    assert view.store.take_unpacked(unpacked_folder) == archive
    # The Library scans; the new folder comes back selected, its archive's search kept.
    folder_entry = LibraryEntry(folder, scan_item(unpacked_folder), ItemState.ORPHAN)
    view.set_entries([entry, folder_entry])
    assert view.entry == folder_entry
    assert view.why_not(folder_entry) is None
    assert view.create_button.text() == "Create Draft"


def test_bbcode_renders_as_html_without_running_markup() -> None:
    from torrentlinker.bbcode import bbcode_to_html

    out = bbcode_to_html(
        "[center][img]https://i.example/a.png[/img][/center]\n[b]x[/b] <script>[*]y"
        "[url=javascript:alert(1)]no[/url]"
    )

    assert '<img src="https://i.example/a.png"' in out and "<b>x</b>" in out
    assert "&lt;script&gt;" in out and "<script>" not in out
    assert "javascript" in out and 'href="javascript' not in out
