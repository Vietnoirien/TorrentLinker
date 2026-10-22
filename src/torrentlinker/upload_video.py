"""c411's Films & Vidéos category, its strictest: names are parsed by the *arr tools
(docs/research/upload-rules.md, ADR-0012). Facts come from MediaInfo, which is read by
`inspect` off the GUI thread; TMDb names the film or series in French.

Import `VideoProfile` from torrentlinker.upload, which registers it (this module needs
that one's types, so it cannot be imported first).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from guessit import guessit

from torrentlinker import media_info
from torrentlinker.credentials import TMDB_API_KEY, get_secret
from torrentlinker.domain import ContentKind, LocalItem
from torrentlinker.matching import IgnoreList
from torrentlinker.media_info import MediaFacts, read_media
from torrentlinker.options import Chosen, OptionType
from torrentlinker.queries import find_ids, name_query
from torrentlinker.tmdb import Tmdb, TmdbInfo
from torrentlinker.upload import (
    ARCHIVES,
    CATEGORY_VIDEO,
    IMAGE_PLACEHOLDER,
    NOTAG,
    ExistingQuery,
    Judgement,
    Problem,
    Refusal,
    Subcategory,
    SubcategoryVideo,
    UploadFile,
    UploadWarning,
    _ascii,
    _content,
    _ext,
    _first_segment,
    _words,
    human_size,
)

# c411's containers; a disc is an ISO, or a BDMV / VIDEO_TS folder.
CONTAINERS = ("mkv", "mp4", "m4v", "avi", "ts", "m2ts")
REFUSED_CONTAINERS = (
    "wmv",
    "mov",
    "swf",
    "flv",
    "rm",
    "rmvb",
    "webm",
    "mpg",
    "mpeg",
    "ogv",
    "3gp",
    "asf",
)
DISC_FOLDERS = ("bdmv", "video_ts")
BANNED_TEAMS = (
    "wawacity",
    "wawa",
    "kore",
    "k0re",
    "p2p",
    "rarbg",
    "fyr3n",
    "arkas",
    "r3z",
    "byplex",
    "webvision",
    "agroaqc",
)
# Minimum video bitrates in kb/s, by resolution and codec; encodes only.
MIN_KBPS = {
    ("1080p", "x264"): 2500,
    ("1080p", "x265"): 1200,
    ("1080p", "AV1"): 800,
    ("2160p", "x265"): 2800,
    ("2160p", "AV1"): 2200,
    ("SD", "XVID"): 1500,
}
FRENCH_VARIANTS = ("VFF", "VFQ", "VFI", "VFB", "VOF", "TRUEFRENCH")
PACK_MAX_NFO = 10  # a pack of more may list its first episode only
EPISODE_SUBCATEGORIES = (
    SubcategoryVideo.SERIES,
    SubcategoryVideo.ANIMATION_SERIES,
    SubcategoryVideo.DOCUMENTARY_SERIES,
)
PURE = {"AVC": "AVC", "HEVC": "HEVC", "VC1": "VC1", "MPEG2": "MPEG2"}
WEB_CODECS = {"AVC": "H264", "HEVC": "H265"}


@lru_cache(maxsize=1024)
def _guess(name: str) -> dict[str, Any]:
    return dict(guessit(re.sub(r"\{[^}]*\}", " ", name)))


def _team(stem: str) -> str:
    """The team tag a release name ends with: `-TFA`, special characters dropped."""
    found = re.search(r"-([A-Za-z0-9]+(?:-[A-Za-z0-9]+)?)$", stem)
    return re.sub(r"[^A-Za-z0-9]+", "", found.group(1)) if found else ""


def _stem(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def _is_disc(files: dict[str, int]) -> bool:
    return any(
        _ext(p) == "iso" or any(part.casefold() in DISC_FOLDERS for part in p.split("/"))
        for p in files
    )


def _media(files: dict[str, int]) -> dict[str, int]:
    """The video files MediaInfo is read from (a disc's streams are not)."""
    if _is_disc(files):
        return {}
    return {p: s for p, s in files.items() if _ext(p) in CONTAINERS}


def _default_tmdb() -> Tmdb | None:
    key = get_secret(TMDB_API_KEY)
    return Tmdb(key) if key else None


class VideoProfile:
    """The Films & Vidéos category: Film or Série TV by default from the name."""

    category: int = CATEGORY_VIDEO
    renders_models = False
    media_extensions: tuple[str, ...] = CONTAINERS
    subcategories: tuple[Subcategory, ...] = (
        Subcategory(SubcategoryVideo.ANIMATION, "Animation"),
        Subcategory(SubcategoryVideo.ANIMATION_SERIES, "Animated series"),
        Subcategory(SubcategoryVideo.CONCERT, "Concert"),
        Subcategory(SubcategoryVideo.DOCUMENTARY, "Documentary"),
        Subcategory(SubcategoryVideo.DOCUMENTARY_SERIES, "Documentary series"),
        Subcategory(SubcategoryVideo.TV_SHOW, "TV programme"),
        Subcategory(SubcategoryVideo.MOVIE, "Movie"),
        Subcategory(SubcategoryVideo.SERIES, "TV series"),
        Subcategory(SubcategoryVideo.SHOW, "Stage show"),
        Subcategory(SubcategoryVideo.SPORT, "Sport"),
        Subcategory(SubcategoryVideo.CLIPS, "Music videos"),
        Subcategory(SubcategoryVideo.COLLECTION, "Collection"),
    )

    def __init__(
        self,
        reader: Callable[[Any], MediaFacts | None] = read_media,
        available: Callable[[], bool] = media_info.available,
        tmdb: Callable[[], Tmdb | None] = _default_tmdb,
    ) -> None:
        self.reader = reader
        self.available = available
        self.tmdb = tmdb
        self.facts: dict[tuple[str, int], MediaFacts] = {}
        self.identified: dict[str, TmdbInfo] = {}  # by the Local Item's name

    def image_is_sheet(self, subcategory: int) -> bool:
        return False

    # Inspection ----------------------------------------------------------------

    def inspect(self, item: LocalItem, ignore: IgnoreList) -> None:
        """MediaInfo of every video file, then the item's TMDb identity."""
        if self.available():
            for path, size in _media(_content(item, ignore)).items():
                if (path, size) not in self.facts and (found := self.reader(item.save_path / path)):
                    self.facts[(path, size)] = found
        self._identify(item)

    def _identify(self, item: LocalItem) -> None:
        """The TMDb id from the item's name or .nfo, else a search; failures are silent
        (no key, offline): the name then uses the title as it is."""
        try:
            client = self.tmdb()
            if client is None or item.path.name in self.identified:
                return
            guess = _guess(_first_segment(item))
            kind = "tv" if guess.get("type") == "episode" else "movie"
            found = find_ids(item).tmdb
            if found is None:
                title, year = str(guess.get("title", "")), guess.get("year")
                found = client.lookup(
                    title, year, ContentKind.SERIES if kind == "tv" else ContentKind.MOVIE
                )
            if found and (info := client.details(found, kind)):
                self.identified[item.path.name] = info
        except Exception:  # noqa: BLE001 - identification is a bonus, never a failure
            return

    def _facts_of(self, files: dict[str, int]) -> list[tuple[str, MediaFacts]]:
        found = [(p, self.facts.get((p, s))) for p, s in sorted(_media(files).items())]
        return [(p, f) for p, f in found if f is not None]

    # Rules -------------------------------------------------------------------

    def refusals(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int | None = None
    ) -> list[Refusal]:
        if not self.available():
            return [Refusal(Problem.NO_MEDIAINFO)]
        files = _content(item, ignore)
        if not files:
            return [Refusal(Problem.NO_FILE)]
        found = []
        archives = sorted({e for p in files if (e := _ext(p)) in ARCHIVES})
        if archives:
            found.append(Refusal(Problem.ARCHIVE, ", ".join(archives)))
        videos = {p for p in files if _ext(p) in CONTAINERS + REFUSED_CONTAINERS}
        if not videos and not _is_disc(files):
            return [*found, Refusal(Problem.NO_VIDEO_FILE)]
        bad = sorted({e.upper() for p in videos if (e := _ext(p)) in REFUSED_CONTAINERS})
        if bad:
            found.append(Refusal(Problem.BAD_CONTAINER, ", ".join(bad)))
        banned = sorted(
            {t.upper() for p in [item.path.name, *videos] for t in _tokens(p) if t in BANNED_TEAMS}
        )
        if banned:
            found.append(Refusal(Problem.BANNED_TEAM, ", ".join(banned)))
        facts = self._facts_of(files)
        if gpu := sorted({f.gpu_encoder for _, f in facts if f.gpu_encoder}):
            found.append(Refusal(Problem.GPU_ENCODER, ", ".join(gpu)))
        if low := sorted({m for _, f in facts if (m := _too_low(f))}):
            found.append(Refusal(Problem.LOW_VIDEO_BITRATE, ", ".join(low)))
        for path, f in facts:
            if not any(t.french for t in f.audio) and not any(s.full_french for s in f.subtitles):
                found.append(Refusal(Problem.NO_FRENCH, path.rsplit("/", 1)[-1]))
                break
        if differing := _pack_differences(facts, files):
            found.append(Refusal(Problem.MIXED_PACK, differing))
        return found

    def warnings(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int
    ) -> list[UploadWarning]:
        files = _content(item, ignore)
        info = self.identified.get(item.path.name)
        found = [
            UploadWarning(Judgement.FRENCH_TITLE, info.title if info else ""),
            UploadWarning(Judgement.FORBIDDEN_SOURCE),
        ]
        names = [item.path.name, *(p.rsplit("/", 1)[-1] for p in _media(files))]
        if any(_guess(n).get("source") == "Web" for n in names[:2]):
            found.append(UploadWarning(Judgement.WEB_PLATFORM))
        if any("MICKEY" == t.upper() for n in names for t in _tokens(n, upper=True)):
            found.append(UploadWarning(Judgement.MICKEY_TAG))
        if subcategory in EPISODE_SUBCATEGORIES and (gaps := _missing_episodes(files)):
            found.append(UploadWarning(Judgement.INCOMPLETE_SEASON, ", ".join(gaps)))
        found.append(UploadWarning(Judgement.SLOTS))
        return found

    def default_subcategory(self, item: LocalItem, ignore: IgnoreList) -> int:
        """Série TV for a name with a season or an episode, else Film."""
        if _guess(_first_segment(item)).get("type") == "episode":
            return SubcategoryVideo.SERIES
        return SubcategoryVideo.MOVIE

    # Release name --------------------------------------------------------------

    def suggested_name(
        self, item: LocalItem, ignore: IgnoreList, source: str, subcategory: int
    ) -> str:
        """The template of the subcategory (docs/research/upload-rules.md), from the
        existing name and MediaInfo; `source` is the team tag, else the name's own, else
        NOTAG. Editable."""
        files = _content(item, ignore)
        media = _media(files)
        main = max(media, key=lambda p: media[p]) if media else ""
        guess = {
            **_guess(main.rsplit("/", 1)[-1] if main else ""),
            **_guess(_first_segment(item)),
        }
        facts = self.facts.get((main, media[main])) if main else None
        info = self.identified.get(item.path.name)
        title = (info.title if info else "") or str(guess.get("title", "") or item.path.stem)
        year = str(guess.get("year") or (info.year if info else "") or "")
        team = re.sub(r"[^A-Za-z0-9]+", "", _ascii(source)) or _team(_stem(main or item.path.name))
        tag = f"-{team or NOTAG}"
        technical = self._technical(item, files, facts, guess, main)
        language = self._language(facts, item.path.name)
        episode = _episodes(files, guess)
        if subcategory in (SubcategoryVideo.CLIPS, SubcategoryVideo.CONCERT):
            parts = [_words(title).upper(), year, *technical["picture"], *technical["audio"]]
            parts += technical["codec"]
        elif subcategory == SubcategoryVideo.COLLECTION:
            parts = [_words(title), "COLLECTION", _years(files, guess), language]
            parts += [*technical["picture"], *technical["audio"], *technical["codec"]]
        elif subcategory == SubcategoryVideo.TV_SHOW:
            date = ".".join(re.findall(r"\d+", str(guess.get("date", "")))) or year
            parts = [_words(title), episode, date, language]
            parts += [*technical["picture"], *technical["audio"], *technical["codec"]]
        elif subcategory in EPISODE_SUBCATEGORIES:
            parts = [_words(title), year]
            if subcategory == SubcategoryVideo.DOCUMENTARY_SERIES:
                parts.append("DOC")
            parts += [episode, language, *technical["picture"], *technical["audio"]]
            parts += technical["codec"]
        else:
            parts = [_words(title), year]
            if subcategory == SubcategoryVideo.DOCUMENTARY:
                parts.append("DOC")
            parts += [language, *technical["picture"], *technical["audio"], *technical["codec"]]
        return ".".join(p for p in parts if p) + tag

    def _technical(
        self,
        item: LocalItem,
        files: dict[str, int],
        facts: MediaFacts | None,
        guess: dict[str, Any],
        main: str,
    ) -> dict[str, list[str]]:
        disc = _is_disc(files)
        other = guess.get("other")
        others = [other] if isinstance(other, str) else list(other or [])
        remux = "Remux" in others
        resolution = facts.resolution if facts else str(guess.get("screen_size") or "")
        if resolution in ("SD", "480p", "576p"):
            resolution = ""
        name = (main or item.path.name).casefold()
        kind = str(guess.get("source") or "")
        if kind == "Ultra HD Blu-ray" or (kind == "Blu-ray" and resolution == "2160p"):
            source = "UHD.BluRay"
        elif kind == "Blu-ray":
            source = "BluRay"
        elif kind == "Web":
            source = "WEBRip" if "webrip" in name or "Rip" in others else "WEB-DL"
        elif kind == "DVD":
            source = "DVDRip" if "Rip" in others else "DVD"
        else:
            source = {"HDTV": "HDTV", "Digital TV": "PDTV"}.get(kind, "")
        pure = ""
        if disc:
            pure = "ISO" if any(_ext(p) == "iso" for p in files) else "BDMV"
            if any(part.casefold() == "video_ts" for p in files for part in p.split("/")):
                pure = "VIDEO_TS"
        elif remux:
            pure = "REMUX"
        picture = [resolution, source, pure, *self._hdr(facts)]
        audio = self._audio(facts)
        codec = self._video_codec(facts, source, bool(pure), guess)
        return {
            "picture": [p for p in picture if p],
            "audio": audio,
            "codec": [codec] if codec else [],
        }

    def _hdr(self, facts: MediaFacts | None) -> list[str]:
        if facts is None:
            return []
        if facts.hdr10plus:
            return ["HDR10PLUS"]
        if facts.dv_profile in (7, 8) and facts.hdr10:
            return ["DV.HDR10"]
        if facts.dv_profile:
            return ["DV"]
        if facts.hdr10:
            return ["HDR10"]
        return ["HDR"] if facts.hlg else []

    def _audio(self, facts: MediaFacts | None) -> list[str]:
        """The French track with most channels (lossy), or the lossless track with most
        channels in any language; `EAC3.ATMOS.7.1`."""
        if facts is None or not facts.audio:
            return []
        french = [t for t in facts.audio if t.french]
        best_french = max(french, key=lambda t: (t.channels, t.bitrate), default=None)
        lossless = [t for t in facts.audio if t.lossless]
        best_lossless = max(lossless, key=lambda t: (t.channels, t.bitrate), default=None)
        if best_lossless and (
            best_french is None or best_lossless.channels >= best_french.channels
        ):
            track = best_lossless
        else:
            track = best_french or max(facts.audio, key=lambda t: (t.channels, t.bitrate))
        parts = [track.codec]
        if track.atmos:
            parts.append("ATMOS")
        return [".".join([*parts, track.layout])]

    def _video_codec(
        self, facts: MediaFacts | None, source: str, pure: bool, guess: dict[str, Any]
    ) -> str:
        if facts is None:
            return {"H.264": "x264", "H.265": "x265"}.get(str(guess.get("video_codec") or ""), "")
        codec = facts.video_codec
        if pure:
            return PURE.get(codec, codec)
        if facts.encoder in ("x264", "x265"):
            return facts.encoder
        if codec in WEB_CODECS and source.startswith("WEB-DL"):
            return WEB_CODECS[codec]
        return {"AVC": "x264", "HEVC": "x265"}.get(codec, codec)

    def _language(self, facts: MediaFacts | None, name: str) -> str:
        """VFF, VFQ…, `MULTI.VFF` when other languages come with it, `MULTI.VF2` for VFF
        and VFQ together, VOSTFR with only French subtitles, MUET without audio."""
        named = next((t for t in _tokens(name, upper=True) if t in FRENCH_VARIANTS), "")
        if facts is None:
            return named
        variants = {t.variant for t in facts.audio if t.french}
        others = any(t.language and not t.french for t in facts.audio)
        if variants:
            if {"VFF", "VFQ"} <= variants:
                return "MULTI.VF2"
            variant = named if named and len(variants) == 1 else sorted(variants)[0]
            return f"MULTI.{variant}" if others else variant
        if not facts.audio:
            return "MUET"
        return "VOSTFR" if any(s.full_french for s in facts.subtitles) else named

    # Category Options ----------------------------------------------------------

    def suggested_options(
        self, item: LocalItem, ignore: IgnoreList, types: list[OptionType]
    ) -> Chosen:
        """Language, quality, source and codec from MediaInfo and the name, where the
        option's values name them."""
        files = _content(item, ignore)
        media = _media(files)
        main = max(media, key=lambda p: media[p]) if media else ""
        facts = self.facts.get((main, media[main])) if main else None
        if facts is None:
            return {}
        guess = {**_guess(main.rsplit("/", 1)[-1]), **_guess(_first_segment(item))}
        tech = self._technical(item, files, facts, guess, main)
        language = self._language(facts, item.path.name)
        wanted = {
            "langue": _LANGUAGE_LABELS.get(language, []),
            "qualit": [facts.resolution],
            "résolution": [facts.resolution],
            "resolution": [facts.resolution],
            "source": [t for t in tech["picture"][1:2]],
            "codec": [*tech["codec"], facts.video_codec],
        }
        chosen: Chosen = {}
        for t in types:
            name = t.name.casefold()
            tokens = next((v for k, v in wanted.items() if name.startswith(k)), [])
            for token in tokens:
                ids = [v.id for v in t.values if _norm(token) and _norm(token) in _norm(v.label)]
                if ids:
                    chosen[t.id] = ids if t.multiple else ids[:1]
                    break
        return chosen

    # NFO, description, Draft ---------------------------------------------------

    def nfo(self, title: str, files: list[UploadFile]) -> str:
        """A short header, then MediaInfo's text of each file under the name the torrent
        gives it; a pack of more than ten files lists the first only."""
        known = self._known(files)
        lines = [
            title,
            "",
            f"Fichiers ....... : {len(files)}",
            f"Taille totale .. : {human_size(sum(f.size for f in files))}",
        ]
        if known:
            lines.append(f"Durée .......... : {_clock(sum(f.duration for _, f in known))}")
            lines.append("")
            shown = known[:1] if len(known) > PACK_MAX_NFO else known
            for upload_file, f in shown:
                lines += [
                    media_info.with_file_name(
                        f.text, upload_file.torrent_path.split("/")[-1]
                    ).strip(),
                    "",
                ]
        else:
            lines += ["", "Contenu :", *(f"  {f.torrent_path.split('/', 1)[-1]}" for f in files)]
        return "\n".join(lines).rstrip("\n") + "\n"

    def description(self, title: str, files: list[UploadFile], source: str, image_url: str) -> str:
        """An image, the French and original titles, TMDb's synopsis and the facts."""
        known = self._known(files)
        info = self.identified.get(files[0].local_path.split("/")[0])
        heading = (info.title if info else "") or _guess(title).get("title") or title
        lines = [
            f"[center][img]{image_url or IMAGE_PLACEHOLDER}[/img][/center]",
            "",
            f"[center][h2]{heading}[/h2][/center]",
            "",
            "[h3]Synopsis[/h3]",
            (info.overview if info else "") or "",
            "",
            "[h3]Informations[/h3]",
        ]
        if info and info.original_title:
            lines.append(f"[b]Titre original :[/b] {info.original_title}")
        if info and info.year:
            lines.append(f"[b]Année :[/b] {info.year}")
        if known:
            facts = known[0][1]
            lines += [
                f"[b]Conteneur :[/b] {facts.container}",
                f"[b]Durée :[/b] {_clock(sum(f.duration for _, f in known))}",
                f"[b]Vidéo :[/b] {facts.video_codec} {facts.resolution}"
                + (f", {facts.video_bitrate} kb/s" if facts.video_bitrate else ""),
            ]
            for t in facts.audio:
                lines.append(
                    f"[b]Audio :[/b] {t.codec} {t.layout}"
                    f"{' Atmos' if t.atmos else ''} {t.language.upper() or '?'}"
                )
            for s in facts.subtitles:
                kind = "forcés" if s.forced else "SDH" if s.sdh else "complets"
                lines.append(
                    f"[b]Sous-titres :[/b] {s.language.upper() or '?'} ({s.format}, {kind})"
                )
        if _guess(title).get("source") == "Web":
            lines.append("[b]Plateforme VOD :[/b] ")
        lines += [
            f"[b]Fichiers :[/b] {len(files)}",
            f"[b]Taille totale :[/b] {human_size(sum(f.size for f in files))}",
        ]
        return "\n".join(lines) + "\n"

    def existing_query(self, item: LocalItem, ignore: IgnoreList) -> ExistingQuery:
        """By TMDb id once the item is identified, else by its title words."""
        info = self.identified.get(item.path.name)
        ids = {"tmdbId": info.id, "tmdbType": info.type} if info else {}
        return ExistingQuery(name_query(item), ids)

    def draft_fields(
        self, item: LocalItem, ignore: IgnoreList, files: list[UploadFile]
    ) -> dict[str, Any]:
        """The Draft's `mediainfo` (the NFO's MediaInfo text) and `tmdbData` when known."""
        known = self._known(files)
        info = self.identified.get(item.path.name)
        text = "\n\n".join(f.text.strip() for _, f in known[:PACK_MAX_NFO]) if known else None
        return {"mediainfo": text, "tmdbData": info.raw if info else None}

    def _known(self, files: list[UploadFile]) -> list[tuple[UploadFile, MediaFacts]]:
        found = [(f, self.facts.get((f.local_path, f.size))) for f in files]
        return [(f, m) for f, m in found if m is not None]


_LANGUAGE_LABELS = {
    "VFF": ["VFF"],
    "VOF": ["VFF"],
    "TRUEFRENCH": ["VFF"],
    "VFI": ["VFF"],
    "VFB": ["VFF"],
    "VFQ": ["VFQ"],
    "MULTI.VF2": ["Multi VF2"],
    "VOSTFR": ["VOSTFR"],
    "MUET": ["Muet"],
}
_LANGUAGE_LABELS.update({f"MULTI.{v}": ["Multi (Français inclus)"] for v in FRENCH_VARIANTS})
_LANGUAGE_LABELS["MULTI.VFQ"] = ["Multi (Québecois inclus)"]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii(text).casefold())


def _tokens(name: str, upper: bool = False) -> list[str]:
    """The words of a name; lowercase to compare with the lists above, or upper."""
    words = re.split(r"[^A-Za-z0-9]+", name.rsplit("/", 1)[-1])
    return [w.upper() if upper else w.casefold() for w in words if w]


def _too_low(f: MediaFacts) -> str:
    """`1080p x264 800 kb/s (minimum 2500)` for an encode under c411's minimum; a WEB-DL
    or a pure source shows no encoder and has none."""
    codec = (
        "XVID" if f.video_codec == "XVID" else f.encoder if f.encoder in ("x264", "x265") else ""
    )
    if not codec and f.video_codec == "AV1" and f.encoder:
        codec = "AV1"
    minimum = MIN_KBPS.get((f.resolution, codec))
    rate = f.video_bitrate or f.bitrate
    if minimum and rate and rate < minimum:
        return f"{f.resolution} {codec} {rate} kb/s (minimum {minimum})"
    return ""


def _spec(f: MediaFacts) -> tuple[str, str, str]:
    return (f.video_codec, f.resolution, f"{f.dv_profile}{f.hdr10}")


def _pack_differences(facts: list[tuple[str, MediaFacts]], files: dict[str, int]) -> str:
    """What differs among the files of a pack: their specs or their teams."""
    if len(facts) < 2:
        return ""
    found = []
    if len({_spec(f) for _, f in facts}) > 1:
        found.append("specs")
    teams = {_team(_stem(p)) for p, _ in facts}
    if len(teams) > 1:
        found.append("teams")
    return ", ".join(found)


def _episodes(files: dict[str, int], guess: dict[str, Any]) -> str:
    """`S01E02` for an episode, `S01` for a season's files, `S01S03` for several seasons;
    nothing when the name numbers none."""
    seasons: set[int] = set()
    numbers: list[tuple[int, int]] = []
    for p in _media(files) or {}:
        g = _guess(p.rsplit("/", 1)[-1])
        season, episode = g.get("season"), g.get("episode")
        for s in [season] if isinstance(season, int) else list(season or []):
            seasons.add(int(s))
            if isinstance(episode, int):
                numbers.append((int(s), episode))
    if not seasons:
        season, episode = guess.get("season"), guess.get("episode")
        if isinstance(season, int):
            return f"S{season:02d}" + (f"E{episode:02d}" if isinstance(episode, int) else "")
        return ""
    if len(numbers) == 1 and len(_media(files)) == 1:
        return f"S{numbers[0][0]:02d}E{numbers[0][1]:02d}"
    low, high = min(seasons), max(seasons)
    return f"S{low:02d}" if low == high else f"S{low:02d}S{high:02d}"


def _years(files: dict[str, int], guess: dict[str, Any]) -> str:
    years = sorted(
        {int(g["year"]) for p in _media(files) if (g := _guess(p.rsplit("/", 1)[-1])).get("year")}
    )
    if not years:
        return str(guess.get("year") or "")
    return str(years[0]) if len(years) == 1 else f"{years[0]}.{years[-1]}"


def _missing_episodes(files: dict[str, int]) -> list[str]:
    """`S01E03` for each episode missing between a season's first and last."""
    seen: dict[int, set[int]] = {}
    for p in _media(files):
        g = _guess(p.rsplit("/", 1)[-1])
        season, episode = g.get("season"), g.get("episode")
        if isinstance(season, int):
            seen.setdefault(season, set()).update(
                [episode] if isinstance(episode, int) else list(episode or [])
            )
    missing = []
    for season, episodes in sorted(seen.items()):
        if episodes:
            missing += [
                f"S{season:02d}E{n:02d}"
                for n in range(min(1, min(episodes)), max(episodes) + 1)
                if n not in episodes
            ]
    return missing


def _clock(seconds: float) -> str:
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"
