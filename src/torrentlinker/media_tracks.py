"""Source-bound track inventories and acknowledged preparation before playback."""

from __future__ import annotations

import time


def text(value, maximum=300):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("Invalid player track text.")
    return value


def inventory(value, current):
    if not isinstance(value, dict):
        raise ValueError("Invalid player track inventory.")
    result = {key: text(value.get(key, ""), 128) for key in ("source_token", "media_id")}
    if result["media_id"] != current:
        raise ValueError("Track inventory belongs to a different media source.")
    for key in ("ready", "audio_supported", "subtitle_supported"):
        if not isinstance(value.get(key), bool):
            raise ValueError("Track support must be true or false.")
        result[key] = value[key]
    if result["ready"] and (not current or not result["source_token"]):
        raise ValueError("Loaded tracks require a media source and source token.")
    for kind in ("audio", "subtitles"):
        rows = value.get(kind, [])
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("A player can report at most 100 tracks of each kind.")
        clean, ids = [], set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("selected"), bool):
                raise ValueError("Invalid player track.")
            entry = {
                key: text(row.get(key, ""), 128 if key == "id" else 300)
                for key in ("id", "label", "language")
            }
            if not entry["id"] or entry["id"] in ids or entry["id"] == "off":
                raise ValueError("Track IDs must be unique and nonempty.")
            ids.add(entry["id"])
            clean.append({**entry, "selected": row["selected"]})
        result[kind] = clean
    return result


def result_report(value):
    if not isinstance(value, dict) or not isinstance(value.get("applied"), bool):
        raise ValueError("Invalid track command result.")
    sequence = value.get("sequence")
    if type(sequence) is not int or sequence < 1:
        raise ValueError("Invalid track command sequence.")
    return {
        "sequence": sequence,
        "applied": value["applied"],
        "error": text(value.get("error", ""), 1000),
    }


def selection(state, kind, track_id, source_token):
    tracks = state.get("track_state", {})
    if kind not in {"audio", "subtitle"}:
        raise ValueError("Choose audio or subtitle tracks.")
    if not tracks.get("ready"):
        raise ValueError(
            "The attached player has not loaded its tracks yet. Read them again after loading."
        )
    if (
        not source_token
        or tracks.get("source_token") != source_token
        or tracks.get("media_id") != state.get("current_id")
    ):
        raise ValueError("The media source changed. Read the player's tracks again.")
    if not tracks.get(kind + "_supported"):
        raise ValueError(f"This player cannot select {kind} tracks. Use a supported player.")
    rows = tracks["audio" if kind == "audio" else "subtitles"]
    if not (kind == "subtitle" and track_id == "off") and not any(
        row["id"] == track_id for row in rows
    ):
        raise ValueError("Choose an exact track ID returned by read_media_tracks.")
    return {
        "action": "select_track",
        "kind": kind,
        "track_id": track_id,
        "source_token": source_token,
        "media_id": state["current_id"],
    }


def language(value):
    code = value.strip().lower().replace("_", "-").split("-")[0]
    return {
        "eng": "en",
        "english": "en",
        "anglais": "en",
        "fra": "fr",
        "fre": "fr",
        "french": "fr",
        "français": "fr",
        "spa": "es",
        "spanish": "es",
        "espagnol": "es",
        "deu": "de",
        "ger": "de",
        "german": "de",
        "ita": "it",
        "jpn": "ja",
        "por": "pt",
        "rus": "ru",
        "zho": "zh",
        "chi": "zh",
        "kor": "ko",
        "ara": "ar",
        "hin": "hi",
        "nld": "nl",
        "dut": "nl",
    }.get(code, code)


def preferences(audio_language="", subtitle_language="", audio_label="", subtitle_label=""):
    result = {}
    for kind, lang, label in (
        ("audio", audio_language, audio_label),
        ("subtitle", subtitle_language, subtitle_label),
    ):
        lang, label = text(lang, 100).strip(), text(label).strip()
        if lang or label:
            if kind == "audio" and lang.lower() == "off":
                raise ValueError(
                    "Audio requires a language or track label; only subtitles accept off."
                )
            result[kind] = {"language": language(lang), "label": label}
    return result


def resolve(state, requested):
    tracks = state["track_state"]
    commands = []
    for kind, preference in requested.items():
        if not tracks.get(kind + "_supported"):
            raise ValueError(f"This player cannot select {kind} tracks. Use a supported player.")
        lang, label = preference["language"], preference["label"].casefold()
        if kind == "subtitle" and lang == "off":
            identifier = "off"
        else:
            rows = tracks["audio" if kind == "audio" else "subtitles"]
            matches = [
                row
                for row in rows
                if (not lang or language(row["language"]) == lang)
                and (not label or label in row["label"].casefold())
            ]
            if len(matches) != 1:
                reason = (
                    "Multiple tracks match; ask the user to choose a track label"
                    if matches
                    else "No available track matches the requested language and label"
                )
                raise ValueError(f"{kind}: {reason}. Read read_media_tracks for available choices.")
            identifier = matches[0]["id"]
        commands.append(selection(state, kind, identifier, tracks["source_token"]))
    return commands


def advance(state, commands, append, allowed):
    """Prepare paused, select one track at a time, then resume the same source."""
    request = state.get("track_request")
    if not request or request["status"] in {"failed", "completed"}:
        return commands
    try:
        if not allowed:
            raise ValueError(
                "Media permission or player attachment changed; automatic playback cancelled."
            )
        if time.time() > request["deadline"]:
            raise ValueError(
                "The player did not finish preparing tracks. Read its state before retrying."
            )
        if state.get("command_ack", 0) < request["sequence"]:
            return commands
        tracks = state.get("track_state", {})
        if (
            request["status"] == "loading"
            and state.get("current_id") == request["media_id"]
            and tracks.get("source_token", "") in {"", request.get("previous_source_token", "")}
        ):
            return commands
        if (
            state.get("current_id") != request["media_id"]
            or tracks.get("source_token") != request["source_token"]
        ):
            raise ValueError("The media source changed; automatic playback cancelled.")
        if request["status"] == "loading":
            if not tracks.get("ready"):
                return commands
            request["remaining"] = resolve(state, request["preferences"])
        elif request["status"] in {"selecting", "resuming"}:
            result = state.get("track_result", {})
            if result.get("sequence") != request["sequence"] or not result.get("applied"):
                raise ValueError(
                    result.get("error") or "The player did not confirm the requested track action."
                )
            if request["status"] == "resuming":
                request["status"] = "completed"
                return commands
            chosen = request["selected"]
            rows = tracks["audio" if chosen["kind"] == "audio" else "subtitles"]
            active = [row["id"] for row in rows if row["selected"]]
            if active != ([] if chosen["track_id"] == "off" else [chosen["track_id"]]):
                raise ValueError("The player did not report the requested track as selected.")
        if request["remaining"]:
            command = request["remaining"].pop(0)
            request.update(status="selecting", selected=command)
        else:
            command = {
                "action": "play",
                "media_id": request["media_id"],
                "source_token": request["source_token"],
            }
            request["status"] = "resuming"
        command["request_token"] = request["source_token"]
        commands = append(state, commands, command)
        request["sequence"] = commands[-1]["sequence"]
    except (ValueError, PermissionError) as error:
        request.update(status="failed", error=str(error))
        commands = [c for c in commands if c.get("request_token") != request["source_token"]]
    return commands
