import httpx
import pytest

from tests.test_indexer import FakeClock
from torrentlinker.indexer import Indexer
from torrentlinker.torrent_search import listing_tags, native_search, parse_listing_row, parse_tree

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


RICH_ROW = {
    "leechers": 5,
    "completions": 12,
    "comments": 2,
    "uploader": " Biloute ",
    "isExclusive": True,
    "isFreeleech": False,
    "posterUrl": "https://image.tmdb.org/t/p/w500/x.jpg",
    "media": {"kind": "movie", "title": "Ajami", "year": 2009, "rating": 7.1},
    "tech": {
        "resolution": "1080p",
        "source": "BluRay",
        "videoCodec": "H.264",
        "hdrFormat": "SDR",
        "audioCodec": "AC3",
        "audioChannels": "5.1",
        "languages": ["MULTI", "VFF"],
    },
}


def test_listing_row_reads_the_display_fields():
    row = parse_listing_row(RICH_ROW)
    assert (row.leechers, row.completions, row.comments) == (5, 12, 2)
    assert row.uploader == "Biloute" and row.exclusive and not row.freeleech
    assert (row.title, row.year, row.rating, row.kind) == ("Ajami", 2009, 7.1, "movie")
    assert row.poster_url.startswith("https://image.tmdb.org/")
    assert row.tags == (
        ("lang", "MULTI.VFF"),
        ("resolution", "1080p"),
        ("source", "BluRay"),
        ("audio", "AC3 5.1"),
        ("codec", "H.264"),
    )


def test_listing_row_survives_missing_and_malformed_fields():
    row = parse_listing_row(
        {
            "leechers": "many",
            "completions": -3,
            "posterUrl": "http://insecure.example/p.jpg",
            "media": {"year": 99999, "rating": 0},
            "tech": ["not", "a", "dict"],
        }
    )
    assert row == parse_listing_row({})
    assert row.poster_url == "" and row.tags == () and row.year is None and row.rating is None
    assert listing_tags({"hdrFormat": "HDR10", "resolution": "2160p"}) == (
        ("resolution", "2160p"),
        ("hdr", "HDR10"),
    )


def test_native_search_keeps_details_and_counts_from_the_listing_meta():
    payload = listing()
    payload["data"][0].update(RICH_ROW)
    payload["meta"].update(
        {
            "totalSize": 1757108743727203,
            "categories": [{"id": 1, "count": 138019}, {"id": 2, "count": 39241}, {"id": "x"}],
            "subcategories": [{"id": 6, "name": "Film", "count": 61157}],
        }
    )
    page = native_search(fake_indexer(lambda r: httpx.Response(200, json=payload)), {})
    assert page.details["a" * 40].uploader == "Biloute"
    assert page.root_counts == {1: 138019, 2: 39241}
    assert page.subcategory_counts == {6: 61157}
    assert page.total_size == 1757108743727203
    bare = native_search(fake_indexer(lambda r: httpx.Response(200, json=listing())), {})
    assert bare.root_counts == {} and bare.total_size is None
    assert bare.details["a" * 40].tags == ()


def test_a_release_with_many_languages_shows_the_first_three():
    tags = listing_tags({"languages": ["MULTI", "VFF", "VF", "ANGLAIS", "ESPAGNOL"]})
    assert tags == (("lang", "MULTI.VFF.VF.+2"),)
