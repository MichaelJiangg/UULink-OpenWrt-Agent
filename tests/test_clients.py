import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "files/usr/share/rpcd/ucode/uulink.uc"
SAMPLER = ROOT / "files/usr/libexec/uulink/sampler.uc"


class ClientPrivacyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the ucode-compatible contract check")
    def test_clients_response_and_snapshot_exclude_identity(self):
        script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ucodeToJs = source => source.replace(/^import .*;\s*$/gm, '')
    .replace(/for \(let (\w+) in /g, 'for (let $1 of ');
const type = value => value == null ? 'null' : Array.isArray(value) ? 'array' :
    typeof value === 'number' ? (Number.isInteger(value) ? 'int' : 'double') : typeof value;
const length = value => value == null ? 0 : typeof value === 'object' && !Array.isArray(value) ?
    Object.keys(value).length : value.length;
const match = (value, pattern) => value.match(pattern);
let currentStatus;
let currentCode = 0;
const bus = { defer: (_object, _method, _args, callback) => {
    callback(currentCode, currentStatus);
    return true;
} };
const plugin = new Function('type', 'length', 'match', 'push', 'connect', 'readfile', 'json', 'clock', 'int',
    ucodeToJs(fs.readFileSync(process.argv[1], 'utf8')) + '\n')(
        type, length, match, (array, value) => array.push(value), () => bus, () => null,
        JSON.parse, () => [0, 0], Number.parseInt);
function call(name, status, code = 0) {
    currentStatus = status;
    currentCode = code;
    let response;
    const immediate = plugin.uulink[name].call({ reply: value => { response = value; } });
    return response || immediate;
}
const status = {
    info: { wifi: {
        up: 1, ssid: 'Test Wi-Fi', channel: '36', band: '5g', width: '80 MHz',
        clients_n: 2, psk: 'DO_NOT_LEAK',
        clients: [
            { host: 'Laptop', ip: '192.168.1.2', imei: '123456789012345', password: 'DO_NOT_LEAK' },
            { host: 'Phone', ip: '192.168.1.3' }
        ]
    }, lan: { leases: 4, list: [
        { host: 'Bridge laptop', ip: '192.168.78.20', left: 3600,
          mac: 'aa:bb:cc:dd:ee:ff', password: 'DO_NOT_LEAK' },
        { host: 'Expired', ip: '192.168.78.21', left: 0 },
        { host: 'Phone', ip: '192.168.78.22', left: 60 },
        { host: 'No address', ip: '', left: 60 }
    ]
    } },
    cell: { ident: { imei1: '123456789012345', slot: 0 } }
};
const clients = call('clients', status);
assert.deepEqual(clients, {
    schema: 1, available: true,
    wifi: { clients_n: 2, clients: [
        { host: 'Laptop', ip: '192.168.1.2' },
        { host: 'Phone', ip: '192.168.1.3' }
    ] },
    lan: { list: [
        { ip: '192.168.78.20', host: 'Bridge laptop' },
        { ip: '192.168.78.22', host: 'Phone' }
    ] }
});
assert.equal(JSON.stringify(clients).includes('123456789012345'), false);
assert.equal(JSON.stringify(clients).includes('DO_NOT_LEAK'), false);
assert.equal(JSON.stringify(clients).includes('aa:bb:cc:dd:ee:ff'), false);
assert.deepEqual(call('clients', { info: { wifi: { clients_n: 3 } } }), {
    schema: 1, available: true, wifi: { clients_n: 3, clients: [] }, lan: {}
});
assert.deepEqual(call('clients', { info: { lan: { list: [] } } }).lan, { list: [] });
const manyLeases = call('clients', { info: { lan: { list: Array.from({ length: 260 }, (_, index) => ({
    host: 'x'.repeat(129), ip: `192.0.2.${index % 256}`, left: 1
})) } } });
assert.equal(manyLeases.lan.list.length, 256);
assert.deepEqual(manyLeases.lan.list[0], { ip: '192.0.2.0' });
assert.deepEqual(call('clients', {}, 0), { schema: 1, available: false });
assert.deepEqual(call('clients', status, 1), { schema: 1, available: false });
const details = call('details', status);
assert.equal(details.cell.ident.imei1, '123456789012345');
assert.deepEqual(details.info.wifi, clients.wifi);
assert.deepEqual(details.info.lan, clients.lan);

const samplerSource = ucodeToJs(fs.readFileSync(process.argv[2], 'utf8')).split('mkdir(directory);')[0];
const sampler = new Function('type', 'length', samplerSource + '\nreturn { sanitize };')(type, length);
const snapshot = sampler.sanitize(status);
assert.deepEqual(snapshot.info.wifi, {
    up: 1, ssid: 'Test Wi-Fi', channel: '36', band: '5g', width: '80 MHz', clients_n: 2
});
assert.equal(JSON.stringify(snapshot).includes('123456789012345'), false);
assert.equal(JSON.stringify(snapshot).includes('DO_NOT_LEAK'), false);
assert.equal(JSON.stringify(snapshot).includes('clients\":['), false);
assert.equal(Object.hasOwn(snapshot.info, 'lan'), false);
const oversized = sampler.sanitize({ info: { wifi: {
    up: 3, ssid: 'x'.repeat(129), channel: 'x'.repeat(33),
    band: '5g', width: '80 MHz', clients_n: 5000
} }, cell: {} });
assert.deepEqual(oversized.info.wifi, { band: '5g', width: '80 MHz' });
console.log('CLIENTS_PRIVACY_OK');
"""
        result = subprocess.run(
            ["node", "-e", script, str(PLUGIN), str(SAMPLER)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLIENTS_PRIVACY_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
