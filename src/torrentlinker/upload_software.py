"""c411's software categories: GPS, Emulation, Applications and Games
(docs/research/upload-rules.md). Their names are exempt from the dot rule, and their
NFOs state a title, version, system, size, languages and install instructions.

Import the profiles from torrentlinker.upload, which registers them (this module needs
that one's types, so it cannot be imported first).
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterable
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from torrentlinker.domain import LocalItem
from torrentlinker.matching import IgnoreList
from torrentlinker.options import Chosen, OptionType
from torrentlinker.queries import name_query
from torrentlinker.upload import (
    ARCHIVES,
    CATEGORY_APPS,
    CATEGORY_EMULATION,
    CATEGORY_GAMES,
    CATEGORY_GPS,
    IMAGE_PLACEHOLDER,
    ExistingQuery,
    Judgement,
    Problem,
    Refusal,
    Subcategory,
    SubcategoryApps,
    SubcategoryEmulation,
    SubcategoryGames,
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
    r"down\s?loader|(?:web|online|stub)[-_ .]?(?:setup|install\w*)"
    r"|(?:setup|install\w*)[-_ .]?(?:web|online|stub)|net[-_ .]?install|bootstrapper",
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


class ReleaseType(StrEnum):
    """How an application release is activated; the label is what its name carries."""

    KEYGEN = "Keygen"
    CRACK = "Crack"
    PATCH = "Patch"
    INSTALLER = "Installer"
    PORTABLE = "Portable"


# c411's decision table is on /wiki/cat-applications, which could not be read: this one
# is the app's own reading, marked unverified in docs/research/upload-rules.md.
KEYGEN_WORDS = ("keygen", "keymaker", "serialfish")
CRACK_WORDS = ("crack", "cracked", "activator", "loader", "kmspico")
PATCH_WORDS = ("patch", "patcher")
INSTALLER_EXTENSIONS = ("msi", "dmg", "pkg", "deb", "rpm", "apk", "xapk", "ipa", "appimage")
INSTALLER_WORDS = ("setup", "install", "installer", "inst")
APP_SYSTEMS = {
    SubcategoryApps.WINDOWS: ("exe", "msi"),
    SubcategoryApps.MACOS: ("dmg", "pkg", "app"),
    SubcategoryApps.LINUX: ("deb", "rpm", "appimage"),
    SubcategoryApps.SMARTPHONE: ("apk", "xapk", "ipa"),
}
OS_NAMES = ("Windows", "macOS", "Linux", "Android", "iOS")
MOBILE = (SubcategoryApps.SMARTPHONE, SubcategoryApps.TABLET)
LANGUAGE_TAGS = {
    "multi": "MULTI",
    "multilang": "MULTI",
    "multilingual": "MULTI",
    "french": "FR",
    "fr": "FR",
    "english": "EN",
    "en": "EN",
}


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", text.casefold()) if w]


def release_type(paths: Iterable[str], name: str = "") -> ReleaseType:
    """The release type, decided from the files present: `portable` when the name says
    so, then a keygen, a crack, a patch, an installer (a setup program or a package);
    program files without installer are portable."""
    paths = list(paths)
    words = [*_words(name), *(w for p in paths for w in _words(PurePosixPath(p).stem))]
    if "portable" in words:
        return ReleaseType.PORTABLE
    for kind, vocabulary in (
        (ReleaseType.KEYGEN, KEYGEN_WORDS),
        (ReleaseType.CRACK, CRACK_WORDS),
        (ReleaseType.PATCH, PATCH_WORDS),
    ):
        if any(w in vocabulary for w in words):
            return kind
    exes = [p for p in paths if _ext(p) == "exe"]
    installer = any(_ext(p) in INSTALLER_EXTENSIONS for p in paths) or any(
        w in INSTALLER_WORDS for p in exes for w in _words(PurePosixPath(p).stem)
    )
    if exes and not installer:
        return ReleaseType.PORTABLE
    return ReleaseType.INSTALLER


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


class ApplicationsProfile:
    """c411's Applications category: software for Windows, macOS, Linux and mobile."""

    category: int = CATEGORY_APPS
    renders_models = False
    media_extensions: tuple[str, ...] = ()
    dotted_names = False
    subcategories: tuple[Subcategory, ...] = (
        Subcategory(SubcategoryApps.OTHER, "Other"),
        Subcategory(SubcategoryApps.TRAINING, "Training"),
        Subcategory(SubcategoryApps.LINUX, "Linux"),
        Subcategory(SubcategoryApps.MACOS, "macOS"),
        Subcategory(SubcategoryApps.SMARTPHONE, "Smartphone"),
        Subcategory(SubcategoryApps.TABLET, "Tablet"),
        Subcategory(SubcategoryApps.WINDOWS, "Windows"),
    )

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
        kind = release_type(_content(item, ignore), _stem(item))
        found = [UploadWarning(Judgement.RELEASE_TYPE, kind.value)]
        if kind is not ReleaseType.PORTABLE:
            found.append(UploadWarning(Judgement.INSTALL_NOTE))
        found += [
            UploadWarning(Judgement.NO_ALPHA),
            UploadWarning(Judgement.NO_IPTV),
            UploadWarning(Judgement.OLDER_VERSION),
        ]
        return found

    def default_subcategory(self, item: LocalItem, ignore: IgnoreList) -> int:
        """From the files: `.exe`/`.msi` Windows, `.dmg`/`.pkg`/`.app` macOS, `.deb`/`.rpm`/
        `.AppImage` Linux, `.apk`/`.ipa` Smartphone, else Autre."""
        extensions = {_ext(p) for p in _content(item, ignore)}
        for sub, exts in APP_SYSTEMS.items():
            if extensions & set(exts):
                return sub
        return SubcategoryApps.OTHER

    def suggested_name(
        self, item: LocalItem, ignore: IgnoreList, source: str, subcategory: int
    ) -> str:
        """`Nom Version [OS Langue Type]`; mobile `[OS] Nom Version Langue [EXT]`.
        Spaces are allowed. `source` is not used. Editable."""
        files = _content(item, ignore)
        stem = _stem(item)
        version = _version(stem)
        name = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", stem)
        name = VERSION_RE.sub(" ", name).replace("_", " ")
        name = " ".join(w for w in name.split() if w.casefold() not in LANGUAGE_TAGS)
        language = next((LANGUAGE_TAGS[w] for w in _words(stem) if w in LANGUAGE_TAGS), "")
        system = _system(files) or _SUBCATEGORY_SYSTEMS.get(subcategory, "")
        if subcategory in MOBILE:
            ext = next((_ext(p).upper() for p in sorted(files) if _ext(p) in SYSTEMS), "")
            parts = [f"[{system}]" if system else "", name, version, language]
            return " ".join(p for p in parts if p) + (f" [{ext}]" if ext else "")
        kind = release_type(files, stem)
        tags = " ".join(t for t in (system, language, kind.value) if t)
        return " ".join(p for p in (name, version, f"[{tags}]") if p)

    def suggested_options(
        self, item: LocalItem, ignore: IgnoreList, types: list[OptionType]
    ) -> Chosen:
        return {}  # c411 lists no options for the subcategories read

    def _rows(self, title: str, files: list[UploadFile]) -> list[tuple[str, str]]:
        sizes = {f.local_path: f.size for f in files}
        name = _item_name(files)
        tags = " ".join(re.findall(r"\[([^\]]*)\]", title)).split()
        system = next((t for t in tags if t in OS_NAMES), "") or _system(sizes)
        kinds = {k.value: k for k in ReleaseType}
        kind = next((t for t in tags if t in kinds), "") or release_type(sizes, name).value
        language = next(
            (
                t
                for t in tags
                if t.casefold() in LANGUAGE_TAGS.values() or t.casefold() in LANGUAGE_TAGS
            ),
            "",
        )
        return [
            ("Titre", re.sub(r"\[[^\]]*\]", "", title).strip()),
            ("Version", _version(title) or _version(name)),
            ("Système", system),
            ("Année", _year(title) or _year(name)),
            ("Taille", human_size(sum(sizes.values()))),
            ("Langues", language),
            ("Activation", kind),
            ("Configuration", ""),
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


_SUBCATEGORY_SYSTEMS: dict[int, str] = {
    SubcategoryApps.WINDOWS: "Windows",
    SubcategoryApps.MACOS: "macOS",
    SubcategoryApps.LINUX: "Linux",
    SubcategoryApps.SMARTPHONE: "Android",
    SubcategoryApps.TABLET: "Android",
}


class GameType(StrEnum):
    """How a PC game release was made; the label is what the Upload tab shows."""

    SCENE = "Scene"
    REPACK = "Repack"
    PORTABLE = "Portable"
    GOG = "GOG"
    DRM_FREE = "DRM-free"
    PREACTIVATED = "Preactivated"


# c411's decision table is on /wiki/cat-jeux-video, which could not be read: this one is
# the app's own reading, marked unverified in docs/research/upload-rules.md.
REPACKERS = (
    "fitgirl",
    "dodi",
    "elamigos",
    "gnarly",
    "xatab",
    "kaos",
    "corepack",
    "darck",
    "qoob",
    "masquerade",
    "repack",
)
SCENE_GROUPS = (
    "codex",
    "skidrow",
    "plaza",
    "reloaded",
    "flt",
    "hoodlum",
    "darksiders",
    "tinyiso",
    "cpy",
    "rune",
    "doge",
    "tenoke",
    "razor1911",
    "empress",
    "simplex",
)
CRACK_WORDS_GAMES = ("crack", "cracked", *SCENE_GROUPS)
PREACTIVATED_WORDS = ("preactivated", "steamrip", "goldberg", "smartsteamemu")
# Container extensions each console takes, besides archives (one archive per game).
CONSOLE_CONTAINERS = {
    SubcategoryGames.NINTENDO: (
        "nsp",
        "xci",
        "nsz",
        "xcz",
        "nds",
        "3ds",
        "cia",
        "wbfs",
        "rvz",
        "iso",
        "gcm",
        "wux",
        "wua",
    ),
    SubcategoryGames.SONY: ("pkg", "iso", "cso", "bin", "cue", "chd"),
    SubcategoryGames.MICROSOFT: ("iso", "xex", "xbe"),
}
SUPPORT_EXTENSIONS = ("nfo", "txt", "jpg", "jpeg", "png", "xml", "md", "sfv", "diz", "url")
CONSOLE_DEFAULTS = {
    "nsp": SubcategoryGames.NINTENDO,
    "xci": SubcategoryGames.NINTENDO,
    "nsz": SubcategoryGames.NINTENDO,
    "xcz": SubcategoryGames.NINTENDO,
    "nds": SubcategoryGames.NINTENDO,
    "3ds": SubcategoryGames.NINTENDO,
    "cia": SubcategoryGames.NINTENDO,
    "wbfs": SubcategoryGames.NINTENDO,
    "rvz": SubcategoryGames.NINTENDO,
    "pkg": SubcategoryGames.SONY,
    "cso": SubcategoryGames.SONY,
    "xex": SubcategoryGames.MICROSOFT,
    "xbe": SubcategoryGames.MICROSOFT,
}
GAME_REGIONS = {
    "eur": "EU",
    "europe": "EU",
    "pal": "EU",
    "eu": "EU",
    "usa": "US",
    "ntscu": "US",
    "us": "US",
    "jpn": "JP",
    "japan": "JP",
    "ntscj": "JP",
    "jp": "JP",
    "hk": "HK",
}
GAME_LANGUAGES = {
    **LANGUAGE_TAGS,
    "multi5": "MULTI",
    "multi10": "MULTI",
    "multi3": "MULTI",
    "multi2": "MULTI",
    "vff": "FR",
}
PS_TITLE_RE = re.compile(r"\b(CUSA\d{5}|PPSA\d{5})\b")
GAME_SYSTEMS: dict[int, str] = {
    SubcategoryGames.WINDOWS: "Windows",
    SubcategoryGames.MACOS: "macOS",
    SubcategoryGames.LINUX: "Linux",
    SubcategoryGames.SMARTPHONE: "Android",
    SubcategoryGames.TABLET: "Android",
    SubcategoryGames.VR: "Windows",
}
CONSOLES = (SubcategoryGames.NINTENDO, SubcategoryGames.SONY, SubcategoryGames.MICROSOFT)
NFO_MAX_BYTES = 256 * 1024


def game_type(paths: Iterable[str], name: str = "", nfo: str = "") -> GameType:
    """The release type, decided from the files present: portable when the name says so,
    scene when it names a scene group, GOG (a GOG file or GOG in the NFO), a repack (a
    repacker's name, or a `setup.exe` with `.bin` data), scene again for an `.iso` or
    crack files, a preactivated release (a `steam_api` library) and otherwise DRM-free."""
    paths = list(paths)
    words = [*_words(name), *(w for p in paths for w in _words(PurePosixPath(p).name))]
    if "portable" in words:
        return GameType.PORTABLE
    if any(w in SCENE_GROUPS for w in _words(name)):
        return GameType.SCENE  # `Game-GOG-CODEX` is a scene release of a GOG game
    if "gog" in words or "goggame" in " ".join(words) or "gog" in _words(nfo):
        return GameType.GOG
    names = {PurePosixPath(p).name.casefold() for p in paths}
    if any(w in REPACKERS for w in words) or (
        "setup.exe" in names and any(_ext(p) == "bin" for p in paths)
    ):
        return GameType.REPACK
    folders = [w for p in paths for part in PurePosixPath(p).parts[:-1] for w in _words(part)]
    if (
        any(w in SCENE_GROUPS for w in words)
        or any(_ext(p) == "iso" for p in paths)
        or any(w in CRACK_WORDS_GAMES for w in [*folders, *words])
    ):
        return GameType.SCENE
    if any(n.startswith("steam_api") for n in names) or any(w in PREACTIVATED_WORDS for w in words):
        return GameType.PREACTIVATED
    return GameType.DRM_FREE


class GamesProfile:
    """c411's Jeux Vidéo category: PC games by release type, and console games."""

    category: int = CATEGORY_GAMES
    renders_models = False
    media_extensions: tuple[str, ...] = ()
    dotted_names = False
    subcategories: tuple[Subcategory, ...] = (
        Subcategory(SubcategoryGames.OTHER, "Other"),
        Subcategory(SubcategoryGames.LINUX, "Linux"),
        Subcategory(SubcategoryGames.MACOS, "macOS"),
        Subcategory(SubcategoryGames.MICROSOFT, "Microsoft"),
        Subcategory(SubcategoryGames.NINTENDO, "Nintendo"),
        Subcategory(SubcategoryGames.SMARTPHONE, "Smartphone"),
        Subcategory(SubcategoryGames.SONY, "Sony"),
        Subcategory(SubcategoryGames.TABLET, "Tablet"),
        Subcategory(SubcategoryGames.WINDOWS, "Windows"),
        Subcategory(SubcategoryGames.VR, "VR"),
    )

    def __init__(self) -> None:
        self.nfos: dict[str, str] = {}  # the release's own .nfo, by the Local Item's name

    def image_is_sheet(self, subcategory: int) -> bool:
        return False

    def inspect(self, item: LocalItem, ignore: IgnoreList) -> None:
        """Read the release's own .nfo (the largest under 256 Ko): a scene NFO is kept as
        it is, and GOG may be named in it."""
        found = [
            (size, path)
            for path, size in item.files.items()
            if _ext(path) == "nfo" and size <= NFO_MAX_BYTES
        ]
        for _, path in sorted(found, reverse=True):
            try:
                data = (item.save_path / path).read_bytes()
            except OSError:
                continue
            try:
                self.nfos[item.path.name] = data.decode("utf-8")
            except UnicodeDecodeError:
                self.nfos[item.path.name] = data.decode("cp437")  # scene art, DOS code page
            return

    def _type(self, item: LocalItem, ignore: IgnoreList) -> GameType:
        return game_type(_content(item, ignore), _stem(item), self.nfos.get(item.path.name, ""))

    # Rules -------------------------------------------------------------------

    def refusals(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int | None = None
    ) -> list[Refusal]:
        files = _content(item, ignore)
        if not files:
            return [Refusal(Problem.NO_FILE)]
        sub = subcategory if subcategory is not None else self.default_subcategory(item, ignore)
        found = []
        if sub in CONSOLES:
            accepted = (*CONSOLE_CONTAINERS[SubcategoryGames(sub)], *ARCHIVES, *SUPPORT_EXTENSIONS)
            wrong = sorted({e for p in files if (e := _ext(p)) and e not in accepted})
            if wrong:
                found.append(Refusal(Problem.CONSOLE_CONTAINER, ", ".join(wrong)))
        elif archives := _archives(files):
            found.append(Refusal(Problem.ARCHIVE, ", ".join(archives)))
        if downloaders := _downloaders(files):
            found.append(Refusal(Problem.DOWNLOADER, ", ".join(downloaders)))
        return found

    def warnings(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int
    ) -> list[UploadWarning]:
        if subcategory in CONSOLES:
            region = self._region(_stem(item))
            return [
                UploadWarning(Judgement.ONE_PER_CONSOLE),
                UploadWarning(Judgement.REGION, region),
            ]
        kind = self._type(item, ignore)
        found = [UploadWarning(Judgement.RELEASE_TYPE, kind.value)]
        if kind is GameType.GOG:
            found.append(UploadWarning(Judgement.ONE_GOG))
        elif kind in (GameType.SCENE, GameType.REPACK, GameType.PORTABLE):
            found.append(UploadWarning(Judgement.ONE_PER_RELEASE, kind.value))
        return found

    def default_subcategory(self, item: LocalItem, ignore: IgnoreList) -> int:
        """From the files: `.nsp`/`.xci` Nintendo, `.pkg` Sony, `.xex` Microsoft, `.apk`
        Smartphone, `.dmg` MacOS, `.AppImage` Linux, `.exe` Windows (VR when the name
        says so), else Autre."""
        files = _content(item, ignore)
        extensions = [_ext(p) for p in files]
        for ext in extensions:
            if ext in CONSOLE_DEFAULTS:
                return CONSOLE_DEFAULTS[ext]
        has = set(extensions)
        if has & {"apk", "xapk", "ipa"}:
            return SubcategoryGames.SMARTPHONE
        if has & {"dmg", "app"}:
            return SubcategoryGames.MACOS
        if has & {"appimage", "deb", "rpm"}:
            return SubcategoryGames.LINUX
        if has & {"exe", "msi"}:
            if "vr" in _words(_stem(item)):
                return SubcategoryGames.VR
            return SubcategoryGames.WINDOWS
        return SubcategoryGames.OTHER

    # Name ----------------------------------------------------------------------

    def _region(self, name: str) -> str:
        return next((GAME_REGIONS[w] for w in _words(name) if w in GAME_REGIONS), "")

    def suggested_name(
        self, item: LocalItem, ignore: IgnoreList, source: str, subcategory: int
    ) -> str:
        """Scene and repack names are kept as they are; portable `Nom - version [OS -
        Langue - PORTABLE]`, GOG `Nom (Version) [Langue - OS][GOG]`, VR prefixed `[VR]`,
        console `[Console]Nom [Région - Langue] Conteneur` (PS4/PS5 add `-CUSA…`/`-PPSA…`).
        Spaces and accents are allowed. Editable."""
        files = _content(item, ignore)
        stem = _stem(item)
        if subcategory in CONSOLES:
            return self._console_name(stem, files, subcategory)
        kind = self._type(item, ignore)
        version = _version(stem)
        title = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", VERSION_RE.sub(" ", stem))
        title = " ".join(
            w
            for w in title.replace("_", " ").replace(".", " ").split()
            if w.casefold() not in (*GAME_LANGUAGES, "gog", "portable")
        )
        system = GAME_SYSTEMS.get(subcategory) or _system(files)
        language = next((GAME_LANGUAGES[w] for w in _words(stem) if w in GAME_LANGUAGES), "")
        if kind is GameType.GOG:
            name = f"{title} ({version})" if version else title
            tags = " - ".join(t for t in (language, system) if t)
            name = f"{name} [{tags}][GOG]" if tags else f"{name} [GOG]"
        elif kind is GameType.PORTABLE:
            name = f"{title} - {version}" if version else title
            tags = " - ".join(t for t in (system, language, "PORTABLE") if t)
            name = f"{name} [{tags}]"
        else:
            name = stem  # scene and repack names are kept as they are
        if subcategory == SubcategoryGames.VR and not name.startswith("[VR]"):
            name = f"[VR]{name}"
        return name

    def _console_name(self, stem: str, files: dict[str, int], subcategory: int) -> str:
        accepted = CONSOLE_CONTAINERS[SubcategoryGames(subcategory)]
        main = next((p for p in sorted(files) if _ext(p) in (*accepted, *ARCHIVES)), "")
        container = _ext(main).upper() if main else ""
        words = _words(stem)
        title = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", PS_TITLE_RE.sub(" ", stem))
        title = " ".join(
            w
            for w in title.replace("_", " ").replace(".", " ").split()
            if w.casefold() not in (*GAME_REGIONS, *GAME_LANGUAGES, "multi", "ntsc", "ntsc-u")
        )
        region = self._region(stem)
        languages = [GAME_LANGUAGES[w] for w in words if w in GAME_LANGUAGES]
        language = (
            "MULTI" if len(set(languages)) > 1 or "multi" in words else (languages or [""])[0]
        )
        tags = " - ".join(t for t in (region, language) if t)
        console = self._console(subcategory, words, _ext(main), stem)
        name = f"[{console}]{title}" + (f" [{tags}]" if tags else "")
        name += f" {container}" if container else ""
        if match := PS_TITLE_RE.search(stem):
            name += f"-{match.group(1)}"
        return name

    def _console(self, subcategory: int, words: list[str], ext: str, stem: str) -> str:
        if subcategory == SubcategoryGames.SONY:
            if (match := PS_TITLE_RE.search(stem)) is not None:
                return "PS4" if match.group(1).startswith("CUSA") else "PS5"
            for tag in ("ps2", "ps3", "psp", "ps4", "ps5", "vita"):
                if tag in words:
                    return tag.upper() if tag != "vita" else "PS Vita"
            return "PlayStation"
        if subcategory == SubcategoryGames.MICROSOFT:
            return "Xbox 360" if ext == "xex" or "360" in words else "Xbox"
        if ext in ("nsp", "xci", "nsz", "xcz") or "switch" in words:
            return "Switch"
        if ext in ("3ds", "cia"):
            return "3DS"
        if ext == "nds":
            return "DS"
        for tag, label in (("wiiu", "Wii U"), ("wii", "Wii"), ("gamecube", "GameCube")):
            if tag in words:
                return label
        return "Wii" if ext in ("wbfs", "rvz") else "Nintendo"

    # Category Options ----------------------------------------------------------

    def suggested_options(
        self, item: LocalItem, ignore: IgnoreList, types: list[OptionType]
    ) -> Chosen:
        """The language named in the release name, where c411's values name it."""
        words = _words(_stem(item))
        wanted = (
            "Multi (Français inclus)"
            if "multi" in words or any(w.startswith("multi") for w in words)
            else "Français"
            if {"fr", "french", "vff", "truefrench"} & set(words)
            else "Anglais"
            if {"en", "english"} & set(words)
            else ""
        )
        chosen: Chosen = {}
        for t in types:
            if wanted and t.name.casefold().startswith("langue"):
                ids = [v.id for v in t.values if v.label.startswith(wanted)]
                if ids:
                    chosen[t.id] = ids[:1]
        return chosen

    # NFO and description -------------------------------------------------------

    def _rows(self, title: str, files: list[UploadFile]) -> list[tuple[str, str]]:
        sizes = {f.local_path: f.size for f in files}
        name = _item_name(files)
        words = _words(title)
        kind = game_type(sizes, name, self.nfos.get(files[0].local_path.split("/")[0], ""))
        console = bool(re.match(r"\[[^\]]*\]", title)) and not title.startswith("[VR]")
        return [
            ("Titre", re.sub(r"^\[[^\]]*\]", "", title).strip()),
            ("Version", _version(name) or _version(title)),
            ("Système", _system(sizes)),
            ("Année", _year(title) or _year(name)),
            ("Taille", human_size(sum(sizes.values()))),
            (
                "Langues",
                ", ".join(sorted({GAME_LANGUAGES[w] for w in words if w in GAME_LANGUAGES})),
            ),
            ("Région", self._region(title) if console else ""),
            ("Crack / loader", "" if console else kind.value),
            ("Configuration", ""),
        ]

    def nfo(self, title: str, files: list[UploadFile]) -> str:
        """A scene release's own .nfo as it is; else the facts, the install instructions
        to write (in French) and every file."""
        own = self.nfos.get(files[0].local_path.split("/")[0])
        sizes = {f.local_path: f.size for f in files}
        name = _item_name(files)
        if own and game_type(sizes, name, own) is GameType.SCENE:
            return own if own.endswith("\n") else own + "\n"
        return _info_nfo(title, self._rows(title, files), files)

    def description(self, title: str, files: list[UploadFile], source: str, image_url: str) -> str:
        return _info_description(title, self._rows(title, files), files, image_url)

    def existing_query(self, item: LocalItem, ignore: IgnoreList) -> ExistingQuery:
        return ExistingQuery(name_query(item))

    def draft_fields(
        self, item: LocalItem, ignore: IgnoreList, files: list[UploadFile]
    ) -> dict[str, Any]:
        return {}
