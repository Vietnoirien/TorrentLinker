import shutil
from pathlib import Path

from torrentlinker.audio_tags import AudioTags, TagCache, image_size, read_tags
from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.matching import IgnoreList
from torrentlinker.options import OptionType, OptionValue
from torrentlinker.scan import scan_item
from torrentlinker.upload import (
    CATEGORY_AUDIO,
    PROFILES,
    AudioProfile,
    EbookProfile,
    Judgement,
    Problem,
    SubcategoryAudio,
    SubcategoryEbook,
    default_category,
    profile_for,
    upload_files,
)

AUDIO = Path(__file__).parent / "fixtures" / "audio"
IGNORE = IgnoreList.default()
MUSIC, PODCAST, SAMPLES = SubcategoryAudio.MUSIC, SubcategoryAudio.PODCAST, SubcategoryAudio.SAMPLES


def folder(tmp_path: Path, name: str, files: dict[str, str | bytes]) -> LocalItem:
    """A Local Item holding the recorded fixtures (or bytes) under these names."""
    root = tmp_path / name
    root.mkdir()
    for target, source in files.items():
        (root / target).parent.mkdir(parents=True, exist_ok=True)
        if isinstance(source, bytes):
            (root / target).write_bytes(source)
        else:
            shutil.copy(AUDIO / source, root / target)
    return scan_item(root)


def inspected(item: LocalItem) -> AudioProfile:
    profile = AudioProfile()
    profile.inspect(item, IGNORE)
    return profile


def tag(**kw: object) -> AudioTags:
    base: dict[str, object] = dict(
        artist="Daft Punk",
        album="Discovery",
        title="One More Time",
        year="2001",
        track=1,
        duration=320.0,
        codec="FLAC",
        bitrate=900,
        constant=True,
        sample_rate=44100,
        bits=16,
        channels=2,
    )
    return AudioTags(**{**base, **kw})  # type: ignore[arg-type]


def faked(tags: dict[str, AudioTags]) -> AudioProfile:
    """A profile whose tag reader answers from `tags`, by file name."""
    return AudioProfile(TagCache(lambda path: tags.get(path.name)))


def flac_album(tmp_path: Path, extra: dict[str, str | bytes] | None = None) -> LocalItem:
    files: dict[str, str | bytes] = {
        "Daft Punk - Discovery (2001)/01 One More Time.flac": "track16.flac",
        "Daft Punk - Discovery (2001)/02 Aerodynamic.flac": "track16.flac",
    }
    for name, source in (extra or {}).items():
        files[f"Daft Punk - Discovery (2001)/{name}"] = source
    item = folder(tmp_path, "lib", files)
    return scan_item(item.path / "Daft Punk - Discovery (2001)")


# Tags ------------------------------------------------------------------------


def test_tags_are_read_from_the_files_with_codec_bitrate_sample_rate_and_depth() -> None:
    flac = read_tags(AUDIO / "track16.flac")
    assert flac is not None
    assert (flac.artist, flac.album, flac.title, flac.year, flac.track) == (
        "Daft Punk",
        "Discovery",
        "One More Time",
        "2001",
        1,
    )
    assert (flac.codec, flac.lossless, flac.sample_rate, flac.bits, flac.channels) == (
        "FLAC",
        True,
        44100,
        16,
        2,
    )
    hires = read_tags(AUDIO / "track24.flac")
    assert hires is not None and (hires.bits, hires.sample_rate) == (24, 96000)
    mp3 = read_tags(AUDIO / "cbr320.mp3")
    assert mp3 is not None and (mp3.codec, mp3.bitrate, mp3.constant, mp3.bits) == (
        "MP3",
        320,
        True,
        0,
    )
    vbr = read_tags(AUDIO / "vbr.mp3")
    assert vbr is not None and not vbr.constant
    assert read_tags(AUDIO / "alac.m4a").codec == "ALAC"  # type: ignore[union-attr]
    assert read_tags(AUDIO / "aac96.m4a").codec == "AAC"  # type: ignore[union-attr]
    assert read_tags(AUDIO / "vorbis.ogg").codec == "OGG"  # type: ignore[union-attr]
    wav = read_tags(AUDIO / "plain.wav")
    assert wav is not None and (wav.codec, wav.artist, wav.bits) == ("WAV", "", 16)


def test_a_file_mutagen_cannot_read_has_no_tags(tmp_path: Path) -> None:
    broken = tmp_path / "x.mp3"
    broken.write_bytes(b"not audio")
    assert read_tags(broken) is None


def test_cover_sizes_are_read_from_jpeg_and_png_headers(tmp_path: Path) -> None:
    png = tmp_path / "c.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + (600).to_bytes(4, "big") * 2)
    assert image_size(png) == (600, 600)
    jpg = tmp_path / "c.jpg"
    jpg.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x04ab\xff\xc0\x00\x11\x08"
        + (480).to_bytes(2, "big")
        + (640).to_bytes(2, "big")
        + b"\x03" * 12
    )
    assert image_size(jpg) == (640, 480)
    assert image_size(tmp_path / "missing.jpg") is None


# The profile -----------------------------------------------------------------


def test_the_audio_profile_is_category_3_with_four_subcategories_proposed_for_music() -> None:
    profile = PROFILES[CATEGORY_AUDIO]
    assert isinstance(profile, AudioProfile) and profile.category == 3
    assert [s.id for s in profile.subcategories] == [17, 18, 19, 20]
    assert default_category(ContentKind.MUSIC) == CATEGORY_AUDIO
    assert profile_for(ContentKind.MUSIC) is profile
    assert list(PROFILES) == sorted(PROFILES)  # the picker lists them by category id


def test_the_default_subcategory_is_music(tmp_path: Path) -> None:
    item = flac_album(tmp_path)
    assert AudioProfile().default_subcategory(item, IGNORE) == SubcategoryAudio.MUSIC


def test_no_file_no_audio_and_archives_are_refused(tmp_path: Path) -> None:
    profile = AudioProfile()
    empty = tmp_path / "empty"
    empty.mkdir()
    assert [r.problem for r in profile.refusals(scan_item(empty), IGNORE)] == [Problem.NO_FILE]
    pictures = folder(tmp_path, "pics", {"cover.jpg": b"jpg"})
    assert [r.problem for r in profile.refusals(pictures, IGNORE)] == [Problem.NO_AUDIO_FILE]
    zipped = folder(tmp_path, "zipped", {"album.zip": b"zip", "a.flac": "track16.flac"})
    found = profile.refusals(zipped, IGNORE, MUSIC)
    assert [(r.problem, r.detail) for r in found if r.problem is Problem.ARCHIVE] == [
        (Problem.ARCHIVE, "zip")
    ]


def test_formats_c411_does_not_list_are_refused(tmp_path: Path) -> None:
    item = folder(tmp_path, "a", {"1.flac": "track16.flac", "2.opus": b"x", "3.ape": b"y"})
    found = AudioProfile().refusals(item, IGNORE, MUSIC)
    assert [(r.problem, r.detail) for r in found] == [(Problem.AUDIO_FORMAT, "APE, OPUS")]


def test_a_single_audio_file_needs_a_cue_except_in_podcasts(tmp_path: Path) -> None:
    image = folder(tmp_path, "image", {"Album.flac": "track16.flac"})
    profile = AudioProfile()
    assert [r.problem for r in profile.refusals(image, IGNORE, MUSIC)] == [Problem.NEEDS_CUE]
    assert profile.refusals(image, IGNORE, PODCAST) == []
    with_cue = folder(tmp_path, "cue", {"Album.flac": "track16.flac", "Album.cue": b"FILE"})
    assert profile.refusals(with_cue, IGNORE, MUSIC) == []


def test_mp3_under_320_cbr_is_refused_but_vbr_is_accepted(tmp_path: Path) -> None:
    low = folder(tmp_path, "low", {"1.mp3": "cbr128.mp3", "2.mp3": "cbr128.mp3"})
    found = inspected(low).refusals(low, IGNORE, MUSIC)
    assert [(r.problem, r.detail) for r in found] == [
        (Problem.LOW_BITRATE, "MP3 128 kbps (minimum 320)")
    ]
    vbr = folder(tmp_path, "vbr", {"1.mp3": "vbr.mp3", "2.mp3": "vbr.mp3"})
    assert inspected(vbr).refusals(vbr, IGNORE, MUSIC) == []
    good = folder(tmp_path, "good", {"1.mp3": "cbr320.mp3", "2.mp3": "cbr320.mp3"})
    assert inspected(good).refusals(good, IGNORE, MUSIC) == []


def test_aac_needs_256_and_podcasts_and_radio_128(tmp_path: Path) -> None:
    low = folder(tmp_path, "low", {"1.m4a": "aac96.m4a", "2.m4a": "aac96.m4a"})
    profile = inspected(low)
    assert [r.problem for r in profile.refusals(low, IGNORE, MUSIC)] == [Problem.LOW_BITRATE]
    assert [r.problem for r in profile.refusals(low, IGNORE, PODCAST)] == [Problem.LOW_BITRATE]
    ok = folder(tmp_path, "ok", {"1.mp3": "cbr128.mp3", "2.mp3": "cbr128.mp3"})
    assert inspected(ok).refusals(ok, IGNORE, PODCAST) == []
    aac = faked(
        {
            "1.m4a": tag(codec="AAC", bitrate=256, bits=0),
            "2.m4a": tag(codec="AAC", bitrate=256, bits=0),
        }
    )
    fine = folder(tmp_path, "fine", {"1.m4a": "aac96.m4a", "2.m4a": "aac96.m4a"})
    aac.inspect(fine, IGNORE)
    assert aac.refusals(fine, IGNORE, MUSIC) == []


def test_formats_or_bitrates_mixed_in_one_album_are_refused(tmp_path: Path) -> None:
    formats = folder(tmp_path, "f", {"1.flac": "track16.flac", "2.mp3": "cbr320.mp3"})
    found = inspected(formats).refusals(formats, IGNORE, MUSIC)
    assert [(r.problem, r.detail) for r in found] == [(Problem.MIXED_AUDIO, "FLAC, MP3")]
    rates = folder(tmp_path, "r", {"1.mp3": "cbr320.mp3", "2.mp3": "cbr128.mp3"})
    found = inspected(rates).refusals(rates, IGNORE, PODCAST)
    assert [(r.problem, r.detail) for r in found] == [(Problem.MIXED_AUDIO, "128 kbps, 320 kbps")]


def test_before_the_files_are_inspected_only_the_names_count(tmp_path: Path) -> None:
    low = folder(tmp_path, "low", {"1.mp3": "cbr128.mp3", "2.mp3": "cbr128.mp3"})
    assert AudioProfile().refusals(low, IGNORE, MUSIC) == []  # no tags read yet


def test_judgement_rules_are_warnings_never_refusals(tmp_path: Path) -> None:
    item = flac_album(tmp_path)
    profile = faked(
        {
            "01 One More Time.flac": tag(duration=1500.0),
            "02 Aerodynamic.flac": tag(duration=1500.0),
        }
    )
    profile.inspect(item, IGNORE)
    found = profile.warnings(item, IGNORE, MUSIC)
    assert [w.judgement for w in found] == [Judgement.NO_TRANSCODE]


def test_a_single_under_twenty_minutes_is_warned_about(tmp_path: Path) -> None:
    item = folder(tmp_path, "single", {"1.flac": "track16.flac", "1.cue": b"x"})
    profile = inspected(item)  # half a second of audio
    assert Judgement.SHORT_SINGLE in [w.judgement for w in profile.warnings(item, IGNORE, MUSIC)]
    long = faked({"1.flac": tag(duration=1500.0)})
    long.inspect(item, IGNORE)
    assert Judgement.SHORT_SINGLE not in [w.judgement for w in long.warnings(item, IGNORE, MUSIC)]


def test_two_albums_in_one_item_look_like_a_discography(tmp_path: Path) -> None:
    item = folder(tmp_path, "disco", {"a/1.flac": "track16.flac", "b/1.flac": "track16.flac"})
    profile = faked({"1.flac": tag(album="Discovery")})
    profile.inspect(item, IGNORE)
    assert Judgement.DISCOGRAPHY not in [w.judgement for w in profile.warnings(item, IGNORE, MUSIC)]
    mixed = AudioProfile(TagCache(lambda p: tag(album="One" if p.parent.name == "a" else "Two")))
    mixed.inspect(item, IGNORE)
    assert Judgement.DISCOGRAPHY in [w.judgement for w in mixed.warnings(item, IGNORE, MUSIC)]


def test_a_cd_rip_is_warned_about_what_it_lacks(tmp_path: Path) -> None:
    ripped = flac_album(tmp_path, {"Discovery.cue": b"FILE"})
    profile = inspected(ripped)
    found = {w.judgement: w.detail for w in profile.warnings(ripped, IGNORE, MUSIC)}
    assert found[Judgement.CD_RIP_MISSING] == "cover.jpg, EAC .log"
    assert Judgement.CD_RIP_LINKS in found


def test_a_cd_rip_cover_must_be_500_pixels_wide_and_high(tmp_path: Path) -> None:
    def png(side: int) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + side.to_bytes(4, "big") * 2

    small = flac_album(
        tmp_path, {"Discovery.cue": b"x", "Discovery.log": b"x", "cover.png": png(300)}
    )
    found = {w.judgement: w.detail for w in inspected(small).warnings(small, IGNORE, MUSIC)}
    assert found[Judgement.CD_RIP_MISSING] == "cover.jpg (500×500 or more)"
    big = tmp_path / "big"
    big.mkdir()
    full = flac_album(big, {"Discovery.cue": b"x", "Discovery.log": b"x", "cover.png": png(600)})
    found = {w.judgement: w.detail for w in inspected(full).warnings(full, IGNORE, MUSIC)}
    assert Judgement.CD_RIP_MISSING not in found
    assert Judgement.CD_RIP_LINKS in found  # the catalogue number and link are for the user


def test_a_web_release_is_not_a_cd_rip(tmp_path: Path) -> None:
    item = folder(tmp_path, "web", {"1.mp3": "cbr320.mp3", "2.mp3": "cbr320.mp3"})
    judged = [w.judgement for w in inspected(item).warnings(item, IGNORE, MUSIC)]
    assert Judgement.CD_RIP_LINKS not in judged


# Names -----------------------------------------------------------------------


def test_music_is_named_artist_album_year_and_the_lossless_quality(tmp_path: Path) -> None:
    item = flac_album(tmp_path)
    name = inspected(item).suggested_name(item, IGNORE, "", MUSIC)
    assert name == "Daft.Punk.Discovery.2001.FLAC.16bit.44.1kHz-NOTAG"


def test_a_cd_rip_says_so_and_hires_states_its_depth_and_rate(tmp_path: Path) -> None:
    ripped = flac_album(tmp_path, {"Discovery.log": b"x"})
    name = inspected(ripped).suggested_name(ripped, IGNORE, "TEAM", MUSIC)
    assert name == "Daft.Punk.Discovery.2001.CD-Rip.FLAC.16bit.44.1kHz-TEAM"
    hires = folder(tmp_path, "hires", {"a/1.flac": "track24.flac", "a/2.flac": "track24.flac"})
    assert (
        inspected(hires).suggested_name(hires, IGNORE, "", MUSIC).endswith("FLAC.24bit.96kHz-NOTAG")
    )


def test_lossy_music_states_its_bitrate_and_vbr_says_vbr(tmp_path: Path) -> None:
    item = folder(tmp_path, "mp3", {"1.mp3": "cbr320.mp3", "2.mp3": "cbr320.mp3"})
    assert inspected(item).suggested_name(item, IGNORE, "", MUSIC) == (
        "Daft.Punk.Discovery.2001.MP3.320kbps-NOTAG"
    )
    vbr = folder(tmp_path, "vbr", {"1.mp3": "vbr.mp3", "2.mp3": "vbr.mp3"})
    assert inspected(vbr).suggested_name(vbr, IGNORE, "", MUSIC).endswith("MP3.VBR-NOTAG")


def test_without_tags_the_name_comes_from_the_folder_and_the_extension(tmp_path: Path) -> None:
    item = folder(tmp_path, "Étienne Daho - Pop Satori (1986)", {"a.flac": b"x", "b.flac": b"y"})
    assert AudioProfile().suggested_name(item, IGNORE, "", MUSIC) == (
        "Etienne.Daho.Pop.Satori.1986.FLAC-NOTAG"
    )


def test_several_artists_make_a_various_artists_name(tmp_path: Path) -> None:
    item = folder(tmp_path, "compil", {"1.flac": b"x", "2.flac": b"y"})
    profile = AudioProfile(TagCache(lambda p: tag(artist="A" if p.name == "1.flac" else "B")))
    profile.inspect(item, IGNORE)
    assert profile.suggested_name(item, IGNORE, "", MUSIC).startswith("Various.Discovery.2001")


def test_a_podcast_is_named_show_date_integrale_and_quality(tmp_path: Path) -> None:
    item = folder(
        tmp_path, "Le Masque et la Plume 2024-05-12", {"1.mp3": "cbr128.mp3", "2.mp3": "cbr128.mp3"}
    )
    profile = AudioProfile(
        TagCache(lambda p: tag(album="", artist="France Inter", codec="MP3", bits=0, bitrate=128))
    )
    profile.inspect(item, IGNORE)
    assert profile.suggested_name(item, IGNORE, "Team", PODCAST) == (
        "France.Inter.2024.05.12.INTEGRALE.MP3.128kbps-Team"
    )
    plain = folder(tmp_path, "Le Masque et la Plume 2024-05-12 b", {"1.mp3": b"x", "2.mp3": b"y"})
    assert (
        AudioProfile()
        .suggested_name(plain, IGNORE, "", PODCAST)
        .startswith("Le.Masque.Et.La.Plume.B.2024.05.12.INTEGRALE.MP3")
    )
    episode = folder(tmp_path, "Un épisode 2024-05-12", {"ep.mp3": "cbr128.mp3"})
    profile.inspect(episode, IGNORE)
    assert "INTEGRALE" not in profile.suggested_name(episode, IGNORE, "", PODCAST)


def test_samples_are_named_name_year_codec_and_bitrate_without_a_tag(tmp_path: Path) -> None:
    item = folder(tmp_path, "Drum Kit (2023)", {"kick.wav": "plain.wav", "snare.wav": "plain.wav"})
    profile = AudioProfile(
        TagCache(lambda p: tag(artist="", album="", year="", codec="WAV", bitrate=1411))
    )
    profile.inspect(item, IGNORE)
    assert profile.suggested_name(item, IGNORE, "Team", SAMPLES) == "Drum.Kit.2023.wav.1411kbps"


# NFO, description, options ---------------------------------------------------


def test_the_nfo_lists_the_facts_and_a_tracklist_with_durations(tmp_path: Path) -> None:
    item = flac_album(tmp_path, {"Discovery.log": b"x"})
    profile = faked(
        {
            "01 One More Time.flac": tag(title="One More Time", track=1, duration=320.0),
            "02 Aerodynamic.flac": tag(title="Aerodynamic", track=2, duration=212.0),
        }
    )
    profile.inspect(item, IGNORE)
    files = upload_files(item, "Daft.Punk.Discovery.2001.CD-Rip.FLAC.16bit.44.1kHz-NOTAG", IGNORE)
    nfo = profile.nfo("Daft.Punk.Discovery.2001.CD-Rip.FLAC.16bit.44.1kHz-NOTAG", files)
    for line in (
        "Artiste ........ : Daft Punk",
        "Album .......... : Discovery",
        "Année .......... : 2001",
        "Source ......... : CD",
        "Codec .......... : FLAC",
        "Profondeur ..... : 16 bits",
        "Fréquence ...... : 44.1kHz",
        "Pistes ......... : 2",
        "Durée .......... : 8:52",
        "  01. One More Time  5:20",
        "  02. Aerodynamic  3:32",
    ):
        assert line in nfo, line


def test_a_lossy_nfo_states_the_bitrate_and_the_description_the_tracklist(tmp_path: Path) -> None:
    item = folder(tmp_path, "m", {"1.mp3": "cbr320.mp3", "2.mp3": "vbr.mp3"})
    profile = AudioProfile()
    profile.inspect(item, IGNORE)
    files = upload_files(item, "T", IGNORE)
    assert "Débit .......... : 320 kbps" in profile.nfo("T", files)
    text = profile.description("T", files, "", "")
    assert "[img]…[/img]" in text and "[h2]Daft Punk - Discovery[/h2]" in text
    assert "[spoiler=Liste des pistes]" in text and "Digital Love" in text
    assert "Numéro de catalogue" not in text  # not a CD-Rip


def test_a_cd_rip_description_asks_for_the_catalogue_number_and_link(tmp_path: Path) -> None:
    item = flac_album(tmp_path, {"Discovery.log": b"x"})
    profile = inspected(item)
    files = upload_files(item, "T", IGNORE)
    text = profile.description("T", files, "", "https://img/x.png")
    assert "[img]https://img/x.png[/img]" in text
    assert "[b]Numéro de catalogue :[/b] " in text and "Discogs / MusicBrainz" in text


def test_the_options_are_pre_filled_with_format_source_and_type(tmp_path: Path) -> None:
    types = [
        OptionType(
            15,
            "Format Musique",
            False,
            True,
            (
                OptionValue(158, "FLAC (16 bit)"),
                OptionValue(159, "FLAC (24 bit)"),
                OptionValue(161, "MP3"),
            ),
        ),
        OptionType(16, "Source", False, True, (OptionValue(169, "CD"), OptionValue(172, "Web"))),
        OptionType(
            17,
            "Type Musique",
            False,
            True,
            (OptionValue(173, "Album"), OptionValue(175, "Discographie")),
        ),
        OptionType(18, "Genre Musique", True, False, (OptionValue(1, "Pop"),)),
    ]
    ripped = flac_album(tmp_path, {"Discovery.log": b"x"})
    assert inspected(ripped).suggested_options(ripped, IGNORE, types) == {
        15: [158],
        16: [169],
        17: [173],
    }
    mp3 = folder(tmp_path, "m", {"1.mp3": "cbr320.mp3", "2.mp3": "cbr320.mp3"})
    assert inspected(mp3).suggested_options(mp3, IGNORE, types) == {15: [161], 17: [173]}
    assert AudioProfile().suggested_options(mp3, IGNORE, types) == {}  # not inspected


def test_existing_releases_are_looked_up_by_title_words(tmp_path: Path) -> None:
    item = flac_album(tmp_path)
    assert AudioProfile().existing_query(item, IGNORE).text


# Audiobooks (Ebook profile) ---------------------------------------------------


def test_an_audiobook_under_64_kbps_is_refused(tmp_path: Path) -> None:
    item = folder(tmp_path, "Livre audio", {"1.mp3": "cbr128.mp3", "2.mp3": "cbr128.mp3"})
    slow = EbookProfile(TagCache(lambda p: tag(codec="MP3", bits=0, bitrate=32)))
    slow.inspect(item, IGNORE)
    found = slow.refusals(item, IGNORE)
    assert [(r.problem, r.detail) for r in found] == [
        (Problem.LOW_BITRATE, "MP3 32 kbps (minimum 64)")
    ]
    fine = EbookProfile()
    fine.inspect(item, IGNORE)
    assert fine.refusals(item, IGNORE) == []
    assert fine.default_subcategory(item, IGNORE) == SubcategoryEbook.AUDIO
