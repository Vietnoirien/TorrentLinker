import json
from pathlib import Path

from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.matching import IgnoreList
from torrentlinker.options import parse_options
from torrentlinker.scan import scan_item
from torrentlinker.upload import (
    CATEGORY_GAMES,
    PROFILES,
    GamesProfile,
    Judgement,
    Problem,
    SubcategoryGames,
    default_category,
    profile_for,
    upload_files,
)
from torrentlinker.upload_software import GameType, game_type

FIXTURES = Path(__file__).parent / "fixtures"
IGNORE = IgnoreList.default()
GAMES = GamesProfile()
WINDOWS, NINTENDO, SONY = SubcategoryGames.WINDOWS, SubcategoryGames.NINTENDO, SubcategoryGames.SONY


def item(tmp_path: Path, name: str, files: list[str] | dict[str, bytes]) -> LocalItem:
    data = files if isinstance(files, dict) else {f: b"x" * 100 for f in files}
    root = tmp_path / name
    for rel, content in data.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(content)
    return scan_item(root)


def test_the_games_profile_is_category_5_with_ten_subcategories_proposed_for_games() -> None:
    profile = PROFILES[CATEGORY_GAMES]
    assert isinstance(profile, GamesProfile) and profile.category == 5
    assert sorted(s.id for s in profile.subcategories) == [28, 29, 30, 31, 32, 33, 34, 35, 36, 55]
    assert default_category(ContentKind.GAME) == CATEGORY_GAMES
    assert profile_for(ContentKind.GAME) is profile
    assert profile.dotted_names is False


def test_the_default_subcategory_comes_from_the_files(tmp_path: Path) -> None:
    for files, name, expected in (
        (["game.nsp"], "g1", SubcategoryGames.NINTENDO),
        (["game.xci"], "g2", SubcategoryGames.NINTENDO),
        (["game.pkg"], "g3", SubcategoryGames.SONY),
        (["default.xex"], "g4", SubcategoryGames.MICROSOFT),
        (["game.apk"], "g5", SubcategoryGames.SMARTPHONE),
        (["Game.dmg"], "g6", SubcategoryGames.MACOS),
        (["Game.AppImage"], "g7", SubcategoryGames.LINUX),
        (["game.exe", "data.pak"], "g8", SubcategoryGames.WINDOWS),
        (["game.exe"], "Beat Saber VR", SubcategoryGames.VR),
        (["readme.txt"], "g9", SubcategoryGames.OTHER),
    ):
        assert GAMES.default_subcategory(item(tmp_path, name, files), IGNORE) == expected, name


def test_the_release_type_is_decided_from_the_files_present() -> None:
    assert game_type(["G/setup.exe", "G/setup-1.bin"], "G") is GameType.REPACK
    assert game_type(["G/game.exe"], "G-FitGirl Repack") is GameType.REPACK
    assert game_type(["G/game.iso", "G/g.nfo"], "G-RUNE") is GameType.SCENE
    assert game_type(["G/game.exe", "G/Crack/steam_api64.dll"], "G") is GameType.SCENE
    assert game_type(["G/game.exe"], "Game.Update.v1.0-CODEX") is GameType.SCENE
    assert game_type(["G/game.exe", "G/steam_api64.dll"], "G") is GameType.PREACTIVATED
    assert game_type(["G/game.exe"], "G Portable") is GameType.PORTABLE
    assert game_type(["G/goggame-123.info", "G/game.exe"], "G") is GameType.GOG
    assert game_type(["G/game.exe"], "G", nfo="Installer by GOG.com") is GameType.GOG
    assert game_type(["G/game.exe", "G/data.pak"], "G") is GameType.DRM_FREE
    assert game_type(["G/game.exe", "G/steam_api.dll"], "G Portable") is GameType.PORTABLE


def test_pc_games_refuse_archives_and_downloaders(tmp_path: Path) -> None:
    bad = item(tmp_path, "Bad", ["game.rar", "Game Downloader.exe", "game.exe"])
    found = {r.problem: r.detail for r in GAMES.refusals(bad, IGNORE, WINDOWS)}
    assert found == {Problem.ARCHIVE: "rar", Problem.DOWNLOADER: "Game Downloader.exe"}
    ok = item(tmp_path, "Ok", ["game.exe", "data.pak"])
    assert GAMES.refusals(ok, IGNORE, WINDOWS) == []
    empty = tmp_path / "vide"
    empty.mkdir()
    assert [r.problem for r in GAMES.refusals(scan_item(empty), IGNORE)] == [Problem.NO_FILE]


def test_console_games_may_be_archived_one_per_game_but_not_hold_other_containers(
    tmp_path: Path,
) -> None:
    pack = item(tmp_path, "Switch", ["Zelda.zip", "Mario.nsp", "cover.jpg", "game.nfo"])
    assert GAMES.refusals(pack, IGNORE, NINTENDO) == []
    wrong = item(tmp_path, "Wrong", ["Zelda.nsp", "setup.exe", "readme.rtf"])
    found = {r.problem: r.detail for r in GAMES.refusals(wrong, IGNORE, NINTENDO)}
    assert found == {Problem.CONSOLE_CONTAINER: "exe, rtf"}
    sony = item(tmp_path, "Sony", ["Game.pkg", "game.iso"])
    assert GAMES.refusals(sony, IGNORE, SONY) == []
    assert GAMES.refusals(sony, IGNORE) == []  # the list judges by the default subcategory


def test_pc_game_warnings_show_the_type_and_the_one_per_release_rules(tmp_path: Path) -> None:
    scene = item(tmp_path, "Game-CODEX", ["game.iso"])
    found = {w.judgement: w.detail for w in GAMES.warnings(scene, IGNORE, WINDOWS)}
    assert found == {Judgement.RELEASE_TYPE: "Scene", Judgement.ONE_PER_RELEASE: "Scene"}
    gog = item(tmp_path, "Game GOG", ["goggame-1.info", "game.exe"])
    assert [w.judgement for w in GAMES.warnings(gog, IGNORE, WINDOWS)] == [
        Judgement.RELEASE_TYPE,
        Judgement.ONE_GOG,
    ]
    free = item(tmp_path, "Free", ["game.exe"])
    assert [w.judgement for w in GAMES.warnings(free, IGNORE, WINDOWS)] == [Judgement.RELEASE_TYPE]


def test_console_warnings_are_one_version_and_the_region(tmp_path: Path) -> None:
    game = item(tmp_path, "Zelda (Europe)", ["Zelda.nsp"])
    found = {w.judgement: w.detail for w in GAMES.warnings(game, IGNORE, NINTENDO)}
    assert found == {Judgement.ONE_PER_CONSOLE: "", Judgement.REGION: "EU"}
    unknown = item(tmp_path, "Zelda", ["Zelda.nsp"])
    found = {w.judgement: w.detail for w in GAMES.warnings(unknown, IGNORE, NINTENDO)}
    assert found[Judgement.REGION] == ""


def name(tmp_path: Path, folder: str, files: list[str], sub: int = WINDOWS) -> str:
    return GAMES.suggested_name(item(tmp_path, folder, files), IGNORE, "", sub)


def test_scene_and_repack_names_are_kept_as_they_are(tmp_path: Path) -> None:
    assert name(tmp_path, "Cyberpunk.2077.v1.5-GOG-CODEX", ["g.iso"]) == (
        "Cyberpunk.2077.v1.5-GOG-CODEX"
    )
    assert name(tmp_path, "Elden Ring [FitGirl Repack]", ["setup.exe", "setup-1.bin"]) == (
        "Elden Ring [FitGirl Repack]"
    )


def test_a_portable_game_is_named_title_version_and_os_language_portable(tmp_path: Path) -> None:
    assert name(tmp_path, "Doom v1.2 FR Portable", ["doom.exe"]) == (
        "Doom - 1.2 [Windows - FR - PORTABLE]"
    )


def test_a_gog_game_is_named_title_version_language_os_and_gog(tmp_path: Path) -> None:
    assert name(tmp_path, "The Witcher 3 v4.04 MULTI GOG", ["goggame-1.info", "w.exe"]) == (
        "The Witcher 3 (4.04) [MULTI - Windows][GOG]"
    )


def test_a_vr_game_is_prefixed(tmp_path: Path) -> None:
    named = name(tmp_path, "Beat Saber VR v1.3 Portable", ["bs.exe"], SubcategoryGames.VR)
    assert named.startswith("[VR]Beat Saber VR - 1.3 [Windows")


def test_a_console_game_is_named_console_title_region_language_and_container(
    tmp_path: Path,
) -> None:
    assert name(tmp_path, "Zelda Breath (EUR) FR", ["Zelda.nsp"], NINTENDO) == (
        "[Switch]Zelda Breath [EU - FR] NSP"
    )
    assert name(tmp_path, "Bayonetta MULTI USA", ["b.xci"], NINTENDO) == (
        "[Switch]Bayonetta [US - MULTI] XCI"
    )
    assert name(tmp_path, "Mario", ["m.zip"], NINTENDO) == "[Nintendo]Mario ZIP"


def test_ps4_and_ps5_names_end_with_their_title_id(tmp_path: Path) -> None:
    assert name(tmp_path, "God of War CUSA07408 EUR", ["gow.pkg"], SONY) == (
        "[PS4]God of War [EU] PKG-CUSA07408"
    )
    assert name(tmp_path, "Returnal PPSA01234 USA", ["r.pkg"], SONY) == (
        "[PS5]Returnal [US] PKG-PPSA01234"
    )
    assert name(tmp_path, "Halo 3", ["default.xex"], SubcategoryGames.MICROSOFT) == (
        "[Xbox 360]Halo 3 XEX"
    )


def test_a_scene_releases_own_nfo_is_kept_as_it_is(tmp_path: Path) -> None:
    root = tmp_path / "Game-RUNE"
    root.mkdir()
    (root / "game.iso").write_bytes(b"x" * 100)
    (root / "rune.nfo").write_bytes("Rélease by RUNE\n██".encode("cp437", "replace"))
    scene = scan_item(root)
    profile = GamesProfile()
    files = upload_files(scene, "Game-RUNE", IGNORE)

    assert "Titre" in profile.nfo("Game-RUNE", files)  # not inspected: the facts
    profile.inspect(scene, IGNORE)
    nfo = profile.nfo("Game-RUNE", files)
    assert nfo.startswith("R") and "RUNE" in nfo and "Titre" not in nfo
    assert profile.nfos["Game-RUNE"].count("\n") == 1


def test_a_non_scene_nfo_is_made_from_the_facts_with_room_for_the_install_instructions(
    tmp_path: Path,
) -> None:
    folder = item(tmp_path, "Doom v1.2 (2016) FR Portable", ["doom.exe", "base/a.pak"])
    title = "Doom - 1.2 [Windows - FR - PORTABLE]"
    files = upload_files(folder, title, IGNORE)
    nfo = GAMES.nfo(title, files)
    for line in (
        "Titre .......... : Doom - 1.2 [Windows - FR - PORTABLE]",
        "Version ........ : 1.2",
        "Système ........ : Windows",
        "Année .......... : 2016",
        "Taille ......... : 200 o",
        "Langues ........ : FR",
        "Crack / loader . : Portable",
        "Configuration .. : -",
        "Installation :",
        "base/a.pak",
    ):
        assert line in nfo, line
    text = GAMES.description(title, files, "", "https://i/x.png")
    assert "[img]https://i/x.png[/img]" in text and "[b]Crack / loader :[/b] Portable" in text


def test_a_console_nfo_states_the_region_and_no_crack(tmp_path: Path) -> None:
    folder = item(tmp_path, "Zelda (EUR) FR", ["Zelda.nsp"])
    title = "[Switch]Zelda [EU - FR] NSP"
    nfo = GAMES.nfo(title, upload_files(folder, title, IGNORE))
    assert "Titre .......... : Zelda [EU - FR] NSP" in nfo
    assert "Région ......... : EU" in nfo and "Crack / loader . : -" in nfo


def test_the_language_option_is_pre_filled_from_the_name(tmp_path: Path) -> None:
    types = parse_options(json.loads((FIXTURES / "c411_options_6.json").read_text("utf-8")))
    langue = next(t for t in types if t.name == "Langue")
    value = {v.label: v.id for v in langue.values}
    for folder, label in (
        ("Game MULTI5", "Multi (Français inclus)"),
        ("Jeu FR", "Français (VFF/TrueFrench)"),
        ("Game English", "Anglais"),
    ):
        game = item(tmp_path, folder, ["g.exe"])
        assert GAMES.suggested_options(game, IGNORE, types) == {langue.id: [value[label]]}, folder
    plain = item(tmp_path, "Game", ["g.exe"])
    assert GAMES.suggested_options(plain, IGNORE, types) == {}
    assert GAMES.existing_query(plain, IGNORE).text == "Game"
    assert GAMES.draft_fields(plain, IGNORE, []) == {}
