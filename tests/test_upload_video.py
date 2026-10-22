from pathlib import Path

from pymediainfo import MediaInfo

from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.matching import IgnoreList
from torrentlinker.media_info import MediaFacts, facts_from
from torrentlinker.options import OptionType, OptionValue
from torrentlinker.scan import scan_item
from torrentlinker.tmdb import TmdbInfo
from torrentlinker.upload import (
    CATEGORY_VIDEO,
    PROFILES,
    Judgement,
    Problem,
    SubcategoryVideo,
    VideoProfile,
    default_category,
    draft_body,
    profile_for,
    upload_files,
)

FIXTURES = Path(__file__).parent / "fixtures" / "mediainfo"  # MediaInfo's answers, recorded
IGNORE = IgnoreList.default()
MOVIE, SERIES = SubcategoryVideo.MOVIE, SubcategoryVideo.SERIES
FR_1080 = "Le.Film.2020.FRENCH.1080p.BluRay.x264-TFA.mkv"


def recorded(fixture: str, name: str = "") -> MediaFacts:
    xml = (FIXTURES / f"{fixture}.xml").read_text(encoding="utf-8")
    text = (FIXTURES / f"{fixture}.txt").read_text(encoding="utf-8")
    facts = facts_from(MediaInfo(xml), text, name)
    assert facts is not None
    return facts


class Tmdb:
    """A TMDb that knows one film, and what it was asked."""

    def __init__(self, info: TmdbInfo | None = None) -> None:
        self.info = info
        self.asked: list[tuple[str, str]] = []

    def lookup(self, title: str, year: int | None, kind: ContentKind) -> str | None:
        self.asked.append((title, str(year)))
        return self.info.id if self.info else None

    def details(self, tmdb_id: str, media_type: str) -> TmdbInfo | None:
        return self.info


INCEPTION = TmdbInfo(
    "27205", "movie", "Inception", "Inception", "2010", "Un voleur de rêves.", {"id": 27205}
)
LE_FILM = TmdbInfo(
    "1", "movie", "Le Film Français", "The Film", "2020", "Une histoire.", {"id": 1, "x": "y"}
)


def profile(
    facts: dict[str, str] | None = None,
    available: bool = True,
    tmdb: Tmdb | None = None,
) -> VideoProfile:
    """A profile whose MediaInfo answers from the recordings, by file name."""
    names = facts or {}

    def reader(path: Path) -> MediaFacts | None:
        return recorded(names[path.name], path.name) if path.name in names else None

    return VideoProfile(reader, lambda: available, lambda: tmdb)  # type: ignore[arg-type,return-value]


def release(tmp_path: Path, files: dict[str, int] | list[str], folder: str = "") -> LocalItem:
    """A Local Item: a lone file, or a folder of files (sizes are what matter)."""
    sizes = files if isinstance(files, dict) else {f: 1000 for f in files}
    if not folder:
        ((name, size),) = sizes.items()
        (tmp_path / name).write_bytes(b"v" * size)
        return scan_item(tmp_path / name)
    root = tmp_path / folder
    for name, size in sizes.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(b"v" * size)
    return scan_item(root)


def problems(p: VideoProfile, item: LocalItem, sub: int = MOVIE) -> dict[Problem, str]:
    return {r.problem: r.detail for r in p.refusals(item, IGNORE, sub)}


# The profile -----------------------------------------------------------------


def test_the_video_profile_is_category_1_with_twelve_subcategories_for_movies_and_series() -> None:
    video = PROFILES[CATEGORY_VIDEO]
    assert isinstance(video, VideoProfile) and video.category == 1
    assert sorted(s.id for s in video.subcategories) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 54, 57]
    assert default_category(ContentKind.MOVIE) == default_category(ContentKind.SERIES) == 1
    assert profile_for(ContentKind.SERIES) is video


def test_film_is_the_default_and_a_season_or_episode_in_the_name_makes_it_a_series(
    tmp_path: Path,
) -> None:
    p = profile()
    assert p.default_subcategory(release(tmp_path, [FR_1080]), IGNORE) == SubcategoryVideo.MOVIE
    episode = release(tmp_path, ["Show.S01E02.FRENCH.1080p.WEB.x264-TFA.mkv"])
    assert p.default_subcategory(episode, IGNORE) == SubcategoryVideo.SERIES


# Refusals --------------------------------------------------------------------


def test_without_libmediainfo_every_item_is_refused_with_one_clear_reason(tmp_path: Path) -> None:
    p = profile(available=False)
    item = release(tmp_path, [FR_1080])
    assert [r.problem for r in p.refusals(item, IGNORE)] == [Problem.NO_MEDIAINFO]
    p.inspect(item, IGNORE)  # and inspecting reads nothing instead of crashing
    assert p.facts == {}


def test_a_compliant_release_has_no_refusal(tmp_path: Path) -> None:
    item = release(tmp_path, [FR_1080])
    p = profile({FR_1080: "film_x264_1080p_fr"})
    p.inspect(item, IGNORE)
    assert p.refusals(item, IGNORE, MOVIE) == []


def test_no_file_no_video_and_archives_are_refused(tmp_path: Path) -> None:
    p = profile()
    empty = tmp_path / "vide"
    empty.mkdir()
    assert problems(p, scan_item(empty)) == {Problem.NO_FILE: ""}
    pictures = release(tmp_path, ["cover.jpg", "notes.txt"], "Dossier")
    assert problems(p, pictures) == {Problem.NO_VIDEO_FILE: ""}
    zipped = release(tmp_path, ["film.rar", "film.mkv"], "Zippé")
    assert problems(p, zipped)[Problem.ARCHIVE] == "rar"


def test_containers_c411_forbids_are_refused_but_discs_are_not(tmp_path: Path) -> None:
    p = profile()
    wmv = release(tmp_path, ["a.wmv", "b.MOV", "c.mkv"], "Divers")
    assert problems(p, wmv)[Problem.BAD_CONTAINER] == "MOV, WMV"
    iso = release(tmp_path, ["Film.2020.FRENCH.1080p.BluRay.ISO-TEAM.iso"])
    assert problems(p, iso) == {}
    bdmv = release(tmp_path, ["BDMV/STREAM/00000.m2ts", "BDMV/index.bdmv"], "Disque")
    assert problems(p, bdmv) == {}


def test_banned_teams_and_known_detag_sources_are_refused(tmp_path: Path) -> None:
    p = profile()
    for name, banned in (
        ("Film.2020.FRENCH.1080p.WEB.x264-RARBG.mkv", "RARBG"),
        ("Film.2020.FRENCH.1080p.WEB.x264-kORE.mkv", "KORE"),
        ("Film.2020.FRENCH.1080p.WEB.x264-Wawacity.mkv", "WAWACITY"),
    ):
        assert problems(p, release(tmp_path, [name]))[Problem.BANNED_TEAM] == banned


def test_gpu_encoders_are_refused(tmp_path: Path) -> None:
    name = "Film.2020.FRENCH.1080p.BluRay.x264-TFA.mkv"
    item = release(tmp_path, [name])
    p = profile({name: "film_nvenc"})
    p.inspect(item, IGNORE)
    assert problems(p, item)[Problem.GPU_ENCODER] == "NVENC"


def test_an_encode_under_the_minimum_bitrate_is_refused_not_a_web_dl(tmp_path: Path) -> None:
    low = "Film.2020.FRENCH.1080p.BluRay.x264-TFA.mkv"
    item = release(tmp_path, [low])
    p = profile({low: "film_x264_1080p_en_low"})
    p.inspect(item, IGNORE)
    found = problems(p, item)
    assert found[Problem.LOW_VIDEO_BITRATE] == "1080p x264 800 kb/s (minimum 2500)"
    web = "Film.2020.FRENCH.1080p.WEB-DL.H264-TEAM.mp4"
    item = release(tmp_path / "w" if (tmp_path / "w").mkdir() is None else tmp_path, [web])
    p = profile({web: "film_webdl_1080p"})
    p.inspect(item, IGNORE)
    assert Problem.LOW_VIDEO_BITRATE not in problems(p, item)  # 637 kb/s, but untouched


def test_an_encode_the_minimums_do_not_reach_is_judged_by_its_own_row(tmp_path: Path) -> None:
    uhd = "Film.2020.FRENCH.2160p.UHD.BluRay.x265-TFA.mkv"
    item = release(tmp_path, [uhd])
    p = profile({uhd: "film_x265_2160p_hdr"})
    p.inspect(item, IGNORE)
    assert problems(p, item)[Problem.LOW_VIDEO_BITRATE] == "2160p x265 1059 kb/s (minimum 2800)"
    xvid = tmp_path / "x"
    xvid.mkdir()
    name = "Vieux.1999.FRENCH.DVDRip.XviD-TEAM.avi"
    item = release(xvid, [name])
    p = profile({name: "film_xvid_sd"})
    p.inspect(item, IGNORE)
    assert problems(p, item)[Problem.LOW_VIDEO_BITRATE] == "SD XVID 100 kb/s (minimum 1500)"


def test_a_release_needs_french_audio_or_full_french_subtitles(tmp_path: Path) -> None:
    english = "Film.2020.1080p.BluRay.x264-TFA.mkv"
    item = release(tmp_path, [english])
    p = profile({english: "film_x264_1080p_en_low"})
    p.inspect(item, IGNORE)
    assert problems(p, item)[Problem.NO_FRENCH] == english
    sub = tmp_path / "s"
    sub.mkdir()
    item = release(sub, [FR_1080])
    p = profile({FR_1080: "film_x264_1080p_fr"})
    p.inspect(item, IGNORE)
    assert Problem.NO_FRENCH not in problems(p, item)
    multi = tmp_path / "m"
    multi.mkdir()
    item = release(multi, ["Film.2020.MULTI.1080p.BluRay.x264-TFA.mkv"])
    p = profile({"Film.2020.MULTI.1080p.BluRay.x264-TFA.mkv": "film_multi"})
    p.inspect(item, IGNORE)
    assert Problem.NO_FRENCH not in problems(p, item)


def test_the_files_of_a_pack_share_their_specs_and_their_team(tmp_path: Path) -> None:
    a, b = (
        "Show.S01E01.FRENCH.1080p.WEB.x264-TFA.mkv",
        "Show.S01E02.FRENCH.1080p.WEB.x265-OTHER.mkv",
    )
    item = release(tmp_path, [a, b], "Show.S01")
    p = profile({a: "film_x264_1080p_fr", b: "film_x265_2160p_hdr"})
    p.inspect(item, IGNORE)
    assert problems(p, item, SERIES)[Problem.MIXED_PACK] == "specs, teams"
    same = tmp_path / "same"
    same.mkdir()
    c = "Show.S01E03.FRENCH.1080p.WEB.x264-TFA.mkv"
    item = release(same, [a, c], "Show.S01")
    p = profile({a: "film_x264_1080p_fr", c: "film_x264_1080p_fr"})
    p.inspect(item, IGNORE)
    assert Problem.MIXED_PACK not in problems(p, item, SERIES)


def test_before_inspection_only_names_count(tmp_path: Path) -> None:
    low = "Film.2020.1080p.BluRay.x264-TFA.mkv"
    assert problems(profile({low: "film_nvenc"}), release(tmp_path, [low])) == {}


# Warnings --------------------------------------------------------------------


def test_judgement_rules_are_warnings_with_the_french_title_when_tmdb_gave_it(
    tmp_path: Path,
) -> None:
    item = release(tmp_path, [FR_1080])
    p = profile({FR_1080: "film_x264_1080p_fr"}, tmdb=Tmdb(LE_FILM))
    judged = {w.judgement: w.detail for w in p.warnings(item, IGNORE, MOVIE)}
    assert judged[Judgement.FRENCH_TITLE] == ""  # not identified yet
    p.inspect(item, IGNORE)
    judged = {w.judgement: w.detail for w in p.warnings(item, IGNORE, MOVIE)}
    assert judged[Judgement.FRENCH_TITLE] == "Le Film Français"
    assert Judgement.FORBIDDEN_SOURCE in judged and Judgement.SLOTS in judged
    assert Judgement.WEB_PLATFORM not in judged and Judgement.MICKEY_TAG not in judged


def test_web_needs_its_platform_and_mickey_is_a_known_detag(tmp_path: Path) -> None:
    item = release(tmp_path, ["Film.2020.FRENCH.1080p.WEB.x264-MICKEY.mkv"])
    judged = [w.judgement for w in profile().warnings(item, IGNORE, MOVIE)]
    assert Judgement.WEB_PLATFORM in judged and Judgement.MICKEY_TAG in judged


def test_a_season_with_a_missing_episode_is_warned_about(tmp_path: Path) -> None:
    files = [f"Show.S01E0{n}.FRENCH.1080p.WEB.x264-TFA.mkv" for n in (1, 2, 4, 5)]
    item = release(tmp_path, files, "Show.S01.FRENCH.1080p.WEB.x264-TFA")
    found = {w.judgement: w.detail for w in profile().warnings(item, IGNORE, SERIES)}
    assert found[Judgement.INCOMPLETE_SEASON] == "S01E03"
    assert Judgement.INCOMPLETE_SEASON not in {
        w.judgement for w in profile().warnings(item, IGNORE, MOVIE)
    }


# Names -----------------------------------------------------------------------


def named(
    tmp_path: Path,
    file: str,
    fixture: str,
    sub: int = MOVIE,
    source: str = "",
    tmdb: Tmdb | None = None,
) -> str:
    item = release(tmp_path, [file])
    p = profile({file: fixture}, tmdb=tmdb)
    p.inspect(item, IGNORE)
    return p.suggested_name(item, IGNORE, source, sub)


def test_a_film_is_named_from_its_file_name_and_mediainfo(tmp_path: Path) -> None:
    assert named(tmp_path, FR_1080, "film_x264_1080p_fr") == (
        "Le.Film.2020.VFF.1080p.BluRay.AC3.5.1.x264-TFA"
    )


def test_tmdbs_french_title_replaces_the_title_in_the_name(tmp_path: Path) -> None:
    name = named(tmp_path, FR_1080, "film_x264_1080p_fr", tmdb=Tmdb(LE_FILM))
    assert name == "Le.Film.Francais.2020.VFF.1080p.BluRay.AC3.5.1.x264-TFA"


def test_a_web_dl_says_h264_an_encode_x265_and_hdr_is_tagged(tmp_path: Path) -> None:
    web = "Film.2020.FRENCH.1080p.WEB-DL.H264-TEAM.mp4"
    assert named(
        tmp_path / "a" if (tmp_path / "a").mkdir() is None else tmp_path, web, "film_webdl_1080p"
    ) == ("Film.2020.VFF.1080p.WEB-DL.AAC.2.0.H264-TEAM")
    uhd = "Film.2020.FRENCH.2160p.UHD.BluRay.x265-TFA.mkv"
    sub = tmp_path / "b"
    sub.mkdir()
    assert named(sub, uhd, "film_x265_2160p_hdr") == (
        "Film.2020.VFF.2160p.UHD.BluRay.HDR10.EAC3.5.1.x265-TFA"
    )


def test_a_remux_or_a_disc_says_avc_and_its_kind_and_a_disc_has_no_tag_to_keep(
    tmp_path: Path,
) -> None:
    remux = "Film.2020.FRENCH.1080p.BluRay.REMUX.AVC-TFA.mkv"
    assert named(tmp_path, remux, "film_x264_1080p_fr") == (
        "Film.2020.VFF.1080p.BluRay.REMUX.AC3.5.1.AVC-TFA"
    )


def test_languages_are_named_vff_multi_vostfr_or_muet(tmp_path: Path) -> None:
    p = profile()
    assert p._language(recorded("film_multi"), "Film.MULTI.mkv") == "MULTI.VFF"
    assert p._language(recorded("film_x264_1080p_fr"), "Film.mkv") == "VFF"
    assert p._language(recorded("film_x264_1080p_fr"), "Film.TRUEFRENCH.mkv") == "TRUEFRENCH"
    assert p._language(recorded("film_x264_1080p_en_low"), "Film.mkv") == ""
    assert p._language(None, "Film.VFQ.mkv") == "VFQ"
    facts = recorded("film_x264_1080p_en_low")
    assert p._language(facts, "Film.mkv") == ""  # English only, no subtitles: refused
    from dataclasses import replace

    subs = replace(recorded("film_x264_1080p_fr"), audio=())
    assert p._language(subs, "Film.mkv") == "MUET"
    subbed = replace(facts, subtitles=recorded("film_x264_1080p_fr").subtitles)
    assert p._language(subbed, "Film.mkv") == "VOSTFR"
    from torrentlinker.media_info import AudioTrack

    quebec = replace(
        facts,
        audio=(
            AudioTrack("AC3", 6, "fr", "VFF", False, 448),
            AudioTrack("AC3", 6, "fr", "VFQ", False, 448),
        ),
    )
    assert p._language(quebec, "Film.mkv") == "MULTI.VF2"


def test_the_audio_tag_is_the_french_track_with_most_channels_or_the_lossless_one(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from torrentlinker.media_info import AudioTrack

    p = profile()
    base = recorded("film_multi")
    tracks = (
        AudioTrack("EAC3", 6, "fr", "VFF", False, 640),
        AudioTrack("DTS.HD.MA", 8, "en", "", False, 4000),
    )
    assert p._audio(replace(base, audio=tracks)) == ["DTS.HD.MA.7.1"]
    atmos = (
        AudioTrack("EAC3", 8, "fr", "VFF", True, 768),
        AudioTrack("AAC", 2, "fr", "VFF", False, 128),
    )
    assert p._audio(replace(base, audio=atmos)) == ["EAC3.ATMOS.7.1"]
    assert p._audio(None) == []


def test_a_series_episode_season_and_several_seasons_are_named_by_their_files(
    tmp_path: Path,
) -> None:
    episode = "Show.S01E02.FRENCH.1080p.WEB.x264-TFA.mkv"
    assert named(tmp_path, episode, "film_x264_1080p_fr", SERIES) == (
        "Show.S01E02.VFF.1080p.WEB-DL.AC3.5.1.x264-TFA"
    )
    names = [f"Show.S0{s}E0{e}.FRENCH.1080p.WEB.x264-TFA.mkv" for s in (1, 2) for e in (1, 2)]
    facts = {n: "film_x264_1080p_fr" for n in names}
    season = tmp_path / "season"
    season.mkdir()
    item = release(season, names[:2], "Show.S01.FRENCH.1080p.WEB.x264-TFA")
    p = profile(facts)
    p.inspect(item, IGNORE)
    assert p.suggested_name(item, IGNORE, "", SERIES).startswith("Show.S01.VFF.1080p")
    seasons = tmp_path / "seasons"
    seasons.mkdir()
    item = release(seasons, names, "Show.FRENCH.1080p.WEB.x264-TFA")
    p.inspect(item, IGNORE)
    assert p.suggested_name(item, IGNORE, "", SERIES).startswith("Show.S01S02.VFF.1080p")


def test_the_other_subcategories_follow_their_own_templates(tmp_path: Path) -> None:
    f = "Mon.Doc.2019.FRENCH.1080p.WEB.x264-TFA.mkv"
    assert named(tmp_path, f, "film_x264_1080p_fr", SubcategoryVideo.DOCUMENTARY).startswith(
        "Mon.Doc.2019.DOC.VFF.1080p"
    )
    clip = tmp_path / "c"
    clip.mkdir()
    assert named(
        clip,
        "Artiste.Titre.2020.1080p.WEB.x264-TFA.mkv",
        "film_x264_1080p_fr",
        SubcategoryVideo.CLIPS,
    ) == ("ARTISTE.TITRE.2020.1080p.WEB-DL.AC3.5.1.x264-TFA")
    tv = tmp_path / "t"
    tv.mkdir()
    assert named(
        tv,
        "Le.Journal.2024.05.12.FRENCH.1080p.HDTV.x264-TFA.mkv",
        "film_x264_1080p_fr",
        SubcategoryVideo.TV_SHOW,
    ).startswith("Le.Journal.2024.05.12.VFF.1080p.HDTV")
    coll = tmp_path / "col"
    coll.mkdir()
    names = [
        "Saga.2001.FRENCH.1080p.BluRay.x264-TFA.mkv",
        "Saga.2005.FRENCH.1080p.BluRay.x264-TFA.mkv",
    ]
    item = release(coll, names, "Saga")
    p = profile({n: "film_x264_1080p_fr" for n in names})
    p.inspect(item, IGNORE)
    assert p.suggested_name(item, IGNORE, "", SubcategoryVideo.COLLECTION).startswith(
        "Saga.COLLECTION.2001.2005.VFF.1080p"
    )


def test_the_team_is_kept_special_characters_dropped_notag_when_none(tmp_path: Path) -> None:
    anime = "Naruto.S01E01.FRENCH.1080p.WEB.x264-Tsundere-Raws.mkv"
    assert named(tmp_path, anime, "film_x264_1080p_fr", SERIES).endswith("-TsundereRaws")
    none = tmp_path / "n"
    none.mkdir()
    assert named(none, "Film.2020.FRENCH.1080p.BluRay.mkv", "film_x264_1080p_fr").endswith("-NOTAG")
    own = tmp_path / "o"
    own.mkdir()
    assert named(own, FR_1080, "film_x264_1080p_fr", source="Ma Team").endswith("-MaTeam")


# Detag -----------------------------------------------------------------------


def test_the_one_media_file_of_a_folder_is_named_exactly_the_title(tmp_path: Path) -> None:
    item = release(tmp_path, [FR_1080, "Subs/fr.srt", "cover.jpg"], "Le Film (2020)")
    title = "Le.Film.2020.VFF.1080p.BluRay.AC3.5.1.x264-TFA"
    files = upload_files(item, title, IGNORE, VideoProfile.media_extensions)
    assert [f.torrent_path for f in files] == [
        f"{title}/{title}.mkv",
        f"{title}/Subs/fr.srt",
        f"{title}/cover.jpg",
    ]
    packs = release(tmp_path, ["a.S01E01.mkv", "a.S01E02.mkv"], "Pack")
    names = [
        f.torrent_path
        for f in upload_files(packs, "Pack.S01", IGNORE, VideoProfile.media_extensions)
    ]
    assert names == ["Pack.S01/a.S01E01.mkv", "Pack.S01/a.S01E02.mkv"]  # each keeps its own name
    assert [f.torrent_path for f in upload_files(item, "T", IGNORE)][-1] != "T/T.mkv"


# NFO, description, Draft -----------------------------------------------------


def uploaded(
    tmp_path: Path, file: str = FR_1080, fixture: str = "film_x264_1080p_fr", **kw: object
):  # type: ignore[no-untyped-def]
    item = release(tmp_path, [file])
    p = profile({file: fixture}, **kw)  # type: ignore[arg-type]
    p.inspect(item, IGNORE)
    title = "Le.Film.2020.VFF.1080p.BluRay.AC3.5.1.x264-TFA"
    return p, item, title, upload_files(item, title, IGNORE, p.media_extensions)


def test_the_nfo_is_mediainfos_text_under_the_name_the_torrent_gives_the_file(
    tmp_path: Path,
) -> None:
    p, item, title, files = uploaded(tmp_path)
    nfo = p.nfo(title, files)
    assert nfo.startswith(f"{title}\n\nFichiers ....... : 1\n")
    assert f"Complete name                            : {title}.mkv" in nfo
    assert "Format                                   : AVC" in nfo
    assert "/tmp" not in nfo and str(tmp_path) not in nfo
    assert "Durée .......... : 0:00:01" in nfo


def test_a_pack_of_more_than_ten_files_lists_the_first_in_the_nfo(tmp_path: Path) -> None:
    names = [f"Show.S01E{n:02d}.FRENCH.1080p.WEB.x264-TFA.mkv" for n in range(1, 13)]
    item = release(tmp_path, names, "Show.S01")
    p = profile({n: "film_x264_1080p_fr" for n in names})
    p.inspect(item, IGNORE)
    nfo = p.nfo("Show.S01", upload_files(item, "Show.S01", IGNORE, p.media_extensions))
    assert nfo.count("Complete name") == 1 and "Fichiers ....... : 12" in nfo
    few = tmp_path / "few"
    few.mkdir()
    item = release(few, names[:3], "Show.S01")
    p.inspect(item, IGNORE)
    assert (
        p.nfo("T", upload_files(item, "T", IGNORE, p.media_extensions)).count("Complete name") == 3
    )


def test_a_disc_nfo_lists_its_files(tmp_path: Path) -> None:
    item = release(tmp_path, ["BDMV/STREAM/00000.m2ts"], "Disque")
    p = profile()
    p.inspect(item, IGNORE)
    assert "Contenu :" in p.nfo("Disque", upload_files(item, "Disque", IGNORE, p.media_extensions))


def test_the_description_has_the_image_the_titles_the_synopsis_and_the_facts(
    tmp_path: Path,
) -> None:
    p, item, title, files = uploaded(tmp_path, tmdb=Tmdb(LE_FILM))
    text = p.description(title, files, "", "")
    assert "[img]…[/img]" in text and "[h2]Le Film Français[/h2]" in text
    assert "[b]Titre original :[/b] The Film" in text and "Une histoire." in text
    assert "[b]Vidéo :[/b] AVC 1080p, 6000 kb/s" in text
    assert (
        "[b]Audio :[/b] AC3 5.1 FR" in text and "[b]Sous-titres :[/b] FR (UTF-8, complets)" in text
    )
    assert "Plateforme VOD" not in text
    web = tmp_path / "w"
    web.mkdir()
    name = "Film.2020.FRENCH.1080p.WEB-DL.H264-TEAM.mp4"
    p, item, title, files = uploaded(web, name, "film_webdl_1080p")
    web_title = "Film.2020.VFF.1080p.WEB-DL.AAC.2.0.H264-TEAM"
    assert "[b]Plateforme VOD :[/b] " in p.description(web_title, files, "", "https://i/x.png")


def test_the_draft_carries_the_mediainfo_text_and_tmdb_data_when_known(tmp_path: Path) -> None:
    p, item, title, files = uploaded(tmp_path, tmdb=Tmdb(LE_FILM))
    fields = p.draft_fields(item, IGNORE, files)
    assert fields["tmdbData"] == {"id": 1, "x": "y"}
    assert "Format                                   : Matroska" in fields["mediainfo"]
    body = draft_body(title, "d", 1, 6, b"t", "n", None, fields)
    assert body["mediainfo"] == fields["mediainfo"] and body["tmdbData"] == fields["tmdbData"]
    unknown = tmp_path / "u"
    unknown.mkdir()
    p, item, title, files = uploaded(unknown)
    assert p.draft_fields(item, IGNORE, files)["tmdbData"] is None


def test_an_identified_item_is_looked_up_on_c411_by_tmdb_id(tmp_path: Path) -> None:
    p, item, title, files = uploaded(tmp_path, tmdb=Tmdb(LE_FILM))
    query = p.existing_query(item, IGNORE)
    assert query.ids == {"tmdbId": "1", "tmdbType": "movie"} and query.text
    other = tmp_path / "o"
    other.mkdir()
    p, item, title, files = uploaded(other)
    assert p.existing_query(item, IGNORE).ids == {}


def test_a_series_is_identified_as_tv_and_a_failing_tmdb_changes_nothing(tmp_path: Path) -> None:
    class Down(Tmdb):
        def lookup(self, title, year, kind):  # type: ignore[no-untyped-def]
            raise OSError("offline")

    item = release(tmp_path, [FR_1080])
    p = profile({FR_1080: "film_x264_1080p_fr"}, tmdb=Down())
    p.inspect(item, IGNORE)
    assert p.identified == {} and p.facts  # MediaInfo still read
    tv = tmp_path / "tv"
    tv.mkdir()
    asked = Tmdb(TmdbInfo("9", "tv", "Série", "Show", "2020", "", {}))
    item = release(tv, ["Show.S01E02.FRENCH.1080p.WEB.x264-TFA.mkv"])
    profile(tmdb=asked).inspect(item, IGNORE)
    assert asked.asked == [("Show", "None")]


def test_an_id_in_the_item_name_is_used_without_a_search(tmp_path: Path) -> None:
    asked = Tmdb(INCEPTION)
    item = release(tmp_path, ["Inception.2010.FRENCH.1080p.BluRay.x264-TFA {tmdb-27205}.mkv"])
    p = profile(tmdb=asked)
    p.inspect(item, IGNORE)
    assert asked.asked == [] and p.identified[item.path.name].id == "27205"


# Options ---------------------------------------------------------------------


def test_options_are_pre_filled_from_mediainfo_where_their_values_name_them(tmp_path: Path) -> None:
    langue = OptionType(
        1,
        "Langue",
        True,
        True,
        (
            OptionValue(1, "Anglais"),
            OptionValue(2, "Français (VFF/TrueFrench)"),
            OptionValue(3, "Multi (Français inclus)"),
        ),
    )
    quality = OptionType(
        7, "Qualité", False, False, (OptionValue(70, "720p"), OptionValue(71, "1080p"))
    )
    source = OptionType(
        8, "Source", False, False, (OptionValue(80, "WEB-DL"), OptionValue(81, "BluRay"))
    )
    codec = OptionType(
        9, "Codec vidéo", False, False, (OptionValue(90, "x265"), OptionValue(91, "x264"))
    )
    genre = OptionType(5, "Genre", True, False, (OptionValue(50, "Action"),))
    p, item, title, files = uploaded(tmp_path)
    assert p.suggested_options(item, IGNORE, [langue, quality, source, codec, genre]) == {
        1: [2],
        7: [71],
        8: [81],
        9: [91],
    }
    multi = tmp_path / "m"
    multi.mkdir()
    name = "Film.2020.MULTI.1080p.BluRay.x264-TFA.mkv"
    p, item, title, files = uploaded(multi, name, "film_multi")
    assert p.suggested_options(item, IGNORE, [langue]) == {1: [3]}
    assert profile().suggested_options(item, IGNORE, [langue]) == {}  # not inspected


def test_the_c411_film_options_take_the_language_from_mediainfo(tmp_path: Path) -> None:
    import json

    from torrentlinker.options import parse_options

    types = parse_options(json.loads((FIXTURES.parent / "c411_options_6.json").read_text("utf-8")))
    p, item, title, files = uploaded(tmp_path)
    chosen = p.suggested_options(item, IGNORE, types)
    langue = next(t for t in types if t.name == "Langue")
    french = next(v.id for v in langue.values if v.label.startswith("Français"))
    assert chosen == {langue.id: [french]}
