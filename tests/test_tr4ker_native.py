"""tr4ker native Search and detail (issue 177): synthetic rows, a fake companion session."""

import json
from types import SimpleNamespace

import pytest

from torrentlinker import tr4ker_native
from torrentlinker.companion_downloads import SessionFetchError
from torrentlinker.indexer import Candidate, SearchQuery
from torrentlinker.merged_search import filter_tracker, sort_merged, tr4ker_row
from torrentlinker.tr4ker_account import Tr4kerAccount
from torrentlinker.web.operations import JobRequest, Operations

HASH = "ab" * 20


def listing(*rows):
    return {"limit": 50, "page": 1, "total": 1001, "total_capped": True, "torrents": list(rows)}


def row(n, **extra):
    return {
        "id": n,
        "slug": f"film-{n}-2020-1080p",
        "name": f"Film {n} 2020 1080p",
        "size_bytes": 1000 * n,
        "file_count": 1,
        "seeders": 5 - n,
        "leechers": n,
        "times_completed": 10 * n,
        "is_freeleech": n == 1,
        "created_at": f"2026-11-0{n}T10:00:00Z",
        "parent_cat_slug": "films",
        "parent_cat_name": "Films",
        "tmdb_id": 99,
        "year": 2020,
        **extra,
    }


class Session:
    def __init__(self, body=None, can_read=True, error=None):
        self.body, self.can_read, self.error, self.paths = body, can_read, error, []

    def read_json(self, path, timeout=60.0):
        self.paths.append(path)
        if self.error:
            raise self.error
        return self.body


class Torznab:
    def __init__(self):
        self.queries = []

    def search(self, query: SearchQuery):
        self.queries.append(query)
        return [
            Candidate("Fallback.2020", 5, "https://tr4ker.net/api/torrents/x/download", 1, HASH)
        ]


def test_native_path_uses_only_working_parameters():
    path = tr4ker_native.native_path(
        "big buck", category="films", page=2, limit=500, tmdb_id=10, freeleech=True
    )
    assert path == (
        "/api/torrents?q=big%20buck&cat=films&tmdb_id=10&freeleech=1&sort=recent&page=2&limit=100"
    )
    assert "completed" in tr4ker_native.native_path(sort="completed")


@pytest.mark.parametrize("sort", ["seeders", "title", "size", "leechers"])
def test_broken_sorts_are_never_sent(sort):
    with pytest.raises(ValueError, match="fails on sort"):
        tr4ker_native.native_path("x", sort=sort)
    with pytest.raises(ValueError, match="search_in"):
        tr4ker_native.refuse_broken({"search_in": "title"})


def test_a_listing_becomes_candidates_without_an_info_hash():
    page = tr4ker_native.parse_listing(listing(row(1), {"slug": "../bad", "name": "x"}, "junk"))
    assert page.total == 1001 and page.capped and len(page.rows) == 1
    found = page.rows[0]
    assert found.infohash is None
    assert found.download_url == "https://tr4ker.net/api/torrents/film-1-2020-1080p/download"
    assert found.details_url == "https://tr4ker.net/torrent/film-1-2020-1080p"
    assert found.metadata["freeleech"] is True and found.metadata["tracker"] == "tr4ker"
    assert found.metadata["slug"] == "film-1-2020-1080p" and found.metadata["tr4ker_id"] == 1


def test_seeders_size_and_title_sort_inside_torrentlinker():
    session = Session(listing(row(1), row(2), row(3)))
    page = tr4ker_native.search(session, None, "film", sort="seeders")
    assert [c.seeders for c in page.rows] == [4, 3, 2]
    assert "sort=recent" in session.paths[0] and "sort=seeders" not in session.paths[0]
    assert page.notes and page.backend == "tr4ker-native"
    by_title = tr4ker_native.search(session, None, "film", sort="title")
    assert [c.title for c in by_title.rows] == [
        "Film 3 2020 1080p",
        "Film 2 2020 1080p",
        "Film 1 2020 1080p",
    ]
    by_size = tr4ker_native.search(session, None, "film", sort="size")
    assert by_size.rows[0].size == 3000


def test_without_a_companion_search_falls_back_to_torznab():
    torznab = Torznab()
    page = tr4ker_native.search(Session(can_read=False), torznab, "film", page=2, limit=50)
    assert page.backend == "torznab" and page.rows[0].infohash == HASH
    assert page.rows[0].metadata["tracker"] == "tr4ker"
    assert torznab.queries[0].offset == 50 and torznab.queries[0].limit == 50
    with pytest.raises(ValueError, match="Pair the tr4ker companion"):
        tr4ker_native.search(None, None, "film")


def test_a_native_failure_is_not_hidden_behind_torznab():
    torznab = Torznab()
    session = Session(error=SessionFetchError("The session read was refused.", 500))
    with pytest.raises(SessionFetchError):
        tr4ker_native.search(session, torznab, "film")
    assert torznab.queries == [] and len(session.paths) == 1


DETAIL = {
    "id": 42,
    "slug": "film-1-2020-1080p",
    "info_hash": HASH.upper(),
    "name": "Film 1 2020 1080p",
    "size_bytes": 3000,
    "seeders": 2,
    "leechers": 1,
    "times_completed": 9,
    "created_at": "2026-11-01T10:00:00Z",
    "description": "<p>Synopsis <img src='https://image.example/p.jpg'></p><script>x()</script>",
    "nfo": "General\nFormat : Matroska",
    "tags": ["multi"],
    "poster_url": "https://image.example/poster.jpg",
    "year": 2020,
    "tmdb_id": 99,
    "tmdb_type": "movie",
    "is_freeleech": True,
    "is_anonymous": True,
    "uploader": "someone",
    "cat_name": "Films",
    "sub_cat_name": None,
    "files": [{"path": "a/b.mkv", "size_bytes": 2000}, {"path": "a/b.nfo", "size_bytes": 1000}],
}


def test_detail_has_files_nfo_description_and_separate_identity():
    session = Session(DETAIL)
    document = tr4ker_native.read_detail(session, "film-1-2020-1080p")
    assert session.paths == ["/api/torrents/film-1-2020-1080p"]
    assert document["files"] == (("a/b.mkv", 2000), ("a/b.nfo", 1000))
    assert "Format : Matroska" in document["nfo"] and "<script" not in document["description"]
    assert document["tr4ker"] == {"id": 42, "slug": "film-1-2020-1080p", "info_hash": HASH}
    assert document["info"]["uploader"] == "" and document["info"]["category"] == "Films"
    assert document["info"]["media"]["tmdb_id"] == "99"
    assert document["unavailable"] and document["tracker"] == "tr4ker"
    with pytest.raises(ValueError):
        tr4ker_native.read_detail(session, "../me")


def test_detail_workspace_loads_a_tr4ker_key():
    from torrentlinker.details_workspace import DetailsWorkspace

    workspace = DetailsWorkspace(SimpleNamespace(), tr4ker=Session(DETAIL))
    assert workspace.load("tr4ker:film-1-2020-1080p")["title"] == "Film 1 2020 1080p"
    with pytest.raises(ValueError, match="Pair"):
        DetailsWorkspace(SimpleNamespace()).load("tr4ker:film-1-2020-1080p")


def test_both_trackers_merge_with_a_badge_and_sort_across():
    c411 = {
        "hash": "c" * 40,
        "title": "Film 9",
        "size": 5000,
        "seeders": 3,
        "tracker": "c411",
        "published_at": 1.0,
    }
    one = tr4ker_native.parse_row(row(1))
    assert one is not None
    badge = tr4ker_row("tr4ker:film-1-2020-1080p", one, 0.0)
    assert badge["tracker"] == "tr4ker" and badge["zen"] is None
    by_size = sort_merged([c411, badge], "size")
    assert [r["tracker"] for r in by_size] == ["c411", "tr4ker"]
    assert [r["tracker"] for r in sort_merged([c411, badge], "title")] == ["tr4ker", "c411"]
    same = {**c411, "title": badge["title"]}  # the same release on both stays two rows
    assert len(sort_merged([same, badge], "seeders")) == 2


def test_a_tracker_switched_off_leaves_its_rows_out():
    rows = [{"tracker": "c411", "title": "a"}, {"tracker": "tr4ker", "title": "b"}, {"title": "c"}]
    assert [r["title"] for r in filter_tracker(rows, ["tr4ker"])] == ["b"]
    assert [r["title"] for r in filter_tracker(rows, ["c411"])] == ["a", "c"]


def test_a_tr4ker_key_is_a_valid_selection_but_a_bad_slug_is_not():
    key = "tr4ker:Film-1_2020"
    assert JobRequest(kind="search", hashes=[key, "AB" * 20]).hashes == [key, "ab" * 20]
    with pytest.raises(ValueError, match="Invalid torrent hash"):
        JobRequest(kind="search", hashes=["tr4ker:../x"])


def test_search_offers_tr4ker_once_it_is_added_or_its_companion_is_paired():
    def stub(entry, paired):
        def find(identifier):
            if entry is None:
                raise ValueError("Unknown Indexer.")
            return SimpleNamespace(enabled=entry)

        return SimpleNamespace(
            setup=SimpleNamespace(
                settings=SimpleNamespace(find_indexer=find),
                tr4ker_session=lambda: SimpleNamespace(paired=paired),
            )
        )

    assert Operations.searchable_trackers(stub(None, False)) == ["c411"]
    assert Operations.searchable_trackers(stub(False, False)) == ["c411"]
    assert Operations.searchable_trackers(stub(True, False)) == ["c411", "tr4ker"]
    assert Operations.searchable_trackers(stub(None, True)) == ["c411", "tr4ker"]


def test_operations_adds_tr4ker_rows_and_reports_a_failure():
    stub = SimpleNamespace(
        candidates={},
        setup=SimpleNamespace(
            tr4ker_session=lambda: Session(listing(row(1), row(2))),
            tr4ker_torznab=lambda: None,
            settings=SimpleNamespace(hides=lambda categories: False),
        ),
    )
    request = JobRequest(kind="search", query="film", trackers=["c411", "tr4ker"])
    result = [{"hash": "c" * 40, "title": "Film"}]
    info = Operations.add_tr4ker_rows(stub, request, result, 5.0)
    assert [r["tracker"] for r in result] == ["c411", "tr4ker", "tr4ker"]
    assert result[1]["hash"] == "tr4ker:film-1-2020-1080p" and set(stub.candidates) == {
        "tr4ker:film-1-2020-1080p",
        "tr4ker:film-2-2020-1080p",
    }
    assert info["backend"] == "tr4ker-native" and info["total_capped"] is True
    stub.setup.tr4ker_session = lambda: Session(error=SessionFetchError("refused", 500))
    result = [{"hash": "c" * 40}]
    assert "refused" in Operations.add_tr4ker_rows(stub, request, result, 5.0)["error"]
    assert len(result) == 1  # c411's rows are kept
    assert JobRequest(kind="search").trackers == ["c411"]  # c411 alone is the default


def test_account_read_queue(tmp_path):
    now = [1000.0]
    account = Tr4kerAccount(tmp_path, clock=lambda: now[0])
    account._pair = ("a" * 64, "chrome-extension://" + "a" * 32)
    account.data["account"] = {"id": "7"}
    with pytest.raises(ValueError, match="cannot be read"):
        account.submit_read("/api/me")
    with pytest.raises(ValueError, match="cannot be read"):
        account.submit_read("/api/me/api-key")
    assert not account.can_read
    assert account._poll(5) == {"commands": []} and account.can_read
    identifier = account.submit_read("/api/torrents?q=a&sort=recent")
    command = account._poll(5)["commands"][0]
    assert command == {"id": identifier, "path": "/api/torrents?q=a&sort=recent", "accountId": "7"}
    account._receive_read({"id": identifier, "status": 200, "data": json.dumps(listing())})
    assert account.reads[identifier]["status"] == "complete"
    with pytest.raises(ValueError):
        account._receive_read({"id": identifier, "status": 200, "data": "{}"})
    second = account.submit_read("/api/torrents/some-slug")
    account._poll(1)
    account._receive_read({"id": second, "status": 429, "retryAfter": 5})
    assert account.retry_at >= now[0] + 60
    with pytest.raises(ValueError, match="wait"):
        account.submit_read("/api/torrents/other")
    now[0] += 61
    last = account.submit_read("/api/public/categories")
    account._poll(1)
    account._receive_read({"id": last, "status": 403})
    with pytest.raises(ValueError, match="refused the session"):
        account.submit_read("/api/torrents/other")


def test_read_json_returns_what_the_tab_sent(tmp_path):
    import threading
    import time

    account = Tr4kerAccount(tmp_path)
    account._pair = ("a" * 64, "chrome-extension://" + "a" * 32)
    account.data["account"] = {"id": "7"}

    def browser():
        while True:
            for command in account._poll(5)["commands"]:
                account._receive_read(
                    {"id": command["id"], "status": 200, "data": json.dumps(listing(row(1)))}
                )
                return
            time.sleep(0.01)

    thread = threading.Thread(target=browser)
    thread.start()
    page = tr4ker_native.search(account, None, "film")
    thread.join()
    assert page.rows[0].metadata["slug"] == "film-1-2020-1080p"
    assert account.reads == {}
    with pytest.raises(SessionFetchError):
        account.read_json("/api/me")
