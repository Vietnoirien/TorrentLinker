"""Archives in the Library: what is inside, and unpacking them so they can be Reseeded.

A Local Item may be a .zip, .rar or .7z of what a torrent holds unpacked. Its listing
(names and uncompressed sizes) is compared with Candidates like a folder would be. To
Reseed, the archive is unpacked into a new folder next to it (ADR-0007): nothing is
overwritten and the archive is kept.

Zip needs nothing more. Rar and 7z are read with 7-Zip, or unrar for rar; without them
those archives are compared as plain files.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath

from torrentlinker.domain import LocalItem

ARCHIVE_SUFFIXES = (".zip", ".rar", ".7z")
SEVEN_ZIP = ("7z", "7zz", "7za")
WINDOWS_TOOLS = {
    "7z": (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"),
    "unrar": (r"C:\Program Files\WinRAR\UnRAR.exe", r"C:\Program Files (x86)\WinRAR\UnRAR.exe"),
}
CHUNK = 1 << 20


class ArchiveError(Exception):
    pass


@dataclass(frozen=True)
class Unpacked:
    """Where an archive goes once unpacked, and the Local Item it then becomes."""

    archive: Path
    into: Path  # the folder the archive's entries are written under
    item: LocalItem  # the new folder, with the files the listing promises

    @property
    def size(self) -> int:
        return self.item.size


def is_archive(item: LocalItem) -> bool:
    return item.path.suffix.lower() in ARCHIVE_SUFFIXES and len(item.files) == 1


def unpacked(item: LocalItem) -> Unpacked | None:
    """The archive as it will be once unpacked; None if it is not one, or cannot be read."""
    if not is_archive(item):
        return None
    try:
        stat = item.path.stat()
        entries = _listing(item.path, stat.st_size, stat.st_mtime_ns)
    except (OSError, ArchiveError):
        return None
    return _layout(item.path, entries) if entries else None


def _layout(archive: Path, entries: dict[str, int]) -> Unpacked:
    """One folder of its own: the archive's top folder when it has a single one, or a
    folder named after the archive."""
    tops = {PurePosixPath(name).parts[0] for name in entries}
    nested = all(len(PurePosixPath(name).parts) > 1 for name in entries)
    if len(tops) == 1 and nested:
        folder = archive.parent / next(iter(tops))
        return Unpacked(archive, archive.parent, LocalItem(folder, dict(entries)))
    folder = archive.parent / archive.stem
    files = {f"{folder.name}/{name}": size for name, size in entries.items()}
    return Unpacked(archive, folder, LocalItem(folder, files))


@lru_cache(maxsize=512)
def _listing(path: Path, size: int, mtime: int) -> dict[str, int]:
    """Files inside the archive and their uncompressed sizes (cached per version of it)."""
    del size, mtime  # only part of the cache key
    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as z:
                entries = {i.filename: i.file_size for i in z.infolist() if not i.is_dir()}
        except zipfile.BadZipFile as e:
            raise ArchiveError(str(e)) from e
    elif seven := _tool("7z"):
        entries = _seven_zip_listing(seven, path)
    elif path.suffix.lower() == ".rar" and (unrar := _tool("unrar")):
        entries = _unrar_listing(unrar, path)
    else:
        raise ArchiveError(f"no tool to read {path.suffix} archives: install 7-Zip")
    for name in entries:
        _check_safe(name)
    return entries


def _tool(name: str) -> str | None:
    names = SEVEN_ZIP if name == "7z" else (name,)
    for n in names:
        if found := shutil.which(n):
            return found
    if sys.platform == "win32":
        for candidate in WINDOWS_TOOLS.get(name, ()):
            if Path(candidate).is_file():
                return candidate
    return None


def _run(args: list[str]) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash on Windows
    done = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
        check=False,
    )
    if done.returncode != 0:
        raise ArchiveError(done.stderr.strip() or f"{Path(args[0]).name} failed")
    return done.stdout


def _blocks(text: str, separator: str) -> list[dict[str, str]]:
    """Blank-line separated blocks of `key<separator>value` lines."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in [*text.splitlines(), ""]:
        if not line.strip():
            if current:
                blocks.append(current)
            current = {}
        elif separator in line:
            key, _, value = line.partition(separator)
            current.setdefault(key.strip(), value)
    return blocks


def _seven_zip_listing(tool: str, path: Path) -> dict[str, int]:
    out = _run([tool, "l", "-slt", "-ba", "-sccUTF-8", str(path)])
    blocks = _blocks(out, " = ")
    if any(
        b.get("Symbolic Link")
        or b.get("Hard Link")
        or any(a.startswith("l") for a in b.get("Attributes", "").split())
        for b in blocks
    ):
        raise ArchiveError("links inside archives are not supported")
    return {
        b["Path"].replace("\\", "/"): int(b.get("Size") or 0)
        for b in blocks
        if b.get("Path") and b.get("Folder") != "+" and not b.get("Attributes", "").startswith("D")
    }


def _unrar_listing(tool: str, path: Path) -> dict[str, int]:
    out = _run([tool, "lt", "-cfg-", str(path)])
    blocks = _blocks(out, ": ")
    if any("link" in b.get("Type", "").lower() for b in blocks):
        raise ArchiveError("links inside archives are not supported")
    return {
        b["Name"].replace("\\", "/"): int(b.get("Size") or 0)
        for b in blocks
        if b.get("Name") and b.get("Type") == "File"
    }


def _check_safe(name: str) -> None:
    parts = PurePosixPath(name).parts
    if not parts or name.startswith(("/", "\\")) or ":" in parts[0] or ".." in parts:
        raise ArchiveError(f"unsafe path in archive: {name}")


def unpack(
    target: Unpacked, progress: Callable[[int, int], None] = lambda done, total: None
) -> None:
    """Unpack into a new folder; never overwrites, and removes what it wrote if it fails.

    `progress(done, total)` follows the bytes written.
    """
    folder = target.item.path
    if folder.exists():
        raise ArchiveError(f"{folder} already exists")
    total = target.size
    try:
        if target.archive.suffix.lower() == ".zip":
            _unzip(target, progress)
        else:
            _unpack_with_tool(target, progress)
        for name, size in target.item.files.items():
            path = folder.parent / PurePosixPath(name)
            if not path.is_file() or path.stat().st_size != size:
                raise ArchiveError(f"{name} was not unpacked whole")
        progress(total, total)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)  # only this call's new folder
        raise


def _unzip(target: Unpacked, progress: Callable[[int, int], None]) -> None:
    done, total = 0, target.size
    with zipfile.ZipFile(target.archive) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            _check_safe(info.filename)
            dest = target.into.joinpath(*PurePosixPath(info.filename).parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, dest.open("xb") as out:  # x: never overwrite
                while chunk := src.read(CHUNK):
                    out.write(chunk)
                    done += len(chunk)
                    progress(done, total)


def _unpack_with_tool(target: Unpacked, progress: Callable[[int, int], None]) -> None:
    """Unpack with each available tool in turn; a tool may list an archive it cannot
    decompress (Debian's 7-Zip and RAR5), so the next one gets a clean try."""
    commands = _unpack_commands(target.archive, target.into)
    if not commands:
        raise ArchiveError(f"no tool to unpack {target.archive.suffix} archives: install 7-Zip")
    errors = []
    for args in commands:
        try:
            _run_unpacking(args, target, progress)
            return
        except ArchiveError as e:
            errors.append(f"{Path(args[0]).name}: {e}")
            shutil.rmtree(target.item.path, ignore_errors=True)  # this call's own folder
    raise ArchiveError("\n".join(errors))


def _unpack_commands(archive: Path, into: Path) -> list[list[str]]:
    commands = []
    if archive.suffix.lower() == ".rar" and (unrar := _tool("unrar")):
        # -o-: never overwrite an existing file.
        commands.append([unrar, "x", "-o-", "-idq", "-cfg-", str(archive), str(into) + os.sep])
    if seven := _tool("7z"):
        # -aos: skip a file that would already exist; never overwrite.
        commands.append([seven, "x", "-aos", "-bd", "-y", "-sccUTF-8", f"-o{into}", str(archive)])
    return commands


def _run_unpacking(args: list[str], target: Unpacked, progress: Callable[[int, int], None]) -> None:
    target.into.mkdir(parents=True, exist_ok=True)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # Errors go to a file: a tool reporting every entry would fill a pipe and stall.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=errors, creationflags=flags
        )
        folder, total = target.item.path, target.size
        try:
            while process.poll() is None:
                time.sleep(0.5)
                progress(_bytes_under(folder), total)
        finally:
            # Cancellation must stop the writer before unpack() removes partial output.
            if process.poll() is None:
                process.kill()
                process.wait()
        if process.returncode != 0:
            errors.seek(0)
            text = errors.read().decode(errors="replace")
            raise ArchiveError(_shortened(text) or f"failed ({process.returncode})")


def _shortened(text: str, keep: int = 3) -> str:
    """A tool's error output cut to a few lines: it may repeat one error per file."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) <= keep:
        return "\n".join(lines)
    return "\n".join([*lines[:keep], f"… and {len(lines) - keep} more lines"])


def _bytes_under(folder: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(folder):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total
