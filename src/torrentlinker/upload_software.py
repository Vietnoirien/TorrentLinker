"""c411's software categories: GPS, Emulation, Applications and Games
(docs/research/upload-rules.md). Their names are exempt from the dot rule, and their
NFOs state a title, version, system, size, languages and install instructions.

Import the profiles from torrentlinker.upload, which registers them (this module needs
that one's types, so it cannot be imported first).
"""

from __future__ import annotations

import re
import zipfile
from pathlib import PurePosixPath
from typing import Any

from torrentlinker.domain import LocalItem
from torrentlinker.matching import IgnoreList
from torrentlinker.options import Chosen, OptionType
from torrentlinker.queries import name_query
from torrentlinker.upload import (
    ARCHIVES,
    CATEGORY_EMULATION,
    CATEGORY_GPS,
    IMAGE_PLACEHOLDER,
    ExistingQuery,
    Judgement,
    Problem,
    Refusal,
    Subcategory,
    SubcategoryEmulation,
    SubcategoryGps,
    UploadFile,
    UploadWarning,
    _ascii,
    _content,
    _ext,
    _first_segment,
    human_size,
)

INSTALLERS = ("exe", "msi", "bat", "cmd")
DOWNLOADER_RE = re.compile(
    r"down\s?loader|web[-_ .]?(?:setup|install\w*)|online[-_ .]?(?:setup|install\w*)"
    r"|stub[-_ .]?(?:setup|install\w*)|net[-_ .]?install|bootstrapper",
    re.IGNORECASE,
)
VERSION_RE = re.compile(r"(?<!\w)v?(\d+(?:\.\d+){1,3})(?![\w])", re.IGNORECASE)
YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")
# What a file extension says about the system an application runs on.
SYSTEMS = {
    "exe": "Windows",
    "msi": "Windows",
    "dmg": "macOS",
    "pkg": "macOS",
    "app": "macOS",
    "deb": "Linux",
    "rpm": "Linux",
    "appimage": "Linux",
    "apk": "Android",
    "xapk": "Android",
    "ipa": "iOS",
}
# Retro machines by ROM extension; mixing machines in one pack is not allowed, except MAME.
MACHINES = {
    "nes": "NES",
    "fds": "Famicom Disk",
    "sfc": "SNES",
    "smc": "SNES",
    "gb": "Game Boy",
    "gbc": "Game Boy Color",
    "gba": "Game Boy Advance",
    "nds": "Nintendo DS",
    "n64": "Nintendo 64",
    "z64": "Nintendo 64",
    "v64": "Nintendo 64",
    "md": "Mega Drive",
    "gen": "Mega Drive",
    "smd": "Mega Drive",
    "sms": "Master System",
    "gg": "Game Gear",
    "32x": "32X",
    "pce": "PC Engine",
    "a26": "Atari 2600",
    "a78": "Atari 7800",
    "lnx": "Lynx",
    "ngp": "Neo Geo Pocket",
    "ws": "WonderSwan",
    "wsc": "WonderSwan",
    "adf": "Amiga",
    "adz": "Amiga",
    "d64": "Commodore 64",
    "t64": "Commodore 64",
    "msa": "Atari ST",
    "tzx": "ZX Spectrum",
    "z80": "ZX Spectrum",
    "sg": "SG-1000",
    "vb": "Virtual Boy",
    "col": "ColecoVision",
}
ROM_REGIONS = {
    "europe": "EU",
    "france": "EU",
    "germany": "EU",
    "spain": "EU",
    "italy": "EU",
    "uk": "EU",
    "usa": "US",
    "japan": "JP",
    "hong kong": "HK",
}
LANGUAGE_CODES = ("fr", "en", "de", "es", "it", "ja", "nl", "pt", "sv", "zh")
ENCRYPTED_ZIP_FLAG = 0x1
PACK_FILES = 50  # archives are allowed in an emulation pack of more files than this


def _stem(item: LocalItem) -> str:
    return _first_segment(item)


def _version(text: str) -> str:
    return found.group(1) if (found := VERSION_RE.search(text)) else ""


def _item_name(files: list[UploadFile]) -> str:
    """The Local Item's own name, which the NFO's version and year are read from (the
    release title may have lost them)."""
    name = files[0].local_path.split("/")[0]
    return name.rsplit(".", 1)[0] if len(files) == 1 and "." in name else name


def _year(text: str) -> str:
    return found.group(1) if (found := YEAR_RE.search(text)) else ""


def _system(files: dict[str, int]) -> str:
    """The system the files say they run on: the most common of Windows, macOS, Linux…"""
    found = [SYSTEMS[e] for p in files if (e := _ext(p)) in SYSTEMS]
    return max(set(found), key=found.count) if found else ""


def _downloaders(files: dict[str, int]) -> list[str]:
    """Installers whose name says they download the program (c411 forbids them)."""
    return sorted(
        {
            PurePosixPath(p).name
            for p in files
            if _ext(p) in INSTALLERS and DOWNLOADER_RE.search(PurePosixPath(p).stem)
        }
    )


def _archives(files: dict[str, int]) -> list[str]:
    return sorted({e for p in files if (e := _ext(p)) in ARCHIVES})


def _info_nfo(title: str, rows: list[tuple[str, str]], files: list[UploadFile]) -> str:
    """The software NFO: each fact on its own line, the install instructions to write
    (in French), then every file with its size."""
    names = [f.torrent_path.split("/", 1)[-1] for f in files]
    width = max(len(n) for n in names)
    lines = [title, ""]
    lines += [f"{(label + ' ').ljust(16, '.')} : {value or '-'}" for label, value in rows]
    lines += [
        "",
        "Installation :",
        "  1. ",
        "",
        "Contenu :",
        *(
            f"  {n.ljust(width)}  {human_size(f.size):>10}"
            for n, f in zip(names, files, strict=True)
        ),
    ]
    return "\n".join(lines) + "\n"


def _info_description(
    title: str, rows: list[tuple[str, str]], files: list[UploadFile], image_url: str
) -> str:
    """An image, a presentation the user writes, the facts, the install instructions to
    write, and the files in a spoiler."""
    names = [f.torrent_path.split("/", 1)[-1] for f in files]
    lines = [
        f"[center][img]{image_url or IMAGE_PLACEHOLDER}[/img][/center]",
        "",
        f"[center][h2]{title}[/h2][/center]",
        "",
        "[h3]Présentation[/h3]",
        "",
        "",
        "[h3]Informations[/h3]",
        *(f"[b]{label} :[/b] {value}" for label, value in rows if value),
        "",
        "[h3]Installation[/h3]",
        "",
    ]
    if len(files) > 1:
        lines += ["[spoiler=Contenu][list]", *(f"[*]{n}" for n in names), "[/list][/spoiler]"]
    return "\n".join(lines) + "\n"


class GpsProfile:
    """c411's GPS category: navigation software, maps and extras."""

    category: int = CATEGORY_GPS
    renders_models = False
    media_extensions: tuple[str, ...] = ()
    dotted_names = False
    subcategories: tuple[Subcategory, ...] = (
        Subcategory(SubcategoryGps.APPLICATIONS, "Applications"),
        Subcategory(SubcategoryGps.MAPS, "Maps"),
        Subcategory(SubcategoryGps.MISC, "Miscellaneous"),
    )
    MAP_FORMATS = ("img", "gmap", "gmapi", "map", "tdb", "mp", "osm", "pbf", "mbtiles")

    def image_is_sheet(self, subcategory: int) -> bool:
        return False

    def inspect(self, item: LocalItem, ignore: IgnoreList) -> None:
        """Nothing to read: the rules go by file names."""

    def refusals(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int | None = None
    ) -> list[Refusal]:
        files = _content(item, ignore)
        if not files:
            return [Refusal(Problem.NO_FILE)]
        found = []
        if archives := _archives(files):
            found.append(Refusal(Problem.ARCHIVE, ", ".join(archives)))
        if downloaders := _downloaders(files):
            found.append(Refusal(Problem.DOWNLOADER, ", ".join(downloaders)))
        return found

    def warnings(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int
    ) -> list[UploadWarning]:
        return [
            UploadWarning(Judgement.VERSION_ACTIVATION),
            UploadWarning(Judgement.NO_ALPHA),
        ]

    def default_subcategory(self, item: LocalItem, ignore: IgnoreList) -> int:
        files = _content(item, ignore)
        if any(_ext(p) in self.MAP_FORMATS for p in files):
            return SubcategoryGps.MAPS
        return SubcategoryGps.APPLICATIONS

    def suggested_name(
        self, item: LocalItem, ignore: IgnoreList, source: str, subcategory: int
    ) -> str:
        """`Marque.Zone.Année.Support` from the name, with the system the files run on
        as support; editable. `source` is not used: GPS names carry no team tag."""
        stem = _stem(item)
        year = _year(stem)
        words = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", YEAR_RE.sub(" ", stem))
        base = ".".join(w for w in re.split(r"[^A-Za-z0-9]+", _ascii(words)) if w)
        support = _system(_content(item, ignore))
        return ".".join(p for p in (base, year, support) if p)

    def suggested_options(
        self, item: LocalItem, ignore: IgnoreList, types: list[OptionType]
    ) -> Chosen:
        return {}  # c411 lists no options for GPS

    def _rows(self, title: str, files: list[UploadFile]) -> list[tuple[str, str]]:
        sizes = {f.local_path: f.size for f in files}
        name = _item_name(files)
        return [
            ("Titre", title),
            ("Version", _version(name)),
            ("Système", _system(sizes)),
            ("Année", _year(title) or _year(name)),
            ("Taille", human_size(sum(sizes.values()))),
            ("Langues", ""),
            ("Activation", ""),
        ]

    def nfo(self, title: str, files: list[UploadFile]) -> str:
        return _info_nfo(title, self._rows(title, files), files)

    def description(self, title: str, files: list[UploadFile], source: str, image_url: str) -> str:
        return _info_description(title, self._rows(title, files), files, image_url)

    def existing_query(self, item: LocalItem, ignore: IgnoreList) -> ExistingQuery:
        return ExistingQuery(name_query(item))

    def draft_fields(
        self, item: LocalItem, ignore: IgnoreList, files: list[UploadFile]
    ) -> dict[str, Any]:
        return {}


class EmulationProfile:
    """c411's Emulation category: emulators, and ROMs or disc images of retro machines."""

    category: int = CATEGORY_EMULATION
    renders_models = False
    media_extensions: tuple[str, ...] = ()
    dotted_names = False
    subcategories: tuple[Subcategory, ...] = (
        Subcategory(SubcategoryEmulation.EMULATORS, "Emulators"),
        Subcategory(SubcategoryEmulation.ROMS, "ROMs / ISOs"),
    )

    def __init__(self) -> None:
        self.protected: dict[str, str] = {}  # item path -> the password-protected zips

    def image_is_sheet(self, subcategory: int) -> bool:
        return False

    def inspect(self, item: LocalItem, ignore: IgnoreList) -> None:
        """Find the password-protected zip archives (the only kind readable without
        7-Zip); a rar or 7z with a password is not detected."""
        found = []
        for path in _content(item, ignore):
            if _ext(path) != "zip":
                continue
            try:
                with zipfile.ZipFile(item.save_path / path) as archive:
                    if any(i.flag_bits & ENCRYPTED_ZIP_FLAG for i in archive.infolist()):
                        found.append(PurePosixPath(path).name)
            except (OSError, zipfile.BadZipFile):
                continue
        self.protected[str(item.path)] = ", ".join(sorted(found))

    def refusals(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int | None = None
    ) -> list[Refusal]:
        files = _content(item, ignore)
        if not files:
            return [Refusal(Problem.NO_FILE)]
        found = []
        if (archives := _archives(files)) and len(files) <= PACK_FILES:
            found.append(Refusal(Problem.ARCHIVE, ", ".join(archives)))
        if archives and (protected := self.protected.get(str(item.path))):
            found.append(Refusal(Problem.PASSWORD_ARCHIVE, protected))
        folders: dict[str, set[str]] = {}
        for p in files:
            folders.setdefault(str(PurePosixPath(p).parent), set()).add(_ext(p))
        if any("bin" in exts and "cue" not in exts for exts in folders.values()):
            found.append(Refusal(Problem.BIN_NO_CUE))
        for exts in folders.values():
            if exts & {"ccd", "sub"} and (missing := {"ccd", "img", "sub"} - exts):
                found.append(
                    Refusal(Problem.CLONECD_INCOMPLETE, ", ".join(f".{e}" for e in sorted(missing)))
                )
                break
        return found

    def warnings(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int
    ) -> list[UploadWarning]:
        files = _content(item, ignore)
        found = [UploadWarning(Judgement.RETRO_ONLY)]
        machines = sorted({MACHINES[e] for p in files if (e := _ext(p)) in MACHINES})
        if len(machines) > 1 and "mame" not in item.path.name.casefold():
            found.append(UploadWarning(Judgement.NO_MIXED_MACHINES, ", ".join(machines)))
        return found

    def default_subcategory(self, item: LocalItem, ignore: IgnoreList) -> int:
        files = _content(item, ignore)
        if any(_ext(p) in MACHINES for p in files):
            return SubcategoryEmulation.ROMS
        if any(_ext(p) in SYSTEMS for p in files):
            return SubcategoryEmulation.EMULATORS
        return SubcategoryEmulation.ROMS

    def suggested_name(
        self, item: LocalItem, ignore: IgnoreList, source: str, subcategory: int
    ) -> str:
        """`[Console]Nom [Région - Langue] Conteneur` for a game; an emulator is named
        `Nom Version [Système]`. Spaces and accents are allowed. Editable."""
        files = _content(item, ignore)
        stem = _stem(item)
        title = " ".join(re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", stem).split())
        if subcategory == SubcategoryEmulation.EMULATORS:
            system = _system(files)
            return f"{title} [{system}]" if system else title
        machines = [MACHINES[e] for p in files if (e := _ext(p)) in MACHINES]
        console = machines[0] if machines else "Console"
        tags = re.findall(r"\(([^)]*)\)", stem)
        region = next(
            (
                ROM_REGIONS[t.casefold()]
                for tag in tags
                for t in re.split(r"\s*,\s*", tag)
                if t.casefold() in ROM_REGIONS
            ),
            "",
        )
        codes = [
            c
            for tag in tags
            for t in re.split(r"\s*,\s*", tag)
            if (c := t.casefold()) in LANGUAGE_CODES
        ]
        language = "MULTI" if len(codes) > 1 else codes[0].upper() if codes else ""
        extra = " - ".join(x for x in (region, language) if x)
        container = next(
            (
                _ext(p).upper()
                for p in sorted(files)
                if _ext(p) in ARCHIVES + ("iso", "chd", "cue", "bin") or _ext(p) in MACHINES
            ),
            "",
        )
        parts = [f"[{console}]{title}"]
        if extra:
            parts.append(f"[{extra}]")
        if container:
            parts.append(container)
        return " ".join(parts)

    def suggested_options(
        self, item: LocalItem, ignore: IgnoreList, types: list[OptionType]
    ) -> Chosen:
        return {}  # c411 lists no options for Emulation

    def nfo(self, title: str, files: list[UploadFile]) -> str:
        """Title, platform, region, language, file count, size, then every file."""
        rows = self._rows(title, files)
        names = [f.torrent_path.split("/", 1)[-1] for f in files]
        width = max(len(n) for n in names)
        lines = [title, ""]
        lines += [f"{(label + ' ').ljust(16, '.')} : {value or '-'}" for label, value in rows]
        lines += [
            "",
            "Contenu :",
            *(
                f"  {n.ljust(width)}  {human_size(f.size):>10}"
                for n, f in zip(names, files, strict=True)
            ),
        ]
        return "\n".join(lines) + "\n"

    def description(self, title: str, files: list[UploadFile], source: str, image_url: str) -> str:
        return _info_description(title, self._rows(title, files), files, image_url)

    def _rows(self, title: str, files: list[UploadFile]) -> list[tuple[str, str]]:
        machines = sorted({MACHINES[e] for f in files if (e := _ext(f.local_path)) in MACHINES})
        tags = re.findall(r"\[([^\]]*)\]", title)
        region, _, language = (tags[1] if len(tags) > 1 else "").partition(" - ")
        return [
            ("Titre", re.sub(r"^\[[^\]]*\]", "", title).strip()),
            ("Plateforme", ", ".join(machines)),
            ("Région", region),
            ("Langue", language),
            ("Fichiers", str(len(files))),
            ("Taille totale", human_size(sum(f.size for f in files))),
        ]

    def existing_query(self, item: LocalItem, ignore: IgnoreList) -> ExistingQuery:
        return ExistingQuery(name_query(item))

    def draft_fields(
        self, item: LocalItem, ignore: IgnoreList, files: list[UploadFile]
    ) -> dict[str, Any]:
        return {}
