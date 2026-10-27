import httpx
import pytest

from torrentlinker.poster_cache import MAX_BYTES, PosterCache, valid_poster_url

URL = "https://image.tmdb.org/t/p/w500/abc.jpg"


@pytest.mark.parametrize(
    "url",
    [
        "http://image.tmdb.org/t/p/w500/a.jpg",
        "https://evil.example/t/p/w500/a.jpg",
        "https://image.tmdb.org.evil.example/t/p/w500/a.jpg",
        "https://user:pw@image.tmdb.org/t/p/w500/a.jpg",
        "https://image.tmdb.org:8443/t/p/w500/a.jpg",
        "https://image.tmdb.org/other/a.jpg",
        "https://image.tmdb.org/t/p/../../x",
        "file:///etc/passwd",
        "",
    ],
)
def test_only_plain_https_tmdb_images_are_allowed(url):
    assert not valid_poster_url(url)


def test_a_tmdb_poster_url_is_allowed():
    assert valid_poster_url(URL)


def cache(tmp_path, handler, **kwargs):
    return PosterCache(
        tmp_path / "posters",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


def image(request):
    return httpx.Response(200, content=b"\x89PNG-bytes", headers={"content-type": "image/png"})


def test_a_poster_is_fetched_once_and_then_read_from_disk(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return image(request)

    posters = cache(tmp_path, handler)
    assert posters.cached(URL) is None
    assert posters.fetch(URL) == b"\x89PNG-bytes"
    assert posters.fetch(URL) == b"\x89PNG-bytes"
    assert posters.cached(URL) == b"\x89PNG-bytes"
    assert len(requests) == 1
    # Nothing identifying travels with the request: no key, cookie or authorization.
    assert not {"authorization", "cookie"} & set(requests[0].headers)


def test_unsafe_or_unusable_answers_give_no_poster_and_are_not_kept(tmp_path):
    answers = iter(
        [
            httpx.Response(404, content=b"x", headers={"content-type": "image/png"}),
            httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}),
            httpx.Response(
                200, content=b"x" * (MAX_BYTES + 1), headers={"content-type": "image/png"}
            ),
            httpx.Response(302, headers={"location": "https://evil.example/a.png"}),
        ]
    )
    posters = cache(tmp_path, lambda request: next(answers))
    for _ in range(4):
        assert posters.fetch(URL) is None
    assert posters.cached(URL) is None


def test_a_network_error_gives_no_poster(tmp_path):
    def boom(request):
        raise httpx.ConnectError("down")

    assert cache(tmp_path, boom).fetch(URL) is None


def test_other_hosts_are_never_requested(tmp_path):
    requests = []
    posters = cache(tmp_path, lambda r: requests.append(r) or image(r))
    assert posters.fetch("https://evil.example/t/p/w500/a.jpg") is None
    assert requests == []


def test_the_oldest_posters_are_dropped_beyond_the_limit(tmp_path):
    import os

    posters = cache(tmp_path, image, max_files=3)
    urls = [f"https://image.tmdb.org/t/p/w500/{n}.jpg" for n in range(5)]
    for age, url in enumerate(urls):
        posters.fetch(url)
        os.utime(posters.path(url), (1000 + age, 1000 + age))
    posters.fetch("https://image.tmdb.org/t/p/w500/last.jpg")
    kept = sorted(p.name for p in posters.folder.glob("*.img"))
    assert len(kept) == 3
    assert posters.path(urls[0]).name not in kept and posters.path(urls[1]).name not in kept
