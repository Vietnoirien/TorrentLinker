import httpx
import pytest

from tests.test_indexer import FakeClock
from torrentlinker.indexer import Indexer
from torrentlinker.torrent_search import native_search, parse_tree

TREE = {
    "data": [
        {
            "id": 1,
            "name": "Films & Vidéos",
            "slug": "films-videos",
            "subcategories": [
                {"id": 1, "name": "Animation", "slug": "animation"},
                {"id": 6, "name": "Film", "slug": "film"},
                {"id": 7, "name": "Série TV", "slug": "serie-tv"},
            ],
        },
        {
            "id": 2,
            "name": "Ebook",
            "slug": "ebook",
            "subcategories": [{"id": 11, "name": "Audio", "slug": "audio"}],
        },
    ]
}
FACETS = {
    "data": [
        {
            "slug": "genre",
            "name": "Genre",
            "values": [{"id": 39, "value": "Action"}, {"id": 40, "value": "Animalier"}],
        },
        {"slug": "saison", "name": "Saison", "values": [{"id": 118, "value": "Série intégrale"}]},
        {"slug": "langue", "name": "Langue", "values": [{"id": 200, "value": "Français"}]},
    ]
}


def listing(page=1, total=41789, total_pages=1000):
    return {
        "data": [
            {
                "infoHash": "a" * 40,
                "name": "Example",
                "size": 1000000000,
                "seeders": 0,
                "createdAt": "2026-10-23T10:00:00.000Z",
                "category": {"id": 1, "name": "Films & Vidéos"},
                "subcategory": {"id": 6, "name": "Film"},
                "palliativeSince": "2026-10-23T10:00:00Z",
            }
        ],
        "meta": {"total": total, "page": page, "perPage": 10, "totalPages": total_pages},
    }


def fake_indexer(handler):
    clock = FakeClock()
    return Indexer(
        "https://c411.org/api",
        "test-key",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock.time,
        sleep=clock.sleep,
    )


def test_native_tree_keeps_colliding_root_and_subcategory_ids_distinct():
    tree = parse_tree(TREE)
    assert tree.categories[1].name == "Films & Vidéos"
    assert tree.categories[-1].name == "Animation"
    assert tree.root(-1) == 1
    assert tree.root(-11) == 2
    assert tree.series(1) and tree.series(-7)
    assert not tree.series(-6)


def test_native_request_uses_server_pagination_and_normal_download_destinations():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=listing())

    indexer = fake_indexer(handler)
    page = native_search(
        indexer, {"category": "1", "subcat": "6", "resolution": "1080p", "palliative": "only"}
    )
    assert requests[0].url.path == "/api/torrents"
    assert requests[0].headers["Authorization"] == "Bearer test-key"
    assert requests[0].url.params["resolution"] == "1080p"
    assert requests[0].url.params["palliative"] == "only"
    assert requests[0].url.params["viewMode"] == "flat"
    assert page.has_more and page.limited  # Short response still has further pages.
    assert page.rows[0].categories == (2030,)
    from datetime import UTC, datetime

    assert page.rows[0].published_at == datetime(2026, 10, 23, 10, tzinfo=UTC).timestamp()
    assert page.labels["a" * 40] == "Films & Vidéos / Film"
    assert "a" * 40 in page.palliative
    assert (
        page.rows[0].download_url
        == "https://c411.org/api?t=get&id=" + "a" * 40 + "&apikey=test-key"
    )
    last = native_search(fake_indexer(lambda r: httpx.Response(200, json=listing(1000))), {}, 1000)
    assert not last.has_more


def test_zero_seeders_alone_does_not_imply_revival():
    payload = listing()
    payload["data"][0]["palliativeSince"] = None
    page = native_search(fake_indexer(lambda r: httpx.Response(200, json=payload)), {})
    assert not page.palliative


def test_invalid_hash_cannot_be_used_to_build_a_download_url():
    payload = listing()
    payload["data"][0]["infoHash"] = "../something"
    with pytest.raises(ValueError, match="hash"):
        native_search(fake_indexer(lambda r: httpx.Response(200, json=payload)), {})


def test_search_metadata_uses_root_filter_options_not_upload_options():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=TREE if request.url.path == "/api/categories" else FACETS)

    indexer = fake_indexer(handler)
    assert indexer.search_categories() == TREE
    assert indexer.search_filter_options(1) == FACETS
    assert [r.url.path for r in requests] == ["/api/categories", "/api/categories/1/filter-options"]
    assert all(r.headers["Authorization"] == "Bearer test-key" for r in requests)
