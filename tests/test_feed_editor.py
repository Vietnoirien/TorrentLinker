from PySide6.QtCore import Qt

from tests import test_catalogue_selection
from torrentlinker.downloads import IndexerCategory
from torrentlinker.feeds import Preferences, Subscription
from torrentlinker.gui.feed_editor import FeedEditor

catalogue_app = test_catalogue_selection.catalogue_app

RICH = Subscription(
    name="Rich",
    query="film",
    categories=[2030, 9999],
    interval_minutes=45,
    wait_minutes=90,
    include_current=True,
    replace_pending=True,
    download_hours=[0, 1, 2, 22, 23],
    daily_bytes=8_000_000_000,
    daily_torrents=7,
    reserve_bytes=123_456_789,
    preferences=Preferences(
        min_size=700 * 1024**2 + 5,
        max_size=8_000_000_000,
        min_seeders=3,
        required={"quality": ["1080p", "720p"], "audio": ["fr"]},
        preferred={"quality": ["1080p"], "codec": ["HEVC", "H264"]},
        excluded={"quality": ["CAM"]},
        priorities=["codec", "quality", "seeders", "audio", "subtitles", "size"],
        prefer_small=True,
    ),
)


def editor(app, qtbot, feed=RICH):
    control = app.state.agent_service.feed_control
    control.service.setup.settings.indexer_categories = {
        2000: IndexerCategory("Movies"),
        2030: IndexerCategory("Movies HD", 2000),
        5000: IndexerCategory("TV"),
    }
    dialog = FeedEditor(control, feed, "id", lambda: None, live=False)
    qtbot.addWidget(dialog)
    return dialog


def test_opening_and_saving_changes_nothing_untouched(catalogue_app, qtbot):
    app, _, _ = catalogue_app
    assert editor(app, qtbot).definition() == RICH


def test_mode_decides_what_is_shown(catalogue_app, qtbot):
    app, _, _ = catalogue_app
    dialog = editor(app, qtbot, Subscription(name="x"))
    dialog.show()
    assert not dialog.where.isVisible() and not dialog.limits.isVisible()
    dialog.modes.cards["app_queue"].radio.click()
    assert dialog.where.isVisible() and not dialog.limits.isVisible()
    dialog.modes.cards["automatic_download"].radio.click()
    assert dialog.where.isVisible() and dialog.limits.isVisible()
    dialog.folder.addItem("films")
    dialog.folder.setCurrentText("films")
    assert dialog.definition().mode == "automatic_download"


def test_categories_by_name_keep_unknown_ids(catalogue_app, qtbot):
    app, _, _ = catalogue_app
    dialog = editor(app, qtbot)
    assert dialog.categories.text() == "Movies HD, #9999"
    items = dialog.categories.items
    items[5000].setCheckState(0, Qt.CheckState.Checked)
    assert dialog.definition().categories == [2030, 9999, 5000]
    items[2030].setCheckState(0, Qt.CheckState.Unchecked)
    assert dialog.definition().categories == [9999, 5000]


def test_sizes_and_hours_use_human_units(catalogue_app, qtbot):
    app, _, _ = catalogue_app
    dialog = editor(app, qtbot, Subscription(name="x"))
    assert (dialog.daily_size.number.value(), dialog.daily_size.unit.currentText()) == (10.0, "GiB")
    dialog.daily_size.number.setValue(500)
    dialog.daily_size.unit.setCurrentText("MiB")
    assert dialog.daily_size.value() == 500 * 1024**2
    assert dialog.max_size.number.value() == 0 and dialog.max_size.value() is None
    dialog.max_size.number.setValue(2)
    assert dialog.max_size.value() == 2 * 1024**3
    assert dialog.hours.preset.currentData() == "any"
    dialog.hours.preset.setCurrentIndex(dialog.hours.preset.findData("night"))
    local = [h for h, cell in enumerate(dialog.hours.cells) if cell.isChecked()]
    assert local == [1, 2, 3, 4, 5, 6]
    assert len(dialog.hours.value()) == 6


def test_automatic_needs_an_hour(catalogue_app, qtbot):
    import pytest

    app, _, _ = catalogue_app
    dialog = editor(app, qtbot, Subscription(name="x"))
    dialog.modes.cards["automatic_download"].radio.click()
    for cell in dialog.hours.cells:
        cell.setChecked(False)
    with pytest.raises(ValueError, match="at least one hour"):
        dialog.definition()


def test_chips_cycle_and_keep_ranking_valid(catalogue_app, qtbot):
    app, _, _ = catalogue_app
    dialog = editor(app, qtbot, Subscription(name="x"))
    row = dialog.criteria.rows["quality"]
    row.chips["1080p"].click()
    assert dialog.definition().preferences.preferred == {"quality": ["1080p"]}
    row.chips["1080p"].click()
    prefs = dialog.definition().preferences
    assert prefs.required == {"quality": ["1080p"]}
    row.chips["1080p"].click()
    assert dialog.definition().preferences.excluded == {"quality": ["1080p"]}
    assert dialog.definition().preferences.required == {}
    assert row.chips["1080p"].property("chip") == "avoid"
    row.chips["1080p"].click()
    assert dialog.definition().preferences.excluded == {}


def test_typed_chip_and_ranking_move(catalogue_app, qtbot):
    app, _, _ = catalogue_app
    dialog = editor(app, qtbot, Subscription(name="x"))
    row = dialog.criteria.rows["format"]
    row.add.setText("EPUB")
    row.add.returnPressed.emit()
    assert "EPUB" in row.chips
    row.chips["EPUB"].click()
    prefs = dialog.definition().preferences
    assert prefs.preferred == {"format": ["EPUB"]}
    assert "format" in prefs.priorities  # the validator ranks every preferred field
    first = prefs.priorities[0]
    dialog.priorities.shift("format", -10)
    assert dialog.definition().preferences.priorities[0] == "format"
    assert dialog.definition().preferences.priorities[1] == first


def test_strip_judges_fetched_rows_without_the_network(catalogue_app, qtbot):
    app, _, _ = catalogue_app
    dialog = editor(app, qtbot, Subscription(name="x"))
    dialog.preview_rows = [
        {"title": "Good.1080p", "size": 10**9, "seeders": 5, "infohash": "a" * 40,
         "download_url": "u", "metadata": {"quality": "1080p", "source": "WEB"}},
        {"title": "Bad.CAM", "size": 10**9, "seeders": 5, "infohash": "b" * 40,
         "download_url": "u", "metadata": {"quality": "CAM"}},
    ]  # fmt: skip
    dialog.criteria.suggest(dialog.preview_rows)
    dialog.criteria.rows["quality"].chips["CAM"].click()  # prefer
    dialog.criteria.rows["quality"].chips["CAM"].click()  # require
    assert dialog.strip.text() == "Would match now: 1 of 2 releases"
    assert dialog.strip_titles.text() == "Bad.CAM"
    dialog.criteria.rows["quality"].chips["CAM"].click()  # avoid
    assert dialog.strip.text() == "Would match now: 1 of 2 releases"
    assert dialog.strip_titles.text() == "Good.1080p"


def test_advanced_shows_the_full_definition(catalogue_app, qtbot):
    app, _, _ = catalogue_app
    dialog = editor(app, qtbot)
    dialog.advanced.toggle.setChecked(True)
    assert '"interval_minutes": 45' in dialog.advanced_text.toPlainText()
    assert "9999" in dialog.advanced_text.toPlainText()
