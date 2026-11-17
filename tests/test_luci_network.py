import shutil
import subprocess
import unittest
from pathlib import Path


VIEW = Path(__file__).resolve().parents[1] / "files/www/luci-static/resources/view/uulink/index.js"


class LuCINetworkTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the LuCI view check")
    def test_network_tab_uses_the_carrier_name_or_a_known_plmn(self):
        script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
function E(tag, attrs, children = []) {
    return { tag, attrs, children: Array.isArray(children) ? children : [children],
        appendChild(child) { this.children.push(child); },
        set textContent(value) { this.children = value ? [value] : []; } };
}
const view = new Function('rpc', 'view', 'poll', 'E', fs.readFileSync(process.argv[1], 'utf8'))(
    { declare() { return () => Promise.resolve(null); } }, { extend: value => value }, { add() {} }, E);
function* elements(node) {
    if (typeof node !== 'object' || node == null) return;
    yield node;
    for (const child of node.children) yield* elements(child);
}
function renderRows(cell) {
    const page = view.render({ schema: 1, statusAgeMs: 400, rates: { ageMs: 400 },
        status: { cell, info: { traffic: { today: 0, used: 1200000000, unitBase: 1000 } } } });
    [...elements(page)].find(node => node.tag === 'button' && node.children[0] === '网络').attrs.click();
    return Object.fromEntries([...elements(page)].filter(node => node.attrs?.class === 'cbi-value')
        .map(node => node.children.map(child => child.children[0])));
}
for (const name of [null, '', '  ', '--', 'unknown']) {
    const rows = renderRows({ operator: { name, plmn: '46000' } });
    assert.equal(rows['运营商'], '中国移动');
    assert.equal(rows['网络标识'], '46000');
}
assert.equal(renderRows({ operator: { name: '固件运营商', plmn: '46000' } })['运营商'], '固件运营商');
assert.equal(renderRows({ operator: { plmn: '46001' } })['运营商'], '中国联通');
assert.equal(renderRows({ operator: { plmn: '46011' } })['运营商'], '中国电信');
assert.equal(renderRows({ operator: { plmn: '46015' } })['运营商'], '中国广电');
const unknown = renderRows({ operator: { plmn: '99999' } });
assert.equal(unknown['运营商'], '—');
assert.equal(unknown['网络标识'], '99999');
assert.equal(renderRows({ error: true, operator: { plmn: '46000' } })['运营商'], '—');
"""
        result = subprocess.run(["node", "-e", script, str(VIEW)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
