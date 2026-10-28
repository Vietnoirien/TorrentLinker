"""Fast checks of the Linux bootstrap's ownership boundary and startup decisions."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from torrentlinker import container_entrypoint as entry

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux container bootstrap")


@pytest.fixture(autouse=True)
def restore_runtime_environment(monkeypatch):
    for name in ("HOME", "XDG_CACHE_HOME", "TMPDIR"):
        monkeypatch.setenv(name, os.environ.get(name, ""))


@pytest.mark.parametrize("value", ["0", "-1", "4294967295", "", "1.5", " 1001", "١٠٠١"])
def test_invalid_identity_is_rejected(monkeypatch, value):
    monkeypatch.setenv("PUID", value)
    with pytest.raises(ValueError, match="PUID must"):
        entry._numeric_id("PUID", 1000)


def test_default_and_numeric_identity(monkeypatch):
    monkeypatch.delenv("PUID", raising=False)
    assert entry._numeric_id("PUID", 1234) == 1234
    monkeypatch.setenv("PUID", "1001")
    assert entry._numeric_id("PUID", 1234) == 1001


def test_repair_skips_symlinks_hardlinks_and_special_files(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    (config / "symlink").symlink_to(outside)
    (config / "dirlink").symlink_to(tmp_path, target_is_directory=True)
    os.link(outside, config / "hardlink")
    os.mkfifo(config / "fifo")
    normal = config / "normal"
    normal.write_text("app state")
    seen = []
    monkeypatch.setattr(os, "chown", lambda path, uid, gid: seen.append(os.stat(path).st_ino))
    entry._repair_ownership(config, 12345, 12345)
    assert set(seen) == {config.stat().st_ino, normal.stat().st_ino}
    assert outside.read_text() == "untouched"


def test_correct_ownership_is_not_changed(tmp_path, monkeypatch):
    (tmp_path / "state").write_text("owned")
    seen = []
    monkeypatch.setattr(os, "chown", lambda *args: seen.append(args))
    entry._repair_ownership(tmp_path, os.getuid(), os.getgid())
    assert seen == []


def test_symlink_config_is_not_followed(tmp_path, monkeypatch):
    link = tmp_path / "config"
    link.symlink_to(tmp_path, target_is_directory=True)
    seen = []
    monkeypatch.setattr(os, "chown", lambda *args: seen.append(args))
    entry._repair_ownership(link, 12345, 12345)
    assert seen == []


def test_mount_boundary_skips_mount_root_and_children(tmp_path, monkeypatch):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "media").write_text("media")
    seen = []

    def mount_id(fd):
        return 1 if os.fstat(fd).st_ino == tmp_path.stat().st_ino else 2

    monkeypatch.setattr(entry, "_mount_id", mount_id)
    monkeypatch.setattr(os, "chown", lambda path, uid, gid: seen.append(os.stat(path).st_ino))
    entry._repair_ownership(tmp_path, 12345, 12345)
    assert seen == [tmp_path.stat().st_ino]


def test_readonly_ownership_failure_warns_and_continues(tmp_path, monkeypatch, capsys):
    def readonly(*args):
        raise PermissionError("read-only or root-squashed")

    monkeypatch.setattr(os, "chown", readonly)
    entry._repair_ownership(tmp_path, 12345, 12345)
    assert "continuing as 12345:12345" in capsys.readouterr().err


def test_runtime_paths_are_writable_and_keep_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TL_WEB_PASSWORD_FILE", "/run/secrets/web_password")
    entry._prepare_runtime(tmp_path)
    for variable in ("HOME", "XDG_CACHE_HOME", "TMPDIR"):
        directory = Path(os.environ[variable])
        assert directory.parent == tmp_path
        assert directory.stat().st_mode & 0o777 == 0o700
        (directory / "probe").write_text("works")
    assert os.environ["TL_WEB_PASSWORD_FILE"] == "/run/secrets/web_password"


def test_runtime_rejects_symlink_directory(tmp_path, monkeypatch):
    (tmp_path / "home").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        entry._prepare_runtime(tmp_path)


def test_nonroot_start_ignores_puid_and_preserves_arguments(tmp_path, monkeypatch):
    monkeypatch.setenv("TL_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(os, "getuid", lambda: 1001)
    monkeypatch.setenv("PUID", "0")
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--port", "9999"])

    class Executed(Exception):
        pass

    def execute(command, args):
        assert command == "/usr/bin/tini"
        assert args == ["/usr/bin/tini", "-s", "-g", "--", "torrentlinker-web", "--port", "9999"]
        raise Executed

    monkeypatch.setattr(os, "execvp", execute)
    monkeypatch.setattr(entry, "_repair_ownership", lambda *args: pytest.fail("non-root chown"))
    with pytest.raises(Executed):
        entry.main()
