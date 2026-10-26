"""Web per-piece camera controls serialize owner edits into render requests."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_advanced_camera_controls_keep_all_fields_and_apply_presets():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    source = Path("src/torrentlinker/web/static/app.js").read_text()
    helper = source[
        source.index("function uploadCameraControls(") : source.index("function uploadModelTools(")
    ]
    script = r"""
const assert = require('node:assert/strict');
const say = en => en;
function element(tag, text) {
  return {tag, text, dataset:{}, children:[], listeners:{}, value:'',
    append(...nodes) { this.children.push(...nodes); },
    addEventListener(name, handler) { this.listeners[name] = handler; },
    checkValidity() {
      const value = Number(this.value);
      return Number.isFinite(value) &&
        (this.min === undefined || value >= Number(this.min)) &&
        (this.max === undefined || value <= Number(this.max));
    }};
}
eval(process.argv[1]);
const preset = element('select'), controls = uploadCameraControls(preset);
const inputs = new Map(controls.element.children.filter(n=>n.tag==='label')
  .map(label=>label.children.find(n=>n.tag==='input')).map(input=>[input.dataset.cameraField,input]));
assert.equal(inputs.size, 6);
preset.value='left'; preset.listeners.change();
assert.equal(controls.read().yaw, -90);
const chosen={yaw:731,pitch:123,roll:47,zoom:2.5,center_x:0.35,center_y:-0.4};
for (const [field,value] of Object.entries(chosen)) {
  inputs.get(field).value=String(value); inputs.get(field).listeners.input?.();
}
assert.equal(preset.value,'custom');
assert.deepEqual(controls.read(),chosen);
inputs.get('zoom').value='11';
assert.throws(()=>controls.read(), /Invalid camera value/);
"""
    subprocess.run([node, "-e", script, helper], check=True, capture_output=True, text=True)
