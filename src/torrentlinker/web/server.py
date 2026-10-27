"""Run one headless server process with an exclusive configuration directory."""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping
from pathlib import Path


def resolve_password(password_file: Path | None, environ: Mapping[str, str]) -> str | None:
    """Return the Web UI password, preferring the file over TL_WEB_PASSWORD."""
    if password_file is not None:
        return password_file.read_text().strip()
    value = environ.get("TL_WEB_PASSWORD", "").strip()
    return value or None


def main() -> int:
    parser = argparse.ArgumentParser(description="TorrentLinker Web UI")
    parser.add_argument("--host", default=os.getenv("TL_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("TL_WEB_PORT", "8787")))
    parser.add_argument(
        "--config", type=Path, default=Path(os.getenv("TL_CONFIG_DIR", "./torrentlinker-data"))
    )
    parser.add_argument("--password-file", type=Path, default=os.getenv("TL_WEB_PASSWORD_FILE"))
    parser.add_argument("--root", action="append", type=Path, default=[])
    parser.add_argument(
        "--secure-cookie", action="store_true", default=os.getenv("TL_SECURE_COOKIE", "0") == "1"
    )
    parser.add_argument("--root-path", default=os.getenv("TL_ROOT_PATH", ""))
    args = parser.parse_args()
    try:
        password = resolve_password(args.password_file, os.environ)
    except OSError as error:
        parser.error(f"Cannot read the password file: {error}")
    if password is None:
        parser.error(
            "Provide --password-file, TL_WEB_PASSWORD_FILE or TL_WEB_PASSWORD, "
            "with a password of at least 12 characters."
        )
    roots = tuple(
        args.root or [Path(p) for p in os.getenv("TL_STORAGE_ROOTS", "").split(os.pathsep) if p]
    )
    directory = args.config.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Only one process may recover jobs or use a connection's rate limits at a time.
    import fcntl

    import uvicorn

    from torrentlinker.web.app import create_app

    with (directory / "server.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another TorrentLinker server already uses this configuration directory.")
        secret_files = {
            name: Path(value)
            for name in (
                "qbit-password",
                "qbit-api-key",
                "deluge-password",
                "transmission-password",
                "utorrent-password",
                "indexer-api-key",
                "announce-url",
                "proxy-password",
            )
            if (value := os.getenv("TL_" + name.upper().replace("-", "_") + "_FILE"))
        }
        try:
            app = create_app(
                directory,
                password=password,
                roots=roots,
                secret_files=secret_files,
                secure_cookie=args.secure_cookie,
            )
        except (ValueError, OSError) as error:
            parser.error(f"Cannot initialize server: {error}")
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            workers=1,
            proxy_headers=False,
            root_path=args.root_path,
            access_log=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
