import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from torrentlinker import i18n

TS = Path(i18n.__file__).parent / "torrentlinker_fr.ts"


def test_every_ui_string_has_a_french_translation() -> None:
    unfinished = [
        m.findtext("source")
        for m in ET.parse(TS).getroot().iter("message")
        if m.find("translation") is None
        or m.find("translation").get("type") == "unfinished"  # type: ignore[union-attr]
        or not (m.findtext("translation") or "").strip()
    ]
    assert unfinished == []


def test_french_is_used_by_default_on_a_french_system_and_can_be_overridden() -> None:
    assert i18n.pick_language("auto", "fr_FR") == "fr"
    assert i18n.pick_language("auto", "de_DE") == "en"
    assert i18n.pick_language("en", "fr_FR") == "en"


def test_installing_french_translates_the_ui(qapp) -> None:  # type: ignore[no-untyped-def]
    translators = i18n.install(qapp, "fr")
    try:
        assert QCoreApplication.translate("MainWindow", "Scan") == "Analyser"
    finally:
        for t in translators:
            qapp.removeTranslator(t)


def test_translation_file_lists_every_string_in_the_code(tmp_path: Path) -> None:
    import shutil
    import subprocess
    import sys

    lupdate = shutil.which("pyside6-lupdate") or str(
        Path(sys.executable).parent / "pyside6-lupdate"
    )
    sources = sorted(str(p) for p in Path(i18n.__file__).parent.parent.rglob("*.py"))
    fresh = tmp_path / "fresh.ts"
    subprocess.run([lupdate, *sources, "-ts", str(fresh)], check=True, capture_output=True)

    def texts(ts: Path) -> set[tuple[str, str]]:
        root = ET.parse(ts).getroot()
        return {
            (c.findtext("name") or "", m.findtext("source") or "")
            for c in root.iter("context")
            for m in c.iter("message")
        }

    assert texts(fresh) - texts(TS) == set(), "run the lupdate command from the README"
