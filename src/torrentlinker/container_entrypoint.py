"""Linux container bootstrap. Only an explicit root start repairs /config ownership."""

from __future__ import annotations

import os
import signal
import stat
import sys
from pathlib import Path

_CONFIG = Path("/config")
_RUNTIME_DIRS = {"HOME": "home", "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp"}
# CHOWN, DAC_OVERRIDE, SETGID, SETUID. The shipped Compose override restores these.
_REQUIRED_CAPS = (1 << 0) | (1 << 1) | (1 << 6) | (1 << 7)


def _warn(message: str) -> None:
    print(f"TorrentLinker container: {message}", file=sys.stderr, flush=True)


def _numeric_id(name: str, default: int) -> int:
    value = os.environ.get(name, str(default))
    if not value.isascii() or not value.isdecimal() or not 0 < int(value) < 2**32 - 1:
        raise ValueError(f"{name} must be a numeric ID between 1 and 4294967294")
    return int(value)


def _mount_id(fd: int) -> int:
    """Unlike st_dev, a Linux mount ID distinguishes same-device bind mounts."""
    for line in Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines():
        if line.startswith("mnt_id:"):
            return int(line.split()[1])
    raise OSError("Linux /proc mount identity is unavailable; ownership repair skipped")


def _repair_ownership(root: Path, uid: int, gid: int) -> None:
    """Visit only this mount, using pinned descriptors rather than mutable paths.

    /config is reserved for app state. Never include another path in this allowlist.
    Hardlinks are skipped because another name may live outside the allowed tree.
    """

    def visit(fd: int, mount: int) -> None:
        info = os.fstat(fd)
        if _mount_id(fd) != mount:
            return
        is_dir = stat.S_ISDIR(info.st_mode)
        if not is_dir and not (stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
            return
        if (info.st_uid, info.st_gid) != (uid, gid):
            try:
                # O_PATH descriptors cannot be fchown'ed. This proc link addresses
                # the pinned inode, even if its directory entry is replaced.
                os.chown(f"/proc/self/fd/{fd}", uid, gid)
            except OSError as exc:
                _warn(f"cannot repair config ownership: {exc}; continuing as {uid}:{gid}")
        if is_dir:
            directory = os.open(".", os.O_RDONLY | os.O_DIRECTORY, dir_fd=fd)
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        child = -1
                        try:
                            child = os.open(entry.name, os.O_PATH | os.O_NOFOLLOW, dir_fd=fd)
                            visit(child, mount)
                        except (OSError, RecursionError) as exc:
                            _warn(f"config entry skipped: {exc}")
                        finally:
                            if child != -1:
                                os.close(child)
            finally:
                os.close(directory)

    fd = -1
    try:
        fd = os.open(root, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
        visit(fd, _mount_id(fd))
    except OSError as exc:
        _warn(f"cannot repair /config ownership: {exc}; continuing as {uid}:{gid}")
    finally:
        if fd != -1:
            os.close(fd)


def _require_capabilities() -> None:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("CapEff:"):
            if int(line.split()[1], 16) & _REQUIRED_CAPS == _REQUIRED_CAPS:
                return
            break
    raise ValueError(
        "root initialization needs CHOWN, DAC_OVERRIDE, SETUID and SETGID; "
        "use deploy/compose.identity.yaml or start with a prepared non-root user"
    )


def _prepare_runtime(config: Path) -> None:
    """Create writable paths as the application user, without following links."""
    config.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = os.open(config, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for variable, name in _RUNTIME_DIRS.items():
            try:
                os.mkdir(name, mode=0o700, dir_fd=root)
            except FileExistsError:
                pass
            directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            os.close(directory)
            os.environ[variable] = str(config / name)
    finally:
        os.close(root)


def main() -> None:
    from .web.server import argument_parser

    args = argument_parser().parse_args()
    try:
        if os.getuid() == 0:
            import pwd

            # During repair this process may be PID 1, whose default SIGTERM is ignored.
            signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
            account = pwd.getpwnam("torrentlinker")
            uid = _numeric_id("PUID", account.pw_uid)
            gid = _numeric_id("PGID", account.pw_gid)
            _require_capabilities()
            _repair_ownership(_CONFIG, uid, gid)
            # Keep TL_* and secret-file settings. Never reset the environment or
            # mutate passwd/home ownership via usermod. A failed exec is fatal.
            os.execvp(
                "setpriv",
                [
                    "setpriv",
                    f"--reuid={uid}",
                    f"--regid={gid}",
                    "--clear-groups",
                    "--inh-caps=-all",
                    "--ambient-caps=-all",
                    "--no-new-privs",
                    sys.executable,
                    "-m",
                    "torrentlinker.container_entrypoint",
                    *sys.argv[1:],
                ],
            )
        _prepare_runtime(args.config)
        # Tini must have the same UID as the child so the minimal capability set
        # needs no CAP_KILL to forward signals after initialization.
        os.execvp(
            "/usr/bin/tini",
            [
                "/usr/bin/tini",
                "-s",
                "-g",
                "--",
                "torrentlinker-web",
                *sys.argv[1:],
            ],
        )
    except (OSError, ValueError, KeyError) as exc:
        _warn(f"startup failed: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
