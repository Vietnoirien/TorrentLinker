"""c411's Audio category: albums, podcasts, samples (docs/research/upload-rules.md).

Import `AudioProfile` from torrentlinker.upload, which registers it (this module needs
that one's types, so it cannot be imported first).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from torrentlinker.audio_tags import AudioTags, TagCache, image_size
from torrentlinker.domain import LocalItem
from torrentlinker.matching import IgnoreList
from torrentlinker.options import Chosen, OptionType
from torrentlinker.queries import name_query
from torrentlinker.upload import (
    ARCHIVES,
    CATEGORY_AUDIO,
    DATE_RE,
    IMAGE_PLACEHOLDER,
    NOTAG,
    ExistingQuery,
    Judgement,
    Problem,
    Refusal,
    Subcategory,
    SubcategoryAudio,
    UploadFile,
    UploadWarning,
    _ascii,
    _content,
    _ext,
    _first_segment,
    _words,
    human_size,
)

# c411's audio formats (by extension); an `.iso` is only for SACD, Blu-ray Audio, DVD-Audio.
ACCEPTED = ("flac", "m4a", "wav", "wv", "aif", "aiff", "mp3", "ogg", "wma", "iso")
# Audio formats c411 refuses, so that "no audio file" does not hide them.
REFUSED = (
    "ape",
    "opus",
    "aac",
    "ac3",
    "dts",
    "m4b",
    "mka",
    "mpc",
    "tta",
    "tak",
    "mp2",
    "dsf",
    "dff",
)
MIN_KBPS = {"MP3": 320, "AAC": 256}  # constant bitrate; VBR MP3 is accepted
MIN_KBPS_SPOKEN = {"MP3": 128, "AAC": 128}  # podcasts and radio
SINGLE_MINUTES = 20
COVER_PIXELS = 500
FORMAT_LABELS = {  # c411's "Format Musique" values by codec
    "AAC": "AAC (M4A)",
    "ALAC": "ALAC (M4A)",
    "AIFF": "AIF",
    "MP3": "MP3",
    "OGG": "OGG",
    "WAV": "WAV",
    "WMA": "WMA",
    "WV": "WavPack",
}
ALBUM_YEAR_RE = re.compile(r"[\[(]\s*((?:19|20)\d\d)\s*[\])]|\b((?:19|20)\d\d)\b")


class AudioProfile:
    """The Audio category: Musique by default, tags read by `inspect`."""

    category: int = CATEGORY_AUDIO
    renders_models = False
    media_extensions: tuple[str, ...] = ()
    dotted_names = True
    subcategories: tuple[Subcategory, ...] = (
        Subcategory(SubcategoryAudio.KARAOKE, "Karaoke"),
        Subcategory(SubcategoryAudio.MUSIC, "Music"),
        Subcategory(SubcategoryAudio.PODCAST, "Podcasts & radio"),
        Subcategory(SubcategoryAudio.SAMPLES, "Samples"),
    )

    def __init__(self, tags: TagCache | None = None) -> None:
        self.tags = tags or TagCache()
        self.covers: dict[tuple[str, int], tuple[int, int] | None] = {}

    def image_is_sheet(self, subcategory: int) -> bool:
        return False

    def draft_fields(
        self, item: LocalItem, ignore: IgnoreList, files: list[UploadFile]
    ) -> dict[str, Any]:
        return {}

    def inspect(self, item: LocalItem, ignore: IgnoreList) -> None:
        """Read the tags of every audio file and the size of the covers."""
        files = _content(item, ignore)
        self.tags.inspect(item, [p for p in files if _ext(p) in ACCEPTED and _ext(p) != "iso"])
        for p, size in files.items():
            if _is_cover(p) and (p, size) not in self.covers:
                self.covers[(p, size)] = image_size(item.save_path / p)

    # Rules -------------------------------------------------------------------

    def refusals(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int | None = None
    ) -> list[Refusal]:
        files = _content(item, ignore)
        if not files:
            return [Refusal(Problem.NO_FILE)]
        found = []
        archives = sorted({e for p in files if (e := _ext(p)) in ARCHIVES})
        if archives:
            found.append(Refusal(Problem.ARCHIVE, ", ".join(archives)))
        audio = {p: s for p, s in files.items() if _ext(p) in ACCEPTED + REFUSED}
        if not audio:
            return [*found, Refusal(Problem.NO_AUDIO_FILE)]
        bad = sorted({e.upper() for p in audio if (e := _ext(p)) in REFUSED})
        if bad:
            found.append(Refusal(Problem.AUDIO_FORMAT, ", ".join(bad)))
        if len(audio) == 1 and not any(_ext(p) == "cue" for p in files):
            if subcategory in (None, SubcategoryAudio.MUSIC):
                found.append(Refusal(Problem.NEEDS_CUE))
        tags = [t for _, t in self.tags.of(audio)]
        minimums = MIN_KBPS_SPOKEN if subcategory == SubcategoryAudio.PODCAST else MIN_KBPS
        low = sorted(
            {
                f"{t.codec} {t.bitrate} kbps (minimum {minimums[t.codec]})"
                for t in tags
                if t.codec in minimums and t.constant and t.bitrate < minimums[t.codec]
            }
        )
        if low:
            found.append(Refusal(Problem.LOW_BITRATE, ", ".join(low)))
        mixed = _mixed(tags)
        if mixed:
            found.append(Refusal(Problem.MIXED_AUDIO, mixed))
        return found

    def warnings(
        self, item: LocalItem, ignore: IgnoreList, subcategory: int
    ) -> list[UploadWarning]:
        files = _content(item, ignore)
        tags = [t for _, t in self.tags.of(files)]
        found = [UploadWarning(Judgement.NO_TRANSCODE)]
        minutes = sum(t.duration for t in tags) / 60
        if tags and subcategory == SubcategoryAudio.MUSIC and len(tags) <= 3:
            if minutes < SINGLE_MINUTES:
                found.append(UploadWarning(Judgement.SHORT_SINGLE))
        if len({t.album for t in tags if t.album}) > 1:
            found.append(UploadWarning(Judgement.DISCOGRAPHY))
        if self._cd_rip(files, tags):
            if missing := self._cd_rip_missing(files):
                found.append(UploadWarning(Judgement.CD_RIP_MISSING, ", ".join(missing)))
            found.append(UploadWarning(Judgement.CD_RIP_LINKS))
        return found

    def default_subcategory(self, item: LocalItem, ignore: IgnoreList) -> int:
        return SubcategoryAudio.MUSIC

    # Release name ------------------------------------------------------------

    def suggested_name(
        self, item: LocalItem, ignore: IgnoreList, source: str, subcategory: int
    ) -> str:
        """Music `Artiste.Nom.Année[.CD-Rip].FLAC.16bit.44.1kHz-TAG` (lossy: `MP3.320kbps`);
        podcast `Emission.Date[.INTEGRALE].MP3.128kbps-TAG`; samples `Nom.Année.wav.1411kbps`.
        From the tags, else the Local Item's name; `source` is the team tag, NOTAG if empty."""
        files = _content(item, ignore)
        audio = {p: s for p, s in files.items() if _ext(p) in ACCEPTED}
        tags = [t for _, t in self.tags.of(audio)]
        guessed = _guess_album(_first_segment(item))
        artist = _artist(tags) or guessed[0]
        album = _album(tags) or guessed[1]
        year = _year(tags) or guessed[2]
        quality = _quality(tags, audio)
        tag = re.sub(r"[^A-Za-z0-9]+", "", _ascii(source)) or NOTAG
        if subcategory == SubcategoryAudio.SAMPLES:
            parts = [_words(album or artist), year, *_quality(tags, audio, samples=True)]
            return ".".join(p for p in parts if p)
        if subcategory == SubcategoryAudio.PODCAST:
            segment = _first_segment(item)
            show = _album(tags) or _artist(tags) or DATE_RE.sub(" ", segment).strip(" ._-")
            parts = [_words(show), _spoken_date(segment) or year]
            if len(audio) > 1:
                parts.append("INTEGRALE")
            return ".".join(p for p in [*parts, *quality] if p) + f"-{tag}"
        parts = [_words(artist), _words(album), year]
        if self._cd_rip(files, tags):
            parts.append("CD-Rip")
        return ".".join(p for p in [*parts, *quality] if p) + f"-{tag}"

    # Category Options --------------------------------------------------------

    def suggested_options(
        self, item: LocalItem, ignore: IgnoreList, types: list[OptionType]
    ) -> Chosen:
        """The format found, CD as source for a CD-Rip, Album or Discographie."""
        files = _content(item, ignore)
        tags = [t for _, t in self.tags.of(files)]
        chosen: Chosen = {}
        if not tags:
            return chosen
        for t in types:
            name = t.name.casefold()
            wanted = ""
            if name.startswith("format"):
                wanted = _format_label(tags[0])
            elif name.startswith("source") and self._cd_rip(files, tags):
                wanted = "CD"
            elif name.startswith("type"):
                wanted = "Discographie" if len({x.album for x in tags if x.album}) > 1 else "Album"
            ids = [v.id for v in t.values if v.label.casefold() == wanted.casefold()]
            if wanted and ids:
                chosen[t.id] = ids[:1]
        return chosen

    # NFO and description -------------------------------------------------------

    def nfo(self, title: str, files: list[UploadFile]) -> str:
        """c411's music NFO: artist, album, year, source, codec, bitrate, sample rate, bit
        depth (lossless), track count, size, then the tracklist with durations."""
        tracks = self._tracks(files)
        tags = [t for _, t in tracks if t is not None]
        first = tags[0] if tags else None
        sizes = {f.local_path: f.size for f in files}
        cd = self._cd_rip(sizes, tags)
        lines = [
            title,
            "",
            f"Artiste ........ : {_artist(tags) or '-'}",
            f"Album .......... : {_album(tags) or '-'}",
            f"Année .......... : {_year(tags) or '-'}",
            f"Source ......... : {'CD' if cd else '-'}",
        ]
        if first is not None:
            lines.append(f"Codec .......... : {first.codec}")
            if first.lossless:
                lines.append(f"Profondeur ..... : {first.bits} bits")
            else:
                mode = "" if first.constant else " (VBR)"
                lines.append(f"Débit .......... : {first.bitrate} kbps{mode}")
            lines.append(f"Fréquence ...... : {_khz(first.sample_rate)}")
        lines += [
            f"Pistes ......... : {len([f for f in files if _ext(f.local_path) in ACCEPTED])}",
            f"Taille totale .. : {human_size(sum(f.size for f in files))}",
            f"Durée .......... : {_clock(sum(t.duration for t in tags))}",
            "",
            "Liste des pistes :",
            *self._tracklist(tracks),
        ]
        return "\n".join(lines) + "\n"

    def description(self, title: str, files: list[UploadFile], source: str, image_url: str) -> str:
        """An image, a presentation the user writes, the facts and the tracklist; a
        CD-Rip adds the catalogue number and the Discogs or MusicBrainz link to fill."""
        tracks = self._tracks(files)
        tags = [t for _, t in tracks if t is not None]
        sizes = {f.local_path: f.size for f in files}
        heading = " - ".join(x for x in (_artist(tags), _album(tags)) if x) or title
        lines = [
            f"[center][img]{image_url or IMAGE_PLACEHOLDER}[/img][/center]",
            "",
            f"[center][h2]{heading}[/h2][/center]",
            "",
            "[h3]Présentation[/h3]",
            "",
            "",
            "[h3]Informations[/h3]",
        ]
        if _artist(tags):
            lines.append(f"[b]Artiste :[/b] {_artist(tags)}")
        if _album(tags):
            lines.append(f"[b]Album :[/b] {_album(tags)}")
        if _year(tags):
            lines.append(f"[b]Année :[/b] {_year(tags)}")
        if tags:
            first = tags[0]
            lines.append(f"[b]Codec :[/b] {first.codec}")
            if first.lossless:
                lines.append(f"[b]Profondeur :[/b] {first.bits} bits")
            else:
                lines.append(f"[b]Débit :[/b] {first.bitrate} kbps")
            lines.append(f"[b]Fréquence :[/b] {_khz(first.sample_rate)}")
        if self._cd_rip(sizes, tags):
            lines += [
                "[b]Source :[/b] CD",
                "[b]Numéro de catalogue :[/b] ",
                "[b]Discogs / MusicBrainz :[/b] ",
            ]
        lines += [
            f"[b]Pistes :[/b] {len(tracks)}",
            f"[b]Taille totale :[/b] {human_size(sum(f.size for f in files))}",
            "",
            "[spoiler=Liste des pistes][list]",
            *(f"[*]{row.strip()}" for row in self._tracklist(tracks)),
            "[/list][/spoiler]",
        ]
        return "\n".join(lines) + "\n"

    def existing_query(self, item: LocalItem, ignore: IgnoreList) -> ExistingQuery:
        return ExistingQuery(name_query(item))

    # Helpers -----------------------------------------------------------------

    def _tracks(self, files: list[UploadFile]) -> list[tuple[UploadFile, AudioTags | None]]:
        """The audio files in track order, with their tags when read."""
        audio = [(f, self.tags.get(f.local_path, f.size)) for f in files]
        audio = [(f, t) for f, t in audio if _ext(f.local_path) in ACCEPTED]
        return sorted(
            audio, key=lambda r: (r[1].track if r[1] and r[1].track else 10**6, r[0].torrent_path)
        )

    def _tracklist(self, tracks: list[tuple[UploadFile, AudioTags | None]]) -> list[str]:
        rows = []
        for number, (f, t) in enumerate(tracks, 1):
            name = (t.title if t and t.title else f.torrent_path.rsplit("/", 1)[-1]).strip()
            rows.append(f"  {number:02d}. {name}  {_clock(t.duration) if t else '-'}")
        return rows

    def _cd_rip(self, files: dict[str, int], tags: list[AudioTags]) -> bool:
        """A lossless 16 bit 44.1 kHz rip with an EAC log or a cue sheet."""
        if not tags or not all(
            t.lossless and t.bits == 16 and t.sample_rate == 44100 for t in tags
        ):
            return False
        return any(_ext(p) in ("log", "cue") for p in files)

    def _cd_rip_missing(self, files: dict[str, int]) -> list[str]:
        missing = []
        covers = [(p, s) for p, s in files.items() if _is_cover(p)]
        if not covers:
            missing.append("cover.jpg")
        elif not any((size := self.covers.get(c)) and min(size) >= COVER_PIXELS for c in covers):
            missing.append(f"cover.jpg ({COVER_PIXELS}×{COVER_PIXELS} or more)")
        for ext, label in (("cue", ".cue"), ("log", "EAC .log")):
            if not any(_ext(p) == ext for p in files):
                missing.append(label)
        return missing


def _is_cover(path: str) -> bool:
    """`cover.jpg` (or png) at the root of the album folder, or of a lone file's folder."""
    parts = path.split("/")
    return len(parts) <= 2 and parts[-1].casefold() in ("cover.jpg", "cover.jpeg", "cover.png")


def _mixed(tags: list[AudioTags]) -> str:
    """What differs among the files of one album: formats, or constant bitrates."""
    codecs = sorted({t.codec for t in tags})
    if len(codecs) > 1:
        return ", ".join(codecs)
    rates = sorted({t.bitrate for t in tags if not t.lossless and t.constant})
    return ", ".join(f"{r} kbps" for r in rates) if len(rates) > 1 else ""


def _common(values: list[str]) -> str:
    counted = Counter(v for v in values if v)
    return counted.most_common(1)[0][0] if counted else ""


def _artist(tags: list[AudioTags]) -> str:
    artists = {t.artist for t in tags if t.artist}
    return "Various" if len(artists) > 1 else _common([t.artist for t in tags])


def _album(tags: list[AudioTags]) -> str:
    albums = {t.album for t in tags if t.album}
    return _common([t.album for t in tags]) if len(albums) == 1 else ""


def _year(tags: list[AudioTags]) -> str:
    return _common([t.year for t in tags])


def _khz(rate: int) -> str:
    return f"{rate / 1000:g}kHz" if rate else ""


def _quality(tags: list[AudioTags], audio: dict[str, int], samples: bool = False) -> list[str]:
    """Codec, then the bit depth and sample rate (lossless) or the bitrate (lossy)."""
    if not tags:
        ext = next((_ext(p) for p in audio), "")
        return [ext.lower() if samples else ext.upper()] if ext else []
    first = tags[0]
    codec = first.codec.lower() if samples else first.codec
    if first.lossless:
        detail = [f"{first.bits}bit", _khz(first.sample_rate)]
    else:
        detail = [f"{first.bitrate}kbps" if first.constant else "VBR"]
    if samples:
        detail = [f"{first.bitrate}kbps"]
    return [codec, *(d for d in detail if d)]


def _format_label(tag: AudioTags) -> str:
    if tag.codec == "FLAC":
        return f"FLAC ({tag.bits} bit)"
    return FORMAT_LABELS.get(tag.codec, "")


def _guess_album(name: str) -> tuple[str, str, str]:
    """(artist, album, year) from `Artiste - Album (2001)`; any part may be empty."""
    year = ""
    if m := ALBUM_YEAR_RE.search(name):
        year = m.group(1) or m.group(2)
        name = name[: m.start()] + name[m.end() :]
    name = re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", " ", name)
    parts = [p.strip(" ._-") for p in re.split(r"\s+-\s+", name.strip()) if p.strip(" ._-")]
    if len(parts) < 2:
        return "", " ".join(parts), year
    return parts[0], " ".join(parts[1:]), year


def _spoken_date(name: str) -> str:
    return ".".join(g for g in m.groups() if g) if (m := DATE_RE.search(name)) else ""


def _clock(seconds: float) -> str:
    """`3:45`, or `1:02:03` from an hour on."""
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
