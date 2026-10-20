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
