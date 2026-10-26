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


def test_epub_pack_extraction_has_one_shared_bound_and_reports_remaining_covers(tmp_path):
    import zipfile

    from torrentlinker.matching import IgnoreList
    from torrentlinker.scan import scan_item
    from torrentlinker.upload import UploadRequest, upload_files
    from torrentlinker.web.uploads import UploadForm

    books = tmp_path / "books"
    books.mkdir()
    for number in range(25):
        with zipfile.ZipFile(books / f"{number}.epub", "w") as archive:
            archive.writestr("cover.png", PNG)
    item = scan_item(books)
    files = upload_files(item, "Pack.EPUB", IgnoreList.default())
    request = UploadRequest(item, "Pack.EPUB", files, "", "", 2, 14, {}, {})
    evidence = {"ebooks": [{"file": file.local_path, "artwork": ["cover.png"]} for file in files]}
    assets = Assets(tmp_path / "config")
    result = assets.extract(request, evidence)
    assert len(result["assets"]) == 12
    assert result["remaining"] == 13
    assert result["errors"] == []
    assert len(list(assets.directory.glob("*.image"))) == 12
    UploadForm(assets=[asset["asset_id"] for asset in result["assets"]])
