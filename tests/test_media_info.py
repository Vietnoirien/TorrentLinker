from pathlib import Path

from pymediainfo import MediaInfo

from torrentlinker.media_info import facts_from, with_file_name

FIXTURES = Path(__file__).parent / "fixtures" / "mediainfo"  # MediaInfo's answers, recorded


def facts(name: str):  # type: ignore[no-untyped-def]
    xml = (FIXTURES / f"{name}.xml").read_text(encoding="utf-8")
    return facts_from(MediaInfo(xml), (FIXTURES / f"{name}.txt").read_text(encoding="utf-8"), name)


def test_a_x264_encode_shows_its_encoder_picture_and_tracks() -> None:
    f = facts("film_x264_1080p_fr")
    assert f is not None
    assert (f.container, f.video_codec, f.encoder, f.resolution) == (
        "Matroska",
        "AVC",
        "x264",
        "1080p",
    )
    assert f.video_bitrate == 6000 and not f.gpu_encoder and not f.hdr10
    (audio,) = f.audio
    assert (audio.codec, audio.channels, audio.layout, audio.language, audio.variant) == (
        "AC3",
        6,
        "5.1",
        "fr",
        "VFF",
    )
    assert audio.french and not audio.lossless
    (sub,) = f.subtitles
    assert sub.language == "fr" and sub.full_french and not sub.forced


def test_hdr10_hevc_and_an_untouched_web_dl_and_xvid_are_told_apart() -> None:
    uhd = facts("film_x265_2160p_hdr")
    assert uhd is not None
    assert (uhd.video_codec, uhd.encoder, uhd.resolution, uhd.hdr10, uhd.dv_profile) == (
        "HEVC",
        "x265",
        "2160p",
        True,
        0,
    )
    assert uhd.audio[0].codec == "EAC3"
    web = facts("film_webdl_1080p")
    assert web is not None and web.encoder == "" and web.container == "MPEG-4"
    xvid = facts("film_xvid_sd")
    assert xvid is not None and (xvid.video_codec, xvid.resolution) == ("XVID", "SD")
    assert xvid.audio[0].language == ""


def test_a_gpu_encoder_is_named_from_the_encode_settings() -> None:
    f = facts("film_nvenc")
    assert f is not None and f.gpu_encoder == "NVENC"
    assert facts("film_x264_1080p_fr").gpu_encoder == ""  # type: ignore[union-attr]


def test_languages_of_several_tracks_are_kept_in_order() -> None:
    f = facts("film_multi")
    assert f is not None
    assert [(t.language, t.variant) for t in f.audio] == [("en", ""), ("fr", "VFF")]


def test_the_text_output_shows_the_file_name_not_where_it_is() -> None:
    f = facts("film_x264_1080p_fr")
    assert f is not None
    assert "Complete name" in f.text and "/tmp" not in f.text
    renamed = with_file_name(f.text, "Titre.mkv")
    assert "Complete name                            : Titre.mkv" in renamed
