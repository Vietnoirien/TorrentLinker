"""The player starts at a quality and falls back by itself; it never asks (media_stream.js)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "src/torrentlinker/web/static/media_stream.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is needed")


def run(expression: str, remembered: str = ""):
    program = f"""
    const store = {{"torrentlinker.quality": {json.dumps(remembered)}}};
    globalThis.localStorage = {{
      getItem: k => store[k] || null, setItem: (k, v) => {{ store[k] = v; }},
    }};
    // A browser without AC-3 or E-AC-3, as Chrome and Firefox on Linux.
    globalThis.document = {{ createElement: () => ({{ canPlayType: () => "" }}) }};
    require("vm").runInThisContext(require("fs").readFileSync({json.dumps(str(SCRIPT))}, "utf8"));
    const all = {{
      available: true, height: 1080, qualities: ["original", "360", "480", "720", "1080"],
    }};
    const limited = {{available: true, height: 1080, qualities: ["360", "480", "720"]}};
    const none = {{qualities: []}};
    const ac3 = {{...all, sound: true, audio: [{{id: 0, codec: "ac3"}}]}};
    const aac = {{...all, sound: true, audio: [{{id: 0, codec: "aac"}}]}};
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


def test_an_original_that_cannot_play_is_transcoded_at_its_own_quality_first():
    assert run('mediaQualityFallback(all, "original", false)') == "source"
    assert (
        run('mediaQualityFallback(limited, "original", false)') == "source"
    )  # lowered by the server
    assert run('mediaQualityFallback(all, "source", false)') == "720"  # below the film's 1080
    assert run('mediaQualityFallback(all, "720", false)') == "480"
    assert run('mediaQualityFallback(limited, "360", false)') == ""  # nothing lower: say so
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
    assert run("mediaQualityStart({...ac3, sound: false})") == "original"  # no copy: try it
    # An original that fails tries its picture as it is before a full conversion.
    assert run('mediaQualityFallback(aac, "original", false)') == "sound"
    assert run('mediaQualityFallback(aac, "sound", false)') == "source"
