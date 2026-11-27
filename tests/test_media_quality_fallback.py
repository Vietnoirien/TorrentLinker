"""The player starts at a quality and falls back by itself; it never asks (media_stream.js)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "src/torrentlinker/web/static/media_stream.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is needed")


def run(expression: str, remembered: str = "", decode: dict | None = None):
    program = f"""
    const store = {{"torrentlinker.quality": {json.dumps(remembered)}}};
    if ({json.dumps(decode)}) store["torrentlinker.decode"] = JSON.stringify({json.dumps(decode)});
    globalThis.localStorage = {{
      getItem: k => store[k] || null, setItem: (k, v) => {{ store[k] = v; }},
    }};
    // Chrome on Linux without the hardware: no AC-3, E-AC-3, HEVC or 10-bit H.264/AV1/VP9, and
    // only a "maybe" for Matroska.
    const unplayable = /ac-3|ec-3|hvc1|avc1\\.6E|vp09\\.02|av01\\.0\\.08M\\.10/;
    globalThis.document = {{ createElement: () => ({{
      canPlayType: t => unplayable.test(t) ? "" : t.includes("matroska") ? "maybe" : "probably",
    }}) }};
    require("vm").runInThisContext(require("fs").readFileSync({json.dumps(str(SCRIPT))}, "utf8"));
    const all = {{
      available: true, height: 1080, qualities: ["original", "360", "480", "720", "1080"],
    }};
    const limited = {{available: true, height: 1080, qualities: ["360", "480", "720"]}};
    const none = {{qualities: []}};
    const ac3 = {{...all, sound: true, audio: [{{id: 0, codec: "ac3"}}]}};
    const aac = {{...all, sound: true, audio: [{{id: 0, codec: "aac"}}]}};
    const hevc = {{...ac3, video_codec: "hevc"}};
    // The South Park releases that showed the error: HEVC and AC-3 in Matroska.
    const tardis = {{...all, sound: true, video_codec: "hevc", bit_depth: 8, container: "matroska",
      audio: [{{id: 0, codec: "ac3"}}]}};
    const film = {{...all, sound: true, video_codec: "h264", bit_depth: 8, container: "matroska",
      audio: [{{id: 0, codec: "aac"}}]}};
    console.log(JSON.stringify({expression}));
    """
    done = subprocess.run(["node", "-e", program], capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def test_a_film_starts_at_the_remembered_quality_else_the_best_allowed():
    assert run("mediaQualityStart(all)") == "original"
    assert run("mediaQualityStart(limited)") == "720"
    assert run("mediaQualityStart(all)", "480") == "480"
    assert run("mediaQualityStart(limited)", "1080") == "720"  # above the limit: the best allowed
    assert run("mediaQualityStart(limited)", "original") == "720"
    assert run("mediaQualityStart(none)") == "original"  # nothing allowed: the server answers


def test_an_original_that_cannot_play_is_transcoded_at_its_own_quality_only():
    assert run('mediaQualityFallback(all, "original", false)') == "source"
    assert (
        run('mediaQualityFallback(limited, "original", false)') == "source"
    )  # lowered by the server
    # The resolution is never lowered by itself: a conversion that fails is reported.
    assert run('mediaQualityFallback(all, "source", false)') == ""
    assert run('mediaQualityFallback(all, "720", false)') == ""
    assert run('mediaQualityFallback(limited, "360", false)') == ""
    assert run('mediaQualityFallback(all, "original", true)') == ""  # a switch reports itself
    assert run("mediaQualityFallback(undefined, 'original', false)") == ""  # music: no facts
    assert (
        run('mediaQualityFallback({available: false, qualities: ["original"]}, "original", false)')
        == ""
    )


def test_a_sound_the_device_cannot_play_is_converted_alone():
    assert run("mediaQualityStart(ac3)") == "sound"  # the picture is kept as it is
    assert run("mediaQualityStart(aac)") == "original"
    assert run("mediaQualityStart(ac3)", "720") == "720"  # a chosen quality is kept
    # No copy possible: the whole film is converted rather than played without sound.
    assert run("mediaQualityStart({...ac3, sound: false})") == "source"
    # An original that fails tries its picture as it is before a full conversion.
    assert run('mediaQualityFallback(aac, "original", false)') == "sound"
    assert run('mediaQualityFallback(aac, "sound", false)') == "source"


def test_an_hevc_film_with_unplayable_sound_is_never_left_silent():
    # Its picture is copied when the browser reads an HEVC stream, else the film is converted.
    reads = "globalThis.MediaSource = {isTypeSupported: t => %s}, mediaQualityStart(hevc)"
    assert run("(" + reads % "t.includes('hvc1')" + ")") == "sound"
    assert run("(" + reads % "false" + ")") == "source"


def test_an_original_playing_without_sound_is_switched_by_itself():
    silent = "{webkitAudioDecodedByteCount: 0, paused: false, dataset: {}}"
    heard = "{webkitAudioDecodedByteCount: 4096, paused: false, dataset: {}}"
    assert run(f"mediaSilentSwitch({silent}, aac)") == "sound"
    assert run(f"mediaSilentSwitch({silent}, {{...all, audio: [{{codec: 'x'}}]}})") == "source"
    assert run(f"mediaSilentSwitch({heard}, aac)") == ""
    assert run(f"mediaSilentSwitch({silent}, {{...aac, audio: []}})") == ""  # a film with no sound
    converted = "{webkitAudioDecodedByteCount: 0, paused: false, dataset: {streamOffset: '0'}}"
    assert run(f"mediaSilentSwitch({converted}, aac)") == ""  # a conversion always has sound
    firefox = "{mozHasAudio: false, paused: false, dataset: {}}"
    assert run(f"mediaSilentSwitch({firefox}, aac)") == "sound"


def test_a_film_starting_at_its_own_resolution_is_streamed_not_loaded_as_the_original():
    # The original was loaded first, failed, and the fallback went below the film's own resolution.
    assert run('mediaQualityConverted(all, "source")') is True
    assert run('mediaQualityConverted(all, "sound")') is False
    assert run('mediaQualityConverted({...all, sound: true}, "sound")') is True
    assert run('mediaQualityConverted(all, "720")') is True
    assert run('mediaQualityConverted(all, "original")') is False
    assert (
        run('mediaQualityConverted({available: false, qualities: ["original"]}, "source")') is False
    )


def test_a_picture_the_device_cannot_show_is_converted_without_trying_the_original():
    assert run("mediaQualityStart(film)") == "original"
    assert run("mediaQualityStart(tardis)") == "source"
    assert run('mediaQualityStart({...film, video_codec: "hevc"})') == "source"  # sound is fine
    assert run('mediaQualityStart({...film, video_codec: "mpeg2video"})') == "source"
    assert run("mediaQualityStart({...film, bit_depth: 10})") == "source"  # 10-bit H.264
    assert run('mediaQualityStart({...film, video_codec: "av1"})') == "original"
    assert run('mediaQualityStart({...film, video_codec: "av1", bit_depth: 10})') == "source"
    # A device that reads HEVC streams keeps the picture and converts only the sound.
    reads = "globalThis.MediaSource = {isTypeSupported: t => t.includes('hvc1.1.6')}"
    assert run(f"({reads}, mediaQualityStart(tardis))") == "sound"
    assert run(f"({reads}, mediaQualityStart({{...tardis, bit_depth: 10}}))") == "source"


def test_a_container_the_device_cannot_open_keeps_the_picture():
    assert run('mediaQualityStart({...film, container: "avi"})') == "sound"
    assert run('mediaQualityStart({...film, container: "mp4"})') == "original"


def test_what_failed_on_this_device_is_remembered_for_files_made_the_same_way():
    # Chrome says "maybe" to Matroska; this one then failed on it.
    failed = "(mediaDecodeLearn(film, 'original', false), mediaQualityStart(film))"
    assert run(failed) == "sound"
    mp4 = "mediaQualityStart({...film, container: 'mp4'})"
    assert run(f"(mediaDecodeLearn(film, 'original', false), {mp4})") == "original"
    # Remembered across pages, and tried again after a month.
    profile = run("(mediaDecodeLearn(film, 'original', false), mediaDecodeProfile())")
    assert run("mediaQualityStart(film)", decode=profile) == "sound"
    month = {**profile, "learned": {k: {**v, "at": 0} for k, v in profile["learned"].items()}}
    assert run("mediaQualityStart(film)", decode=month) == "original"
    # A copied picture that failed is converted whole next time.
    reads = "globalThis.MediaSource = {isTypeSupported: t => t.includes('hvc1')}"
    copied = f"({reads}, mediaDecodeLearn(tardis, 'sound', false), mediaQualityStart(tardis))"
    assert run(copied) == "source"
    # A success overrides a probe that said no.
    played = "(mediaDecodeLearn(tardis, 'original', true), mediaQualityStart(tardis))"
    assert run(played) == "source"  # the picture itself is still unknown to this device


def test_the_profile_is_probed_again_when_the_browser_changes():
    profile = run("mediaDecodeProfile()")
    assert profile["video"]["h264"] is True and profile["video"]["hevc"] is False
    assert profile["audio"]["aac"] is True and profile["audio"]["ac3"] is False
    assert profile["container"]["matroska"] is True
    stale = {**profile, "agent": "an older browser", "video": {**profile["video"], "hevc": True}}
    assert run("mediaDecodeProfile().video.hevc", decode=stale) is False
    kept = {**profile, "video": {**profile["video"], "hevc": True}}
    assert run("mediaDecodeProfile().video.hevc", decode=kept) is True
