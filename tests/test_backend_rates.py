import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAMPLER = ROOT / 'files/usr/libexec/uulink/sampler.uc'
ZWRT_SAMPLER = ROOT / 'u60pro/sampler.uc'
PLUGIN = ROOT / 'files/usr/share/rpcd/ucode/uulink.uc'
UPLOADER_RUNNER = ROOT / 'remote/tests/ucode_compat_runner.js'

PRELUDE = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const readSampler = path => fs.readFileSync(path, 'utf8').replace(/^import .*;\s*$/gm, '')
  .replace(/for \(let (\w+) in /g, 'for (let $1 of ')
  .replace(/\b0([0-7]{3,})\b/g, '0o$1');
const source = readSampler(process.argv[1]);
const type = value => value == null ? null : Array.isArray(value) ? 'array' : typeof value === 'boolean' ? 'bool' :
  typeof value === 'number' ? Number.isInteger(value) ? 'int' : 'double' : typeof value;
const length = value => value == null ? 0 : typeof value === 'string' ? Buffer.byteLength(value) :
  Array.isArray(value) ? value.length : Object.keys(value).length;
const scalarRuntime = {type, length, match: (value, expression) => typeof value === 'string' ? value.match(expression) : null,
  int: Math.trunc};
const backendRates = new Function(...Object.keys(scalarRuntime),
  source.split('mkdir(directory);')[0] + '\nreturn backendRates;')(...Object.values(scalarRuntime));
function shared(overrides = {}) {
  return {schema: 1, data: 'RAW COUNTERS MUST NOT BE USED', rates: {sipa_eth8: {
    available: true, downloadBytesPerSecond: 1234.5, uploadBytesPerSecond: 67.25,
    receivedBytes: '100000000', sentBytes: '20000000',
    monotonicAtMs: 99000, observedAtMs: 1800000000000, windowMs: 1000, ...overrides
  }}};
}
function unknown(value, mono = 100000, wall = 1800000001000) {
  assert.deepEqual(value, {downloadBytesPerSecond: null, uploadBytesPerSecond: null,
    receivedBytes: null, sentBytes: null, observedAtMs: wall, monotonicAtMs: mono});
}
function take(response, device = 'sipa_eth8', wall = 1800000001000, mono = 100000) {
  return backendRates(response, device, wall, mono);
}
function netdev(rx, tx, device = 'sipa_eth8') {
  return {data: 'Inter-| Receive | Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n' +
    ` ${device}: ${rx} 0 0 0 0 0 0 0 ${tx} 0 0 0 0 0 0 0\n`};
}
function thirdParty(rx, tx, ts, overrides = {}) {
  return {available: true, device: 'sipa_eth8', ifindex: 7, boot_id: 'boot-a', ts, rx, tx, ...overrides};
}
function runFrames(sequence) {
  const snapshots = [], calls = [];
  const stop = new Error('synthetic loop complete');
  let iteration = 0;
  const runtime = {...scalarRuntime,
    clock: monotonic => {
      const now = (monotonic ? 100000 : 1800000000000) + sequence[iteration].timeMs;
      return [Math.floor(now / 1000), Math.trunc(now % 1000) * 1000000];
    },
    split: (value, separator, limit) => value.split(separator, limit),
    trim: value => value.trim(), replace: (value, pattern, replacement) => value.replace(pattern, replacement),
    keys: Object.keys,
    mkdir: () => true, chmod: () => true, rename: () => true,
    readfile: () => { throw new Error('sampler must use firmware RPC, not read interface files'); },
    connect: () => ({call: (object, method, args) => {
      calls.push(object + '.' + method); assert.deepEqual(args, {});
      if (object === 'mu300dash' && method === 'status') return sequence[iteration].status ||
        {info: {data_device: 'sipa_eth8', power: {present: true, capacity: 55},
          traffic: {today: 0, used: 0}}};
      if (object === 'mu300dash' && method === 'traffic_get') {
        if (sequence[iteration].traffic_get === undefined) throw new Error('method unavailable');
        return structuredClone(sequence[iteration].traffic_get);
      }
      assert.equal(object, 'mu300rates');
      assert.ok(method === 'netdev' || method === 'rates');
      const reply = sequence[iteration][method];
      if (reply === undefined) throw new Error('method unavailable');
      return structuredClone(reply);
    }}),
    sprintf: (format, value) => {assert.equal(format, '%J'); return JSON.stringify(value);},
    writefile: (path, value) => {snapshots.push(JSON.parse(value)); return Buffer.byteLength(value);},
    sleep: duration => {assert.equal(duration, 1000); if (++iteration === sequence.length) throw stop;}
  };
  try {new Function(...Object.keys(runtime), source)(...Object.values(runtime));}
  catch (error) {assert.equal(error, stop);}
  assert.equal(snapshots.length, sequence.length);
  return {snapshots, calls};
}
function runZwrt(args, overrides = {}) {
  const snapshots = [], calls = [];
  const stop = new Error('synthetic loop complete');
  const replies = {
    'zwrt_mc.device.manager.get_device_info': {
      bat_percent: '0', wa_inner_version: 'B31', device_uptime: '1234', imei: 'must-not-be-cached'
    },
    'zwrt_bsp.charger.list': {charger_connect: '1', charge_status: 0},
    'zwrt_bsp.battery.list': {battery_capacity: '50'},
    'zte_nwinfo_api.nwinfo_get_netinfo': {
      network_type: 18, network_provider: '--', network_provider_fullname: 'CHN-UNICOM',
      nr5g_action_band: 'n41', nr5g_rsrp: '-88', nr5g_rsrq: '-10.5', nr5g_snr: '0',
      lte_rsrp: '-105', imsi: 'must-not-be-cached'
    },
    'zwrt_router.api.router_get_status_no_auth': {current_wan_status: 'ipv4_ipv6_connected'},
    'zwrt_data.get_wwandst': {
      day_rx_bytes: '0', day_tx_bytes: '0', month_rx_bytes: 900, month_tx_bytes: 50,
      real_rx_speed: '12.5', real_tx_speed: '0'
    },
    ...overrides,
  };
  const runtime = {...scalarRuntime,
    global: { ARGV: args },
    clock: monotonic => [monotonic ? 10 : 20, 0],
    trim: value => value.trim(), replace: (value, regex, replacement) => value.replace(regex, replacement),
    uc: value => value.toUpperCase(), lc: value => value.toLowerCase(), index: (array, value) => array.indexOf(value),
    connect: (socket, timeout) => {
      assert.equal(socket, null);
      assert.equal(timeout, 1);
      return {call: (object, method, params) => {
        const name = object + '.' + method;
        calls.push(name);
        assert.ok(Object.hasOwn(replies, name), name);
        assert.deepEqual(params, name === 'zwrt_data.get_wwandst' ? {source_module: 'web', cid: 1, type: 4} : {});
        return replies[name];
      }};
    },
    mkdir: () => assert.notEqual(args[1], '--check-only'), chmod: () => true, rename: () => true,
    sprintf: (_, value) => JSON.stringify(value),
    writefile: (_, value) => {snapshots.push(JSON.parse(value)); return Buffer.byteLength(value);},
    sleep: () => {throw stop;},
    exit: code => {throw {code};},
  };
  let code;
  try {new Function(...Object.keys(runtime), readSampler(process.argv[4]))(...Object.values(runtime));}
  catch (error) {
    if (error !== stop) {
      if (!Number.isInteger(error.code)) throw error;
      code = error.code;
    }
  }
  return {snapshots, calls, code};
}
'''


@unittest.skipUnless(shutil.which('node'), 'Node is required for the sampler source checks')
class BackendRatesTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ucode'), 'Native ucode is needed to check numeric behavior')
    def test_native_rates_keep_fractional_speed_and_exact_second_boundaries(self):
        source = SAMPLER.read_text()
        helpers = source[source.index('function rateNumber('):source.index('\nmkdir(directory);')]
        script = helpers + r'''
let first = {available: true, device: 'sipa_eth0', ifindex: 7, boot_id: 'same-boot',
    ts: 730.33, rx: 2363253, tx: 3585787};
let second = { ...first, ts: 732.34, rx: 2363357, tx: 3585919 };
legacyRates(thirdPartySample(first, null, 100000), 1800000000000, 100000);
let rates = legacyRates(thirdPartySample(second, null, 102010), 1800000002010, 102010);
if (rates.downloadBytesPerSecond < 51.74 || rates.downloadBytesPerSecond > 51.75 ||
    rates.uploadBytesPerSecond < 65.67 || rates.uploadBytesPerSecond > 65.68)
    die('fractional B/s did not survive native ucode');
previousLegacyRate = null;
first.ts = 1.001; second.ts = 2.001; second.rx = first.rx + 100; second.tx = first.tx;
legacyRates(thirdPartySample(first, null, 100000), 1800000000000, 100000);
let boundary = legacyRates(thirdPartySample(second, null, 101000), 1800000001000, 101000);
if (boundary.downloadBytesPerSecond != 100 || boundary.uploadBytesPerSecond != 0)
    die('exact one-second sample dropped by timestamp conversion');
'''
        result = subprocess.run(['ucode', '-'], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def run_script(self, body):
        result = subprocess.run(['node', '-e', PRELUDE + body, str(SAMPLER), str(PLUGIN),
                                 str(UPLOADER_RUNNER), str(ZWRT_SAMPLER)],
                                capture_output=True, text=True, check=False, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_row_passes_original_values_and_times_to_multiple_consumers(self):
        self.run_script(r'''
const response = shared({receivedBytes: '18446744073709551615', sentBytes: '0'});
const expected = {downloadBytesPerSecond: 1234.5, uploadBytesPerSecond: 67.25,
  receivedBytes: '18446744073709551615', sentBytes: '0',
  observedAtMs: 1800000000000, monotonicAtMs: 99000};
assert.deepEqual(take(response), expected);
assert.deepEqual(take(response, 'sipa_eth8', 1800000001100, 100100), expected);
response.rates.sipa_eth8.receivedBytes = '1';
response.rates.sipa_eth8.sentBytes = '18446744073709551615';
assert.equal(take(response).downloadBytesPerSecond, 1234.5);
assert.equal(take(response).uploadBytesPerSecond, 67.25);
''')

    def test_valid_zero_and_interface_selection_use_only_the_selected_row(self):
        self.run_script(r'''
const response = shared({downloadBytesPerSecond: 0, uploadBytesPerSecond: 0});
response.rates.sipa_eth0 = {...response.rates.sipa_eth8, downloadBytesPerSecond: 800};
assert.equal(take(response).downloadBytesPerSecond, 0);
assert.equal(take(response).uploadBytesPerSecond, 0);
for (const device of [null, undefined, ''])
  assert.equal(backendRates(response, device, 1800000001000, 100000).downloadBytesPerSecond, 800);
for (const device of ['missing0', '../sipa_eth0', 1, 0, false, {}]) unknown(take(response, device));
''')

    def test_shared_extension_parser_rejects_legacy_and_unavailable_frames(self):
        self.run_script(r'''
for (const response of [null, {}, {data: 'sipa_eth8: 1000000 0 0 0 0 0 0 0 900000 0 0 0 0 0 0 0'},
  {schema: true, rates: shared().rates}, {schema: 2, rates: shared().rates},
  {schema: 1, rates: []}, {schema: 1, rates: {}}, shared({available: false}),
  shared({available: 1}), shared({available: 'true'}),
  shared({available: false, downloadBytesPerSecond: null, uploadBytesPerSecond: null,
    monotonicAtMs: null, observedAtMs: null, windowMs: null})]) unknown(take(response));
''')

    def test_invalid_rates_clear_the_entire_numeric_pair(self):
        self.run_script(r'''
for (const key of ['downloadBytesPerSecond','uploadBytesPerSecond']) {
  for (const invalid of [null, true, -1, '1', NaN, Infinity, 1000000000001])
    unknown(take(shared({[key]: invalid})));
}
''')

    def test_invalid_future_or_expired_clocks_cannot_reage_numeric_values(self):
        self.run_script(r'''
for (const row of [{monotonicAtMs: 89999}, {monotonicAtMs: 100001}, {monotonicAtMs: -1},
  {monotonicAtMs: null}, {monotonicAtMs: 99000.5}, {monotonicAtMs: '99000'},
  {observedAtMs: -1}, {observedAtMs: null}, {observedAtMs: Infinity}, {observedAtMs: 1800000001001},
  {windowMs: null}, {windowMs: 0}, {windowMs: 999}, {windowMs: 10001}, {windowMs: '1000'}])
  unknown(take(shared(row)));
assert.equal(take(shared({monotonicAtMs: 90000, windowMs: 10000})).monotonicAtMs, 90000);
unknown(take(shared(), 'sipa_eth8', 1800000002000, 110000), 110000, 1800000002000);
''')

    def test_invalid_or_oversized_counter_strings_never_become_calculated_speed(self):
        self.run_script(r'''
for (const key of ['receivedBytes','sentBytes']) {
  for (const invalid of [null, 0, true, '-1', '01', '1.5', '18446744073709551616'])
    unknown(take(shared({[key]: invalid})));
}
unknown(take(shared({available: false, receivedBytes: '18446744073709551615', sentBytes: '0'})));
''')

    def test_sampler_loop_prefers_shared_backend_without_reading_interface_files(self):
        self.run_script(r'''
for (const producerFails of [false, true]) {
  let iteration = 0; const frames = []; const calls = [];
  const stop = new Error('synthetic loop complete');
  const runtime = {...scalarRuntime,
    clock: monotonic => [monotonic ? 100 + iteration : 1800000001 + iteration, 0],
    mkdir: () => true, chmod: () => true, rename: () => true,
    readfile: () => { throw new Error('independent interface read is forbidden'); },
    connect: () => ({call: (object, method, args) => {
      calls.push(object + '.' + method); assert.deepEqual(args, {});
      if (object === 'mu300dash') return {info: {data_device: 'sipa_eth8',
        power: {present: true, capacity: 55}, traffic: {today: 0, used: 0}}};
      assert.equal(object, 'mu300rates');
      if (method === 'netdev') {
        if (producerFails) throw new Error('synthetic producer unavailable');
        return shared();
      }
      assert.equal(method, 'rates');
      throw new Error('synthetic fallback unavailable');
    }}),
    sprintf: (format, value) => {assert.equal(format, '%J'); return JSON.stringify(value);},
    writefile: (path, value) => {frames.push(JSON.parse(value)); return Buffer.byteLength(value);},
    sleep: duration => {assert.equal(duration, 1000); if (++iteration === 2) throw stop;}
  };
  try {new Function(...Object.keys(runtime), source)(...Object.values(runtime));}
  catch (error) {assert.equal(error, stop);}
  assert.deepEqual(calls.slice(0, 2), ['mu300dash.status','mu300rates.netdev']);
  assert.equal(calls.filter(call => call === 'mu300rates.netdev').length, 2);
  if (!producerFails) assert.equal(calls.filter(call => call === 'mu300rates.rates').length, 0);
  assert.equal(frames.length, 2);
  for (const frame of frames) {
    assert.equal(frame.status.info.power.capacity, 55);
    if (producerFails) {assert.equal(frame.rates.downloadBytesPerSecond, null); assert.equal(frame.rates.uploadBytesPerSecond, null);}
    else assert.equal(frame.rates.monotonicAtMs, 99000);
  }
}
''')

    def test_zwrt_projects_active_radio_and_calendar_month_without_identity(self):
        self.run_script(r'''
const result = runZwrt(['zwrt-u60pro']);
assert.deepEqual(result.calls, [
  'zwrt_mc.device.manager.get_device_info', 'zwrt_bsp.charger.list', 'zwrt_bsp.battery.list',
  'zte_nwinfo_api.nwinfo_get_netinfo', 'zwrt_router.api.router_get_status_no_auth', 'zwrt_data.get_wwandst'
]);
assert.equal(result.snapshots.length, 1);
const frame = result.snapshots[0];
assert.equal(frame.status.source, 'zwrt-u60pro');
assert.equal(frame.status.info.fw, 'B31');
assert.equal(frame.status.info.uptime, 1234);
assert.deepEqual(frame.status.info.power, {present: true, capacity: 0, status: 'Unknown'});
assert.deepEqual(frame.status.info.traffic, {today: 0, calendarMonth: 950, unitBase: 1024});
assert.deepEqual(frame.status.cell, {networkType: '5G NSA', operator: {name: 'CHN-UNICOM'},
  sig: {rsrp: -88, rsrq: -10.5, sinr: 0}, connected: true, band: 'n41'});
assert.deepEqual(frame.rates, {downloadBytesPerSecond: 12.5, uploadBytesPerSecond: 0,
  receivedBytes: null, sentBytes: null, observedAtMs: 20000, monotonicAtMs: 10000});
assert.ok(!JSON.stringify(frame).includes('must-not-be-cached'));

const lte = runZwrt(['zwrt-u60pro'], {
  'zwrt_bsp.charger.list': {charger_connect: 0, charge_status: 0},
  'zte_nwinfo_api.nwinfo_get_netinfo': {network_type: 13, wan_active_band: 'B3', lte_rsrp: '-105',
    lte_rsrq: 'unavailable', lte_snr: 0, nr5g_action_band: 41, nr5g_rsrp: -88},
  'zwrt_router.api.router_get_status_no_auth': {current_wan_status: 0},
  'zwrt_data.get_wwandst': {month_tx_bytes: 50, real_rx_speed: false, real_tx_speed: 'invalid'},
}).snapshots[0];
assert.equal(lte.status.info.power.status, 'Discharging');
assert.deepEqual(lte.status.info.traffic, {today: null, calendarMonth: null, unitBase: 1024});
assert.deepEqual(lte.status.cell, {networkType: '4G', operator: {name: null},
  sig: {rsrp: -105, rsrq: null, sinr: 0}, connected: false, band: 'B3'});
assert.equal(lte.rates.downloadBytesPerSecond, null);
assert.equal(lte.rates.uploadBytesPerSecond, null);
''')

    def test_zwrt_preflight_requires_basic_fields_and_does_not_write(self):
        self.run_script(r'''
const check = ['zwrt-u60pro', '--check-only'];
const valid = runZwrt(check);
assert.equal(valid.code, 0);
assert.deepEqual(valid.snapshots, []);
for (const unusable of [
  {'zwrt_mc.device.manager.get_device_info': {}},
  {'zwrt_mc.device.manager.get_device_info': {bat_percent: 10}},
  {'zte_nwinfo_api.nwinfo_get_netinfo': {network_type: 'unknown'}},
  {'zwrt_data.get_wwandst': {day_rx_bytes: 10}},
]) {
  const result = runZwrt(check, unusable);
  assert.equal(result.code, 1);
  assert.deepEqual(result.snapshots, []);
}
''')

    def test_traffic_get_only_fills_missing_official_fields_and_keeps_zero(self):
        self.run_script(r'''
const status = (ts, traffic) => ({info: {ts, data_device: 'sipa_eth8',
  power: {present: true, capacity: 55}, traffic}});
const detail = (now, rx, tx, cycle) => ({available: true, clock: true, now,
  today: {date: new Date(now * 1000).toISOString().slice(0, 10), rx, tx}, cycle: {used: cycle}});
const {snapshots, calls} = runFrames([
  {timeMs: 0, status: status(1800000000, {}), traffic_get: detail(1800000000, 100, 23, 456)},
  {timeMs: 6000, status: status(1800000006, {today: 0}), traffic_get: detail(1800000006, 900, 99, 321)},
  {timeMs: 12000, status: status(1800000012, {today: 0, used: 0}), traffic_get: detail(1800000012, 900, 99, 999)},
  {timeMs: 18000, status: status(1800000018, {today: 90}), traffic_get: {config: {}, status: {
    available: true, clock_ok: true, updated_at: 1800000018, cycle_used: 999}}},
  {timeMs: 24000, status: status(1800000024, {}), traffic_get: detail(1800000100, 100, 11, 222)},
  {timeMs: 30000, status: status(1800000030, {}), traffic_get: detail(1800000030,
    Number.MAX_SAFE_INTEGER, 1, 42)}
]);
assert.deepEqual(snapshots.map(frame => frame.status.info.traffic), [
  {today: 123, used: 456, unitBase: 1024},
  {today: 0, used: 321, unitBase: 1024},
  {today: 0, used: 0, unitBase: 1024},
  {today: 90, unitBase: 1024},
  {},
  {used: 42, unitBase: 1024}
]);
assert.equal(calls.filter(call => call === 'mu300dash.traffic_get').length, 5);
''')

    def test_traffic_get_third_party_freshness_and_failures_leave_unknown(self):
        self.run_script(r'''
const status = (ts, traffic) => ({info: {ts, data_device: 'sipa_eth8',
  power: {present: true, capacity: 55}, traffic}});
const detail = (updated, today, cycle) => ({config: {}, status: {
  available: true, clock_ok: true, updated_at: updated,
  today_used: today, cycle_used: cycle}});
const {snapshots, calls} = runFrames([
  {timeMs: 0, status: status(1800000000, {
    today_used: 0, clock_ok: true, updated_at: 1799999995
  }), traffic_get: detail(1799999995, 888, 789)},
  {timeMs: 6000, status: status(1800000006, {
    today_used: 90, cycle_used: 91, clock_ok: true, updated_at: 1799999970
  }), traffic_get: detail(1799999990, 12, 34)},
  {timeMs: 12000, status: status(1800000012, {}), traffic_get: detail(1799999970, 100, 200)},
  {timeMs: 18000, status: status(1800000018, {})},
  {timeMs: 24000, status: status(1800000024, {}), traffic_get: {
    error: 'unavailable', ...detail(1800000024, 111, 222)
  }}
]);
assert.deepEqual(snapshots.map(frame => frame.status.info.traffic), [
  {today: 0, used: 789, unitBase: 1000},
  {today: 12, used: 34, unitBase: 1000},
  {}, {}, {}
]);
assert.equal(calls.filter(call => call === 'mu300dash.traffic_get').length, 5);
''')

    def test_third_party_unavailable_summary_does_not_publish_cached_traffic(self):
        self.run_script(r'''
const start = 1800000000;
const summary = (seconds, fields) => ({info: {ts: start + seconds,
  power: {present: false}, traffic: {clock_ok: true, updated_at: start + seconds,
    today_used: 0, cycle_used: 0, ...fields}}});
const detail = (seconds, available) => ({config: {}, status: {available,
  clock_ok: true, updated_at: start + seconds, today_used: 42, cycle_used: 123}});
const {snapshots, calls} = runFrames([
  {timeMs: 0, status: summary(0, {})},
  {timeMs: 6000, status: summary(6, {available: false, today_used: 129, cycle_used: 4096}),
    traffic_get: detail(6, false)},
  {timeMs: 12000, status: summary(12, {available: 0, today_used: 129, cycle_used: 4096}),
    traffic_get: detail(12, true)},
  {timeMs: 18000, status: summary(18, {available: true})}
]);
assert.deepEqual(snapshots.map(frame => frame.status.info.traffic), [
  {today: 0, used: 0, unitBase: 1000}, {}, {today: 42, used: 123, unitBase: 1000},
  {today: 0, used: 0, unitBase: 1000}
]);
assert.equal(calls.filter(call => call === 'mu300dash.traffic_get').length, 2);
''')

    def test_official_legacy_netdev_uses_elapsed_monotonic_time_and_keeps_zero(self):
        self.run_script(r'''
const {snapshots, calls} = runFrames([
  {timeMs: 0, netdev: netdev(1000, 2000)},
  {timeMs: 1250, netdev: netdev(2250, 2250)},
  {timeMs: 2250, netdev: netdev(2250, 2250)}
]);
assert.equal(snapshots[0].rates.downloadBytesPerSecond, null);
assert.equal(snapshots[0].rates.uploadBytesPerSecond, null);
assert.equal(snapshots[1].rates.downloadBytesPerSecond, 1000);
assert.equal(snapshots[1].rates.uploadBytesPerSecond, 200);
assert.equal(snapshots[1].rates.receivedBytes, '2250');
assert.equal(snapshots[1].rates.sentBytes, '2250');
assert.equal(snapshots[1].rates.monotonicAtMs, 101250);
assert.equal(snapshots[2].rates.downloadBytesPerSecond, 0);
assert.equal(snapshots[2].rates.uploadBytesPerSecond, 0);
assert.equal(calls.filter(call => call === 'mu300rates.rates').length, 0);
''')

    def test_third_party_raw_rates_require_matching_boot_interface_and_index(self):
        self.run_script(r'''
const {snapshots, calls} = runFrames([
  {timeMs: 0, rates: thirdParty(1000, 2000, 100)},
  {timeMs: 1250, rates: thirdParty(2250, 2250, 101.25)},
  {timeMs: 2250, rates: thirdParty(3250, 2450, 102.25, {boot_id: 'boot-b'})},
  {timeMs: 3250, rates: thirdParty(4250, 2650, 103.25, {boot_id: 'boot-b'})},
  {timeMs: 4250, rates: thirdParty(5250, 2850, 104.25, {boot_id: 'boot-b', ifindex: 8})},
  {timeMs: 5250, rates: thirdParty(6250, 3050, 105.25, {boot_id: 'boot-b', ifindex: 8})},
  {timeMs: 6250, rates: thirdParty(7250, 3250, 106.25, {boot_id: 'boot-b', ifindex: 8, device: 'sipa_eth9'})}
]);
assert.equal(snapshots[0].rates.downloadBytesPerSecond, null);
assert.equal(snapshots[1].rates.downloadBytesPerSecond, 1000);
assert.equal(snapshots[1].rates.uploadBytesPerSecond, 200);
assert.equal(snapshots[1].rates.monotonicAtMs, 101250);
for (const index of [2, 4, 6]) {
  assert.equal(snapshots[index].rates.downloadBytesPerSecond, null);
  assert.equal(snapshots[index].rates.uploadBytesPerSecond, null);
}
for (const index of [3, 5]) assert.equal(snapshots[index].rates.downloadBytesPerSecond, 1000);
assert.equal(calls.filter(call => call === 'mu300rates.rates').length, snapshots.length);
''')

    def test_third_party_uptime_includes_suspend_but_output_uses_sampler_clock(self):
        self.run_script(r'''
const {snapshots} = runFrames([
  {timeMs: 0, rates: thirdParty(1000, 2000, 3600)},
  {timeMs: 1250, rates: thirdParty(2250, 2250, 3601.25)},
  {timeMs: 2250, rates: thirdParty(3250, 2450, 7200.25)},
  {timeMs: 3250, rates: thirdParty(4250, 2650, 7201.25)},
  {timeMs: 4250, rates: thirdParty(4250, 2650, 7202.25)}
]);
assert.equal(snapshots[0].rates.downloadBytesPerSecond, null);
assert.equal(snapshots[1].rates.downloadBytesPerSecond, 1000);
assert.equal(snapshots[1].rates.uploadBytesPerSecond, 200);
assert.equal(snapshots[1].rates.monotonicAtMs, 101250);
assert.equal(snapshots[1].rates.observedAtMs, 1800000001250);
assert.equal(snapshots[2].rates.downloadBytesPerSecond, null);
assert.equal(snapshots[3].rates.downloadBytesPerSecond, 1000);
assert.equal(snapshots[4].rates.downloadBytesPerSecond, 0);
assert.equal(snapshots[4].rates.uploadBytesPerSecond, 0);
''')

    def test_third_party_sampler_gap_resets_baseline_even_if_source_delta_is_short(self):
        self.run_script(r'''
const {snapshots} = runFrames([
  {timeMs: 0, rates: thirdParty(1000, 2000, 3600)},
  {timeMs: 1000, rates: thirdParty(2000, 2200, 3601)},
  {timeMs: 12000, rates: thirdParty(3000, 2400, 3602)},
  {timeMs: 13000, rates: thirdParty(4000, 2600, 3603)}
]);
assert.equal(snapshots[1].rates.downloadBytesPerSecond, 1000);
assert.equal(snapshots[2].rates.downloadBytesPerSecond, null);
assert.equal(snapshots[3].rates.downloadBytesPerSecond, 1000);
assert.equal(snapshots[3].rates.monotonicAtMs, 113000);
''')

    def test_third_party_sample_selects_reported_interface_when_status_omits_it(self):
        self.run_script(r'''
const status = {info: {power: {present: true, capacity: 55}}};
const rows = [
  {timeMs: 0, rates: thirdParty(1000, 2000, 100)},
  {timeMs: 1000, rates: thirdParty(2000, 2200, 101)},
  {timeMs: 12000, rates: thirdParty(2000, 2200, 101)},
  {timeMs: 13000, rates: thirdParty(3000, 2400, 113)},
  {timeMs: 14000, rates: thirdParty(4000, 2600, 114)}
].map(row => ({...row, status}));
const {snapshots} = runFrames(rows);
assert.equal(snapshots[0].rates.downloadBytesPerSecond, null);
assert.equal(snapshots[1].rates.downloadBytesPerSecond, 1000);
assert.equal(snapshots[1].rates.uploadBytesPerSecond, 200);
for (const index of [2, 3]) assert.equal(snapshots[index].rates.downloadBytesPerSecond, null);
assert.equal(snapshots[4].rates.downloadBytesPerSecond, 1000);
''')

    def test_legacy_counter_reset_long_gap_and_invalid_sample_clear_rate(self):
        self.run_script(r'''
const {snapshots} = runFrames([
  {timeMs: 0, netdev: netdev(1000, 2000)},
  {timeMs: 1000, netdev: netdev(500, 2200)},
  {timeMs: 2000, netdev: netdev(1500, 2400)},
  {timeMs: 13001, netdev: netdev(5000, 3000)},
  {timeMs: 14001, netdev: netdev(6000, 3200)},
  {timeMs: 15001, netdev: netdev('not-a-counter', 3400)},
  {timeMs: 16001, netdev: netdev(7000, 3600)},
  {timeMs: 17001, netdev: netdev(8000, 3800)}
]);
for (const index of [0, 1, 3, 5, 6]) {
  assert.equal(snapshots[index].rates.downloadBytesPerSecond, null);
  assert.equal(snapshots[index].rates.uploadBytesPerSecond, null);
}
for (const index of [2, 4, 7]) {
  assert.equal(snapshots[index].rates.downloadBytesPerSecond, 1000);
  assert.equal(snapshots[index].rates.uploadBytesPerSecond, 200);
}
''')

    def test_shared_extension_preempts_raw_counter_sources_even_when_unavailable(self):
        self.run_script(r'''
const at = timeMs => ({schema: 1, ...netdev(1000 + timeMs, 2000 + timeMs), rates: {sipa_eth8: {
  available: true, downloadBytesPerSecond: 1234.5, uploadBytesPerSecond: 67.25,
  receivedBytes: '100000000', sentBytes: '20000000',
  monotonicAtMs: 100000 + timeMs, observedAtMs: 1800000000000 + timeMs, windowMs: 1000
}}});
const unavailable = at(1000);
unavailable.rates.sipa_eth8.available = false;
const {snapshots, calls} = runFrames([
  {timeMs: 0, netdev: at(0), rates: thirdParty(1000, 2000, 100)},
  {timeMs: 1000, netdev: unavailable, rates: thirdParty(5000, 6000, 101)}
]);
assert.equal(snapshots[0].rates.downloadBytesPerSecond, 1234.5);
assert.equal(snapshots[0].rates.uploadBytesPerSecond, 67.25);
assert.equal(snapshots[1].rates.downloadBytesPerSecond, null);
assert.equal(snapshots[1].rates.uploadBytesPerSecond, null);
assert.equal(calls.filter(call => call === 'mu300rates.rates').length, 0);
''')

    def test_sampler_reads_counters_only_through_firmware_rpc(self):
        source = SAMPLER.read_text()
        for forbidden in ['readfile(', "'/sys/class/net/", "'/proc/net/dev'"]:
            self.assertNotIn(forbidden, source)
        self.assertIn("bus.call('mu300rates', 'netdev', {})", source)
        self.assertIn('const statusIntervalMs = 5000;', source)
        self.assertIn('sleep(1000);', source)

    def test_unknown_rate_frames_keep_snapshot_battery_and_existing_uploader_usable(self):
        self.run_script(r'''
const pluginSource = fs.readFileSync(process.argv[2], 'utf8').replace(/^import .*;\s*$/gm, '')
  .replace(/for \(let (\w+) in /g, 'for (let $1 of ');
const uploader = require(process.argv[3]).definitions();
for (const [response, expectedRate] of [[shared(), 1234.5], [shared({monotonicAtMs: 85000}), null],
                                     [{data: 'legacy raw counters'}, null]]) {
  const snapshot = {schema: 1, statusMonotonicAtMs: 98000,
    status: {info: {power: {present: true, capacity: 55}}}, rates: take(response)};
  const runtime = {...scalarRuntime, readfile: () => JSON.stringify(snapshot), json: JSON.parse,
    clock: () => [100, 0], connect: () => null, push: (array, value) => array.push(value)};
  const plugin = new Function(...Object.keys(runtime), pluginSource)(...Object.values(runtime));
  const parsed = plugin.uulink.snapshot.call();
  assert.equal(parsed.schema, 1);
  assert.equal(parsed.status.info.power.capacity, 55);
  assert.equal(parsed.statusAgeMs, 2000);
  assert.equal(parsed.rates.downloadBytesPerSecond, expectedRate);
  assert.equal(parsed.rates.ageMs, expectedRate == null ? 0 : 1000);
  const remote = uploader.project(snapshot, 100000);
  assert.equal(remote.data.batteryPercent, 55);
  assert.equal(remote.data.downloadBytesPerSecond, expectedRate);
  assert.equal(remote.ratesAgeMs, expectedRate == null ? 0 : 1000);
}
''')

    def test_native_function_dependencies_are_declared_before_callers(self):
        source = SAMPLER.read_text()
        functions = list(re.finditer(r'^function (\w+)\(', source, re.MULTILINE))
        positions = {f.group(1): f.start() for f in functions}
        call = re.compile(r'(?<![.\w])(' + '|'.join(positions) + r')\s*\(')
        for index, function in enumerate(functions):
            end = functions[index + 1].start() if index + 1 < len(functions) else source.index('mkdir(directory);')
            body = source[function.end():end].split('{', 1)[1]
            for dependency in call.finditer(body):
                self.assertLessEqual(positions[dependency.group(1)], function.start())


if __name__ == '__main__':
    unittest.main()
