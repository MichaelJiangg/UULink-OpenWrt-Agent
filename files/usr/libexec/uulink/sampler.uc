'use strict';

import { chmod, mkdir, rename, writefile } from 'fs';
import { connect } from 'ubus';

const directory = '/tmp/uulink';
const snapshotPath = directory + '/snapshot.json';
const temporaryPath = directory + '/snapshot.json.tmp';
const statusIntervalMs = 5000;

function milliseconds(monotonic) {
    let value = clock(monotonic);
    return value[0] * 1000 + int(value[1] / 1000000);
}

function pick(value, fields) {
    let result = {};
    if (type(value) != 'object')
        return result;
    for (let field in fields)
        if (value[field] != null)
            result[field] = value[field];
    return result;
}

function radio(value) {
    let source = type(value) == 'object' ? value : {};
    let result = pick(source, ['ts', 'partial']);
    if (source.error != null)
        result.error = true;
    result.operator = pick(source.operator, ['name', 'plmn', 'act']);
    result.qos = pick(source.qos, ['qci', 'dl', 'ul']);
    result.reg = pick(source.reg, ['stat', 'act']);
    result.reg5g = pick(source.reg5g, ['stat', 'act']);
    result.sig = pick(source.sig, ['rsrp', 'rsrq', 'sinr']);
    result.lte = pick(source.lte, ['band']);
    result.nr = pick(source.nr, ['band']);
    return result;
}

function wifiSummary(value) {
    let source = type(value) == 'object' ? value : {};
    let result = {};
    if (source.up == 0 || source.up == 1)
        result.up = source.up;
    if (type(source.ssid) == 'string' && length(source.ssid) <= 128)
        result.ssid = source.ssid;
    for (let field in ['channel', 'band', 'width']) {
        let item = source[field];
        if (type(item) == 'string' && length(item) <= 32)
            result[field] = item;
    }
    let count = source.clients_n;
    if ((type(count) == 'int' || type(count) == 'double') && count >= 0 && count <= 4096)
        result.clients_n = count;
    return result;
}

function trafficBytes(value) {
    if (type(value) == 'int')
        return value >= 0 ? value : null;
    if (type(value) == 'double' && value >= 0 && value <= 9007199254740991 && int(value) == value)
        return value;
    return null;
}

function trafficFlag(value) {
    return (type(value) == 'bool' && value) || (type(value) == 'int' && value == 1);
}

function trafficSummary(value, statusTime) {
    if (type(value) != 'object')
        return {};
    let today = trafficBytes(value.today);
    let used = trafficBytes(value.used);
    let thirdToday = trafficBytes(value.today_used);
    let thirdUsed = trafficBytes(value.cycle_used);
    let official = today != null || used != null;
    if (!official && thirdToday == null && thirdUsed == null)
        return {};
    if (!official) {
        let now = trafficBytes(statusTime);
        let updated = trafficBytes(value.updated_at);
        if ((value.available != null && !trafficFlag(value.available)) ||
            type(value.clock_ok) != 'bool' || !value.clock_ok ||
            now == null || updated == null || now < updated || now - updated >= 30)
            return {};
    }
    let result = { unitBase: official ? 1024 : 1000 };
    if (official) {
        if (today != null) result.today = today;
        if (used != null) result.used = used;
    } else {
        if (thirdToday != null) result.today = thirdToday;
        if (thirdUsed != null) result.used = thirdUsed;
    }
    return result;
}

function trafficGetSummary(value, statusTime) {
    if (type(value) != 'object' || value.error != null)
        return {};
    let now = trafficBytes(statusTime);
    if (now == null)
        return {};
    let today = null;
    let used = null;
    let unitBase = null;
    if (type(value.config) == 'object' && type(value.status) == 'object') {
        let detail = value.status;
        let updated = trafficBytes(detail.updated_at);
        if (!trafficFlag(detail.available) || !trafficFlag(detail.clock_ok) ||
            updated == null || updated > now || now - updated >= 30)
            return {};
        today = trafficBytes(detail.today_used);
        used = trafficBytes(detail.cycle_used);
        unitBase = 1000;
    } else {
        let detailNow = trafficBytes(value.now);
        if (!trafficFlag(value.available) || !trafficFlag(value.clock) ||
            detailNow == null || detailNow > now + 30 || now > detailNow + 30)
            return {};
        if (type(value.today) == 'object') {
            let rx = trafficBytes(value.today.rx);
            let tx = trafficBytes(value.today.tx);
            if (rx != null && tx != null && rx <= 9007199254740991 &&
                tx <= 9007199254740991 - rx)
                today = rx + tx;
        }
        used = type(value.cycle) == 'object' ? trafficBytes(value.cycle.used) : null;
        unitBase = 1024;
    }
    if (today == null && used == null)
        return {};
    let result = { unitBase: unitBase };
    if (today != null) result.today = today;
    if (used != null) result.used = used;
    return result;
}

function fillMissingTraffic(current, fallback) {
    if (fallback.unitBase == null ||
        (current.unitBase != null && current.unitBase != fallback.unitBase))
        return current;
    if (current.today == null && fallback.today != null) current.today = fallback.today;
    if (current.used == null && fallback.used != null) current.used = fallback.used;
    if (current.today != null || current.used != null)
        current.unitBase = fallback.unitBase;
    return current;
}

function sanitize(value) {
    if (type(value) != 'object' || type(value.info) != 'object')
        return null;
    let info = pick(value.info, ['data_device', 'uptime', 'fw']);
    info.power = pick(value.info.power, ['present', 'capacity', 'status', 'ua', 'usb']);
    info.traffic = trafficSummary(value.info.traffic, value.info.ts);
    info.temps = pick(value.info.temps, ['soc', 'cpu', 'modem', 'board']);
    info.wifi = wifiSummary(value.info.wifi);
    let cell = radio(value.cell);
    cell.ident = pick(type(value.cell) == 'object' ? value.cell.ident : null, ['fw']);
    return {
        info: info,
        cell: cell,
        sig: radio(value.sig),
        cell_age: value.cell_age,
        sig_age: value.sig_age,
        refreshing: value.refreshing
    };
}

function rateNumber(value, lower, upper) {
    return (type(value) == 'int' || type(value) == 'double') && value >= lower && value <= upper ? value : null;
}

function rateTime(value) {
    let parsed = rateNumber(value, 0, 9007199254740991);
    return parsed != null && int(parsed) == parsed ? parsed : null;
}

function rateCounter(value) {
    if (type(value) != 'string' || match(value, /^(0|[1-9][0-9]{0,19})$/) == null ||
        (length(value) == 20 && value > '18446744073709551615'))
        return null;
    return value;
}

function backendRates(response, device, observedNow, monotonicNow) {
    // Current frame times keep an unknown rate from invalidating fresh status/battery.
    // Numeric values are assigned only together with the original backend sample times.
    let rates = {
        downloadBytesPerSecond: null, uploadBytesPerSecond: null,
        receivedBytes: null, sentBytes: null,
        observedAtMs: rateTime(observedNow), monotonicAtMs: rateTime(monotonicNow)
    };
    if (type(response) != 'object' || type(response.schema) != 'int' || response.schema != 1 ||
        type(response.rates) != 'object') return rates;
    if (device == null || (type(device) == 'string' && length(device) == 0)) device = 'sipa_eth0';
    if (type(device) != 'string' || match(device, /^[A-Za-z0-9_.:-]{1,32}$/) == null) return rates;
    let row = response.rates[device];
    if (type(row) != 'object' || type(row.available) != 'bool' || !row.available) return rates;
    let download = rateNumber(row.downloadBytesPerSecond, 0, 1e12);
    let upload = rateNumber(row.uploadBytesPerSecond, 0, 1e12);
    let observed = rateTime(row.observedAtMs);
    let monotonic = rateTime(row.monotonicAtMs);
    let window = rateTime(row.windowMs);
    let received = rateCounter(row.receivedBytes);
    let sent = rateCounter(row.sentBytes);
    if (download == null || upload == null || observed == null || monotonic == null ||
        window == null || window < 1000 || window > 10000 || received == null || sent == null ||
        rates.monotonicAtMs == null || rates.observedAtMs == null ||
        observed > observedNow || monotonic > monotonicNow || monotonicNow - monotonic > 10000) return rates;
    return { downloadBytesPerSecond: download, uploadBytesPerSecond: upload,
        receivedBytes: received, sentBytes: sent, observedAtMs: observed, monotonicAtMs: monotonic };
}

let previousLegacyRate = null;

function rateDevice(value) {
    return type(value) == 'string' && match(value, /^[A-Za-z0-9_.:-]{1,32}$/) != null ? value : null;
}

function safeCounter(value) {
    let text = null;
    if (type(value) == 'string') {
        if (match(value, /^[0-9]{1,20}$/) == null) return null;
        text = replace(value, /^0+/, '');
        if (length(text) == 0) text = '0';
        if (length(text) > 16 || (length(text) == 16 && text > '9007199254740991')) return null;
    } else if ((type(value) == 'int' || type(value) == 'double') &&
               value >= 0 && value <= 9007199254740991 && int(value) == value) {
        text = '' + value;
    } else {
        return null;
    }
    return { value: +text, text: text };
}

function netdevSample(response, requestedDevice, atMs) {
    let device = requestedDevice == null || requestedDevice == '' ? 'sipa_eth0' : rateDevice(requestedDevice);
    if (device == null || type(response) != 'object' || type(response.data) != 'string' ||
        length(response.data) > 262144) return null;
    for (let line in split(response.data, '\n')) {
        let parts = split(line, ':', 2);
        if (length(parts) != 2 || trim(parts[0]) != device) continue;
        let fields = split(trim(parts[1]), /[ \t]+/);
        if (length(fields) < 16) return null;
        let received = safeCounter(fields[0]);
        let sent = safeCounter(fields[8]);
        if (received == null || sent == null) return null;
        return { source: 'netdev', device: device, identity: '', atMs: atMs,
            received: received, sent: sent };
    }
    return null;
}

function thirdPartySample(response, requestedDevice, monotonicNow) {
    if (type(response) != 'object' || type(response.available) != 'bool' || !response.available)
        return null;
    let device = rateDevice(response.device);
    if (device == null || (requestedDevice != null && requestedDevice != '' &&
        device != rateDevice(requestedDevice))) return null;
    let index = rateTime(response.ifindex);
    let seconds = rateNumber(response.ts, 0, 9007199254740);
    let boot = response.boot_id;
    if (index == null || index < 1 || seconds == null ||
        type(boot) != 'string' || match(boot, /^[A-Za-z0-9-]{1,64}$/) == null) return null;
    let sourceAtMs = rateTime(int(seconds * 1000 + 0.5));
    let received = safeCounter(response.rx);
    let sent = safeCounter(response.tx);
    if (sourceAtMs == null || received == null || sent == null) return null;
    return { source: 'rates', device: device, identity: boot + ':' + index,
        atMs: monotonicNow, sourceAtMs: sourceAtMs, received: received, sent: sent };
}

function legacyRates(sample, observedNow, monotonicNow) {
    let unknown = { downloadBytesPerSecond: null, uploadBytesPerSecond: null,
        receivedBytes: null, sentBytes: null,
        observedAtMs: rateTime(observedNow), monotonicAtMs: rateTime(monotonicNow) };
    if (sample == null || sample.atMs > monotonicNow || monotonicNow - sample.atMs > 10000) {
        previousLegacyRate = null;
        return unknown;
    }
    let previous = previousLegacyRate;
    previousLegacyRate = sample;
    if (previous == null || previous.source != sample.source || previous.device != sample.device ||
        previous.identity != sample.identity) return unknown;
    let samplerElapsed = sample.atMs - previous.atMs;
    let elapsed = sample.source == 'rates' ? sample.sourceAtMs - previous.sourceAtMs : samplerElapsed;
    if (samplerElapsed < 1000 || samplerElapsed > 10000 || elapsed < 1000 || elapsed > 10000 ||
        sample.received.value < previous.received.value || sample.sent.value < previous.sent.value)
        return unknown;
    let download = (sample.received.value - previous.received.value) * 1000.0 / elapsed;
    let upload = (sample.sent.value - previous.sent.value) * 1000.0 / elapsed;
    let observed = rateTime(observedNow - (monotonicNow - sample.atMs));
    if (rateNumber(download, 0, 1e12) == null || rateNumber(upload, 0, 1e12) == null ||
        observed == null || observed > observedNow) return unknown;
    return { downloadBytesPerSecond: download, uploadBytesPerSecond: upload,
        receivedBytes: sample.received.text, sentBytes: sample.sent.text,
        observedAtMs: observed, monotonicAtMs: sample.atMs };
}

mkdir(directory);
if (!chmod(directory, 0700))
    die('cache directory unavailable');
let bus = connect();
if (!bus)
    die('ubus unavailable');

let status = null;
let statusAtMs = 0;
let statusMonotonicAtMs = 0;
let lastStatusAttemptMonotonicMs = 0;

while (true) {
    let now = milliseconds();
    let monotonicNow = milliseconds(true);
    if (lastStatusAttemptMonotonicMs == 0 ||
        monotonicNow - lastStatusAttemptMonotonicMs >= statusIntervalMs) {
        let response = null;
        try {
            response = bus.call('mu300dash', 'status', {});
        } catch (error) {
            response = null;
        }
        lastStatusAttemptMonotonicMs = milliseconds(true);
        let cleaned = sanitize(response);
        if (cleaned != null && type(cleaned.info.power) == 'object' && length(cleaned.info.power) > 0) {
            let traffic = cleaned.info.traffic;
            if (traffic.today == null || traffic.used == null) {
                let fallback = null;
                try { fallback = bus.call('mu300dash', 'traffic_get', {}); } catch (error) {}
                cleaned.info.traffic = fillMissingTraffic(traffic,
                    trafficGetSummary(fallback, response.info.ts));
            }
            status = cleaned;
            statusAtMs = now;
            statusMonotonicAtMs = monotonicNow;
        }
    }

    if (status != null) {
        let backend = null;
        try { backend = bus.call('mu300rates', 'netdev', {}); } catch (error) {}
        let observedNow = milliseconds();
        let monotonicNow = milliseconds(true);
        let rates = null;
        if (type(backend) == 'object' && type(backend.schema) == 'int' && backend.schema == 1) {
            previousLegacyRate = null;
            rates = backendRates(backend, status.info.data_device, observedNow, monotonicNow);
        } else {
            let sample = null;
            if (type(backend) == 'object' && type(backend.data) == 'string') {
                sample = netdevSample(backend, status.info.data_device, monotonicNow);
            } else {
                let raw = null;
                try { raw = bus.call('mu300rates', 'rates', {}); } catch (error) {}
                observedNow = milliseconds();
                monotonicNow = milliseconds(true);
                sample = thirdPartySample(raw, status.info.data_device, monotonicNow);
            }
            rates = legacyRates(sample, observedNow, monotonicNow);
        }

        let snapshot = {
            schema: 1,
            sampledAtMs: statusAtMs,
            statusAtMs: statusAtMs,
            statusMonotonicAtMs: statusMonotonicAtMs,
            status: status,
            rates: rates
        };
        let encoded = sprintf('%J', snapshot);
        if (writefile(temporaryPath, encoded) == length(encoded) &&
            chmod(temporaryPath, 0600)) {
            rename(temporaryPath, snapshotPath);
        }
    }
    sleep(1000);
}
