import zipfile
from pathlib import Path

from torrentlinker.domain import ContentKind
from torrentlinker.matching import IgnoreList
from torrentlinker.scan import scan_item
from torrentlinker.upload import (
    CATEGORY_APPS,
    PROFILES,
    ApplicationsProfile,
    Judgement,
    Problem,
    SubcategoryApps,
    default_category,
    upload_files,
)
from torrentlinker.upload_software import ReleaseType, release_types

IGNORE = IgnoreList.default()
APPS = ApplicationsProfile()
WINDOWS, MOBILE = SubcategoryApps.WINDOWS, SubcategoryApps.SMARTPHONE


def item(tmp_path: Path, name: str, files: list[str]):  # type: ignore[no-untyped-def]
    root = tmp_path / name
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"x" * 100)
    return scan_item(root)


def test_the_applications_profile_is_category_4_with_seven_subcategories_picked_by_the_user() -> (
    None
):
    profile = PROFILES[CATEGORY_APPS]
    assert isinstance(profile, ApplicationsProfile) and profile.category == 4
    assert [s.id for s in profile.subcategories] == [21, 22, 23, 24, 25, 26, 27]
    assert not [k for k in ContentKind if default_category(k) == CATEGORY_APPS]
    assert profile.dotted_names is False


def test_the_default_subcategory_comes_from_the_files(tmp_path: Path) -> None:
    for files, expected in (
        (["setup.exe"], SubcategoryApps.WINDOWS),
        (["app.msi"], SubcategoryApps.WINDOWS),
        (["App.dmg"], SubcategoryApps.MACOS),
        (["App.pkg"], SubcategoryApps.MACOS),
        (["tool.deb"], SubcategoryApps.LINUX),
        (["tool.rpm"], SubcategoryApps.LINUX),
        (["Tool.AppImage"], SubcategoryApps.LINUX),
        (["app.apk"], SubcategoryApps.SMARTPHONE),
        (["app.ipa"], SubcategoryApps.SMARTPHONE),
        (["cours.pdf", "video.mp4"], SubcategoryApps.OTHER),
    ):
        folder = item(tmp_path, f"x{files[0]}", files)
        assert APPS.default_subcategory(folder, IGNORE) == expected, files


K, C, P, U, A, PORT = (
    ReleaseType.KEYGEN,
    ReleaseType.CRACK,
    ReleaseType.PATCH,
    ReleaseType.UNLOCKED,
    ReleaseType.PREACTIVATED,
    ReleaseType.PORTABLE,
)


def test_the_release_type_follows_c411s_table() -> None:
    setup = "App/setup.exe"
    assert release_types([setup, "keygen/KeyGen.exe"]) == (K,)
    assert release_types(["keygen/KeyGen.exe", "App/app.exe"]) == (K, PORT)
    assert release_types([setup, "Crack/crack.exe"]) == (C,)
    assert release_types(["Crack/crack.exe", "App/app.exe"]) == (C, PORT)
    assert release_types([setup, "Patch.exe"]) == (P,)
    assert release_types(["Patch.exe", "App.exe"]) == (P, PORT)
    assert release_types([setup]) == (U,)
    assert release_types(["App/App.exe", "App/lib.dll"]) == (U, PORT)
    assert release_types([setup], "App PreActivated") == (A,)
    assert release_types(["App.exe"], "App Preactivated") == (A, PORT)
    assert release_types([setup], "App Portable") == (U, PORT)
    assert release_types(["a/keygen.exe", "a/crack.exe", setup]) == (K,)  # keygen first
    assert release_types([setup, "Activator.exe", "patch.exe"]) == (C,)
    assert release_types(["Tool.dmg"]) == (U,)
    assert release_types(["app.apk"]) == (U,)
    assert release_types(["Setup_x64.msi", "crack.exe"]) == (C,)
    assert release_types(["readme.txt"]) == (U, PORT)  # no installer


def test_archives_are_refused_but_cabs_and_zipped_support_files_are_not(
    tmp_path: Path,
) -> None:
    ok = item(tmp_path, "Ok", ["setup.exe", "data1.cab", "install.txt", "patch.cs", "run.bat"])
    assert APPS.refusals(ok, IGNORE) == []
    root = tmp_path / "Zipped"
    root.mkdir()
    (root / "setup.exe").write_bytes(b"x")
    with zipfile.ZipFile(root / "notes.zip", "w") as z:
        z.writestr("readme.txt", "hi")
        z.writestr("src/patch.cs", "code")
    assert APPS.refusals(scan_item(root), IGNORE) == []
    with zipfile.ZipFile(root / "more.zip", "w") as z:
        z.writestr("setup2.exe", "binary")
    assert [r.detail for r in APPS.refusals(scan_item(root), IGNORE)] == ["zip"]


def test_downloaders_and_missing_files_are_refused(tmp_path: Path) -> None:
    bad = item(tmp_path, "Bad", ["a.zip", "b.7z", "InstallOnline.exe", "ok.exe"])
    found = {r.problem: r.detail for r in APPS.refusals(bad, IGNORE)}
    assert found == {Problem.ARCHIVE: "7z, zip", Problem.DOWNLOADER: "InstallOnline.exe"}
    empty = tmp_path / "vide"
    empty.mkdir()
    assert [r.problem for r in APPS.refusals(scan_item(empty), IGNORE)] == [Problem.NO_FILE]


def test_trainers_and_hack_tools_are_refused(tmp_path: Path) -> None:
    bad = item(tmp_path, "Bad", ["setup.exe", "Game Trainer.exe", "CheatEngine.exe"])
    found = {r.problem: r.detail for r in APPS.refusals(bad, IGNORE)}
    assert found == {Problem.FORBIDDEN_TOOL: "CheatEngine.exe, Game Trainer.exe"}


def test_archives_and_downloaders_are_refused_but_cabs_and_support_text_are_not(
    tmp_path: Path,
) -> None:
    ok = item(tmp_path, "Ok", ["setup.exe", "data1.cab", "install.txt", "patch.cs", "run.bat"])
    assert APPS.refusals(ok, IGNORE) == []
    bad = item(tmp_path, "Bad", ["a.zip", "b.7z", "InstallOnline.exe", "ok.exe"])
    found = {r.problem: r.detail for r in APPS.refusals(bad, IGNORE)}
    assert found == {Problem.ARCHIVE: "7z, zip", Problem.DOWNLOADER: "InstallOnline.exe"}
    empty = tmp_path / "vide"
    empty.mkdir()
    assert [r.problem for r in APPS.refusals(scan_item(empty), IGNORE)] == [Problem.NO_FILE]


def test_warnings_show_the_release_type_and_ask_for_an_install_note_unless_portable(
    tmp_path: Path,
) -> None:
    crack = item(tmp_path, "Photoshop", ["setup.exe", "crack/crack.exe"])
    found = {w.judgement: w.detail for w in APPS.warnings(crack, IGNORE, WINDOWS)}
    assert found[Judgement.RELEASE_TYPE] == "Crack"
    assert Judgement.PLUGIN_HOST not in found
    for judgement in (
        Judgement.INSTALL_NOTE,
        Judgement.NO_ALPHA,
        Judgement.NO_IPTV,
        Judgement.OLDER_VERSION,
    ):
        assert judgement in found
    portable = item(tmp_path, "Tool Portable", ["Tool.exe"])
    judged = {w.judgement: w.detail for w in APPS.warnings(portable, IGNORE, WINDOWS)}
    assert Judgement.INSTALL_NOTE not in judged
    assert judged[Judgement.RELEASE_TYPE] == "Unlocked + Portable"


def test_plugins_and_trainings_get_their_own_warnings(tmp_path: Path) -> None:
    plugin = item(tmp_path, "Photoshop Plugin 1.0", ["setup.exe"])
    assert Judgement.PLUGIN_HOST in [w.judgement for w in APPS.warnings(plugin, IGNORE, WINDOWS)]
    course = item(tmp_path, "Cours Excel", ["cours.mp4"])
    judged = [w.judgement for w in APPS.warnings(course, IGNORE, SubcategoryApps.TRAINING)]
    assert Judgement.OFFICIAL_TRAINING in judged
    assert Judgement.RELEASE_TYPE not in judged and Judgement.INSTALL_NOTE not in judged
    name = APPS.suggested_name(course, IGNORE, "", SubcategoryApps.TRAINING)
    assert name == "Cours Excel"


def test_a_desktop_name_is_name_version_and_os_language_type(tmp_path: Path) -> None:
    folder = item(tmp_path, "Adobe Photoshop 2024 v25.1.0 MULTi", ["setup.exe", "crack/crack.exe"])
    assert APPS.suggested_name(folder, IGNORE, "", WINDOWS) == (
        "Adobe Photoshop 2024 25.1.0 [Windows MULTI Crack]"
    )
    plain = item(tmp_path, "Notepad++", ["Notepad.exe", "plugins/a.dll"])
    assert (
        APPS.suggested_name(plain, IGNORE, "", WINDOWS) == "Notepad++ [Windows Unlocked Portable]"
    )
    mac = item(tmp_path, "Affinity Photo 2.3 (French)", ["Affinity.dmg"])
    assert APPS.suggested_name(mac, IGNORE, "", SubcategoryApps.MACOS) == (
        "Affinity Photo 2.3 [macOS FR Unlocked]"
    )


def test_a_mobile_name_starts_with_the_os_and_ends_with_the_extension(tmp_path: Path) -> None:
    folder = item(tmp_path, "Spotify Premium 8.9.2 MULTI", ["Spotify.apk"])
    assert APPS.suggested_name(folder, IGNORE, "", MOBILE) == (
        "[Android] Spotify Premium 8.9.2 MULTI [APK]"
    )
    ios = item(tmp_path, "Procreate 5.3", ["Procreate.ipa"])
    assert APPS.suggested_name(ios, IGNORE, "", MOBILE) == "[iOS] Procreate 5.3 [IPA]"


def test_the_nfo_states_the_facts_the_release_type_and_the_install_instructions_to_write(
    tmp_path: Path,
) -> None:
    folder = item(tmp_path, "Adobe Photoshop v25.1.0 (2023)", ["setup.exe", "crack/crack.exe"])
    title = "Adobe Photoshop 25.1.0 [Windows FR Crack]"
    files = upload_files(folder, title, IGNORE)
    nfo = APPS.nfo(title, files)
    for line in (
        "Titre .......... : Adobe Photoshop 25.1.0",
        "Version ........ : 25.1.0",
        "Système ........ : Windows",
        "Année .......... : 2023",
        "Taille ......... : 200 o",
        "Langues ........ : FR",
        "Activation ..... : Crack",
        "Configuration .. : -",
        "Installation :",
        "crack/crack.exe",
    ):
        assert line in nfo, line
    text = APPS.description(title, files, "", "")
    assert "[img]…[/img]" in text and "[b]Activation :[/b] Crack" in text
    assert "[h3]Installation[/h3]" in text
    other = APPS.nfo("Tool [Windows Keygen]", files)
    assert "Activation ..... : Keygen" in other  # editing the name overrides the decision


def test_no_options_and_a_title_word_lookup(tmp_path: Path) -> None:
    folder = item(tmp_path, "Notepad++", ["a.exe"])
    assert APPS.suggested_options(folder, IGNORE, []) == {}
    assert APPS.existing_query(folder, IGNORE).text == "Notepad++"
    assert APPS.draft_fields(folder, IGNORE, []) == {}
