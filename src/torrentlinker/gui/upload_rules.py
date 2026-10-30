"""Localized rules for Upload preparation and saved draft review."""

import re

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication

from torrentlinker.upload import Judgement, Problem, Refusal, UploadWarning


def refusal_text(r: Refusal) -> str:
    if r.problem is Problem.ARCHIVE:
        return QCoreApplication.translate(
            "Upload", "c411 refuses archives ({0}), and this one cannot be read"
        ).format(r.detail)
    if r.problem is Problem.OPTION_MISSING:
        return QCoreApplication.translate("Upload", "Choose a value for {0}").format(r.detail)
    if r.problem is Problem.NO_3D_FILE:
        return QCoreApplication.translate("Upload", "No 3D file (STL, 3MF, OBJ, STEP, GCODE…)")
    if r.problem is Problem.NO_EBOOK_FORMAT:
        return QCoreApplication.translate(
            "Upload",
            "No accepted format (PDF, EPUB, MOBI, DjVu, CBR, CBZ, JPG/PNG, MP3, M4A/M4B, FLAC)",
        )
    if r.problem is Problem.NO_AUDIO_FILE:
        return QCoreApplication.translate("Upload", "No audio file (FLAC, MP3, M4A, WAV, OGG…)")
    if r.problem is Problem.AUDIO_FORMAT:
        return QCoreApplication.translate(
            "Upload", "c411 does not accept these formats: {0}"
        ).format(r.detail)
    if r.problem is Problem.LOW_BITRATE:
        return QCoreApplication.translate("Upload", "Bitrate too low: {0}").format(r.detail)
    if r.problem is Problem.NEEDS_CUE:
        return QCoreApplication.translate("Upload", "A single-file album needs its .cue sheet")
    if r.problem is Problem.MIXED_AUDIO:
        return QCoreApplication.translate(
            "Upload", "One format and bitrate per album, found: {0}"
        ).format(r.detail)
    if r.problem is Problem.NO_MEDIAINFO:
        return QCoreApplication.translate(
            "Upload",
            "MediaInfo is not installed: install libmediainfo (for example the "
            "libmediainfo0v5 package) to upload videos",
        )
    if r.problem is Problem.NO_VIDEO_FILE:
        return QCoreApplication.translate("Upload", "No video file (MKV, MP4, M4V, AVI, TS, M2TS)")
    if r.problem is Problem.BAD_CONTAINER:
        return QCoreApplication.translate(
            "Upload", "c411 does not accept these containers: {0}"
        ).format(r.detail)
    if r.problem is Problem.GPU_ENCODER:
        return QCoreApplication.translate("Upload", "GPU encoders are forbidden ({0})").format(
            r.detail
        )
    if r.problem is Problem.LOW_VIDEO_BITRATE:
        return QCoreApplication.translate("Upload", "Video bitrate too low: {0}").format(r.detail)
    if r.problem is Problem.BANNED_TEAM:
        return QCoreApplication.translate("Upload", "Banned team or source: {0}").format(r.detail)
    if r.problem is Problem.NO_FRENCH:
        return QCoreApplication.translate(
            "Upload", "No French audio and no full French subtitles in {0}"
        ).format(r.detail)
    if r.problem is Problem.MIXED_PACK:
        return QCoreApplication.translate(
            "Upload",
            "The files of a pack must share their specs and their team; they differ in: {0}",
        ).format(r.detail)
    if r.problem is Problem.DOWNLOADER:
        return QCoreApplication.translate(
            "Upload", "Downloader executables are forbidden: {0}"
        ).format(r.detail)
    if r.problem is Problem.BIN_NO_CUE:
        return QCoreApplication.translate("Upload", "A .bin image needs its .cue sheet")
    if r.problem is Problem.CLONECD_INCOMPLETE:
        return QCoreApplication.translate("Upload", "A CloneCD image is missing: {0}").format(
            r.detail
        )
    if r.problem is Problem.PASSWORD_ARCHIVE:
        return QCoreApplication.translate("Upload", "Password-protected archives: {0}").format(
            r.detail
        )
    if r.problem is Problem.CONSOLE_CONTAINER:
        return QCoreApplication.translate(
            "Upload", "Files this console does not take (archives are fine, one per game): {0}"
        ).format(r.detail)
    if r.problem is Problem.FORBIDDEN_TOOL:
        return QCoreApplication.translate(
            "Upload", "Trainers, hack tools and hypervisor cracks are forbidden: {0}"
        ).format(r.detail)
    if r.problem is Problem.ISO_NOT_ALLOWED:
        return QCoreApplication.translate(
            "Upload",
            "An .iso is only allowed for a crack, repack or scene release: extract it first",
        )
    return QCoreApplication.translate("Upload", "No file to upload")


def warning_text(w: UploadWarning) -> str:
    if w.judgement is Judgement.METADATA_CONSISTENCY:
        return QCoreApplication.translate("Upload", "Metadata consistency") + ": " + w.detail
    if w.judgement is Judgement.PACK_THEME:
        return QCoreApplication.translate("Upload", "A pack must have one coherent theme")
    if w.judgement is Judgement.FRENCH_ONLY:
        return QCoreApplication.translate("Upload", "c411 accepts eBooks in French only")
    if w.judgement is Judgement.NO_DUPLICATE:
        return QCoreApplication.translate(
            "Upload", "Duplicates are strictly forbidden (another format is not one)"
        )
    if w.judgement is Judgement.FEW_FORMATS:
        return QCoreApplication.translate("Upload", "At most two or three formats of the same book")
    if w.judgement is Judgement.WHOLE_VOLUMES:
        return QCoreApplication.translate("Upload", "A pack must hold whole volumes")
    if w.judgement is Judgement.EVERY_VOLUME:
        return QCoreApplication.translate("Upload", "A BD pack must hold every volume")
    if w.judgement is Judgement.FRENCH_TITLE:
        if w.detail:
            return QCoreApplication.translate(
                "Upload", "The release title must be the French one: {0}"
            ).format(w.detail)
        return QCoreApplication.translate(
            "Upload",
            "The release title must be the French one (the original goes in the description)",
        )
    if w.judgement is Judgement.FORBIDDEN_SOURCE:
        return QCoreApplication.translate(
            "Upload",
            "Forbidden sources: CAM, TS, upscales, Plex transcodes, films still in cinemas",
        )
    if w.judgement is Judgement.INCOMPLETE_SEASON:
        return QCoreApplication.translate("Upload", "Incomplete season, missing: {0}").format(
            w.detail
        )
    if w.judgement is Judgement.WEB_PLATFORM:
        return QCoreApplication.translate(
            "Upload", "A WEB release must name its VOD platform in the description"
        )
    if w.judgement is Judgement.MICKEY_TAG:
        return QCoreApplication.translate(
            "Upload", "The MICKEY tag is a known detag: check the original release"
        )
    if w.judgement is Judgement.SLOTS:
        return QCoreApplication.translate(
            "Upload",
            "c411 keeps 28 slots per release: check the existing releases for a free one",
        )
    if w.judgement is Judgement.VERSION_ACTIVATION:
        return QCoreApplication.translate(
            "Upload", "State the version and how it is activated (NFO and description)"
        )
    if w.judgement is Judgement.NO_ALPHA:
        return QCoreApplication.translate("Upload", "No alpha or early-access versions")
    if w.judgement is Judgement.RETRO_ONLY:
        return QCoreApplication.translate(
            "Upload", "Only retro cartridge and floppy platforms, and arcade"
        )
    if w.judgement is Judgement.NO_MIXED_MACHINES:
        return QCoreApplication.translate(
            "Upload", "Do not mix machines in one pack (except MAME): {0}"
        ).format(w.detail)
    if w.judgement is Judgement.RELEASE_TYPE:
        return QCoreApplication.translate(
            "Upload", "Release type decided from the files: {0} (edit the name to change it)"
        ).format(w.detail)
    if w.judgement is Judgement.INSTALL_NOTE:
        return QCoreApplication.translate(
            "Upload", "An install note is mandatory unless the release is portable"
        )
    if w.judgement is Judgement.NO_IPTV:
        return QCoreApplication.translate("Upload", "No IPTV software")
    if w.judgement is Judgement.OLDER_VERSION:
        return QCoreApplication.translate(
            "Upload", "An older version of the same generation is removed when this one is accepted"
        )
    if w.judgement is Judgement.ONE_PER_RELEASE:
        return QCoreApplication.translate(
            "Upload",
            "One scene version, plus one repack with language or bonus options, one repacker "
            "release and one portable per scene release; a repack must be compressed and "
            "smaller than the scene release: this is {0}",
        ).format(w.detail)
    if w.judgement is Judgement.OFFICIAL_TRAINING:
        return QCoreApplication.translate(
            "Upload", "Official video trainings only (audio at 64 kbps or more)"
        )
    if w.judgement is Judgement.PLUGIN_HOST:
        return QCoreApplication.translate(
            "Upload",
            "A plugin or extension needs its host software on the tracker, compatible with "
            "that version, with a link to it in the description",
        )
    if w.judgement is Judgement.ORIGINAL_CRACK:
        return QCoreApplication.translate(
            "Upload", "Find the original crack and use the cracker's or repacker's own name"
        )
    if w.judgement is Judgement.UPDATE_ONLY:
        return QCoreApplication.translate(
            "Upload",
            "An update holds only the update files (not a new full pack), states the crack "
            "used, and is one per game version",
        )
    if w.judgement is Judgement.ONE_GOG:
        return QCoreApplication.translate("Upload", "One GOG version per game")
    if w.judgement is Judgement.ONE_PER_CONSOLE:
        return QCoreApplication.translate("Upload", "One version per console game")
    if w.judgement is Judgement.REGION:
        if w.detail:
            return QCoreApplication.translate(
                "Upload", "Region {0}: PAL/EU, NTSC/US, NTSC-J/JP or HK, one release each"
            ).format(w.detail)
        return QCoreApplication.translate(
            "Upload", "State the region: PAL/EU, NTSC/US, NTSC-J/JP or HK"
        )
    if w.judgement is Judgement.NO_TRANSCODE:
        return QCoreApplication.translate(
            "Upload", "No transcodes (MP3 to FLAC, 128 to 320 kbps, stereo to 5.1)"
        )
    if w.judgement is Judgement.SHORT_SINGLE:
        return QCoreApplication.translate("Upload", "Singles are accepted from 20 minutes only")
    if w.judgement is Judgement.DISCOGRAPHY:
        return QCoreApplication.translate(
            "Upload", "Discographies are accepted for inactive artists only"
        )
    if w.judgement is Judgement.CD_RIP_MISSING:
        return QCoreApplication.translate("Upload", "A CD-Rip needs: {0}").format(w.detail)
    if w.judgement is Judgement.CD_RIP_LINKS:
        return QCoreApplication.translate(
            "Upload",
            "A CD-Rip's description gives the catalogue number and a Discogs or MusicBrainz link",
        )
    return QCoreApplication.translate(
        "Upload", "c411 forbids files from independent creators who live off them"
    )


def stored_rule_text(message: str) -> str:
    """Explain web/MCP diagnostic codes while preserving older prose and unknown findings."""
    code, separator, detail = message.partition(":")
    if not separator:
        return message
    try:
        problem = Problem(code)
    except ValueError:
        try:
            judgement = Judgement(code)
        except ValueError:
            return presentation_text(message)
        return warning_text(UploadWarning(judgement, detail.strip()))
    return refusal_text(Refusal(problem, detail.strip()))


def presentation_text(message: str) -> str:
    """Translate recognized completeness findings; leave unknown diagnostics intact."""
    field, _, detail = message.partition(": ")
    # Match both field and wording: the same field can report a missing value,
    # a conflicting fact or a rejected language. Never hide an unfamiliar finding.
    messages = {
        ("title", QT_TRANSLATE_NOOP("UploadPresentation", "Add the release title.")),
        (
            "nfo",
            QT_TRANSLATE_NOOP("UploadPresentation", "Add the NFO describing these exact files."),
        ),
        (
            "description.image",
            QT_TRANSLATE_NOOP(
                "UploadPresentation",
                "Add a public HTTP(S) cover/image inside the description: [img]URL[/img].",
            ),
        ),
        (
            "description.synopsis",
            QT_TRANSLATE_NOOP(
                "UploadPresentation",
                "Fill the [h3]Présentation[/h3] section with a synopsis "
                "before [h3]Informations[/h3].",
            ),
        ),
        (
            "image",
            QT_TRANSLATE_NOOP("UploadPresentation", "Set the hosted image URL before sending."),
        ),
        (
            "description.image",
            QT_TRANSLATE_NOOP(
                "UploadPresentation", "Public image hosting required before sending."
            ),
        ),
    }
    if (field, detail) in messages:
        return QCoreApplication.translate("UploadPresentation", detail)
    if field.startswith("description.") and (
        match := re.fullmatch(
            r"Fill '([^'\n]+)' in the description: \[b\]\1 :\[/b\] value\.", detail
        )
    ):
        return QCoreApplication.translate(
            "UploadPresentation", "Fill '{0}' in the description: [b]{0} :[/b] value."
        ).format(match[1])
    if field.startswith("nfo.") and (
        match := re.fullmatch(
            r"NFO field missing: (.+)\. For a generated NFO use '\1 : value'\. "
            r"Keep original release NFOs unaltered; obtain a complete original NFO\.",
            detail,
        )
    ):
        return QCoreApplication.translate(
            "UploadPresentation",
            "NFO field missing: {0}. For a generated NFO use '{0} : value'. "
            "Keep original release NFOs unaltered; obtain a complete original NFO.",
        ).format(match[1])
    return message
