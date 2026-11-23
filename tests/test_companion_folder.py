"""The app-managed companion folder and the extension's once-per-version reload."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from torrentlinker.companion import bundled_version
from torrentlinker.companion_folder import ManagedCompanion

UPDATE = Path(__file__).parent.parent / "src/torrentlinker/companion_extension/update.js"


def test_folder_is_written_then_left_alone_until_version_or_origin_changes(tmp_path):
    managed = ManagedCompanion(tmp_path / "ext", origin_file=tmp_path / "o.json", needs_origin=True)
    assert managed.sync()["waiting"] == "origin"  # nothing written without an HTTPS origin
    assert not (tmp_path / "ext").exists()
    managed.record("http://plain.example/")  # not HTTPS: ignored
    managed.record("https://tl.example/")
    info = managed.sync()
    assert info["version"] == bundled_version() and info["path"] == str(tmp_path / "ext")
    receiver = tmp_path / "ext" / "receiver.json"
    assert json.loads(receiver.read_text()) == {"webTarget": "https://tl.example"}
    manifest = json.loads((tmp_path / "ext" / "manifest.json").read_text())
    assert "https://tl.example/*" in manifest["host_permissions"]
    assert not (tmp_path / "ext" / ".updating").exists()
    stamp = receiver.stat().st_mtime_ns
    managed.sync()
    assert receiver.stat().st_mtime_ns == stamp  # unchanged: not rewritten
    (tmp_path / "ext" / "old.js").write_text("stale")
    managed.record("https://other.example")
    managed.sync()
    assert json.loads(receiver.read_text()) == {"webTarget": "https://other.example"}
    assert not (tmp_path / "ext" / "old.js").exists()


def test_public_url_wins_over_a_recorded_origin(tmp_path):
    managed = ManagedCompanion(
        tmp_path / "ext", origin_file=tmp_path / "o.json", public_url="https://fixed.example"
    )
    managed.record("https://seen.example")
    assert managed.origin() == "https://fixed.example"


def test_without_a_folder_nothing_is_written(tmp_path):
    assert ManagedCompanion(None, origin_file=tmp_path / "o.json").sync() is None


def test_desktop_folder_needs_no_origin(tmp_path):
    info = ManagedCompanion(tmp_path / "companion").sync()
    assert info["version"] == bundled_version()
    assert json.loads((tmp_path / "companion" / "receiver.json").read_text()) == {"webTarget": None}


def test_replies_announce_the_bundled_version(tmp_path):
    from torrentlinker.profile_workspace import ProfileWorkspace

    workspace = ProfileWorkspace(tmp_path)
    workspace._receive = lambda *args: {"accepted": True}  # type: ignore[method-assign]
    reply = workspace.receive("/api/companion/snapshot", "chrome-extension://x", "", {})
    assert reply == {"accepted": True, "companion_version": bundled_version()}


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_extension_reloads_once_per_announced_version():
    script = f"""
import {{ reloadIfNewer }} from {json.dumps(UPDATE.as_uri())};
const store = {{ connection: {{ token: "t" }} }};
let reloads = 0;
globalThis.chrome = {{
  runtime: {{ getManifest: () => ({{ version: "0.7.1" }}), reload: () => reloads++ }},
  storage: {{ local: {{
    get: async (k) => ({{ [k]: store[k] }}),
    set: async (o) => Object.assign(store, o),
  }} }},
}};
const out = [];
for (const v of ["0.7.1", "0.7.0", undefined, "junk", "0.7.2", "0.7.2", "0.10.0", "0.10.0"])
  out.push(await reloadIfNewer(v));
console.log(JSON.stringify({{ out, reloads, store }}));
"""
    done = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    result = json.loads(done.stdout)
    assert result["out"] == [False, False, False, False, True, False, True, False]
    assert result["reloads"] == 2
    assert result["store"]["connection"] == {"token": "t"}  # pairing state is untouched
    assert result["store"]["reloadedFor"] == "0.10.0"
