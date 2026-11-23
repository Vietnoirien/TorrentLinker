"""The desktop Médias bridge hands over the small WebP covers, not the full-size poster."""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.test_media_api import login, media_app, scan
from tests.test_media_artwork import poster, shown


def test_the_desktop_bridge_hands_over_the_small_webp_as_a_data_url(tmp_path):
    import base64

    from torrentlinker.media_browser import MediaBrowserService

    app, root = media_app(tmp_path)
    poster(root / "track.jpg", "#335577")
    with TestClient(app) as browser:
        login(browser)
        scan(browser)
        item = shown(browser)
        service = MediaBrowserService(app.state.agent_service)
        base = f"media/items/{item['id']}/artwork?client_id=default"
        whole = service.request(base)["data_url"]
        assert whole.startswith("data:image/jpeg;base64,")
        for size, width in (("grid", 342), ("hero", 780)):
            url = service.request(f"{base}&size={size}")["data_url"]
            assert url.startswith("data:image/webp;base64,")
            data = base64.b64decode(url.split(",", 1)[1])
            with Image.open(BytesIO(data)) as copy:
                assert copy.width == width
            assert len(data) < len(base64.b64decode(whole.split(",", 1)[1]))
        with pytest.raises(ValueError, match="size"):
            service.request(f"{base}&size=huge")
