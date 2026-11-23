"""Static files revalidate, text is gzipped, and streams, ranges and downloads stay as they are."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.testclient import TestClient

from tests.test_media_api import login, media_app, scan
from tests.test_web_jobs import login as owner_login
from torrentlinker.web.app import create_app
from torrentlinker.web.compression import TextGZip


def test_static_files_revalidate_and_answer_304(tmp_path):
    app = create_app(tmp_path, password="test-password-long", monitor_verifications=False)
    with TestClient(app) as browser:
        first = browser.get("/static/app.js")
        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-cache"
        assert first.headers["etag"]
        assert (
            "frame-ancestors"
            in browser.get("/static/shell/view.html").headers["content-security-policy"]
        )
        again = browser.get("/static/app.js", headers={"If-None-Match": first.headers["etag"]})
        assert again.status_code == 304
        assert again.headers["cache-control"] == "no-cache"
        assert (
            browser.get("/static/app.js", headers={"If-None-Match": '"other"'}).status_code == 200
        )


def test_api_stays_no_store_and_a_route_keeps_its_own_cache_control(tmp_path):
    app = create_app(tmp_path, password="test-password-long", monitor_verifications=False)

    @app.get("/healthz-own")
    def own() -> Response:
        return Response("x", headers={"Cache-Control": "private, max-age=60"})

    with TestClient(app) as browser:
        assert browser.get("/").headers["cache-control"] == "no-store"
        owner_login(browser)
        assert browser.get("/api/settings").headers["cache-control"] == "no-store"
        assert browser.get("/healthz-own").headers["cache-control"] == "private, max-age=60"
        assert "default-src 'self'" in browser.get("/").headers["content-security-policy"]


def test_text_is_gzipped_and_json_too(tmp_path):
    app = create_app(tmp_path, password="test-password-long", monitor_verifications=False)
    with TestClient(app) as browser:
        script = browser.get("/static/app.js", headers={"Accept-Encoding": "gzip"})
        assert script.headers["content-encoding"] == "gzip"
        assert script.headers["etag"] and script.text.strip()
        assert (
            "content-encoding"
            not in browser.get("/static/app.js", headers={"Accept-Encoding": "identity"}).headers
        )
        owner_login(browser)
        data = browser.get("/api/settings", headers={"Accept-Encoding": "gzip"})
        assert data.headers["content-encoding"] == "gzip"
        assert data.json()


def test_media_ranges_and_downloads_are_never_compressed(tmp_path):
    app, _ = media_app(tmp_path)
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        item = browser.get("/api/media?client_id=default").json()["rows"][0]
        url = f"/api/media/items/{item['id']}/stream?client_id=default"
        ranged = browser.get(url, headers={"Range": "bytes=0-3", "Accept-Encoding": "gzip"})
        assert ranged.status_code == 206 and "content-encoding" not in ranged.headers
        whole = browser.get(url, headers={"Accept-Encoding": "gzip"})
        assert whole.status_code == 200 and "content-encoding" not in whole.headers
        report = browser.get("/api/diagnostics", headers={"Accept-Encoding": "gzip"})
        assert "attachment" in report.headers["content-disposition"]
        assert "content-encoding" not in report.headers


def test_middleware_compresses_only_text_like_whole_responses():
    app = FastAPI()
    big = "x" * 4000

    @app.get("/json")
    def as_json() -> JSONResponse:
        return JSONResponse({"a": big})

    @app.get("/binary")
    def binary() -> Response:
        return Response(big.encode(), media_type="application/octet-stream")

    @app.get("/video")
    def video() -> StreamingResponse:
        return StreamingResponse(iter([big.encode()]), media_type="video/mp4")

    @app.get("/partial")
    def partial() -> Response:
        return Response(big, status_code=206, media_type="text/plain")

    @app.get("/small")
    def small() -> Response:
        return Response("tiny", media_type="text/plain")

    app.add_middleware(TextGZip)
    with TestClient(app) as browser:
        assert browser.get("/json").headers["content-encoding"] == "gzip"
        assert browser.get("/json").json() == {"a": big}
        for path in ("/binary", "/video", "/partial", "/small"):
            assert "content-encoding" not in browser.get(path).headers, path
