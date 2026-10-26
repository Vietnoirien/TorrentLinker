"""Large plans queue in bounded batches without exhausting pending job capacity."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_plan_queue_batches_selected_hashes_and_waits_for_each_client_job():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the web handler test")
    source = Path("src/torrentlinker/web/static/app.js").read_text()
    handler = source.split('$("queue-plan").onclick = ', 1)[1].split('\n$("start-queue")', 1)[0]
    waiter = "async function waitForJob" + source.split("async function waitForJob", 1)[1]
    # Run the actual handler and completion polling, with only transport/UI stubbed.
    script = r"""
const assert = require('node:assert/strict');
const rows = Array.from({length: 21105}, (_, i) => ({
  hash: i.toString(16).padStart(40, '0'), client_id: i < 21001 ? 'home' : 'remote'
}));
const state = {planRows: [...rows, {hash:'unselected', client_id:'home'}],
  planSelected:new Set(rows.map(r=>r.hash)), clientId:'other'};
const calls = [], guard = f => f(), loadQueue = () => {};
const control = {disabled:false}, $ = () => control, say = en => en;
let active = false, read = 0;
const job = async body => {
  assert.equal(active, false, 'previous batch must finish before another is submitted');
  assert(body.hashes.length <= 1000); calls.push(body); active = true; read = 0;
  return String(calls.length);
};
const api = async path => {
  assert.equal(path, 'jobs/' + calls.length);
  if (++read === 1) return {status:'running'};
  active = false; return {status:'completed'};
};
const setTimeout = f => f();
const navigate = async view => {
  assert.equal(view, 'queue'); assert.equal(calls.length, 23); assert.equal(active, false);
};
eval(process.argv[2]);
(async () => {
  const handler = eval('(' + process.argv[1].replace(/;\s*$/, '') + ')');
  await handler();
  assert.equal(control.disabled, false);
  assert.deepEqual(calls.slice(-2).map(c=>[c.client_id,c.hashes.length]),
    [['home',1],['remote',104]]);
  assert.deepEqual(calls.flatMap(c=>c.hashes), rows.map(r=>r.hash));
})().catch(error => { console.error(error); process.exitCode=1; });
"""
    subprocess.run(
        [node, "-e", script, handler, waiter], check=True, capture_output=True, text=True
    )
