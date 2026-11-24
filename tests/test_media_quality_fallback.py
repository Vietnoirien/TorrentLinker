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
    globalThis.localStorage = {{getItem: k => store[k] || null, setItem: (k, v) => {{ store[k] = v; }}}};
    require("vm").runInThisContext(require("fs").readFileSync({json.dumps(str(SCRIPT))}, "utf8"));
    const all = {{qualities: ["original", "360", "480", "720", "1080"]}};
    const limited = {{qualities: ["360", "480", "720"]}};
    const none = {{qualities: []}};
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


def test_a_failing_source_falls_back_one_quality_lower_and_never_while_switching():
    assert run('mediaQualityFallback(all, "original", false)') == "1080"
    assert run('mediaQualityFallback(all, "1080", false)') == "720"
    assert run('mediaQualityFallback(limited, "720", false)') == "480"
    assert run('mediaQualityFallback(limited, "360", false)') == ""  # nothing lower: say so
    assert run('mediaQualityFallback(all, "original", true)') == ""  # a switch reports itself
    assert run("mediaQualityFallback(undefined, 'original', false)") == ""  # music: no facts
