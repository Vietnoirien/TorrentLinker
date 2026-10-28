"""The upload workspace always sends a reviewed, saved revision."""

import pytest

from tests.test_upload_view import model, tab


def test_upload_opens_local_drafts_and_preparation_only_saves(qtbot, tmp_path):
    view, indexer, _ = tab(qtbot, tmp_path, announce="")
    assert view.workspaces.currentWidget() is view.local_drafts
    entry = model(tmp_path)
    view.set_entries([entry])
    view.select(entry.item.path)
    qtbot.waitUntil(lambda: bool(view.files))
    assert view.pages.tabText(0) == "Details"
    assert view.pages.tabText(1) == "Files && NFO"
    assert view.create_button.isHidden()
    view.queue_button.click()
    qtbot.waitUntil(lambda: view.local_drafts.record is not None)
    assert view.workspaces.currentWidget() is view.local_drafts
    assert indexer.saved == []
    assert view.local_drafts.pages.count() == 5


def test_editing_revokes_review_and_refresh_preserves_unsaved_text(qtbot, tmp_path):
    view, _, _ = tab(qtbot, tmp_path)
    entry = model(tmp_path)
    view.set_entries([entry])
    view.select(entry.item.path)
    qtbot.waitUntil(lambda: bool(view.files))
    view.queue_button.click()
    qtbot.waitUntil(lambda: view.local_drafts.record is not None)
    drafts = view.local_drafts
    drafts.pages.setCurrentIndex(4)
    drafts.reviewed.setChecked(True)
    drafts.description.setPlainText("My unsaved changes")
    assert not drafts.reviewed.isChecked()
    assert not drafts.send_button.isEnabled()
    drafts.refresh()
    assert drafts.description.toPlainText() == "My unsaved changes"
    assert drafts.save_button.isEnabled(), (drafts.stale, drafts.busy, drafts.record["status"])
    drafts.save_button.click()
    qtbot.waitUntil(lambda: not drafts.busy)
    assert not drafts.reviewed.isChecked()
    assert drafts.record["revision"] == 2, drafts.status.text()


def test_reopen_selected_draft_after_external_edit(qtbot, tmp_path):
    from PySide6.QtCore import Qt

    view, _, _ = tab(qtbot, tmp_path)
    entry = model(tmp_path)
    view.set_entries([entry])
    view.select(entry.item.path)
    qtbot.waitUntil(lambda: bool(view.files))
    view.queue_button.click()
    drafts = view.local_drafts
    qtbot.waitUntil(lambda: drafts.record is not None)
    record = drafts.record
    drafts.store.save_local_draft(
        {**record, "form": {**record["form"], "title": "Updated elsewhere"}},
        record["id"],
        record["revision"],
    )
    drafts.refresh()
    assert drafts.stale
    view.show()
    qtbot.mouseClick(
        drafts.table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=drafts.table.visualItemRect(drafts.table.item(0, 0)).center(),
    )
    assert not drafts.stale
    assert drafts.title.text() == "Updated elsewhere"
    assert drafts.record["revision"] == 2


def test_category_options_stay_disabled_during_save(qtbot, tmp_path):
    from threading import Event

    from torrentlinker.options import OptionType, OptionValue

    view, _, _ = tab(qtbot, tmp_path)
    entry = model(tmp_path)
    view.set_entries([entry])
    view.select(entry.item.path)
    qtbot.waitUntil(lambda: bool(view.files))
    view.queue_button.click()
    drafts = view.local_drafts
    qtbot.waitUntil(lambda: drafts.record is not None)
    drafts.options_callback = lambda _: [
        OptionType(1, "Format", False, False, (OptionValue(1, "3MF"),)),
    ]
    drafts.load_options()
    qtbot.waitUntil(lambda: bool(drafts.option_widgets))
    drafts.option_widgets[1].setCurrentIndex(1)
    release = Event()
    original_save = drafts.save_callback

    def delayed_save(record, form):
        assert release.wait(5)
        return original_save(record, form)

    drafts.save_callback = delayed_save
    try:
        drafts.save_button.click()
        assert drafts.busy
        assert not drafts.option_widgets[1].isEnabled()
        # A category request that finishes during the save must stay disabled too.
        drafts.load_options()
        qtbot.waitUntil(lambda: bool(drafts.option_widgets))
        assert not drafts.option_widgets[1].isEnabled()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not drafts.busy)


@pytest.mark.parametrize("language", ["en", "fr"])
def test_capture_upload_workspace(qtbot, tmp_path, request, language):
    import os
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from tests.test_upload_completeness import complete_description
    from torrentlinker import i18n
    from torrentlinker.gui.theme import apply_theme

    output = os.getenv("TL_UPLOAD_SCREENSHOTS")
    if not output:
        return
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance()
    translators = i18n.install(app, language)
    request.addfinalizer(lambda: [app.removeTranslator(t) for t in translators])
    view, indexer, _ = tab(qtbot, tmp_path)
    entry = model(tmp_path, "Desk organiser.3mf")
    view.set_entries([entry])
    view.select(entry.item.path)
    qtbot.waitUntil(lambda: bool(view.files))
    view.description.setPlainText(
        complete_description(text="A modular desk organiser with removable trays.")
    )
    view.queue_button.click()
    qtbot.waitUntil(lambda: view.local_drafts.record is not None)
    view.resize(1280, 800)
    view.show()
    for theme in ("dark", "light"):
        apply_theme(app, theme)
        for index, name in enumerate(("details", "files", "description", "artwork", "review")):
            view.local_drafts.pages.setCurrentIndex(index)
            qtbot.wait(60)
            assert view.grab().save(str(target / f"desktop-upload-{name}-{language}-{theme}.png"))
    view.remote_button.click()
    qtbot.wait(100)
    indexer.saved.append({"title": "Cable.Clips.NOTAG.3MF"})
    view._show_drafts(indexer.drafts())
    apply_theme(app, "dark")
    assert view.grab().save(str(target / f"desktop-upload-c411-{language}-dark.png"))
    view.new_button.click()
    assert view.grab().save(str(target / f"desktop-upload-new-{language}-dark.png"))
    assert not indexer.saved[:-1]
