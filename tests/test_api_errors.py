"""The Web shell's api() reports a proxy's HTML error page as a readable error, not a JSON parse error."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_an_html_answer_becomes_a_readable_error():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    app = Path("src/torrentlinker/web/static/app.js").read_text()
    api = app[app.index("async function api(") : app.index("const bytes =")]
    script = """
const assert = require('node:assert/strict');
const nodes = new Map();
const $ = id => { if (!nodes.has(id)) nodes.set(id, {hidden:false}); return nodes.get(id); };
const state = {clientId:'default'};
let language = 'en';
const say = (en, fr) => language === 'fr' ? fr : en;
function clearAgentToken() {}
let answer;
const page = status => ({ok:status < 400, status,
  json:async () => JSON.parse('<!DOCTYPE html><title>' + status + '</title>')});
const json = (status, value) => ({ok:status < 400, status, json:async () => value});
async function fetch() { return answer; }
eval(process.argv[1] + `
(async () => {
  answer = page(502);
  await assert.rejects(api('torrents'), {message:'The server did not answer (HTTP 502). Try again in a moment.'});
  answer = page(200);
  await assert.rejects(api('torrents'), /HTTP 200/);
  language = 'fr'; answer = page(504);
  await assert.rejects(api('torrents'), error => error.message.startsWith('Le serveur n’a pas répondu (HTTP 504)'));
  language = 'en'; answer = json(409, {detail:'Busy', action:'retry'});
  await assert.rejects(api('torrents'), error => error.message === 'Busy' && error.action === 'retry');
  answer = json(401, {detail:'Sign in'});
  await assert.rejects(api('torrents'), /Sign in/);
  assert.equal($('workspace').hidden, true);
  answer = json(200, {rows:[]});
  assert.deepEqual(await api('torrents'), {rows:[]});
})().catch(error => { console.error(error); process.exitCode = 1; });
`);
"""
    subprocess.run([node, "-e", script, api], check=True, timeout=30)
