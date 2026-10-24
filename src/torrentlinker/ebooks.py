"""Local, read-only books and the seeding threshold for the hidden reading room."""

from __future__ import annotations

import json
import math
import os
import posixpath
import re
import subprocess
import tempfile
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from torrentlinker import archives
from torrentlinker.config import Settings
from torrentlinker.domain import ContentKind
from torrentlinker.downloads import IndexerCategory
from torrentlinker.seeding import Seeding

UNLOCK_COUNT = 10_000
BOOK_SUFFIXES = {".epub", ".pdf", ".cbz", ".cbr"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
MAX_MEMBER = 32 * 1024 * 1024
MAX_ENTRIES = 20_000


def ebook_category(category: int | None, categories: Mapping[int, IndexerCategory]) -> bool:
    seen: set[int] = set()
    while category is not None and category not in seen:
        if category == 7000:
            return True
        seen.add(category)
        entry = categories.get(category)
        if entry is None or entry.parent is None:
            # Standard Torznab ebook IDs, and c411's audiobook subcategory.
            return 7000 <= category < 8000 or category == 3030
        category = entry.parent
    return False


def seeded_ebooks(view: Seeding) -> int:
    return len(
        {
            row.torrent.hash.lower()
            for row in view.rows
            if row.torrent.is_seeding and ebook_category(row.category, view.categories)
        }
    )


def book_roots(settings: Settings, view: Seeding) -> tuple[Path, ...]:
    roots = {folder.path for folder in settings.library_folders if folder.kind == ContentKind.EBOOK}
    for row in view.rows:
        if ebook_category(row.category, view.categories):
            roots.add(row.torrent.save_path)
    for category in {7000, *settings.download_folders.by_category}:
        if ebook_category(category, settings.indexer_categories):
            folder = settings.download_folders.resolve(category, settings.indexer_categories)
            if folder is not None:
                roots.add(folder)
    return tuple(sorted(roots))


def book_categories(settings: Settings, view: Seeding) -> dict[Path, tuple[str, ...]]:
    """Associate local paths with known categories, never infer a category from a format."""
    categories = {**settings.indexer_categories, **view.categories}
    paths: dict[Path, tuple[str, ...]] = {}

    def labels(category: int) -> tuple[str, ...]:
        result = []
        seen: set[int] = set()
        current: int | None = category
        while current is not None and current not in seen:
            seen.add(current)
            entry = categories.get(current)
            if entry is None:
                break
            result.append(entry.name)
            current = entry.parent
        return tuple(reversed(result))

    def add(path: Path, category: int) -> None:
        value = labels(category)
        if path in paths:
            previous = paths[path]
            # Shared folders/files only imply their common parent category.
            length = 0
            for left, right in zip(previous, value, strict=False):
                if left != right:
                    break
                length += 1
            value = value[:length]
        paths[path] = value

    for category, folder in settings.download_folders.by_category.items():
        if folder.strip() and ebook_category(category, categories):
            add(Path(folder), category)
    for row in view.rows:
        if row.category is None or not ebook_category(row.category, categories):
            continue
        torrent = row.torrent
        if torrent.files:
            for name in torrent.files:
                add(torrent.save_path / name, row.category)
        else:
            # The torrent's root may be a single file or a directory containing a pack.
            add(torrent.save_path / torrent.name, row.category)
    return paths


@dataclass(frozen=True)
class Book:
    path: Path
    category: tuple[str, ...] = ()

    @property
    def title(self) -> str:
        return self.path.stem.replace("_", " ")


@dataclass(frozen=True)
class BookLibrary:
    books: list[Book]
    unavailable: int


def discover_books(
    roots: Iterable[Path],
    stop: Callable[[], bool] = lambda: False,
    categories: Mapping[Path, tuple[str, ...]] | None = None,
) -> BookLibrary:
    """Scan once per directory; do not follow directory symlinks or open book contents."""
    hints = {path.resolve(): names for path, names in (categories or {}).items()}
    found: dict[Path, Book] = {}
    visited: set[Path] = set()
    unavailable = 0

    def failed(_error: OSError) -> None:
        nonlocal unavailable
        unavailable += 1

    for root in sorted(set(roots), key=lambda p: len(p.parts)):
        if stop():
            break
        if not root.is_dir():
            unavailable += 1
            continue
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
            if stop():
                return BookLibrary([], unavailable)
            path = Path(directory).resolve()
            if path in visited:
                dirs[:] = []
                continue
            visited.add(path)
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                file = path / name
                if file.suffix.lower() in BOOK_SUFFIXES:
                    resolved = file.resolve()
                    category: tuple[str, ...] = ()
                    for parent in (resolved, *resolved.parents):
                        if parent in hints:
                            category = hints[parent]
                            break
                    found.setdefault(resolved, Book(resolved, category))
    return BookLibrary(
        sorted(found.values(), key=lambda book: str(book.path).casefold()), unavailable
    )


class BookError(Exception):
    """Unreadable, unsupported or malformed local book."""


def member_path(base: str, href: str) -> str:
    url = urlsplit(href)
    if url.scheme or url.netloc or url.path.startswith(("/", "\\")):
        raise BookError("External book resource")
    name = (
        posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(url.path)))
        if url.path
        else base
    )
    if name.startswith(("../", "/")) or name == ".." or "\\" in name:
        raise BookError("Invalid book resource path")
    return name


class ZipBook:
    def __init__(self, path: Path) -> None:
        self.path = path
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ENTRIES:
                raise BookError("Too many book resources")
            self.members = {
                entry.filename: entry.file_size for entry in entries if not entry.is_dir()
            }

    def read(self, name: str) -> bytes:
        if name not in self.members or self.members[name] > MAX_MEMBER:
            raise BookError("Missing or oversized book resource")
        with zipfile.ZipFile(self.path) as archive, archive.open(name) as source:
            result = source.read(MAX_MEMBER + 1)
        if len(result) > MAX_MEMBER:
            raise BookError("Oversized book resource")
        return result

    def xml(self, name: str) -> ET.Element:
        raw = self.read(name)
        if len(raw) > 2 * 1024 * 1024 or b"<!ENTITY" in raw.upper():
            raise BookError("Invalid book metadata")
        return ET.fromstring(raw)


@dataclass(frozen=True)
class Chapter:
    name: str
    title: str


class EpubBook(ZipBook):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        container = self.xml("META-INF/container.xml")
        rootfile = container.find(".//{*}rootfile")
        if rootfile is None:
            raise BookError("Missing EPUB package")
        package = member_path("", rootfile.get("full-path", ""))
        metadata = self.xml(package)
        title = metadata.find(".//{*}title")
        self.title = title.text if title is not None and title.text else path.stem
        manifest = {}
        for item in metadata.findall(".//{*}manifest/{*}item"):
            if item.get("media-type") in ("application/xhtml+xml", "text/html"):
                try:
                    manifest[item.get("id")] = member_path(package, item.get("href", ""))
                except BookError:
                    continue  # optional remote resources cannot be read offline
        labels: dict[str, str] = {}
        # EPUB 2's NCX and EPUB 3's navigation document provide human-readable titles.
        for item in metadata.findall(".//{*}manifest/{*}item"):
            if item.get("media-type") == "application/x-dtbncx+xml":
                toc = member_path(package, item.get("href", ""))
                for point in self.xml(toc).findall(".//{*}navPoint"):
                    content, label = point.find("{*}content"), point.find("{*}navLabel/{*}text")
                    if content is not None and label is not None and label.text:
                        try:
                            labels.setdefault(member_path(toc, content.get("src", "")), label.text)
                        except BookError:
                            continue
            elif "nav" in item.get("properties", "").split():
                toc = member_path(package, item.get("href", ""))
                for anchor in self.xml(toc).findall(".//{*}a"):
                    try:
                        labels.setdefault(
                            member_path(toc, anchor.get("href", "")), "".join(anchor.itertext())
                        )
                    except BookError:
                        continue
        self.chapters = [
            Chapter(manifest[ref.get("idref")], labels.get(manifest[ref.get("idref")], f"{i + 1}"))
            for i, ref in enumerate(metadata.findall(".//{*}spine/{*}itemref"))
            if ref.get("idref") in manifest and ref.get("linear") != "no"
        ]
        if not self.chapters:
            raise BookError("No readable EPUB chapters")


def natural_key(name: str) -> list[tuple[int, str | int]]:
    return [
        (0, int(piece)) if piece.isdigit() else (1, piece.casefold())
        for piece in re.split(r"(\d+)", name)
    ]


class ComicBook:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.zip = ZipBook(path) if zipfile.is_zipfile(path) else None
        self.tool: str | None = None
        if self.zip is not None:
            self.members = self.zip.members
        elif path.suffix.lower() == ".cbr":
            # Reuse the archive tools already supported for Library/Reseed operations.
            self.tool = archives._tool("unrar") or archives._tool("7z")
            if self.tool is None:
                raise BookError("Install 7-Zip or unrar to read CBR books")
            unrar = "unrar" in Path(self.tool).name.lower()
            args = (
                [self.tool, "lt", "-cfg-", "-p-", "--", str(path)]
                if unrar
                else [self.tool, "l", "-slt", "-ba", "-sccUTF-8", "-p", "--", str(path)]
            )
            listing = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=20,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if listing.returncode != 0:
                raise BookError("Could not read comic archive")
            self.members = (
                {
                    b["Name"].replace("\\", "/"): int(b.get("Size") or 0)
                    for b in archives._blocks(listing.stdout, ": ")
                    if b.get("Name") and b.get("Type") == "File"
                }
                if unrar
                else {
                    b["Path"].replace("\\", "/"): int(b.get("Size") or 0)
                    for b in archives._blocks(listing.stdout, " = ")
                    if b.get("Path")
                    and b.get("Folder") != "+"
                    and not b.get("Attributes", "").startswith("D")
                }
            )
        else:
            raise BookError("Invalid comic archive")
        if len(self.members) > MAX_ENTRIES:
            raise BookError("Too many comic pages")
        self.pages = sorted(
            (name for name in self.members if Path(name).suffix.lower() in IMAGE_SUFFIXES),
            key=natural_key,
        )
        if not self.pages:
            raise BookError("No images in comic archive")

    def read(self, name: str) -> bytes:
        if name not in self.members or self.members[name] > MAX_MEMBER:
            raise BookError("Missing or oversized comic page")
        if self.zip is not None:
            return self.zip.read(name)
        archives._check_safe(name)
        assert self.tool is not None
        args = (
            [self.tool, "p", "-inul", "-p-", "--", str(self.path), name]
            if "unrar" in Path(self.tool).name.lower()
            else [self.tool, "x", "-so", "-spd", "-p", "--", str(self.path), name]
        )
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(
                args,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0 or output.tell() > MAX_MEMBER:
                raise BookError("Could not read comic page")
            output.seek(0)
            return output.read(MAX_MEMBER)


class ReadingProgress:
    """Reading locations live in app data, never inside a seeded book."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.positions: dict[str, list[float]] = {}
        try:
            raw = json.loads(path.read_text())
            if isinstance(raw, dict):
                self.positions = {
                    key: value
                    for key, value in raw.items()
                    if isinstance(key, str)
                    and isinstance(value, list)
                    and len(value) == 2
                    and all(
                        isinstance(number, (int, float)) and math.isfinite(number) and number >= 0
                        for number in value
                    )
                }
        except (OSError, ValueError):
            pass

    def get(self, path: Path) -> tuple[int, float]:
        page, fraction = self.positions.get(str(path), [0, 0])
        return int(page), min(fraction, 1.0)

    def save(self, path: Path, page: int, fraction: float) -> None:
        self.positions[str(path)] = [page, fraction]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.positions), encoding="utf-8")
        temporary.replace(self.path)
