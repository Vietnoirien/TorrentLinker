"""Upload review rejects incomplete presentations without losing editable drafts."""

import pytest

from torrentlinker.upload_presentation import assess, requirements


def complete_form(category=2, subcategory=14):
    contract = requirements(category, subcategory)
    values = {
        "title": "Alice au pays des merveilles",
        "author": "Lewis Carroll",
        "language": "Français",
        "format": "EPUB",
        "files": "1",
        "size": "185 KiB",
        "subtitles": "Aucun",
        "tracklist": "01. Silence (00:01)",
    }
    description = "[img]https://example.org/cover.jpg[/img]\n[h3]Présentation[/h3]\n"
    description += (
        "Alice suit un lapin blanc et découvre un monde peuplé de "
        "créatures étranges.\n[h3]Informations[/h3]\n"
    )
    description += "\n".join(
        f"[b]{field['label']} :[/b] {values.get(field['id'], 'Verified facts from this release')}"
        for field in contract["fields"]
    )
    return dict(
        category=category,
        subcategory=subcategory,
        title="Alice.FR.EPUB-NOTAG",
        image="https://example.org/cover.jpg",
        description=description,
        nfo="\n".join(
            f"{field['label']} : {values.get(field['id'], 'Verified facts from this release')}"
            for field in contract["fields"]
        ),
    )


def test_one_sentence_cannot_replace_the_ebook_presentation():
    form = complete_form()
    form["description"] = "[img]https://example.org/cover.jpg[/img]\nL’œuvre de Lewis Carroll."
    result = assess(form)
    assert result["status"] == "incomplete"
    assert {row["field"] for row in result["missing_fields"]} >= {
        "description.synopsis",
        "description.author",
        "description.language",
        "description.format",
    }
    assert all(row["message"] for row in result["missing_fields"])


@pytest.mark.parametrize(
    "category,subcategory", [(1, 6), (2, 14), (3, 18), (4, 23), (5, 36), (6, 38), (7, 39), (10, 51)]
)
def test_category_templates_have_named_requirements_and_reject_blanks(category, subcategory):
    contract = requirements(category, subcategory)
    form = complete_form(category, subcategory)
    assert assess(form)["status"] == "complete"
    form["description"] = contract["template"]
    assert assess(form)["status"] == "incomplete"
    assert contract["fields"] and contract["source"]


@pytest.mark.parametrize("placeholder", ["", "?", "À compléter", "Unknown", "...", "TODO"])
def test_placeholder_is_not_a_filled_field(placeholder):
    form = complete_form()
    form["description"] = form["description"].replace("Lewis Carroll", placeholder)
    assert "description.author" in {x["field"] for x in assess(form)["missing_fields"]}


def test_foreign_ebook_language_is_not_accepted_as_french():
    form = complete_form()
    form["description"] = form["description"].replace("Français", "English")
    result = assess(form)
    assert any(
        x["field"] == "description.language" and "French" in x["message"]
        for x in result["missing_fields"]
    )


def test_conditional_requirements_and_unsupported_category():
    form = complete_form(1, 6)
    form["description"] = form["description"].replace(
        "[b]Source :[/b] Verified facts from this release", "[b]Source :[/b] WEB-DL"
    )
    assert "description.platform" in {x["field"] for x in assess(form)["missing_fields"]}
    assert assess({**form, "category": 999})["status"] == "incomplete"


def complete_description(category=10, subcategory=51, text="Reviewed description"):
    return complete_form(category, subcategory)["description"].replace(
        "Alice suit un lapin blanc et découvre un monde peuplé de créatures étranges.", text
    )


def test_file_metadata_rejects_an_english_epub_even_when_form_claims_french(tmp_path):
    from tests.test_assistant_uploads_live import sample_file
    from torrentlinker.upload_presentation import epub_languages

    path = sample_file(tmp_path / "ebook", "ebook")
    languages = epub_languages(path)
    assert languages == ["en"]
    result = assess(
        complete_form(), {"file_count": 1, "ebooks": [{"file": path.name, "languages": languages}]}
    )
    assert any("EPUB metadata declares en" in f["message"] for f in result["missing_fields"])


def test_direct_send_rejects_before_hashing_or_contacting_tracker(tmp_path):
    from torrentlinker.scan import scan_item
    from torrentlinker.store import Store
    from torrentlinker.upload import UploadFile, UploadRequest, create_upload

    path = tmp_path / "model.stl"
    path.write_text("solid test\nendsolid test")
    request = UploadRequest(
        scan_item(path),
        "Model",
        [UploadFile("Model.stl", path.name, path.stat().st_size)],
        "NFO",
        "One sentence",
        10,
        51,
    )
    calls = []
    with pytest.raises(ValueError, match="description.synopsis"):
        create_upload(
            request,
            "https://tracker.invalid/announce/test",
            tmp_path / "uploads",
            calls.append,
            Store(tmp_path / "store.db"),
        )
    assert not calls and not (tmp_path / "uploads").exists()


def test_synopsis_cannot_be_only_technical_labels():
    form = complete_form()
    form["description"] = form["description"].replace(
        "Alice suit un lapin blanc et découvre un monde peuplé de "
        "créatures étranges.\n[h3]Informations[/h3]",
        "",
    )
    assert "description.synopsis" in {f["field"] for f in assess(form)["missing_fields"]}


def test_nfo_cannot_be_empty_of_technical_facts():
    form = complete_form()
    form["nfo"] = "hello"
    assert {f["field"] for f in assess(form)["missing_fields"]} >= {
        "nfo.author",
        "nfo.language",
        "nfo.format",
    }


def test_track_durations_and_subtitle_details_are_required():
    form = complete_form(3, 18)
    form["description"] = form["description"].replace("01. Silence (00:01)", "01. Silence")
    assert "description.tracklist[1].duration" in {
        f["field"] for f in assess(form)["missing_fields"]
    }
    form = complete_form(1, 6)
    form["description"] = form["description"].replace("Aucun", "Français")
    assert "description.subtitle_formats" in {f["field"] for f in assess(form)["missing_fields"]}


def test_mediainfo_nfo_is_recognized_without_rewriting_original_text():
    form = complete_form(1, 6)
    form["nfo"] = (
        form["title"]
        + """
General
Complete name : Movie.WEB-DL.mkv
Format : Matroska
File size : 185 KiB
Duration : 1 h 30 min

Video
Format : AVC
Bit rate : 3 000 kb/s
Width : 1 920 pixels
Height : 1 080 pixels

Audio
Format : AAC
Bit rate : 256 kb/s
Channel(s) : 2 channels
Language : French
"""
    )
    original = form["nfo"]
    assert assess(form)["status"] == "complete"
    assert form["nfo"] == original
    form["nfo"] = form["nfo"].replace("Bit rate : 256 kb/s", "")
    assert "nfo.audio_bitrate" in {f["field"] for f in assess(form)["missing_fields"]}


def test_misplaced_upload_path_returns_actionable_validation_error():
    from torrentlinker.web.uploads import UploadForm

    with pytest.raises(ValueError, match="operation.path"):
        UploadForm.model_validate({"path": "/library/book.epub"})


def test_inline_first_track_does_not_hide_later_missing_durations():
    form = complete_form(3, 18)
    for key in ("nfo", "description"):
        form[key] = form[key].replace(
            "01. Silence (00:01)", "01. First song (03:42)\n02. Second song"
        )
    assert {f["field"] for f in assess(form)["missing_fields"]} >= {
        "description.tracklist[2].duration",
        "nfo.tracklist[2].duration",
    }
