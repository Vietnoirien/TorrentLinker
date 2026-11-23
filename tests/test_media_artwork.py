"""Posters as small cached WebP copies: generated once, never stale, still checked."""

import random
import threading
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.test_media_api import login, media_app, scan


def poster(path: Path, colour: str, size=(1000, 1500), fmt="JPEG") -> None:
    picture = Image.new("RGB", size, colour)
    noise = random.Random(colour)
    for _ in range(400):  # a flat image compresses to nothing: make the original a real size
        box = (noise.randrange(size[0]), noise.randrange(size[1]))
        picture.paste(
            tuple(noise.randrange(256) for _ in range(3)),
            (*box, min(size[0], box[0] + 60), min(size[1], box[1] + 60)),
        )
    picture.save(path, format=fmt, quality=95)


def shown(browser):
    rows = browser.get("/api/media?client_id=default&kind=music").json()["rows"]
    return rows[0]


def test_grid_and_hero_are_webp_of_their_width_and_far_smaller(tmp_path):
    app, root = media_app(tmp_path)
    poster(root / "track.jpg", "#335577")
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        url = "/" + shown(browser)["artwork_url"]
        original = browser.get(url)
        assert original.headers["content-type"] == "image/jpeg"
        for size, width in (("grid", 342), ("hero", 780)):
            image = browser.get(url + f"&size={size}")
            assert image.status_code == 200, image.text
            assert image.headers["content-type"] == "image/webp"
            with Image.open(BytesIO(image.content)) as copy:
                assert copy.format == "WEBP" and copy.width == width
            assert len(image.content) < len(original.content)
        assert browser.get(url + "&size=huge").status_code == 422


def test_a_size_is_generated_once_and_the_local_poster_read_once_per_size(tmp_path, monkeypatch):
    app, root = media_app(tmp_path)
    poster(root / "track.jpg", "#335577")
    opened = []
    real = Image.open

    def counting(target, *args, **kwargs):
        if str(target).endswith("track.jpg"):
            opened.append(str(target))
        return real(target, *args, **kwargs)

    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        url = "/" + shown(browser)["artwork_url"]
        monkeypatch.setattr(Image, "open", counting)
        for _ in range(3):
            assert browser.get(url + "&size=grid").status_code == 200
        assert len(opened) == 1
        assert browser.get(url + "&size=hero").status_code == 200
        assert len(opened) == 2


def test_two_threads_asking_for_one_size_generate_it_once(tmp_path, monkeypatch):
    app, root = media_app(tmp_path)
    poster(root / "track.jpg", "#335577")
    opened = []
    real = Image.open

    def counting(target, *args, **kwargs):
        if str(target).endswith("track.jpg"):
            opened.append(1)
        return real(target, *args, **kwargs)

    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        url = "/" + shown(browser)["artwork_url"]
        monkeypatch.setattr(Image, "open", counting)
        results = []
        gate = threading.Barrier(6)

        def ask():
            gate.wait()
            results.append(browser.get(url + "&size=grid").content)

        threads = [threading.Thread(target=ask) for _ in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(opened) == 1 and len({bytes(r) for r in results}) == 1


def test_the_versioned_url_is_immutable_and_every_response_has_an_etag_for_304(tmp_path):
    app, root = media_app(tmp_path)
    poster(root / "track.jpg", "#335577")
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        link = shown(browser)["artwork_url"]
        assert "&v=" in link
        versioned = browser.get("/" + link + "&size=grid")
        assert versioned.headers["cache-control"] == "private, max-age=31536000, immutable"
        etag = versioned.headers["etag"]
        again = browser.get("/" + link + "&size=grid", headers={"If-None-Match": etag})
        assert again.status_code == 304 and not again.content
        assert again.headers["etag"] == etag
        assert "immutable" in again.headers["cache-control"]
        bare = browser.get("/" + link.split("&v=")[0] + "&size=grid")
        assert bare.headers["cache-control"] == "private, no-cache" and bare.headers["etag"] == etag
        whole = browser.get("/" + link)  # no size: today's behaviour, now revalidatable
        assert whole.headers["content-type"] == "image/jpeg" and whole.headers["etag"]
        assert (
            browser.get("/" + link, headers={"If-None-Match": whole.headers["etag"]}).status_code
            == 304
        )


def test_another_poster_for_the_item_is_never_a_stale_copy(tmp_path):
    app, root = media_app(tmp_path)
    poster(root / "track.jpg", "#cc2222")
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        first = shown(browser)["artwork_url"]
        before = browser.get("/" + first + "&size=grid")
        # The same file replaced in place: the copy is keyed by where, when and how big.
        poster(root / "track.jpg", "#2222cc", size=(900, 1350))
        after = browser.get("/" + first + "&size=grid")
        assert after.content != before.content and after.headers["etag"] != before.headers["etag"]
        with Image.open(BytesIO(after.content)) as copy:
            assert copy.getpixel((1, 1))[2] > copy.getpixel((1, 1))[0]
        # The next scan sees the change: the row's URL changes with the poster.
        scan(browser)
        assert shown(browser)["artwork_url"] != first


def test_a_symlinked_or_unregistered_poster_is_still_refused(tmp_path):
    app, root = media_app(tmp_path)
    poster(root / "track.jpg", "#335577")
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        url = "/" + shown(browser)["artwork_url"]
        assert browser.get(url + "&size=grid").status_code == 200
        real = tmp_path / "elsewhere.jpg"
        (root / "track.jpg").rename(real)
        (root / "track.jpg").symlink_to(real)
        assert browser.get(url + "&size=grid").status_code == 404
        assert browser.get(url).status_code == 404


def test_an_item_without_a_poster_has_no_artwork_to_request(tmp_path):
    app, _ = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        item = shown(browser)
        assert item["artwork_url"] == ""
        url = f"/api/media/items/{item['id']}/artwork?client_id=default&size=grid"
        assert browser.get(url).status_code == 404


def test_a_corrupt_poster_is_a_404_not_a_crash(tmp_path):
    app, root = media_app(tmp_path)
    (root / "track.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        url = "/" + shown(browser)["artwork_url"]
        assert browser.get(url + "&size=grid").status_code == 404


@pytest.mark.parametrize("size", ["grid", "hero"])
def test_an_embedded_cover_and_a_cached_poster_have_variants(tmp_path, size):
    from mutagen.flac import FLAC, Picture

    app, root = media_app(tmp_path)
    cover_data = BytesIO()
    Image.new("RGB", (1400, 1400), "#cc5533").save(cover_data, format="PNG")
    audio = FLAC(root / "track.flac")
    cover = Picture()
    cover.type, cover.mime, cover.data = 3, "image/png", cover_data.getvalue()
    audio.add_picture(cover)
    audio.save()
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        link = shown(browser)["artwork_url"]
        image = browser.get("/" + link + f"&size={size}")
        assert image.status_code == 200 and image.headers["content-type"] == "image/webp"
        variants = tmp_path / "config" / "media-artwork" / "variants"
        assert [p.suffix for p in variants.iterdir()] == [".webp"]
