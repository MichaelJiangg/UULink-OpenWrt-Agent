'use strict';

import { chmod, mkdir, readfile, rename, writefile } from 'fs';
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

function sanitize(value) {
    if (type(value) != 'object' || type(value.info) != 'object')
        return null;
    let info = pick(value.info, ['data_device', 'uptime', 'fw']);
    info.power = pick(value.info.power, ['present', 'capacity', 'status', 'ua', 'usb']);
    info.traffic = pick(value.info.traffic, ['today', 'used']);
    info.temps = pick(value.info.temps, ['soc', 'cpu']);
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

function counters(device) {
    if (type(device) != 'string' || match(device, /^[A-Za-z0-9_.:-]{1,32}$/) == null)
        return null;
    let content = readfile('/proc/net/dev');
    if (type(content) != 'string')
        return null;
    for (let line in split(content, '\n')) {
        let halves = split(line, ':', 2);
        if (length(halves) != 2 || ltrim(rtrim(halves[0])) != device)
            continue;
        let values = split(ltrim(rtrim(halves[1])), /[ \t]+/);
        if (length(values) < 16)
            return null;
        let received = int(values[0]);
        let sent = int(values[8]);
        if (!(received >= 0) || !(sent >= 0))
            return null;
        return { received: received, sent: sent };
    }
    return null;
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
let previous = null;

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
            status = cleaned;
            statusAtMs = now;
            statusMonotonicAtMs = monotonicNow;
        }
    }

    if (status != null) {
        let device = status.info.data_device;
        let current = counters(device);
        let observedAtMs = milliseconds();
        let monotonicAtMs = milliseconds(true);
        let rates = {
            downloadBytesPerSecond: null,
            uploadBytesPerSecond: null,
            receivedBytes: null,
            sentBytes: null,
            observedAtMs: observedAtMs,
            monotonicAtMs: monotonicAtMs
        };
        if (current != null) {
            rates.receivedBytes = sprintf('%d', current.received);
            rates.sentBytes = sprintf('%d', current.sent);
            if (previous != null && previous.device == device &&
                current.received >= previous.received && current.sent >= previous.sent &&
                monotonicAtMs > previous.atMs) {
                let windowMs = monotonicAtMs - previous.atMs;
                rates.downloadBytesPerSecond = (current.received - previous.received) * 1000.0 / windowMs;
                rates.uploadBytesPerSecond = (current.sent - previous.sent) * 1000.0 / windowMs;
            }
            previous = { device: device, received: current.received, sent: current.sent, atMs: monotonicAtMs };
        } else {
            previous = null;
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
