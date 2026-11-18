import io
import runpy
import shutil
import subprocess
import tarfile
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
    typeof value === 'number' ? (Number.isInteger(value) ? 'int' : 'double') :
    typeof value === 'boolean' ? 'bool' : typeof value;
const length = value => value == null ? 0 : typeof value === 'object' && !Array.isArray(value) ?
    Object.keys(value).length : value.length;
const match = (value, pattern) => value.match(pattern);
const substr = (value, offset, count) => value.substr(offset, count);
let currentStatus;
let currentCode = 0;
let monotonicSeconds = 0;
let diagnosticAvailable = false;
let diagnosticResponse = {};
const readRequests = [];
const stat = path => diagnosticAvailable && path === '/dev/sdiag_nr' ? {type: 'char'} : null;
const popen = command => {
    const slot = command.includes('\\201') ? 0 : 1;
    readRequests.push(slot);
    return { read: () => diagnosticResponse[slot], close: () => {} };
};
const task = (job, reply) => { reply(job({ send: reply })); return true; };
const timer = () => ({ cancel: () => {} });
const bus = { defer: (_object, _method, _args, callback) => {
    callback(currentCode, currentStatus);
    return true;
} };
const plugin = new Function('type', 'length', 'match', 'push', 'connect', 'readfile', 'json', 'clock', 'int',
    'substr', 'stat', 'popen', 'task', 'timer',
    ucodeToJs(fs.readFileSync(process.argv[1], 'utf8')) + '\n')(
        type, length, match, (array, value) => array.push(value), () => bus, () => null,
        JSON.parse, () => [monotonicSeconds, 0], Number.parseInt, substr, stat, popen, task, timer);
function call(name, status, code = 0) {
    currentStatus = status;
    currentCode = code;
    let response;
    let replyCount = 0;
    const immediate = plugin.uulink[name].call({ reply: value => {
        replyCount++;
        response = value;
    } });
    assert.ok(replyCount <= 1, 'One RPC request must produce one reply');
    return response || immediate;
}
const status = {
    info: { temps: { soc: 42.5, cpu: 41, modem: 38.75, board: 0, secret: 'DO_NOT_LEAK' }, wifi: {
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

const validFirst = '012345678901234';
const validSecond = '222222222222222';
const legacy = '333333333333333';
const identity = (info, cell) => call('details', { info, cell }).cell.ident;
assert.deepEqual(identity({modem: {imeis: [validFirst, validSecond]}}, {ident: {imei: legacy}, card: 1}),
    {imei1: validFirst, imei2: validSecond, imei: legacy, slot: 1});
assert.deepEqual(identity({modem: {imeis: [null, validSecond]}}, {error: true}), {imei2: validSecond});
assert.deepEqual(identity({modem: {imeis: ['000000000000000', null]}}, {card: 1, ident: {imei: legacy}}),
    {imei2: legacy, imei: legacy, slot: 1});
assert.deepEqual(identity({}, {ident: {imei1: validFirst, imei2: '000000000000000', imei: legacy, slot: 1}}),
    {imei1: validFirst, imei2: legacy, imei: legacy, slot: 1});
assert.deepEqual(identity({}, {card: 1, ident: {imei: legacy}}), {imei2: legacy, imei: legacy, slot: 1});
assert.deepEqual(identity({modem: {imeis: [null, null]}}, {card: '1', ident: {imei: legacy, slot: 0}}),
    {imei2: legacy, imei: legacy, slot: 1});
assert.deepEqual(identity({}, {card: false, ident: {imei: legacy, slot: 2}}), {imei1: legacy, imei: legacy});
assert.deepEqual(identity({}, {ident: {imei: legacy}}), {imei1: legacy, imei: legacy});
const privateStatus = {info: {modem: {imeis: [validFirst, validSecond], identity: 'DO_NOT_LEAK'}}, cell: {ident: {imei: legacy}}};
assert.equal(JSON.stringify(call('clients', privateStatus)).includes(validFirst), false);

const encode = imei => ('a' + imei).match(/../g).map(pair => pair[1] + pair[0]).join('');
const frame = (sequence, imei) => '7e' + sequence + '00000074005e01' + encode(imei) + '00'.repeat(16) + '7e';
diagnosticAvailable = true;
diagnosticResponse = {0: frame('12', validFirst), 1: frame('12', validSecond)};
assert.deepEqual(identity(privateStatus.info, privateStatus.cell),
    {imei1: validFirst, imei2: validSecond, imei: legacy});
assert.deepEqual(readRequests, []);
assert.deepEqual(identity({modem: {imeis: ['000000000000000', validSecond]}}, {}),
    {imei2: validSecond});
assert.deepEqual(readRequests, [0]);
diagnosticResponse[0] = frame('11', validFirst);
monotonicSeconds = 59;
assert.deepEqual(identity({modem: {imeis: [null, validSecond]}}, {}), {imei2: validSecond});
assert.deepEqual(readRequests, [0]);
monotonicSeconds = 60;
assert.deepEqual(identity({modem: {imeis: [null, '000000000000000']}}, {}),
    {imei1: validFirst, imei2: validSecond});
assert.deepEqual(readRequests, [0, 0, 1]);
assert.deepEqual(identity({modem: {imeis: [legacy, '000000000000000']}}, {}),
    {imei1: legacy, imei2: validSecond});
assert.deepEqual(readRequests, [0, 0, 1]);
assert.deepEqual(call('details', privateStatus, 1), {schema: 1, available: false});
assert.deepEqual(call('details', {}), {schema: 1, available: false});
assert.deepEqual(readRequests, [0, 0, 1]);

const samplerSource = ucodeToJs(fs.readFileSync(process.argv[2], 'utf8')).split('mkdir(directory);')[0];
const sampler = new Function('type', 'length', 'int', samplerSource + '\nreturn { sanitize };')(
    type, length, Number.parseInt);
const snapshot = sampler.sanitize(status);
assert.equal(JSON.stringify(sampler.sanitize(privateStatus)).includes(validFirst), false);
assert.equal(JSON.stringify(sampler.sanitize(privateStatus)).includes(legacy), false);
assert.deepEqual(sampler.sanitize({ info: { traffic: {
    today: 12544, used: 1200000000, today_used: 99, cycle_used: 99
} } }).info.traffic, { today: 12544, used: 1200000000, unitBase: 1024 });
assert.deepEqual(sampler.sanitize({ info: { ts: 1800000000, traffic: {
    today: { rx: 100, tx: 200 }, today_used: 12544,
    cycle_used: 1200000000, month_used: 999,
    clock_ok: true, updated_at: 1799999995
} } }).info.traffic, { today: 12544, used: 1200000000, unitBase: 1000 });
assert.deepEqual(sampler.sanitize({ info: { ts: 1800000000, traffic: {
    today_used: 0, month_used: 999, clock_ok: true, updated_at: 1799999971
} } }).info.traffic, { today: 0, unitBase: 1000 });
for (const invalid of [
    {clock_ok: false, updated_at: 1799999995},
    {clock_ok: true, updated_at: 1799999970},
    {clock_ok: true, updated_at: 1800000001},
    {clock_ok: true, updated_at: null}
]) assert.deepEqual(sampler.sanitize({info: {ts: 1800000000, traffic: {
    today_used: 12544, cycle_used: 1200000000, ...invalid
}}}).info.traffic, {});
assert.deepEqual(sampler.sanitize({ info: { traffic: {
    today: -1, used: 1.5, today_used: false, cycle_used: 'bad'
} } }).info.traffic, {});
assert.deepEqual(snapshot.info.temps, { soc: 42.5, cpu: 41, modem: 38.75, board: 0 });
assert.deepEqual(sampler.sanitize({ info: { temps: { soc: 45, cpu: 46 } } }).info.temps,
    { soc: 45, cpu: 46 });
assert.deepEqual(sampler.sanitize({ info: {} }).info.temps, {});
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

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the ucode-compatible contract check")
    def test_u60pro_candidate_details_use_only_fresh_local_snapshot(self):
        builder = runpy.run_path(str(ROOT / "build-u60pro-candidate.py"))
        with tarfile.open(fileobj=io.BytesIO(builder["make_bundle"]()), mode="r:gz") as archive:
            member = f"uulink-agent/{PLUGIN.relative_to(ROOT).as_posix()}"
            source = archive.extractfile(member).read()
            self.assertEqual(source, (ROOT / "u60pro/uulink.uc").read_bytes())

        script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(0, 'utf8').replace(/^import .*;\s*$/gm, '')
    .replace(/for \(let (\w+) in /g, 'for (let $1 of ');
const type = value => value == null ? 'null' :
    typeof value === 'number' ? (Number.isInteger(value) ? 'int' : 'double') : typeof value;
const unavailable = { schema: 1, available: false };
const power = { present: true, capacity: 62, status: 'Charging' };
const traffic = { today: 150, calendarMonth: 250, unitBase: 1024 };
const cell = { connected: true, networkType: '5G', sig: { rsrp: -95 } };
const snapshot = {
    schema: 1, statusMonotonicAtMs: 10000, rates: { monotonicAtMs: 10000 },
    status: {
        source: 'zwrt-u60pro', cell,
        info: { uptime: 42, power, traffic, fw: 'example', lan: { list: ['private'] } }
    }
};
let nowMs = 20000;
let reads = 0;
let legacyConnections = 0;
const readfile = path => {
    assert.equal(path, '/tmp/uulink/snapshot.json');
    reads++;
    return JSON.stringify(snapshot);
};
const connect = () => { legacyConnections++; return null; };
const clock = monotonic => {
    assert.equal(monotonic, true);
    return [Math.floor(nowMs / 1000), (nowMs % 1000) * 1000000];
};
const plugin = new Function('type', 'length', 'readfile', 'json', 'connect', 'clock', 'int', source)(
    type, value => value.length, readfile, JSON.parse, connect, clock, Math.trunc).uulink;
assert.equal(plugin.snapshot.call().statusAgeMs, 10000);
assert.deepEqual(plugin.details.call(), {
    schema: 1, available: true, source: 'zwrt-u60pro', info: { lan: {}, uptime: 42, power, traffic }, cell
});
assert.deepEqual(plugin.clients.call(), unavailable);
assert.equal(reads, 2);
nowMs++;
assert.deepEqual(plugin.details.call(), unavailable);
nowMs = 11000;
delete snapshot.status.source;
assert.deepEqual(plugin.details.call(), unavailable);
assert.equal(legacyConnections, 0);
"""
        result = subprocess.run(
            ["node", "-e", script], input=source.decode("utf8"), capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
