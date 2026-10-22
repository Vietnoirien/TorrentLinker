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
from torrentlinker.upload_software import ReleaseType, release_type

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


def test_the_release_type_is_decided_from_the_files_present() -> None:
    assert release_type(["App/setup.exe"]) is ReleaseType.INSTALLER
    assert release_type(["App/setup.exe", "Crack/crack.exe"]) is ReleaseType.CRACK
    assert release_type(["App/setup.exe", "keygen/KeyGen.exe"]) is ReleaseType.KEYGEN
    assert release_type(["App/setup.exe", "Patch.exe"]) is ReleaseType.PATCH
    assert release_type(["App/App.exe", "App/lib.dll"]) is ReleaseType.PORTABLE
    assert release_type(["App.exe"], "App Portable") is ReleaseType.PORTABLE
    assert release_type(["Tool.dmg"]) is ReleaseType.INSTALLER
    assert release_type(["app.apk"]) is ReleaseType.INSTALLER
    assert release_type(["setup.exe", "Activator.exe", "patch.exe"]) is ReleaseType.CRACK
    assert release_type(["a/keygen.exe", "a/crack.exe"]) is ReleaseType.KEYGEN
    assert release_type(["readme.txt"]) is ReleaseType.INSTALLER
    assert release_type(["Setup_x64.msi"]) is ReleaseType.INSTALLER


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
    for judgement in (
        Judgement.INSTALL_NOTE,
        Judgement.NO_ALPHA,
        Judgement.NO_IPTV,
        Judgement.OLDER_VERSION,
    ):
        assert judgement in found
    portable = item(tmp_path, "Tool Portable", ["Tool.exe"])
    judged = [w.judgement for w in APPS.warnings(portable, IGNORE, WINDOWS)]
    assert Judgement.INSTALL_NOTE not in judged and Judgement.RELEASE_TYPE in judged


def test_a_desktop_name_is_name_version_and_os_language_type(tmp_path: Path) -> None:
    folder = item(tmp_path, "Adobe Photoshop 2024 v25.1.0 MULTi", ["setup.exe", "crack/crack.exe"])
    assert APPS.suggested_name(folder, IGNORE, "", WINDOWS) == (
        "Adobe Photoshop 2024 25.1.0 [Windows MULTI Crack]"
    )
    plain = item(tmp_path, "Notepad++", ["Notepad.exe", "plugins/a.dll"])
    assert APPS.suggested_name(plain, IGNORE, "", WINDOWS) == "Notepad++ [Windows Portable]"
    mac = item(tmp_path, "Affinity Photo 2.3 (French)", ["Affinity.dmg"])
    assert APPS.suggested_name(mac, IGNORE, "", SubcategoryApps.MACOS) == (
        "Affinity Photo 2.3 [macOS FR Installer]"
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
