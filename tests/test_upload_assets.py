"""Draft assets remain private, durable and bound to their Local Item."""

import io

import pytest
from PIL import Image

from torrentlinker.upload_assets import Assets

output = io.BytesIO()
Image.new("RGB", (4, 4), "red").save(output, format="PNG")
PNG = output.getvalue()


def test_assets_survive_restart_and_reject_another_item(tmp_path):
    assets = Assets(tmp_path)
    saved = assets.put(PNG, "image/png", "/library/a", {"origin": "embedded_cover"})
    restarted = Assets(tmp_path)
    assert restarted.read(saved["asset_id"], "/library/a")[0] == PNG
    with pytest.raises(ValueError, match="belong"):
        restarted.read(saved["asset_id"], "/library/b")
    with pytest.raises(ValueError):
        restarted.read("../../secret", "/library/a")


def test_private_image_allows_review_but_send_still_requires_hosting(tmp_path):
    from tests.test_upload_completeness import complete_form
    from torrentlinker.agent.upload_presentations import draft_item
    from torrentlinker.store import Store
    from torrentlinker.upload_presentation import assess, require_complete

    store = Store(tmp_path / "state.sqlite")
    assets = Assets(tmp_path)
    asset = assets.put(PNG, "image/png", "/library/book.epub")
    form = complete_form()
    form["description"] = form["description"].replace(
        "[img]https://example.org/cover.jpg[/img]", ""
    )
    form["image"] = ""
    form["assets"] = [asset["asset_id"]]
    evidence = {"file_count": 1, "assets": form["assets"]}
    check = assess(form, evidence, local=True)
    assert check["local_review_ready"] is True
    assert check["send_ready"] is False
    assert check["hosting_required"] is True
    with pytest.raises(ValueError, match="description.image"):
        require_complete(form, evidence)
    draft = {
        "id": "draft",
        "revision": 1,
        "status": "queued",
        "path": "/library/book.epub",
        "form": form,
        "review": {"file_facts": evidence},
        "files": [],
    }
    card = draft_item(draft, "0", store)
    assert card["image_url"].startswith("data:image/png;base64,")
    assert card["description_images"] == [card["image_url"]]
    assert "preview-image:0" in card["description_html"]
