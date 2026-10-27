from tests import test_catalogue_selection
from tests.test_feeds import Source, release
from torrentlinker.feeds import Subscription
from torrentlinker.gui.feeds import FEED_NAME, FEED_UNREAD, FeedsTab

catalogue_app = test_catalogue_selection.catalogue_app


def test_desktop_feed_sidebar_selection_and_read_state(catalogue_app, qtbot, monkeypatch):
    app, browser, token = catalogue_app
    control = app.state.agent_service.feed_control
    source = Source()
    source.rows = []
    monkeypatch.setattr(control.feeds, "indexer", lambda: source)
    feed = control.feeds.save(Subscription(name="Films"))
    control.feeds.refresh(feed.id)
    source.rows = [release(title="New film")]
    control.feeds.refresh(feed.id)
    widget = FeedsTab(lambda: control)
    qtbot.addWidget(widget)
    widget.show()
    assert widget.sidebar.item(1).data(FEED_NAME) == "Films"
    assert widget.sidebar.item(1).data(FEED_UNREAD) == 1
    widget.sidebar.setCurrentRow(1)
    assert widget.table.rowCount() == 1
    widget.table.selectRow(0)
    widget.mark("read")
    assert widget.sidebar.item(1).data(FEED_UNREAD) == 0
    widget.set_filter(1)
    assert widget.table.rowCount() == 0


def test_desktop_feed_page_header_and_selection_bar(catalogue_app, qtbot, monkeypatch):
    app, browser, token = catalogue_app
    control = app.state.agent_service.feed_control
    widget = FeedsTab(lambda: control)
    qtbot.addWidget(widget)
    widget.show()
    assert widget.stack.currentIndex() == 1  # no subscription yet: the empty state
    source = Source()
    source.rows = [release(title="New film")]
    monkeypatch.setattr(control.feeds, "indexer", lambda: source)
    feed = control.feeds.save(Subscription(name="Films"))
    control.feeds.refresh(feed.id)
    control.set_paused(feed.id, True)
    widget.reload()
    assert widget.stack.currentIndex() == 0
    assert widget.main_action.text() == "New subscription"  # "All feeds" is selected
    widget.sidebar.setCurrentRow(1)
    assert widget.title.text() == "Films"
    assert widget.main_action.text() == "Refresh now"
    assert widget.status.text() == "Paused · Updated 1 min ago"
    assert "Resume" in [a.text() for a in widget.more_menu.actions()]
    assert not widget.selection_bar.isVisible()
    widget.table.selectRow(0)
    assert widget.selection_bar.isVisible()
    assert widget.selection_count.text() == "1 selected"
    assert widget.table.item(0, 1).text() == "1 KiB"
    assert widget.table.item(0, 3).text().startswith("Today")
