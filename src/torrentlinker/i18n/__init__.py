"""Translations: English source strings, French shipped as a compiled .qm."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

HERE = Path(__file__).parent
AVAILABLE = ("fr",)


def pick_language(setting: str, system: str | None = None) -> str:
    """The language to use: the setting, or the system language when available."""
    if setting != "auto":
        return setting
    system = system or QLocale.system().name()
    lang = system.split("_")[0].lower()
    return lang if lang in AVAILABLE else "en"


def install(app: QApplication, language: str) -> list[QTranslator]:
    """Install the app's and Qt's own translators; keep the returned list alive."""
    if language == "en":
        return []
    installed = []
    ours = QTranslator(app)
    if ours.load(str(HERE / f"torrentlinker_{language}.qm")):
        app.installTranslator(ours)
        installed.append(ours)
    qt = QTranslator(app)
    qt_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if qt.load(f"qtbase_{language}", qt_dir):
        app.installTranslator(qt)
        installed.append(qt)
    return installed
