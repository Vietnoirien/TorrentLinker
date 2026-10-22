import zipfile
from pathlib import Path

from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.matching import IgnoreList
from torrentlinker.options import OptionType, OptionValue
from torrentlinker.scan import scan_item
from torrentlinker.upload import (
    CATEGORY_EMULATION,
    CATEGORY_GPS,
    PROFILES,
    EmulationProfile,
    GpsProfile,
    Judgement,
    Problem,
    SubcategoryEmulation,
    SubcategoryGps,
    default_category,
    upload_files,
)

IGNORE = IgnoreList.default()
GPS = GpsProfile()
ROMS, EMULATORS = SubcategoryEmulation.ROMS, SubcategoryEmulation.EMULATORS


def folder(tmp_path: Path, name: str, files: list[str] | dict[str, bytes]) -> LocalItem:
    data = files if isinstance(files, dict) else {f: b"x" * 100 for f in files}
    root = tmp_path / name
    for rel, content in data.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(content)
    return scan_item(root)


def problems(profile: GpsProfile | EmulationProfile, item: LocalItem) -> dict[Problem, str]:
    return {r.problem: r.detail for r in profile.refusals(item, IGNORE)}


# GPS ---------------------------------------------------------------------------


def test_the_gps_profile_is_category_7_with_three_subcategories_picked_by_the_user() -> None:
    profile = PROFILES[CATEGORY_GPS]
    assert isinstance(profile, GpsProfile) and profile.category == 7
    assert [s.id for s in profile.subcategories] == [39, 40, 41]
    assert ContentKind.OTHER not in {k for k in ContentKind if default_category(k) == 7}
    assert profile.dotted_names is False


def test_map_files_default_to_maps_the_rest_to_applications(tmp_path: Path) -> None:
    maps = folder(tmp_path, "Garmin Europe", ["gmapsupp.img", "readme.txt"])
    assert GPS.default_subcategory(maps, IGNORE) == SubcategoryGps.MAPS
    app = folder(tmp_path, "Sygic", ["setup.exe"])
    assert GPS.default_subcategory(app, IGNORE) == SubcategoryGps.APPLICATIONS


def test_gps_refuses_archives_and_downloaders_but_not_install_cabs_or_text(tmp_path: Path) -> None:
    ok = folder(tmp_path, "Ok", ["setup.exe", "install.cab", "notice.txt", "keygen.nfo"])
    assert problems(GPS, ok) == {}
    bad = folder(tmp_path, "Bad", ["maps.rar", "Sygic Downloader.exe", "WebSetup.exe", "a.exe"])
    found = problems(GPS, bad)
    assert found[Problem.ARCHIVE] == "rar"
    assert found[Problem.DOWNLOADER] == "Sygic Downloader.exe, WebSetup.exe"
    empty = tmp_path / "vide"
    empty.mkdir()
    assert problems(GPS, scan_item(empty)) == {Problem.NO_FILE: ""}


def test_gps_warns_about_version_activation_and_the_application_bans(tmp_path: Path) -> None:
    item = folder(tmp_path, "App", ["a.exe"])
    judged = [w.judgement for w in GPS.warnings(item, IGNORE, SubcategoryGps.APPLICATIONS)]
    assert judged == [Judgement.VERSION_ACTIVATION, Judgement.NO_ALPHA]


def test_a_gps_name_is_brand_zone_year_and_support(tmp_path: Path) -> None:
    item = folder(tmp_path, "Garmin Europe Cartes (2024)", ["setup.exe"])
    assert GPS.suggested_name(item, IGNORE, "", SubcategoryGps.MAPS) == (
        "Garmin.Europe.Cartes.2024.Windows"
    )
    plain = folder(tmp_path, "Étrange", ["a.txt"])
    assert GPS.suggested_name(plain, IGNORE, "", SubcategoryGps.MISC) == "Etrange"


def test_the_gps_nfo_states_the_facts_and_leaves_the_install_instructions_to_write(
    tmp_path: Path,
) -> None:
    item = folder(tmp_path, "Sygic v21.4 (2023)", ["setup.exe", "data/map.img"])
    title = "Sygic.v21.4.2023.Windows"
    files = upload_files(item, title, IGNORE)
    nfo = GPS.nfo(title, files)
    for line in (
        f"Titre .......... : {title}",
        "Version ........ : 21.4",
        "Système ........ : Windows",
        "Année .......... : 2023",
        "Taille ......... : 200 o",
        "Langues ........ : -",
        "Activation ..... : -",
        "Installation :",
        "Contenu :",
        "data/map.img",
    ):
        assert line in nfo, line
    text = GPS.description(title, files, "", "")
    assert "[img]…[/img]" in text and "[b]Version :[/b] 21.4" in text
    assert "[h3]Installation[/h3]" in text and "[spoiler=Contenu]" in text
    assert "Langues" not in text  # empty facts are left out of the description


def test_gps_has_no_options_and_looks_up_by_title_words(tmp_path: Path) -> None:
    item = folder(tmp_path, "Garmin", ["a.exe"])
    types = [OptionType(1, "Langue", True, True, (OptionValue(1, "x"),))]
    assert GPS.suggested_options(item, IGNORE, types) == {}
    assert GPS.existing_query(item, IGNORE).text == "Garmin"
    assert GPS.draft_fields(item, IGNORE, []) == {}


# Emulation ------------------------------------------------------------------------


def test_the_emulation_profile_is_category_6_with_emulators_and_roms() -> None:
    profile = PROFILES[CATEGORY_EMULATION]
    assert isinstance(profile, EmulationProfile) and profile.category == 6
    assert [s.id for s in profile.subcategories] == [37, 38]
    assert profile.dotted_names is False


def test_roms_default_to_roms_programs_to_emulators(tmp_path: Path) -> None:
    emu = EmulationProfile()
    assert emu.default_subcategory(folder(tmp_path, "a", ["mario.nes"]), IGNORE) == ROMS
    assert emu.default_subcategory(folder(tmp_path, "b", ["retroarch.exe"]), IGNORE) == EMULATORS
    assert emu.default_subcategory(folder(tmp_path, "c", ["game.iso"]), IGNORE) == ROMS


def test_archives_are_refused_unless_the_pack_holds_more_than_fifty_files(tmp_path: Path) -> None:
    emu = EmulationProfile()
    small = folder(tmp_path, "small", ["a.zip", "b.nes"])
    assert problems(emu, small) == {Problem.ARCHIVE: "zip"}
    big = folder(tmp_path, "big", [f"game{n}.zip" for n in range(51)])
    assert problems(emu, big) == {}
    exactly = tmp_path / "exact"
    exactly.mkdir()
    fifty = folder(exactly, "fifty", [f"game{n}.zip" for n in range(50)])
    assert Problem.ARCHIVE in problems(emu, fifty)


def test_a_password_protected_zip_in_a_pack_is_refused_when_detectable(tmp_path: Path) -> None:
    emu = EmulationProfile()
    pack = folder(tmp_path, "pack", [f"game{n}.nes" for n in range(60)])
    plain = pack.path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("a.nes", b"rom")
    locked = pack.path / "locked.zip"
    with zipfile.ZipFile(locked, "w") as z:
        z.writestr("a.nes", b"rom")
    data = bytearray(locked.read_bytes())
    for marker, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = data.index(marker)
        data[i + offset] |= 1  # the "encrypted" bit of the general purpose flags
    locked.write_bytes(bytes(data))
    item = scan_item(pack.path)

    assert problems(emu, item) == {}  # not inspected yet
    emu.inspect(item, IGNORE)
    assert problems(emu, item) == {Problem.PASSWORD_ARCHIVE: "locked.zip"}


def test_a_bin_needs_a_cue_and_clonecd_needs_its_three_files(tmp_path: Path) -> None:
    emu = EmulationProfile()
    assert problems(emu, folder(tmp_path, "a", ["game.bin"])) == {Problem.BIN_NO_CUE: ""}
    assert problems(emu, folder(tmp_path, "b", ["game.bin", "game.cue"])) == {}
    assert problems(emu, folder(tmp_path, "c", ["g.ccd", "g.img"])) == {
        Problem.CLONECD_INCOMPLETE: ".sub"
    }
    assert problems(emu, folder(tmp_path, "d", ["g.ccd", "g.img", "g.sub"])) == {}
    assert problems(emu, folder(tmp_path, "e", ["a/g.bin", "b/g.cue"])) == {Problem.BIN_NO_CUE: ""}


def test_emulation_warns_about_retro_platforms_and_mixed_machines(tmp_path: Path) -> None:
    emu = EmulationProfile()
    one = folder(tmp_path, "one", ["a.nes", "b.nes"])
    assert [w.judgement for w in emu.warnings(one, IGNORE, ROMS)] == [Judgement.RETRO_ONLY]
    mixed = folder(tmp_path, "mixed", ["a.nes", "b.sfc", "c.gba"])
    found = {w.judgement: w.detail for w in emu.warnings(mixed, IGNORE, ROMS)}
    assert found[Judgement.NO_MIXED_MACHINES] == "Game Boy Advance, NES, SNES"
    mame = folder(tmp_path, "MAME 0.250 ROMs", ["a.nes", "b.sfc"])
    assert Judgement.NO_MIXED_MACHINES not in {
        w.judgement for w in emu.warnings(mame, IGNORE, ROMS)
    }


def test_a_console_game_is_named_console_title_region_language_and_container(
    tmp_path: Path,
) -> None:
    emu = EmulationProfile()
    game = folder(tmp_path, "Zelda (Europe) (Fr,En,De)", ["Zelda.sfc"])
    assert emu.suggested_name(game, IGNORE, "", ROMS) == "[SNES]Zelda [EU - MULTI] SFC"
    french = folder(tmp_path, "Bomberman (France) (Fr)", ["b.nes"])
    assert emu.suggested_name(french, IGNORE, "", ROMS) == "[NES]Bomberman [EU - FR] NES"
    disc = folder(tmp_path, "Jeu Rétro", ["disc.iso"])
    assert emu.suggested_name(disc, IGNORE, "", ROMS) == "[Console]Jeu Rétro ISO"
    program = folder(tmp_path, "Snes9x 1.62", ["snes9x.exe"])
    assert emu.suggested_name(program, IGNORE, "", EMULATORS) == "Snes9x 1.62 [Windows]"


def test_the_emulation_nfo_lists_platform_region_language_count_size_and_every_file(
    tmp_path: Path,
) -> None:
    emu = EmulationProfile()
    item = folder(tmp_path, "Zelda (Europe) (Fr,En)", ["Zelda.sfc", "Zelda.srm"])
    title = "[SNES]Zelda [EU - MULTI] SFC"
    files = upload_files(item, title, IGNORE)
    nfo = emu.nfo(title, files)
    for line in (
        "Titre .......... : Zelda [EU - MULTI] SFC",
        "Plateforme ..... : SNES",
        "Région ......... : EU",
        "Langue ......... : MULTI",
        "Fichiers ....... : 2",
        "Taille totale .. : 200 o",
        "Zelda.sfc",
        "Zelda.srm",
    ):
        assert line in nfo, line
    text = emu.description(title, files, "", "https://i/x.png")
    assert "[img]https://i/x.png[/img]" in text and "[b]Plateforme :[/b] SNES" in text
    assert emu.suggested_options(item, IGNORE, []) == {}
    assert emu.existing_query(item, IGNORE).text == "Zelda Europe Fr,En"
