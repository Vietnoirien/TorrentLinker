"""The connect page tells an outdated companion apart instead of relaying its misleading error."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")

PAGE = Path(__file__).parents[1] / "src/torrentlinker/web/static/companion-connect.js"


def run_page(payload: dict, replies: dict) -> dict:
    """Run the page with a stub companion answering `replies` by action; return what it shows."""
    script = f"""
const replies = {json.dumps(replies)};
const sent = [];
const element = () => ({{ textContent: "", hidden: true }});
const shownStatus = element(), shownInstall = element();
globalThis.document = {{ getElementById: (id) => (id === "status" ? shownStatus : shownInstall) }};
globalThis.location = {{
  hash: "#" + encodeURIComponent({json.dumps(json.dumps(payload))}),
  protocol: "https:", hostname: "tl.example", pathname: "/companion/connect",
}};
globalThis.history = {{ replaceState() {{}} }};
globalThis.setTimeout = () => {{}};
globalThis.chrome = {{ runtime: {{ sendMessage: async (id, message) => {{
  sent.push(message.action);
  const reply = replies[message.action];
  if (reply === undefined) throw new Error("not installed");
  return reply;
}} }} }};
{PAGE.read_text()}
await new Promise((resolve) => setImmediate(resolve));
await new Promise((resolve) => setImmediate(resolve));
console.log(JSON.stringify(
  {{ status: shownStatus.textContent, install: !shownInstall.hidden, sent }}
));
"""
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


TR4KER = {"target": "https://tl.example", "code": "c" * 48, "tracker": "tr4ker"}
OLD_ERROR = {"error": "Start the connection from TorrentLinker’s Profile tab."}


def test_an_old_companion_is_told_to_update_before_pairing_tr4ker():
    shown = run_page(TR4KER, {"version": OLD_ERROR, "connect": OLD_ERROR})
    assert "too old to pair tr4ker" in shown["status"] and shown["install"]
    assert shown["sent"] == ["version"]  # the pairing code is never sent to it


def test_a_current_companion_pairs_tr4ker():
    shown = run_page(TR4KER, {"version": {"version": "0.7.0"}, "connect": {"connected": True}})
    assert shown["status"].startswith("Connected.") and shown["sent"] == ["version", "connect"]


def test_an_old_companion_still_pairs_c411():
    c411 = {"target": "https://tl.example", "code": "c" * 48, "accountId": "42"}
    shown = run_page(c411, {"version": OLD_ERROR, "connect": {"connected": True}})
    assert shown["status"].startswith("Connected.")
