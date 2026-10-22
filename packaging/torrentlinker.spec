# PyInstaller spec: one-file .exe on Windows, one-dir build on Linux (wrapped into an AppImage).
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

windows = sys.platform == "win32"

datas = (
    collect_data_files("torrentlinker")
    + collect_data_files("guessit")
    + collect_data_files("babelfish")
)
hiddenimports = (
    collect_submodules("keyring.backends")
    + collect_submodules("guessit")
    + collect_submodules("babelfish")
    + collect_submodules("rebulk")
    # mutagen picks its format readers by file type (the Audio and Ebook uploads)
    + collect_submodules("mutagen")
    # Imported only when a SOCKS proxy is set (httpx, and requests for qBittorrent)
    + collect_submodules("socksio")
    + ["socks", "sockshandler"]
    # The Upload tab's 3D view is a QML scene, which PyInstaller cannot see from imports
    + ["PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets", "PySide6.QtQml"]
)
# libmediainfo, which pymediainfo's wheels carry (ADR-0012)
binaries = collect_dynamic_libs("pymediainfo")
excludes = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtPdf", "tkinter"]

a = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
)
pyz = PYZ(a.pure)

if windows:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        name="TorrentLinker",
        console=False,
        icon="../src/torrentlinker/assets/icon.png",
    )
else:
    exe = EXE(pyz, a.scripts, exclude_binaries=True, name="torrentlinker", console=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="torrentlinker")
