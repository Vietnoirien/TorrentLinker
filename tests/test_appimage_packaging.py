"""Exercise the AppDir assembly without downloading or compressing an AppImage."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "linux", reason="Linux AppImage packaging")
def test_appimage_uses_host_compiler_runtime(tmp_path):
    root = Path(__file__).resolve().parents[1]
    packaging = tmp_path / "packaging"
    packaging.mkdir()
    shutil.copy(root / "packaging/build_appimage.sh", packaging)
    (packaging / "torrentlinker.desktop").write_text("[Desktop Entry]\n")
    assets = tmp_path / "src/torrentlinker/assets"
    assets.mkdir(parents=True)
    (assets / "icon.png").write_bytes(b"icon")
    bundle = tmp_path / "dist/torrentlinker"
    internal = bundle / "_internal"
    nested = internal / "nested"
    nested.mkdir(parents=True)
    for directory in (internal, nested):
        (directory / "libstdc++.so.6.0.30").write_bytes(b"old runtime")
        (directory / "libstdc++.so.6").symlink_to("libstdc++.so.6.0.30")
        (directory / "libgcc_s.so.1").write_bytes(b"old runtime")
    (internal / "libpulse.so.0").write_bytes(b"keep audio")
    launcher = bundle / "torrentlinker"
    launcher.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    launcher.chmod(0o755)
    build = tmp_path / "build"
    build.mkdir()
    tool = build / "appimagetool"
    tool.write_text('#!/bin/sh\ntest -x "$1/AppRun"\n')
    tool.chmod(0o755)

    subprocess.run(["bash", str(packaging / "build_appimage.sh")], check=True)
    appdir = build / "AppDir"
    assert not list(appdir.rglob("libstdc++.so*"))
    assert not list(appdir.rglob("libgcc_s.so*"))
    assert (appdir / "usr/bin/_internal/libpulse.so.0").read_bytes() == b"keep audio"
    assert (internal / "libstdc++.so.6").exists(), "Source build must stay intact"
    result = subprocess.run(
        [str(appdir / "AppRun"), "an argument", "--smoke-test"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == ["an argument", "--smoke-test"]
