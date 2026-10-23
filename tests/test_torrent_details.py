import httpx
import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QUrl
from PySide6.QtGui import QImage, QTextDocument

from tests.test_torrent_search import fake_indexer
from torrentlinker.gui.torrent_details import TorrentDetailsDialog, decode_preview
from torrentlinker.indexer import Candidate, Indexer
from torrentlinker.torrent_details import fetch_image, parse_details, preview_html, website_url

DETAILS = {
    "name": "Example",
    "descriptionFormat": "standard",
    "description": '<h2>Synopsis</h2><p>A journey.</p><img src="https://images.example/poster.png">',
    "metadata": {
        "hasNfo": True,
        "nfoContent": "┌── NFO ──┐\n<plain text>\n1080p",
        "tmdbData": {"posterUrl": "https://images.example/poster.png"},
    },
    "files": [{"path": ["Folder", "film.mkv"], "length": 1024}],
}


def png():
    image = QImage(60, 80, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.darkCyan)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def test_details_parse_flat_response_and_preserve_nfo_as_plain_text():
    details = parse_details(DETAILS)
    assert details.nfo == "┌── NFO ──┐\n<plain text>\n1080p"
    assert details.has_nfo
    assert details.files == (("Folder/film.mkv", 1024),)
    rendered, images = preview_html(details.description, details.poster)
    assert "<h2>Synopsis</h2>" in rendered
    assert images == ("https://images.example/poster.png",)
    assert '<img src="preview-image:0"' in rendered


def test_preview_strips_active_content_and_local_resources_but_keeps_formatting():
    rendered, images = preview_html("""<script>alert(1)</script><style>body{color:red}</style>
      <p style="background:url(file:///etc/passwd)">Hello <strong>world</strong></p>
      <img src="file:///etc/passwd"><img src="https://images.example/a.png" onerror="alert(2)">
      <a href="javascript:alert(3)">bad</a><a href="https://example.org/info">good</a>""")
    assert "alert" not in rendered and "file:" not in rendered and "javascript:" not in rendered
    assert "<strong>world</strong>" in rendered and 'href="https://example.org/info"' in rendered
    assert images == ("https://images.example/a.png",)
    markup, images = preview_html(
        "[b]Title[/b]\n[img]https://images.example/b.png[/img]", "https://images.example/a.png"
    )
    assert "<b>Title</b>" in markup
    assert len(images) == 2


def test_website_links_use_hash_and_reject_non_web_schemes():
    indexer = fake_indexer(lambda r: httpx.Response(200, json=DETAILS))
    assert (
        website_url(Candidate("title", 1, "download", infohash="A" * 40), indexer)
        == "https://c411.org/torrents/" + "a" * 40
    )
    generic = Indexer("https://example.test/api", "key")
    assert not website_url(
        Candidate("title", 1, "download", details_url="file:///tmp/file"), generic
    )
    assert (
        website_url(
            Candidate("title", 1, "download", details_url="https://example.test/details"), generic
        )
        == "https://example.test/details"
    )


def test_image_requests_do_not_send_api_credentials_or_follow_local_redirects(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    monkeypatch.setattr(
        "torrentlinker.torrent_details.net.client",
        lambda **kw: httpx.Client(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(ValueError, match="Local"):
        fetch_image("https://images.example/a.png")
    assert len(seen) == 1
    assert "authorization" not in seen[0].headers and "cookie" not in seen[0].headers


def test_image_byte_limit_and_decoder(monkeypatch, qtbot):
    monkeypatch.setattr("torrentlinker.torrent_details.MAX_IMAGE_BYTES", 8)
    monkeypatch.setattr(
        "torrentlinker.torrent_details.net.client",
        lambda **kw: httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, content=b"a" * 9, headers={"content-type": "image/png"}
                )
            ),
            **kw,
        ),
    )
    with pytest.raises(ValueError, match="exceeds"):
        fetch_image("https://images.example/a.png")
    assert not decode_preview(png()).isNull()
    with pytest.raises(ValueError):
        decode_preview(b"not image data")


def test_dialog_previews_description_nfo_files_and_image_without_torrent_download(
    qtbot, monkeypatch
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=DETAILS)

    monkeypatch.setattr("torrentlinker.gui.torrent_details.fetch_image", lambda url: png())
    dialog = TorrentDetailsDialog(
        Candidate("Example", 1024, "DO NOT DOWNLOAD", 2, "a" * 40),
        fake_indexer(handler),
        "≈ 0.25",
        "Estimate",
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.reload.isEnabled() and not dialog.status.text())
    assert [r.url.path for r in requests] == ["/api/torrents/" + "a" * 40]
    assert "Synopsis" in dialog.description.toPlainText()
    assert dialog.nfo.toPlainText() == DETAILS["metadata"]["nfoContent"]
    assert dialog.files.item(0, 0).text() == "Folder/film.mkv"
    image = dialog.description.document().resource(
        QTextDocument.ResourceType.ImageResource, QUrl("preview-image:0")
    )
    assert isinstance(image, QImage) and not image.isNull()
    assert dialog.description.loadResource(2, QUrl("file:///etc/passwd")) is None
    dialog.close()


def test_late_details_after_close_are_ignored_and_failures_allow_retry(qtbot, monkeypatch):
    jobs = []
    monkeypatch.setattr(
        "torrentlinker.gui.torrent_details.run_in_background",
        lambda work, done, fail: jobs.append((work, done, fail)),
    )
    dialog = TorrentDetailsDialog(
        Candidate("Example", 1, "download", infohash="b" * 40),
        fake_indexer(lambda r: httpx.Response(200, json=DETAILS)),
        "≈ 0.10",
        "Estimate",
    )
    qtbot.addWidget(dialog)
    dialog.show()
    jobs.pop()[2](ValueError("Unavailable"))
    assert dialog.reload.isEnabled() and "Unavailable" in dialog.status.text()
    dialog.reload.click()
    assert not dialog.reload.isEnabled()
    dialog.close()
    jobs.pop()[1](parse_details(DETAILS))
    assert not jobs  # No image fetches after closing.


def test_large_valid_cover_is_not_rejected_by_old_ten_mib_limit(monkeypatch, qtbot):
    # The reported cover is a 17,018,281-byte PNG, well within the decoder's pixel limit.
    content = png() + b"\0" * 17_018_281
    monkeypatch.setattr(
        "torrentlinker.torrent_details.net.client",
        lambda **kw: httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, content=content, headers={"content-type": "image/png"}
                )
            ),
            **kw,
        ),
    )
    assert not decode_preview(fetch_image("https://images.example/cover.png")).isNull()


def test_description_centers_blocks_and_preserves_explicit_alignment(qtbot):
    from torrentlinker.gui.torrent_details import DescriptionBrowser

    browser = DescriptionBrowser()
    qtbot.addWidget(browser)
    markup, _ = preview_html(
        '<h2>Heading</h2><p>Summary</p><p style="text-align: right">Credit</p>'
    )
    browser.setHtml(markup)
    block = browser.document().begin()
    alignments = {}
    while block.isValid():
        if block.text():
            alignments[block.text()] = block.blockFormat().alignment()
        block = block.next()
    assert alignments["Heading"] & Qt.AlignmentFlag.AlignHCenter
    assert alignments["Summary"] & Qt.AlignmentFlag.AlignHCenter
    assert alignments["Credit"] & Qt.AlignmentFlag.AlignRight


def test_failed_images_use_compact_links_and_host_cooldown_then_retry(qtbot, monkeypatch):
    payload = {
        "description": '<p><img src="https://limited.example/a.png"></p><p><img src="https://limited.example/b.png"></p>',
        "metadata": {},
    }
    calls = []

    def limited(url):
        calls.append(url)
        response = httpx.Response(
            429, headers={"Retry-After": "120"}, request=httpx.Request("GET", url)
        )
        response.raise_for_status()

    monkeypatch.setattr("torrentlinker.gui.torrent_details.fetch_image", limited)
    dialog = TorrentDetailsDialog(
        Candidate("Example", 1, "", infohash="a" * 40),
        fake_indexer(lambda r: httpx.Response(200, json=payload)),
        "0.1",
        "",
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._image_failures == 2)
    assert len(calls) == 1
    assert "<img " not in dialog.description.toHtml()
    assert "HTTP 429" in dialog.description.toPlainText()
    assert not dialog.retry_images.isEnabled()
    dialog._host_retry.clear()
    dialog._update_image_retry()
    monkeypatch.setattr("torrentlinker.gui.torrent_details.fetch_image", lambda url: png())
    dialog.retry_images.click()
    qtbot.waitUntil(lambda: len(dialog._loaded_images) == 2 and not dialog._images_busy)
    assert not dialog._image_errors and not dialog.status.text()
    assert "<img " in dialog.description.toHtml()
    dialog.close()


def test_details_window_has_download_actions_bound_to_its_candidate_and_folder(qtbot):
    actions = []
    dialog = TorrentDetailsDialog(
        Candidate("Example", 1, "", infohash="a" * 40),
        Indexer("https://example.test/api", "key"),
        "–",
        "",
        download=lambda folder, now: actions.append((folder, now)) or "Done",
        folder="/tmp/downloads",
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.add_queue.click()
    dialog.download_now.click()
    assert actions == [("/tmp/downloads", False), ("/tmp/downloads", True)]
    assert dialog.action_status.text() == "Done"
    dialog.close()
