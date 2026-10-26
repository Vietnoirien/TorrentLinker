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
Source : WEB-DL
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


def test_label_edits_preserve_following_fields_and_replace_entire_tracklist():
    from torrentlinker.upload_presentation import update_fields

    text = (
        "Titre : \nFichiers : 2\nListe des pistes :\n01. Old (01:00)\n"
        "02. Old (02:00)\nTaille totale : 12 MiB"
    )
    changed = update_fields(
        text, {"title": "Correct title", "tracklist": "01. New (03:00)"}, bbcode=False
    )
    assert "Fichiers : 2" in changed
    assert "Old" not in changed
    assert "Taille totale : 12 MiB" in changed
    assert "Liste des pistes : 01. New (03:00)" in changed


def test_incidental_filename_does_not_establish_rip_source():
    from torrentlinker.upload_presentation import media_nfo_values

    facts = media_nfo_values(
        "General\nComplete name : Movie.BluRay.mkv\nFormat : Matroska\nVideo\nFormat : AVC"
    )
    assert "source" not in facts


def test_send_readiness_requires_the_hosted_image_form_field():
    form = complete_form()
    form["image"] = ""
    result = assess(form, local=True)
    assert result["local_review_ready"] is True
    assert result["send_ready"] is False
    assert any(row["field"] == "image" for row in result["send_missing_fields"])


@pytest.mark.parametrize(
    "field,label",
    [("tracklist", "Tracklist"), ("contents", "Contents"), ("installation", "Installation")],
)
def test_multiline_field_edit_preserves_following_editorial_sections(field, label):
    from torrentlinker.upload_presentation import update_fields

    text = f"[b]{label} :[/b] 01. Old (02:00)\n[h3]Notes[/h3]\nOwner editorial text to preserve"
    changed = update_fields(text, {field: "Replacement"})
    assert "[h3]Notes[/h3]\nOwner editorial text to preserve" in changed
    assert "Old" not in changed


def test_original_nfo_conflicts_with_extracted_codec_duration_and_counts_without_rewriting():
    from torrentlinker.upload_presentation import update_fields

    form = complete_form(3, 18)
    form["description"] = update_fields(
        form["description"],
        {
            "codec": "FLAC",
            "duration": "01:00",
            "tracks": "2",
        },
    )
    form["nfo"] = update_fields(
        form["nfo"],
        {
            "codec": "MP3",
            "duration": "02:00",
            "files": "9",
            "tracks": "3",
        },
        bbcode=False,
    )
    form["nfo_origin"] = "original"
    original = form["nfo"]
    evidence = {
        "file_count": 1,
        "fields": {
            key: {"value": value, "kind": "extracted"}
            for key, value in {
                "codec": "FLAC",
                "duration": "01:00",
                "files": "1",
                "tracks": "2",
            }.items()
        },
    }
    check = assess(form, evidence, local=True)
    fields = {entry["field"] for entry in check["missing_fields"]}
    assert {"nfo.codec", "nfo.duration", "nfo.files", "nfo.tracks"} <= fields
    assert check["local_review_ready"] is False
    assert form["nfo"] == original


def test_nfo_duration_rounding_and_codec_aliases_are_not_false_conflicts():
    from torrentlinker.upload_presentation import update_fields

    form = complete_form(1, 6)
    form["nfo"] = update_fields(
        form["nfo"], {"duration": "1 h 30 min", "video_codec": "AVC"}, bbcode=False
    )
    evidence = {
        "file_count": 1,
        "fields": {
            "duration": {"value": "1:30:28"},
            "video_codec": {"value": "H.264"},
        },
    }
    check = assess(form, evidence)
    assert not {"nfo.duration", "nfo.video_codec"} & {
        entry["field"] for entry in check["missing_fields"]
    }
