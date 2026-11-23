"""The companion's tr4ker reader, run under Node with a fake tab (no network, no browser).

It checks what stays in the tab: only allowlisted GETs, redirects refused, the account
re-checked, and `/api/me` filtered before anything is returned.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_tr4ker_companion import ME, SECRETS, STATS

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
MODULE = Path(__file__).parent.parent / "src/torrentlinker/companion_extension/tr4ker.js"

DRIVER = """
import { collectTr4ker } from %(module)s;
const input = JSON.parse(process.env.INPUT);
const seen = [];
globalThis.location = { origin: input.origin || "https://tr4ker.net" };
globalThis.fetch = async (path, init) => {
  seen.push({ path, init });
  if (input.redirect) throw new TypeError("redirect");
  let body = input.routes[path];
  if (typeof body === "function") body = body();
  if (path === "/api/me" && input.second && seen.filter((s) => s.path === path).length > 1)
    body = input.second;
  if (body === undefined)
    return { ok: false, status: 404, headers: new Map(), json: async () => ({}) };
  return {
    ok: true, status: 200,
    headers: { get: () => "application/json" },
    json: async () => structuredClone(body),
  };
};
let out;
try { out = { ok: await collectTr4ker(input.options) }; }
catch (error) { out = { error: error.message }; }
console.log(JSON.stringify({ out, seen: seen.map((s) => [s.path, s.init]) }));
"""


def run(routes, options=None, **extra):
    script = DRIVER % {"module": json.dumps(MODULE.as_uri())}
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        env={
            "INPUT": json.dumps({"routes": routes, "options": options or {}, **extra}),
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(result.stdout)


ROUTES = {
    "/api/me": ME,
    "/api/me/stats": STATS,
    "/api/shop": {
        "items": [{"id": 1, "name": "+25 GB", "description": "d", "price": 400, "bonus_bytes": 1}]
    },
    "/api/me/sw-rewards?limit=50&offset=0": {
        "entries": [
            {
                "id": 3,
                "amount": 12,
                "seeders": 2,
                "created_at": "2026-11-23T10:00:00Z",
                "torrent": {"slug": "abc", "category": {"slug": "films"}},
                "free_text": "x",
            }
        ],
        "total": 1,
    },
}


def test_me_is_filtered_in_the_tab_and_only_allowed_gets_are_made():
    result = run(ROUTES, {"shop": True, "payoutPages": 3})
    blob = json.dumps(result["out"])
    assert not any(secret in blob for secret in SECRETS), blob
    assert "api_key" not in blob and "passkey" not in blob and "totp" not in blob
    assert "recovery" not in blob and "bio" not in blob
    snapshot = result["out"]["ok"]["snapshot"]
    assert snapshot["source"] == "https://tr4ker.net" and snapshot["tracker"] == "tr4ker"
    assert snapshot["account"] == {"id": "7", "username": "demo_t4k"}
    assert snapshot["me"]["money"] == 250 and snapshot["stats"]["summary"]["raw_uploaded"] == 900
    assert snapshot["shop"] == [{"id": "1", "name": "+25 GB", "price": 400, "bonus_bytes": 1}]
    payout = result["out"]["ok"]["payoutPages"][0][0]
    assert payout == {
        "id": "3",
        "amount": 12,
        "seeders": 2,
        "size_bytes": None,
        "seedtime_seconds": None,
        "at": "2026-11-23T10:00:00.000Z",
        "slug": "abc",
        "category": "films",
        "multiplier": None,
    }
    paths = [path for path, _ in result["seen"]]
    assert paths == [
        "/api/me",
        "/api/me/stats",
        "/api/shop",
        "/api/me/sw-rewards?limit=50&offset=0",
        "/api/me",
    ]
    for _, init in result["seen"]:
        assert init["method"] == "GET" and init["redirect"] == "error"
        assert init["credentials"] == "same-origin" and "body" not in init and "headers" not in init
    assert not any("api-key" in path for path in paths)


def test_a_redirect_or_another_origin_stops_the_read():
    assert "error" in run(ROUTES, redirect=True)["out"]
    other = run(ROUTES, origin="https://c411.org")
    assert other["out"]["error"].startswith("Open tr4ker.net") and other["seen"] == []


def test_the_account_is_rechecked_after_the_read():
    result = run(ROUTES, second={**ME, "id": 8})
    assert "Account changed" in result["out"]["error"]


def test_empty_accounts_and_missing_optional_reads_are_normal():
    result = run({"/api/me": {"id": 1, "username": "u"}}, {"shop": True, "payoutPages": 2})
    snapshot = result["out"]["ok"]["snapshot"]
    assert "stats" not in snapshot and "shop" not in snapshot
    assert result["out"]["ok"]["payoutPages"] is None
    empty = run(
        {**ROUTES, "/api/me/sw-rewards?limit=50&offset=0": {"entries": [], "total": 0}},
        {"payoutPages": 2},
    )
    assert empty["out"]["ok"]["payoutPages"] == [[]]


def test_identity_only_reads_nothing_but_the_account():
    result = run(ROUTES, {"identityOnly": True})
    assert result["out"]["ok"] == {"account": {"id": "7", "username": "demo_t4k"}}
    assert [p for p, _ in result["seen"]] == ["/api/me"]


def test_the_extension_has_no_route_to_the_api_key():
    source = MODULE.read_text()
    assert "/api/me/api-key" not in source.replace("Never /api/me/api-key", "")
    manifest = json.loads((MODULE.parent / "manifest.json").read_text())
    assert "https://tr4ker.net/*" in manifest["host_permissions"]
    # tr4ker needs 0.7.0 or later (the connect page checks the same floor).
    assert tuple(map(int, manifest["version"].split("."))) >= (0, 7, 0)
