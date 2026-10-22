"""Upload: turn an Orphan into a new torrent, its NFO and a c411 Draft (ADR-0011).

The torrent's paths follow c411's naming rules while the data stays where it is: the
torrent is then added to the Torrent Client with its paths renamed onto the local
files, as a Reseed does, so no file of the user's is ever renamed or written.
Rules are summed up in docs/research/upload-rules.md; 3D models come first.
"""

from __future__ import annotations

import base64
import hashlib
import re
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, Protocol

from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.matching import IgnoreList, Match
from torrentlinker.qbit import Qbit
from torrentlinker.reseed import start_reseed
from torrentlinker.store import SavedUpload, Store
from torrentlinker.torrent_meta import TorrentMeta, read_torrent

MiB = 1 << 20
GB = 1_000_000_000
NOTAG = "NOTAG"
CATEGORY_3D = 10

# c411's categories (GET /api/categories); Nulled and Adult get no profile.
CATEGORIES = {
    1: "Films & Vidéos",
    2: "Ebook",
    3: "Audio",
    4: "Applications",
    5: "Jeux Vidéo",
    6: "Emulation",
    7: "GPS",
    9: "Nulled",
    10: "Imprimante 3D",
}
# The category a Content Kind proposes; `other` proposes none, the user picks.
DEFAULT_CATEGORIES = {
    ContentKind.MOVIE: 1,
    ContentKind.SERIES: 1,
    ContentKind.EBOOK: 2,
    ContentKind.MUSIC: 3,
    ContentKind.GAME: 5,
    ContentKind.MODEL_3D: CATEGORY_3D,
}

# c411's 3D formats, in the order a release name lists them.
FORMATS_3D = ("stl", "3mf", "obj", "step", "stp", "gcode", "blend", "f3d", "f3z", "sldprt", "fcstd")
ARCHIVES = ("rar", "zip", "7z")
READ_CHUNK = 4 * MiB


class Subcategory3D(IntEnum):
    OBJECTS = 51
    CHARACTERS = 52
    PACK = 53


class UploadStopped(Exception):
    """The user stopped the Upload while its torrent was being made."""


@dataclass(frozen=True)
class UploadFile:
    torrent_path: str  # as the torrent names it, the release name first
    local_path: str  # as the Local Item lists it, relative to its save path
    size: int


class Problem(StrEnum):
    """Why c411 would refuse a Local Item; the GUI words each one."""

    NO_FILE = "no-file"
    ARCHIVE = "archive"  # detail: the archive formats found
    NO_3D_FILE = "no-3d-file"


@dataclass(frozen=True)
class Refusal:
    problem: Problem
    detail: str = ""


@dataclass(frozen=True)
class Subcategory:
    id: int
    label: str  # English, translated by the GUI


class UploadProfile(Protocol):
    """What one c411 category needs to become an Upload: its rules, the release name, the
    NFO and a description template. One per category, 3D models first."""

    category: int
    subcategories: tuple[Subcategory, ...]

    def refusals(self, item: LocalItem, ignore: IgnoreList) -> list[Refusal]: ...
    def default_subcategory(self, item: LocalItem, ignore: IgnoreList) -> int: ...
    def suggested_name(
        self, item: LocalItem, ignore: IgnoreList, source: str, subcategory: int
    ) -> str: ...
    def nfo(self, title: str, files: list[UploadFile]) -> str: ...
    def description(
        self, title: str, files: list[UploadFile], source: str, image_url: str
    ) -> str: ...


class Model3DProfile:
    """c411's Imprimante 3D category (docs/research/upload-rules.md)."""

    category: int = CATEGORY_3D
    subcategories: tuple[Subcategory, ...] = (
        Subcategory(Subcategory3D.OBJECTS, "Objects"),
        Subcategory(Subcategory3D.CHARACTERS, "Characters"),
        Subcategory(Subcategory3D.PACK, "Pack"),
    )

    def refusals(self, item: LocalItem, ignore: IgnoreList) -> list[Refusal]:
        files = _content(item, ignore)
        if not files:
            return [Refusal(Problem.NO_FILE)]
        found = []
        archives = sorted({e for p in files if (e := _ext(p)) in ARCHIVES})
        if archives:
            found.append(Refusal(Problem.ARCHIVE, ", ".join(archives)))
        if not any(_ext(p) in FORMATS_3D for p in files):
            found.append(Refusal(Problem.NO_3D_FILE))
        return found

    def default_subcategory(self, item: LocalItem, ignore: IgnoreList) -> int:
        models = [p for p in _content(item, ignore) if _ext(p) in FORMATS_3D]
        return Subcategory3D.PACK if len(models) > 1 else Subcategory3D.OBJECTS

    def suggested_name(
        self, item: LocalItem, ignore: IgnoreList, source: str, subcategory: int
    ) -> str:
        """`Nom.Source.FORMATS`, or `Nom.Source.[PACK].FORMATS`; NOTAG for an unknown
        source."""
        stem = item.path.stem if item.path.is_file() else item.path.name
        parts = [_words(stem), _words(source) or NOTAG]
        if subcategory == Subcategory3D.PACK:
            parts.append("[PACK]")
        if found := _formats_3d(_content(item, ignore)):
            parts.append("-".join(found))
        return ".".join(p for p in parts if p)

    def nfo(self, title: str, files: list[UploadFile]) -> str:
        return nfo_3d(title, files)

    def description(self, title: str, files: list[UploadFile], source: str, image_url: str) -> str:
        return description_3d(title, files, source, image_url)


PROFILES: dict[int, UploadProfile] = {CATEGORY_3D: Model3DProfile()}


def category_name(category: int) -> str:
    """c411's name for a category, as the site spells it."""
    return CATEGORIES.get(category, str(category))


def default_category(kind: ContentKind) -> int | None:
    """The category a Content Kind proposes; None when the user must pick."""
    return DEFAULT_CATEGORIES.get(kind)


def profile_for(kind: ContentKind) -> UploadProfile | None:
    """How a Content Kind becomes an Upload by default; None when its category has no
    profile yet or the kind proposes none."""
    category = default_category(kind)
    return PROFILES.get(category) if category is not None else None


def _formats_3d(paths: Iterable[str]) -> list[str]:
    present = {_ext(p) for p in paths}
    return [f.upper() for f in FORMATS_3D if f in present]


def upload_files(item: LocalItem, title: str, ignore: IgnoreList) -> list[UploadFile]:
    """Each content file under its compliant torrent path, in torrent order.

    A single file is named the release title plus its extension, as c411 names media
    files; a folder becomes the release title, and the names below it lose accents and
    spaces. Ignored Files are left out.
    """
    content = _content(item, ignore)
    if item.path.is_file():
        ((local, size),) = content.items()
        return [UploadFile(f"{title}.{_ext(local)}", local, size)]
    result: dict[str, UploadFile] = {}
    for local, size in content.items():
        below = local.split("/")[1:]
        path = "/".join([title, *(_clean_segment(s) for s in below)])
        if path.casefold() in {p.casefold() for p in result}:
            raise ValueError(f"Two files would share the name {path}")
        result[path] = UploadFile(path, local, size)
    return [result[p] for p in sorted(result)]


def piece_size(total: int) -> int:
    """c411's table: <1 Go 1 Mo, <2 Go 2 Mo, <3 Go 4 Mo, <8 Go 8 Mo, else 16 Mo."""
    for limit, mib in ((1 * GB, 1), (2 * GB, 2), (3 * GB, 4), (8 * GB, 8)):
        if total < limit:
            return mib * MiB
    return 16 * MiB


def make_torrent(
    item: LocalItem,
    files: list[UploadFile],
    announce: str,
    report: Callable[[int, int], None] = lambda done, total: None,
    stopped: Callable[[], bool] = lambda: False,
    now: Callable[[], float] = time.time,
) -> bytes:
    """A private v1 torrent of `files`, hashed from the Local Item's own files."""
    total = sum(f.size for f in files)
    length = piece_size(total)
    pieces = bytearray()
    piece = hashlib.sha1()
    filled = done = 0
    for f in files:
        with open(item.save_path / f.local_path, "rb") as stream:
            while chunk := stream.read(READ_CHUNK):
                if stopped():
                    raise UploadStopped()
                done += len(chunk)
                while chunk:
                    take = chunk[: length - filled]
                    piece.update(take)
                    filled += len(take)
                    chunk = chunk[len(take) :]
                    if filled == length:
                        pieces += piece.digest()
                        piece, filled = hashlib.sha1(), 0
                report(done, total)
    if filled:
        pieces += piece.digest()
    name = files[0].torrent_path.split("/")[0]
    info: dict[str, Any] = {"name": name, "piece length": length, "pieces": bytes(pieces)}
    if item.path.is_file():
        info["length"] = files[0].size
    else:
        info["files"] = [{"length": f.size, "path": f.torrent_path.split("/")[1:]} for f in files]
    info["private"] = 1
    return bencode(
        {
            "announce": announce,
            "created by": "TorrentLinker",
            "creation date": int(now()),
            "info": info,
        }
    )


def seed_match(files: list[UploadFile]) -> Match:
    """The Upload's torrent against its Local Item: Full by construction."""
    return Match({f.torrent_path: f.local_path for f in files})


def nfo_3d(title: str, files: list[UploadFile]) -> str:
    """c411's 3D NFO: name, file count, total size, formats, then every file."""
    names = [f.torrent_path.split("/", 1)[-1] for f in files]
    found = _formats_3d(names)
    width = max(len(n) for n in names)
    lines = [
        title,
        "",
        f"Nom ............ : {title}",
        f"Fichiers ....... : {len(files)}",
        f"Taille totale .. : {human_size(sum(f.size for f in files))}",
        f"Format ......... : {', '.join(found) or '-'}",
        "",
        "Contenu :",
        *(
            f"  {n.ljust(width)}  {human_size(f.size):>10}"
            for n, f in zip(names, files, strict=True)
        ),
    ]
    return "\n".join(lines) + "\n"


def description_3d(title: str, files: list[UploadFile], source: str, image_url: str) -> str:
    """c411's description: an image, a presentation the user writes, then the facts of
    the NFO; a pack lists its files in a spoiler."""
    names = [f.torrent_path.split("/", 1)[-1] for f in files]
    lines = []
    if image_url:
        lines += [f"[center][img]{image_url}[/img][/center]", ""]
    lines += [
        f"[center][h2]{title}[/h2][/center]",
        "",
        "[h3]Présentation[/h3]",
        "",
        "",
        "[h3]Informations[/h3]",
        f"[b]Source :[/b] {source or 'Inconnue'}",
        f"[b]Formats :[/b] {', '.join(_formats_3d(names))}",
        f"[b]Fichiers :[/b] {len(files)}",
        f"[b]Taille totale :[/b] {human_size(sum(f.size for f in files))}",
    ]
    if len(files) > 1:
        lines += ["", "[spoiler=Contenu][list]", *(f"[*]{n}" for n in names), "[/list][/spoiler]"]
    return "\n".join(lines) + "\n"


def draft_body(
    title: str,
    description: str,
    category: int,
    subcategory: int,
    torrent: bytes,
    nfo: str,
) -> dict[str, Any]:
    """The JSON c411's upload page sends to save a Draft."""
    return {
        "name": title,
        "title": title,
        "description": description,
        "categoryId": category,
        "subcategoryId": subcategory,
        "options": {},
        "tmdbData": None,
        "musicData": None,
        "rawgData": None,
        "bookData": None,
        "mediainfo": None,
        "identifiers": [],
        "templateId": None,
        "uploaderNote": None,
        "ebookMetadata": None,
        "torrentFileName": f"{title}.torrent",
        "torrentFileData": base64.b64encode(torrent).decode(),
        "nfoFileName": f"{title}.nfo",
        "nfoFileData": base64.b64encode(nfo.encode()).decode(),
    }


def save_upload_files(folder: Path, title: str, torrent: bytes, nfo: str) -> tuple[Path, Path]:
    """Keep the Upload's .torrent and .nfo in the app's own folder, never in the Library."""
    folder.mkdir(parents=True, exist_ok=True)
    torrent_path, nfo_path = folder / f"{title}.torrent", folder / f"{title}.nfo"
    torrent_path.write_bytes(torrent)
    nfo_path.write_text(nfo, encoding="utf-8")
    return torrent_path, nfo_path


@dataclass(frozen=True)
class PreparedUpload:
    """An Upload whose Draft is saved, ready to seed."""

    saved: SavedUpload
    meta: TorrentMeta
    files: list[UploadFile]


@dataclass(frozen=True)
class UploadRequest:
    """An Upload as the user set it up: the files, the name, the texts and the category."""

    item: LocalItem
    title: str
    files: list[UploadFile]
    nfo: str
    description: str
    category: int
    subcategory: int


def create_upload(
    request: UploadRequest,
    announce: str,
    folder: Path,
    save_draft: Callable[[dict[str, Any]], int],
    store: Store,
    report: Callable[[int, int], None] = lambda done, total: None,
    stopped: Callable[[], bool] = lambda: False,
    now: Callable[[], float] = time.time,
) -> PreparedUpload:
    """Make the torrent, keep it and the NFO in `folder`, then save the c411 Draft."""
    if not announce:
        raise ValueError("No Announce URL: enter yours in Settings → Connections")
    item, title, files, nfo = request.item, request.title, request.files, request.nfo
    torrent = make_torrent(item, files, announce, report, stopped, now)
    save_upload_files(folder, title, torrent, nfo)
    meta = read_torrent(torrent)
    body = draft_body(
        title, request.description, request.category, request.subcategory, torrent, nfo
    )
    saved = SavedUpload(item.path, title, meta.infohash, save_draft(body), now())
    store.save_upload(saved)
    return PreparedUpload(saved, meta, files)


def seed_upload(qbit: Qbit, store: Store, item: LocalItem, prepared: PreparedUpload) -> str:
    """Add the Upload's torrent to the Torrent Client against the local files and verify
    it, as a Reseed: c411 refuses an upload whose uploader is not seeding."""
    key = f"upload:{prepared.meta.infohash}"
    return start_reseed(qbit, store, item, prepared.meta, seed_match(prepared.files), key)


def bencode(value: Any) -> bytes:
    if isinstance(value, bool):
        raise TypeError("bencode has no booleans")
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, list):
        return b"l" + b"".join(bencode(v) for v in value) + b"e"
    if isinstance(value, dict):
        keys = sorted((k.encode() if isinstance(k, str) else k, v) for k, v in value.items())
        return b"d" + b"".join(bencode(k) + bencode(v) for k, v in keys) + b"e"
    raise TypeError(f"cannot bencode {type(value).__name__}")


def human_size(n: float) -> str:
    """Sizes as c411's French NFOs write them."""
    if n < 1024:
        return f"{int(n)} o"
    for unit in ("Ko", "Mo", "Go"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n / 1024:.1f} To"


def _content(item: LocalItem, ignore: IgnoreList) -> dict[str, int]:
    return {p: s for p, s in item.files.items() if not ignore.matches(p)}


def _ext(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].casefold() if "." in name else ""


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _words(text: str) -> str:
    """Words joined by dots, without accents: `Petit étau de bureau` → `Petit.Etau.De.Bureau`."""
    words = re.split(r"[^A-Za-z0-9]+", _ascii(text))
    return ".".join(w[:1].upper() + w[1:] for w in words if w)


def _clean_segment(name: str) -> str:
    """A file or folder name without accents or spaces; its extension kept."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", ".", _ascii(name)).strip(".")
    return re.sub(r"\.{2,}", ".", cleaned) or "_"
