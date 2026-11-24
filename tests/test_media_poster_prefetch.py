"""Remote posters are cached with their grid and hero sizes by the scan, never on first view."""

import json
import threading
import time
from io import BytesIO

from PIL import Image

from tests.test_media_release_details import library
from torrentlinker import media_artwork


def png(colour="#336699") -> bytes:
    out = BytesIO()
    Image.new("RGB", (900, 1350), colour).save(out, format="PNG")
    return out.getvalue()


def films(tmp_path, count=2):
    media = library(tmp_path, [(f"Film {n}", "2020") for n in range(count)])
    media.checked_path = lambda *a: None  # these rows are not real files

    def record(client, identifier):
        with media.lock:
            return media.db.execute(
                "SELECT * FROM media_items WHERE client=? AND id=?", (client, identifier)
            ).fetchone()

    media.record = record
    with media.db:
        for n in range(count):
            row = media.db.execute("SELECT body FROM media_items WHERE id=?", (str(n),)).fetchone()
            body = json.loads(row[0])
            body["remote_artwork"] = f"https://image.tmdb.org/t/p/w500/{n}.jpg"
            media.db.execute("UPDATE media_items SET body=? WHERE id=?", (json.dumps(body), str(n)))
    return media


def body(media, n):
    return json.loads(
        media.db.execute("SELECT body FROM media_items WHERE id=?", (str(n),)).fetchone()[0]
    )


def test_the_scan_caches_every_remote_poster_with_both_sizes(tmp_path, monkeypatch):
    media = films(tmp_path)
    monkeypatch.setattr(
        "torrentlinker.assistant.images.fetch_image", lambda url: (png(), "image/png")
    )
    seen = []
    done = media.prefetch_posters("default", threading.Event(), seen.append)
    assert done == 2 and seen[-1] == {"posters": 2}
    folder = tmp_path / "media-artwork"
    for n in range(2):
        asset = body(media, n)["artwork"]
        assert asset.startswith("asset:")
        # The stored poster is a WebP; its variants are named from the stem, not the suffix.
        key = asset.removeprefix("asset:").rsplit(".", 1)[0]
        for size in media_artwork.WIDTHS:
            assert (folder / "variants" / f"{key}-{size}.webp").is_file()


def test_a_failing_poster_does_not_fail_and_is_retried_next_time(tmp_path, monkeypatch):
    media = films(tmp_path)
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith("0.jpg") and len(calls) < 3:
            raise ValueError("Use a public HTTP(S) image URL.")
        return png(), "image/png"

    monkeypatch.setattr("torrentlinker.assistant.images.fetch_image", fetch)
    assert media.prefetch_posters("default", threading.Event(), lambda _p: None) == 1
    assert not body(media, 0)["artwork"] and body(media, 1)["artwork"]
    assert media.prefetch_posters("default", threading.Event(), lambda _p: None) == 2
    assert body(media, 0)["artwork"]


def test_two_requests_for_an_uncached_poster_download_it_once(tmp_path, monkeypatch):
    media = films(tmp_path, 1)
    calls = []

    def slow(url):
        calls.append(url)
        time.sleep(0.1)
        return png(), "image/png"

    monkeypatch.setattr("torrentlinker.assistant.images.fetch_image", slow)
    gate = threading.Barrier(5)

    def ask():
        gate.wait()
        media.artwork("default", "0")

    threads = [threading.Thread(target=ask) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1


def test_a_cancelled_scan_downloads_no_more_posters(tmp_path, monkeypatch):
    media = films(tmp_path, 3)
    calls = []
    monkeypatch.setattr(
        "torrentlinker.assistant.images.fetch_image",
        lambda url: calls.append(url) or (png(), "image/png"),
    )
    stop = threading.Event()
    stop.set()
    assert media.prefetch_posters("default", stop, lambda _p: None) == 0
    assert calls == []


def test_the_wait_is_bounded(tmp_path, monkeypatch):
    media = films(tmp_path, 3)
    calls = []
    monkeypatch.setattr(
        "torrentlinker.assistant.images.fetch_image",
        lambda url: calls.append(url) or (png(), "image/png"),
    )
    assert media.prefetch_posters("default", threading.Event(), lambda _p: None, limit=-1) == 0
    assert calls == []
