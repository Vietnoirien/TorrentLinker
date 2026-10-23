import httpx
from PySide6.QtCore import Qt

from tests.fake_qbit import FakeQbit
from tests.test_torrent_search import FACETS, TREE, fake_indexer, listing
from torrentlinker.config import Settings
from torrentlinker.gui.category_picker import CategoryPicker
from torrentlinker.gui.search_filters import SearchFilters
from torrentlinker.gui.search_view import SearchTab
from torrentlinker.store import Store
from torrentlinker.torrent_search import parse_tree


def choose(control, *values):
    for i in range(control.items.count()):
        item = control.items.item(i)
        item.setCheckState(
            Qt.CheckState.Checked
            if item.data(Qt.ItemDataRole.UserRole) in values
            else Qt.CheckState.Unchecked
        )


def prepared(qtbot):
    category = CategoryPicker()
    widget = SearchFilters(category)
    qtbot.addWidget(widget)
    qtbot.addWidget(category)
    indexer = fake_indexer(
        lambda r: httpx.Response(200, json=TREE if r.url.path == "/api/categories" else FACETS)
    )
    widget.configure(indexer)
    qtbot.waitUntil(lambda: widget.ready)
    category.select_category(-7)
    qtbot.waitUntil(lambda: widget.ready)
    return widget, category


def test_category_filters_serialize_options_and_clear_inapplicable_values(qtbot):
    filters, category = prepared(qtbot)
    choose(filters.options["saison"], "118")
    choose(filters.options["genre"], "39", "40")
    choose(filters.video["resolution"], "1080p")
    choose(filters.video["profile"], "pure")
    filters.exclusive.setChecked(True)
    filters.palliative.setCurrentIndex(2)
    filters.year.setText("2024")
    filters.uploader.setText(" example ")
    params = filters.params("Ocean")
    assert params == {
        "name": "Ocean",
        "sortBy": "createdAt",
        "sortOrder": "desc",
        "category": "1",
        "subcat": "7",
        "resolution": "1080p",
        "profile": "pure",
        "options": "39,40,118",
        "exclusive": "true",
        "palliative": "only",
        "year": "2024",
        "uploader": "example",
    }
    assert "langue" not in filters.options
    category.select_category(-6)
    assert filters.ready
    assert "saison" not in filters.options
    assert "options" not in filters.params("")
    assert filters.params("")["resolution"] == "1080p"
    category.select_category(2)
    qtbot.waitUntil(lambda: filters.ready)
    assert not filters.video
    assert "resolution" not in filters.params("")
    assert "langue" in filters.options
    filters.clear_button.click()
    assert filters.params("") == {"sortBy": "createdAt", "sortOrder": "desc"}


def test_late_metadata_cannot_replace_current_category_and_failure_can_retry(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "torrentlinker.gui.search_filters.run_in_background",
        lambda work, done, fail: calls.append((work, done, fail)),
    )
    category = CategoryPicker()
    filters = SearchFilters(category)
    qtbot.addWidget(category)
    qtbot.addWidget(filters)
    indexer = fake_indexer(lambda r: httpx.Response(200, json=FACETS))
    filters.configure(indexer)
    calls.pop()[1](parse_tree(TREE))
    category.select_category(1)
    old = calls.pop()
    category.select_category(2)
    current = calls.pop()
    old[1](old[0]())
    assert not filters.ready and not filters.video
    current[2](ValueError("Try again"))
    assert not filters.ready and not filters.retry.isHidden()
    filters.retry.click()
    retried = calls.pop()
    retried[1](retried[0]())
    assert filters.ready and not filters.video and "genre" in filters.options


def test_native_search_paging_keeps_query_snapshot_and_exposes_revival(qtbot, tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/categories":
            data = TREE
        elif request.url.path.endswith("filter-options"):
            data = FACETS
        else:
            data = listing(int(request.url.params["page"]))
        return httpx.Response(200, json=data)

    indexer = fake_indexer(handler)
    view = SearchTab(Store(tmp_path / "state.db"), Settings(), lambda: indexer, FakeQbit)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitUntil(lambda: view.filters.ready)
    view.category.select_category(-6)
    qtbot.waitUntil(lambda: view.filters.ready)
    choose(view.filters.video["resolution"], "1080p")
    view.query.setText("Ocean")
    view.search_button.click()
    qtbot.waitUntil(lambda: not view._searching)
    assert requests[-1].url.params["resolution"] == "1080p"
    assert requests[-1].url.params["subcat"] == "6"
    assert view.results.item(0, 3).text() == "Films & Vidéos / Film"
    assert view.results.item(0, 4).text() == "Soins palliatifs"
    assert "10000" in view.result_status.text()
    assert view.next.isEnabled()
    view.query.setText("Different")
    choose(view.filters.video["resolution"], "720p")
    view.next.click()
    qtbot.waitUntil(lambda: not view._searching)
    assert requests[-1].url.params["page"] == "2"
    assert requests[-1].url.params["name"] == "Ocean"
    assert requests[-1].url.params["resolution"] == "1080p"
    view.search_button.click()
    qtbot.waitUntil(lambda: not view._searching)
    assert requests[-1].url.params["page"] == "1"
    assert requests[-1].url.params["name"] == "Different"
    assert requests[-1].url.params["resolution"] == "720p"
