from tests import test_catalogue_selection
from tests.test_feeds import Source, release
from torrentlinker.feeds import Subscription
from torrentlinker.gui.feeds import FeedsTab

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
    assert widget.sidebar.item(1).text() == "Films (1)"
    widget.sidebar.setCurrentRow(1)
    assert widget.table.rowCount() == 1
    widget.table.selectRow(0)
    widget.mark("read")
    assert widget.sidebar.item(1).text() == "Films (0)"
    widget.filter.setCurrentIndex(1)
    assert widget.table.rowCount() == 0
