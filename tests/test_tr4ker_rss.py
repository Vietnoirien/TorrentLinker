"""tr4ker's passkey RSS feed (issue 180): synthetic XML shaped like the sanitized capture in
docs/research/tr4ker-live-captures.json. The fake passkey must never reach a stored row, a
subscription, an error or a log."""

import json
import logging
import sqlite3

import httpx
import pytest

from torrentlinker import tr4ker_rss
from torrentlinker.feeds import FeedService, Subscription
from torrentlinker.indexer import Candidate

PASSKEY = "FAKE-PASSKEY-0123456789abcdef"
SLUG = "film-one-2020-1080p-1a2b3c4d"


def item(slug=SLUG, guid=None, title="Film One 2020 1080p", free=False, **extra):
    guid = guid or slug
    return f"""<item>
  <title>{title}</title>
  <guid isPermaLink="false">{guid}</guid>
  <link>https://tr4ker.net/torrent/{slug}</link>
  <pubDate>Mon, 23 Nov 2026 10:00:00 +0000</pubDate>
  <category>films</category>
  <enclosure url="https://tr4ker.net/api/torrents/{slug}/download?passkey={PASSKEY}"
    length="123456" type="application/x-bittorrent"/>
  <torznab:attr name="size" value="123456"/>
  <torznab:attr name="seeders" value="4"/>
  <torznab:attr name="peers" value="6"/>
  <torznab:attr name="downloadvolumefactor" value="{0 if free else 1}"/>
  <tr4ker:size>123456</tr4ker:size>
  <tr4ker:seeders>4</tr4ker:seeders>
  <tr4ker:leechers>2</tr4ker:leechers>
  <tr4ker:freeleech>{"true" if free else "false"}</tr4ker:freeleech>
</item>"""


def feed(*items):
    return (
        '<?xml version="1.0"?><rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed"'
        ' xmlns:tr4ker="https://tr4ker.net/rss" xmlns:atom="http://www.w3.org/2005/Atom">'
        "<channel><title>tr4ker</title>" + "".join(items) + "</channel></rss>"
    )


class Site:
    """A fake tr4ker answering feed requests; records every URL asked."""

    def __init__(self, body="", status=200):
        self.body, self.status, self.urls = body, status, []

    def client(self):
        def answer(request):
            self.urls.append(str(request.url))
            return httpx.Response(self.status, text=self.body)

        return httpx.Client(transport=httpx.MockTransport(answer))


class C411:
    url = "https://c411.org/api"

    def __init__(self, rows=()):
        self.rows = list(rows)

    def search(self, query, *, cached):
        return self.rows

    def redact(self, value):
        return value


class Torznab:
    url = "https://tr4ker.net/api"

    def __init__(self, rows=()):
        self.rows, self.queries = list(rows), []

    def search(self, query):
        self.queries.append(query)
        return self.rows

    def redact(self, value):
        return value.replace("KEY", "[secret]")


def service(tmp_path, site=None, c411=None, torznab=None, passkey=PASSKEY):
    return FeedService(
        tmp_path / "feeds.sqlite",
        lambda: c411 or C411(),
        lambda tracker: torznab or Torznab(),
        lambda tracker: passkey,
        site.client() if site else None,
    )


def stored(tmp_path):
    db = sqlite3.connect(tmp_path / "feeds.sqlite")
    return "\n".join(
        str(row) for table in ("subscriptions", "releases", "memberships", "decisions")
        for row in db.execute(f"SELECT * FROM {table}")
    )  # fmt: skip


def test_the_feed_url_carries_the_passkey_category_and_freeleech_only():
    url = tr4ker_rss.feed_url(PASSKEY, "films", True)
    assert url == f"https://tr4ker.net/api/rss?passkey={PASSKEY}&cat=films&freeleech=1"
    assert tr4ker_rss.feed_url(PASSKEY) == f"https://tr4ker.net/api/rss?passkey={PASSKEY}"
    for bad in ("../x", "Films", "a b", "films&x=1"):
        with pytest.raises(ValueError):
            tr4ker_rss.feed_url(PASSKEY, bad)
    with pytest.raises(ValueError, match="passkey"):
        tr4ker_rss.feed_url("")


def test_items_become_rows_without_the_passkey():
    rows = tr4ker_rss.parse_feed(feed(item(), item("other-slug", free=True), item()))
    assert len(rows) == 2  # one per guid
    row = rows[0]
    assert row.infohash == f"tr4ker:{SLUG}" and row.title == "Film One 2020 1080p"
    assert row.download_url == f"https://tr4ker.net/api/torrents/{SLUG}/download"
    assert row.details_url == f"https://tr4ker.net/torrent/{SLUG}"
    assert row.size == 123456 and row.seeders == 4 and row.published_at
    assert row.metadata["leechers"] == 2 and row.metadata["slug"] == SLUG
    assert row.metadata["freeleech"] is False and rows[1].metadata["freeleech"] is True
    assert PASSKEY not in repr(rows)


def test_a_url_off_tr4ker_is_dropped_and_credentials_are_stripped():
    assert tr4ker_rss.clean_url("https://evil.example/api/torrents/x/download?passkey=a") == ""
    assert (
        tr4ker_rss.clean_url("https://tr4ker.net/api/x?passkey=a&apikey=b&k=v")
        == "https://tr4ker.net/api/x?k=v"
    )
    assert tr4ker_rss.redact_passkey(f"GET /a?x=1&passkey={PASSKEY}&y=2") == (
        "GET /a?x=1&passkey=[secret]&y=2"
    )


def test_a_tr4ker_subscription_polls_the_feed_and_dedupes_by_guid(tmp_path, caplog):
    site = Site(feed(item(), item("two-2020", title="Two")))
    feeds = service(tmp_path, site)
    sub = feeds.save(Subscription(name="Films", tracker="tr4ker", feed_category="films"))
    with caplog.at_level(logging.DEBUG):
        feeds.refresh(sub.id, now=100)
    assert site.urls == [f"https://tr4ker.net/api/rss?passkey={PASSKEY}&cat=films"]
    assert {r["infohash"] for r in feeds.inbox()} == {f"tr4ker:{SLUG}", "tr4ker:two-2020"}
    assert all(r["unread"] is False for r in feeds.inbox())  # the first poll is the baseline
    site.body = feed(item("three-2020", title="Three"), item())
    feeds.refresh(sub.id, now=200)
    assert [r["infohash"] for r in feeds.inbox(unread=True)] == ["tr4ker:three-2020"]
    assert len(feeds.inbox()) == 3  # the repeated guid stayed one item
    blob = stored(tmp_path) + caplog.text + json.dumps(feeds.subscriptions())
    assert PASSKEY not in blob and "passkey" not in stored(tmp_path).lower()


def test_the_same_title_on_both_trackers_stays_two_items(tmp_path):
    title = "Film One 2020 1080p"
    c411 = C411([Candidate(title, 5, "https://c411.org/x", 3, "a" * 40)])
    feeds = service(tmp_path, Site(feed(item(title=title))), c411)
    one = feeds.save(Subscription(name="c411", query="film"))
    two = feeds.save(Subscription(name="tr4ker", tracker="tr4ker"))
    feeds.refresh(one.id, now=100)
    feeds.refresh(two.id, now=100)
    rows = feeds.inbox()
    assert sorted(r["title"] for r in rows) == [title, title]
    assert {r["infohash"] for r in rows} == {"a" * 40, f"tr4ker:{SLUG}"}
    assert {s["tracker"] for s in feeds.subscriptions()} == {"c411", "tr4ker"}


def test_a_query_subscription_on_tr4ker_polls_torznab_not_the_feed(tmp_path):
    site = Site(feed(item()))
    torznab = Torznab(
        [Candidate("Q", 5, "https://tr4ker.net/api/torrents/q/download?apikey=KEY", 1, "b" * 40)]
    )
    feeds = service(tmp_path, site, torznab=torznab)
    sub = feeds.save(Subscription(name="Q", tracker="tr4ker", query="film", categories=[2000]))
    feeds.refresh(sub.id, now=100)
    assert site.urls == [] and torznab.queries[0].q == "film"
    row = feeds.inbox()[0]
    assert row["infohash"] == "b" * 40 and row["download_url"].endswith("apikey=[secret]")
    assert row["metadata"]["tracker"] == "tr4ker"


def test_subscription_rules():
    assert Subscription(name="old").tracker == "c411"
    with pytest.raises(ValueError, match="tr4ker subscription"):
        Subscription(name="x", feed_category="films")
    with pytest.raises(ValueError, match="Torznab IDs need a query"):
        Subscription(name="x", tracker="tr4ker", categories=[2000])
    with pytest.raises(ValueError, match="not both"):
        Subscription(name="x", tracker="tr4ker", query="q", freeleech=True)
    assert Subscription(name="x", tracker="tr4ker", freeleech=True).uses_feed
    assert "passkey" not in " ".join(Subscription.model_fields)


def test_existing_subscriptions_stay_c411(tmp_path):
    path = tmp_path / "feeds.sqlite"
    first = FeedService(path, lambda: C411())
    saved = first.save(Subscription(name="Films", categories=[2030]))
    payload = json.loads(first.db.execute("SELECT payload FROM subscriptions").fetchone()[0])
    payload.pop("tracker")
    payload.pop("feed_category")
    payload.pop("freeleech")
    with first.db:
        first.db.execute("UPDATE subscriptions SET payload=?", (json.dumps(payload),))
    again = FeedService(path, lambda: C411())
    assert again.get(saved.id).tracker == "c411"
    assert (
        json.loads(again.db.execute("SELECT payload FROM subscriptions").fetchone()[0])["tracker"]
        == "c411"
    )


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_a_refused_feed_names_the_status_without_the_passkey(tmp_path, status):
    feeds = service(tmp_path, Site("", status))
    sub = feeds.save(Subscription(name="F", tracker="tr4ker"))
    with pytest.raises(tr4ker_rss.FeedRefused) as error:
        feeds.refresh(sub.id, now=100)
    assert str(status) in str(error.value) and PASSKEY not in str(error.value)
    assert PASSKEY not in stored(tmp_path) and str(status) in feeds.subscriptions()[0]["error"]


def test_a_transport_error_and_bad_xml_never_leak_the_url(tmp_path):
    def boom(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    feeds = FeedService(
        tmp_path / "feeds.sqlite", lambda: C411(), lambda t: Torznab(), lambda t: PASSKEY,
        httpx.Client(transport=httpx.MockTransport(boom)),
    )  # fmt: skip
    sub = feeds.save(Subscription(name="F", tracker="tr4ker"))
    with pytest.raises(tr4ker_rss.FeedRefused) as error:
        feeds.refresh(sub.id, now=100)
    assert PASSKEY not in str(error.value) and PASSKEY not in stored(tmp_path)
    bad = service(tmp_path, Site("<rss><oops"))
    with pytest.raises(tr4ker_rss.FeedRefused, match="not valid RSS"):
        bad.refresh(sub.id, now=100)
    missing = service(tmp_path, Site(feed(item())), passkey="")
    with pytest.raises(ValueError, match="passkey"):
        missing.refresh(sub.id, now=100)


def test_a_feed_item_is_never_queued_without_an_info_hash(tmp_path):
    from torrentlinker.store import Store

    feeds = service(tmp_path, Site(feed(item())))
    sub = feeds.save(
        Subscription(
            name="F", tracker="tr4ker", mode="app_queue", folder="/tmp/x", include_current=True
        )
    )
    feeds.refresh(sub.id, now=100)
    store = Store(tmp_path / "queue.sqlite")
    decisions = feeds.process(sub.id, store, present_hashes=set(), present_works=set(), now=200)
    assert decisions[0]["status"] == "blocked" and "no info hash" in decisions[0]["reason"]
