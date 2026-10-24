from fastapi.testclient import TestClient

from torrentlinker.web.app import create_app
from torrentlinker.web.documentation import render


def test_documentation_requires_login_and_serves_only_public_guides(tmp_path):
    with TestClient(create_app(tmp_path, password="test-password-long")) as browser:
        assert browser.get("/api/documentation").status_code == 401
        assert browser.get("/api/documentation/file/guide/images/zen.png").status_code == 401
        browser.post(
            "/api/login", json={"password": "test-password-long"}, headers={"X-TorrentLinker": "1"}
        )
        guides = browser.get("/api/documentation?language=fr").json()
        assert guides[0]["path"] == "guide/fr/demarrage.md"
        page = browser.get("/api/documentation/page/guide/en/getting-started.md").json()["html"]
        assert "Install and configure" in page
        assert 'data-guide="guide/en/web-docker.md"' in page
        assert 'src="api/documentation/file/guide/images/en/' in page
        image = browser.get("/api/documentation/file/guide/images/en/zen.png")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        for path in [
            "page/research/private.md",
            "file/guide/en/getting-started.md",
            "file/%2E%2E/pyproject.toml",
        ]:
            assert browser.get("/api/documentation/" + path).status_code == 404


def test_markdown_escapes_html_and_blocks_remote_images(monkeypatch, tmp_path):
    from torrentlinker import documentation

    page = tmp_path / "example.md"
    page.write_text(
        "<script>alert(1)</script>\n\n![x](https://example.com/image.png)\n\n[unsafe](javascript:alert(1))"
    )
    monkeypatch.setattr(documentation, "document_path", lambda name: page)
    html = render("example.md")
    assert "<script>" not in html
    assert 'src="https://' not in html
    assert 'href="javascript:' not in html
