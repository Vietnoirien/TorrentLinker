import httpx

from torrentlinker.domain import ContentKind
from torrentlinker.tmdb import Tmdb


def test_movie_title_and_year_resolve_to_the_first_tmdb_result() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": [{"id": 194}, {"id": 999}]})

    tmdb = Tmdb("KEY", http=httpx.Client(transport=httpx.MockTransport(handler)))

    assert tmdb.lookup("Amélie", 2001, ContentKind.MOVIE) == "194"
    assert seen[0].url.path == "/3/search/movie"
    assert seen[0].url.params["query"] == "Amélie"
    assert seen[0].url.params["year"] == "2001"


def test_series_are_looked_up_as_tv_and_no_result_gives_none() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    tmdb = Tmdb("KEY", http=httpx.Client(transport=httpx.MockTransport(handler)))

    assert tmdb.lookup("The Show", None, ContentKind.SERIES) is None
    assert seen[0].url.path == "/3/search/tv"
    assert "first_air_date_year" not in seen[0].url.params


def test_details_give_the_french_title_the_original_title_the_year_and_the_synopsis() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": 27205,
                "title": "Inception",
                "original_title": "Inception",
                "release_date": "2010-07-15",
                "overview": "Un voleur.",
            },
        )

    tmdb = Tmdb("KEY", http=httpx.Client(transport=httpx.MockTransport(handler)))

    info = tmdb.details("27205", "movie")

    assert info is not None
    assert (info.id, info.type, info.title, info.year, info.overview) == (
        "27205",
        "movie",
        "Inception",
        "2010",
        "Un voleur.",
    )
    assert info.raw["media_type"] == "movie" and info.raw["id"] == 27205
    assert seen[0].url.path == "/3/movie/27205"
    assert seen[0].url.params["language"] == "fr-FR" and seen[0].url.params["api_key"] == "KEY"


def test_a_series_is_read_with_its_name_fields_and_an_unknown_id_gives_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/1"):
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "name": "Série",
                    "original_name": "Show",
                    "first_air_date": "2019-01-01",
                },
            )
        return httpx.Response(200, json={})

    tmdb = Tmdb("KEY", http=httpx.Client(transport=httpx.MockTransport(handler)))

    info = tmdb.details("1", "tv")
    assert info is not None and (info.title, info.original_title, info.year) == (
        "Série",
        "Show",
        "2019",
    )
    assert tmdb.details("2", "tv") is None
    assert tmdb.details("1", "person") is None
