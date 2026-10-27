import httpx

from tests.fake_qbit import FakeQbit
from tests.test_search_filters import choose
from tests.test_torrent_search import FACETS, TREE, fake_indexer, listing
from torrentlinker.config import Settings
from torrentlinker.gui.pagination import page_numbers
from torrentlinker.gui.search_view import SearchTab
from torrentlinker.store import Store


def test_page_numbers_show_the_ends_and_the_neighbours():
    assert page_numbers(1, 400) == [1, 2, 3, None, 400]
    assert page_numbers(2, 400) == [1, 2, 3, None, 400]
    assert page_numbers(50, 400) == [1, None, 49, 50, 51, None, 400]
    assert page_numbers(399, 400) == [1, None, 398, 399, 400]
    assert page_numbers(4, 400) == [1, 2, 3, 4, 5, None, 400]  # one hidden page is shown
    assert page_numbers(1, 3) == [1, 2, 3]
    assert page_numbers(1, 1) == [1]
    assert page_numbers(9, 0) == []
    assert page_numbers(99, 5) == [1, 2, 3, 4, 5]  # a stale page number is clamped


def listing_with_counts(page=1):
    data = listing(page, total=137565, total_pages=400)
    data["meta"].update(
        {
            "totalSize": 1757108743727203,
            "categories": [{"id": 1, "count": 138013}, {"id": 2, "count": 39239}],
        }
    )
    return data


def make_view(qtbot, tmp_path, requests):
    def handler(request):
        requests.append(request)
        if request.url.path == "/api/categories":
            data = {"data": [{**root, "color": "#3B82F6"} for root in TREE["data"]]}
        elif request.url.path.endswith("filter-options"):
            data = FACETS
        else:
            data = listing_with_counts(int(request.url.params["page"]))
        return httpx.Response(200, json=data)

    indexer = fake_indexer(handler)
    view = SearchTab(Store(tmp_path / "state.db"), Settings(), lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    view.resize(1100, 800)
    view.show()
    qtbot.waitUntil(lambda: view.filters.ready)
    return view


def test_pills_follow_the_category_and_filter_at_once(qtbot, tmp_path):
    requests: list = []
    view = make_view(qtbot, tmp_path, requests)
    assert list(view.pills.buttons) == [None, 1, 2]
    assert view.pills.buttons[None].isChecked()
    view.pills.buttons[2].click()
    qtbot.waitUntil(lambda: not view._searching and view._native_page is not None)
    assert requests[-1].url.params["category"] == "2"
    assert view.category.current_category == 2
    assert view.pills.buttons[2].isChecked()
    # A subcategory lights its parent's pill.
    view.category.select_category(-6)
    assert view.pills.buttons[1].isChecked()
    view.pills.buttons[None].click()
    qtbot.waitUntil(lambda: not view._searching)
    assert "category" not in requests[-1].url.params


def test_pill_counts_are_global_totals_and_the_header_shows_the_filtered_total(qtbot, tmp_path):
    view = make_view(qtbot, tmp_path, [])
    assert view.pills.buttons[1].text() == "Films && Vidéos"  # no counts before a search
    view.query.setText("ocean")
    view.search_button.click()
    qtbot.waitUntil(lambda: view._native_page is not None and not view._searching)
    assert "138" in view.pills.buttons[1].text() and "39" in view.pills.buttons[2].text()
    assert view.pills.buttons[None].text().startswith("All")
    total = view.results_summary.text()
    assert "137" in total and "1.6 PiB" in total


def test_numbered_pages_search_the_chosen_page(qtbot, tmp_path):
    requests: list = []
    view = make_view(qtbot, tmp_path, requests)
    view.search_button.click()
    qtbot.waitUntil(lambda: view._native_page is not None and not view._searching)
    assert view.page_bar.isVisible() and not view.previous.isEnabled()
    view.page_bar.page_requested.emit(3)
    qtbot.waitUntil(lambda: not view._searching)
    assert requests[-1].url.params["page"] == "3"
    assert view.previous.isEnabled()


def test_sort_chips_research_and_flip_the_direction(qtbot, tmp_path):
    requests: list = []
    view = make_view(qtbot, tmp_path, requests)
    sort = view.filters.sort
    assert not sort.buttons["relevance"].isVisible()
    view.query.setText("ocean")
    assert sort.buttons["relevance"].isVisible()
    view.search_button.click()
    qtbot.waitUntil(lambda: view._native_page is not None and not view._searching)
    sort.buttons["seeders"].click()
    qtbot.waitUntil(lambda: not view._searching)
    assert (requests[-1].url.params["sortBy"], requests[-1].url.params["sortOrder"]) == (
        "seeders",
        "desc",
    )
    sort.buttons["seeders"].click()
    qtbot.waitUntil(lambda: not view._searching)
    assert requests[-1].url.params["sortOrder"] == "asc"
    sort.buttons["name"].click()
    qtbot.waitUntil(lambda: not view._searching)
    assert (requests[-1].url.params["sortBy"], requests[-1].url.params["sortOrder"]) == (
        "name",
        "asc",
    )
    sort.buttons["relevance"].click()
    qtbot.waitUntil(lambda: not view._searching)
    assert requests[-1].url.params["sortBy"] == "relevance"
    view.query.clear()  # Relevance means nothing without a query: back to Age
    assert sort.key == "createdAt" and not sort.buttons["relevance"].isVisible()


def test_cast_and_crew_only_applies_to_video_with_a_text_query(qtbot, tmp_path):
    view = make_view(qtbot, tmp_path, [])
    filters = view.filters
    assert filters.crew.isHidden()
    view.category.select_category(1)
    qtbot.waitUntil(lambda: filters.ready)
    assert not filters.crew.isHidden()
    filters.crew.setChecked(True)
    assert filters.params("Ocean")["crew"] == "true"
    assert "crew" not in filters.params("")
    view.category.select_category(2)
    qtbot.waitUntil(lambda: filters.ready)
    assert filters.crew.isHidden() and "crew" not in filters.params("Ocean")


def test_active_filters_are_marked_and_clear_all_resets_them(qtbot, tmp_path):
    view = make_view(qtbot, tmp_path, [])
    view.category.select_category(1)
    qtbot.waitUntil(lambda: view.filters.ready)
    resolution = view.filters.video["resolution"]
    assert resolution.property("active") is False
    choose(resolution, "1080p")
    assert resolution.property("active") is True
    view.filters.sort.buttons["size"].click()
    view.filters.clear_button.click()
    assert resolution.property("active") is False
    assert view.filters.sort.key == "createdAt"


def rich_listing(page=1):
    data = listing_with_counts(page)
    base = data["data"][0]
    data["data"] = [
        {
            **base,
            "infoHash": f"{i:040x}",
            "name": f"Release.{i}.1080p",
            "seeders": i,
            "leechers": 2 * i,
            "completions": 10 * i,
            "uploader": f"up{i}",
            "media": {"kind": "movie", "title": f"Title {i}", "year": 2000 + i, "rating": 7.0},
            "tech": {"resolution": "1080p", "source": "BluRay", "languages": ["VFF"]},
        }
        for i in (1, 2, 3)
    ]
    return data


def make_rich_view(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    ini = str(tmp_path / "ui.ini")
    monkeypatch.setattr(
        SearchTab, "_ui_settings", lambda self: QSettings(ini, QSettings.Format.IniFormat)
    )

    def handler(request):
        if request.url.path == "/api/categories":
            data = TREE
        elif request.url.path.endswith("filter-options"):
            data = FACETS
        else:
            data = rich_listing(int(request.url.params["page"]))
        return httpx.Response(200, json=data)

    indexer = fake_indexer(handler)
    settings = Settings()
    settings.download_folders.default = str(tmp_path)
    view = SearchTab(Store(tmp_path / "state.db"), settings, lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    view.resize(1100, 800)
    view.show()
    qtbot.waitUntil(lambda: view.filters.ready)
    view.search_button.click()
    qtbot.waitUntil(lambda: view._native_page is not None and not view._searching)
    return view, ini


def test_density_switch_changes_columns_and_is_remembered(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    view, ini = make_rich_view(qtbot, tmp_path, monkeypatch)
    table = view.results
    assert view.density == "comfortable" and view.density_buttons["comfortable"].isChecked()
    assert table.isColumnHidden(2) and table.isColumnHidden(6) and not table.isColumnHidden(11)
    assert table.horizontalHeader().isHidden()
    comfortable_height = table.height()
    view.density_buttons["compact"].click()
    assert view.density == "compact"
    assert not table.isColumnHidden(2) and not table.isColumnHidden(8) and table.isColumnHidden(11)
    assert not table.horizontalHeader().isHidden()
    assert table.rowHeight(0) < 60 and table.height() <= comfortable_height
    assert QSettings(ini, QSettings.Format.IniFormat).value("search/density") == "compact"
    # The next page of results keeps the density that was chosen.
    view.page_bar.page_requested.emit(2)
    qtbot.waitUntil(lambda: not view._searching)
    assert table.isColumnHidden(11) and table.rowHeight(0) < 60
    restored = SearchTab(Store(tmp_path / "other.db"), Settings(), lambda: None, FakeQbit)
    qtbot.addWidget(restored)
    assert restored.density == "compact"


def test_listing_details_fill_the_table_and_the_painted_row_view(qtbot, tmp_path, monkeypatch):
    view, _ = make_rich_view(qtbot, tmp_path, monkeypatch)
    table = view.results
    rows = {table.item(r, 0).text(): r for r in range(table.rowCount())}
    row = rows["Release.2.1080p"]
    assert table.item(row, 2).text() == "2" and table.item(row, 8).text() == "4"
    assert table.item(row, 9).text() == "20" and table.item(row, 10).text() == "up2"
    shown = view._row_view(table.model().index(row, 0))
    assert shown.details.title == "Title 2" and shown.details.year == 2002
    assert shown.label == "Films & Vidéos / Film" and shown.color == view.pills.color_for(
        "Films & Vidéos"
    )
    assert [text for _, text in shown.details.tags] == ["VFF", "1080p", "BluRay"]


def test_selection_bar_and_row_download_button(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QModelIndex

    from torrentlinker.download_queue import entries
    from torrentlinker.gui.search_view import DOWNLOAD_COLUMN

    view, _ = make_rich_view(qtbot, tmp_path, monkeypatch)
    assert not view.selection_bar.isVisible()
    view.results.selectRow(0)
    assert view.selection_bar.isVisible() and "1" in view.selection_label.text()
    view.results.clearSelection()
    assert not view.selection_bar.isVisible()
    assert view._row_view(QModelIndex()) is None
    # The download button of one row queues that row only.
    view._cell_clicked(1, DOWNLOAD_COLUMN)
    queued = entries(view.store)
    assert len(queued) == 1 and queued[0].candidate.title == view.results.item(1, 0).text()
    assert "1 added" in view.result_status.text()
