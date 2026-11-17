'use strict';

import { popen, readfile, stat } from 'fs';
import { connect } from 'ubus';
import { task, timer } from 'uloop';

function cachedSnapshot() {
    let raw = readfile('/tmp/uulink/snapshot.json');
    if (type(raw) != 'string' || length(raw) > 16384)
        return { schema: 1, available: false };
    try {
        let value = json(raw);
        if (type(value) == 'object' && value.schema == 1) {
            let clockValue = clock(true);
            if (clockValue == null || type(value.status) != 'object' ||
                type(value.rates) != 'object' ||
                (type(value.statusMonotonicAtMs) != 'int' && type(value.statusMonotonicAtMs) != 'double') ||
                (type(value.rates.monotonicAtMs) != 'int' && type(value.rates.monotonicAtMs) != 'double'))
                return { schema: 1, available: false };
            let nowMs = clockValue[0] * 1000 + int(clockValue[1] / 1000000);
            let statusAgeMs = nowMs - value.statusMonotonicAtMs;
            let ratesAgeMs = nowMs - value.rates.monotonicAtMs;
            if (!(statusAgeMs >= 0) || !(ratesAgeMs >= 0))
                return { schema: 1, available: false };
            value.statusAgeMs = statusAgeMs;
            value.rates.ageMs = ratesAgeMs;
            let extraSeconds = int(statusAgeMs / 1000);
            for (let field in ['cell_age', 'sig_age']) {
                let age = value.status[field];
                if ((type(age) == 'int' || type(age) == 'double') && age >= 0)
                    value.status[field] = age + extraSeconds;
            }
            value.detailsVersion = 1;
            return value;
        }
    } catch (error) {
    }
    return { schema: 1, available: false };
}

function sanitizedWifi(source) {
    source = type(source) == 'object' ? source : {};
    let wifi = {};
    let count = source.clients_n;
    if ((type(count) == 'int' || type(count) == 'double') && count >= 0 && count <= 4096)
        wifi.clients_n = count;
    if (type(source.clients) == 'array') {
        let clients = [];
        for (let entry in source.clients) {
            if (length(clients) >= 256)
                break;
            if (type(entry) != 'object')
                continue;
            let client = {};
            if (type(entry.host) == 'string' && length(entry.host) <= 128)
                client.host = entry.host;
            if (type(entry.ip) == 'string' && length(entry.ip) <= 64)
                client.ip = entry.ip;
            push(clients, client);
        }
        wifi.clients = clients;
    }
    return wifi;
}

function sanitizedLan(source) {
    let lan = {};
    if (type(source) != 'object' || type(source.list) != 'array')
        return lan;
    let leases = [];
    for (let entry in source.list) {
        if (length(leases) >= 256)
            break;
        if (type(entry) != 'object' || type(entry.ip) != 'string' ||
            length(entry.ip) == 0 || length(entry.ip) > 64)
            continue;
        let left = entry.left;
        if ((type(left) == 'int' || type(left) == 'double') && left <= 0)
            continue;
        let lease = { ip: entry.ip };
        if (type(entry.host) == 'string' && length(entry.host) > 0 && length(entry.host) <= 128)
            lease.host = entry.host;
        push(leases, lease);
    }
    lan.list = leases;
    return lan;
}

function onDemandClients(status) {
    if (type(status) != 'object' || type(status.info) != 'object')
        return { schema: 1, available: false };
    let wifi = sanitizedWifi(status.info.wifi);
    if (type(wifi.clients) != 'array')
        wifi.clients = [];
    return { schema: 1, available: true, wifi: wifi, lan: sanitizedLan(status.info.lan) };
}

function validIMEI(value) {
    return type(value) == 'string' && value != '000000000000000' &&
        match(value, /^[0-9]{15}$/) != null;
}

function imeiSlot(value) {
    if ((type(value) == 'int' || type(value) == 'string') && (value === 0 || value === '0')) return 0;
    if ((type(value) == 'int' || type(value) == 'string') && (value === 1 || value === '1')) return 1;
    return null;
}

function diagnosticIMEI(hex, sequence) {
    let header = '7e' + sequence + '00000074005e01';
    if (type(hex) != 'string' || length(hex) > 1024 || substr(hex, 0, length(header)) != header ||
        substr(hex, -2) != '7e')
        return null;

    // The eight-byte BCD block starts with a filler nibble, low nibble first.
    let result = null;
    for (let offset = length(header); offset + 16 <= length(hex) - 2; offset += 2) {
        let block = substr(hex, offset, 16);
        if (match(block, /^[0-9]a[0-9]{14}$/) == null)
            continue;
        let value = '';
        for (let digit = 0; digit < 16; digit += 2)
            value += substr(block, digit + 1, 1) + substr(block, digit, 1);
        value = substr(value, 1);
        if (!validIMEI(value))
            continue;
        if (result != null && result != value)
            return null;
        result = value;
    }
    return result;
}

function readDiagnosticIMEI(slot) {
    const busybox = '/opt/mu300/bin/busybox';
    const device = '/dev/sdiag_nr';
    if (stat(device)?.type != 'char' || stat('/run/mu300/sim-sequence') ||
        stat('/run/mu300/sim-active-unknown'))
        return null;

    // Fixed read-only selectors from MU300's equipment reader. Each slot has a
    // different echoed sequence so a delayed response cannot fill the other slot.
    let sequence = slot == 0 ? '11' : '12';
    let frame = slot == 0 ? '\\176\\021\\000\\000\\000\\012\\000\\136\\201\\000\\000\\176' :
        '\\176\\022\\000\\000\\000\\012\\000\\136\\202\\000\\000\\176';
    let command = busybox + " timeout -s KILL 1 /bin/sh -c 'printf \"%b\" \"$1\" > /dev/sdiag_nr' uulink '" +
        frame + "' 2>/dev/null && " + busybox + ' timeout -s KILL 1 ' + busybox +
        ' dd if=' + device + ' bs=512 count=1 2>/dev/null | ' + busybox + " od -An -tx1 -v | tr -d ' \\n'";
    let handle = popen(command, 'r');
    if (!handle)
        return null;
    let hex = handle.read('all');
    handle.close();
    return diagnosticIMEI(hex, sequence);
}

const diagnosticSlots = ['imei1', 'imei2'];
let diagnosticValues = {};
let diagnosticRetryAt = {};
let diagnosticRunning = false;

function replyDetails(request, details) {
    if (!details.available) {
        request.reply(details);
        return;
    }
    let ident = details.cell.ident;
    let now = clock(true)[0];
    let wanted = [];
    for (let field in diagnosticSlots) {
        if (validIMEI(ident[field]))
            continue;
        if (validIMEI(diagnosticValues[field]))
            ident[field] = diagnosticValues[field];
        else if (now >= (diagnosticRetryAt[field] ?? 0))
            push(wanted, field);
    }
    if (length(wanted) == 0 || diagnosticRunning || stat('/dev/sdiag_nr')?.type != 'char') {
        request.reply(details);
        return;
    }

    diagnosticRunning = true;
    for (let field in wanted)
        diagnosticRetryAt[field] = now + 60;

    let replied = false;
    let deadline = timer(4250, () => {
        replied = true;
        request.reply(details);
    });
    let worker = task(() => {
        let values = {};
        try {
            for (let field in wanted)
                values[field] = readDiagnosticIMEI(field == 'imei1' ? 0 : 1);
        } catch (error) {
        }
        return values;
    }, (values) => {
        diagnosticRunning = false;
        if (type(values) == 'object') {
            for (let field in wanted) {
                if (validIMEI(values[field])) {
                    diagnosticValues[field] = values[field];
                    if (!replied)
                        ident[field] = values[field];
                }
            }
        }
        if (!replied) {
            replied = true;
            deadline.cancel();
            request.reply(details);
        }
    });
    if (!worker) {
        diagnosticRunning = false;
        deadline.cancel();
        request.reply(details);
    }
}

function onDemandDetails(status) {
    if (type(status) != 'object' || type(status.info) != 'object')
        return { schema: 1, available: false };

    let wifi = sanitizedWifi(status.info.wifi);
    let lan = sanitizedLan(status.info.lan);

    let cell = type(status.cell) == 'object' ? status.cell : {};
    let sourceIdent = cell.error == null && type(cell.ident) == 'object' ? cell.ident : {};
    let modem = type(status.info.modem) == 'object' ? status.info.modem : {};
    let hasSlotArray = type(modem.imeis) == 'array';
    let imeis = hasSlotArray ? modem.imeis : [];
    let ident = {};
    // Keep each firmware's preferred source and leave unavailable slots empty.
    let first = validIMEI(imeis[0]) ? imeis[0] : sourceIdent.imei1;
    let second = validIMEI(imeis[1]) ? imeis[1] : sourceIdent.imei2;
    let slot = hasSlotArray ? imeiSlot(cell.card) ?? imeiSlot(sourceIdent.slot) :
        imeiSlot(sourceIdent.slot) ?? imeiSlot(cell.card);
    if (validIMEI(sourceIdent.imei)) {
        ident.imei = sourceIdent.imei;
        if ((slot ?? 0) == 0 && !validIMEI(first)) first = sourceIdent.imei;
        if (slot == 1 && !validIMEI(second)) second = sourceIdent.imei;
    }
    if (validIMEI(first)) ident.imei1 = first;
    if (validIMEI(second)) ident.imei2 = second;
    if (slot != null) ident.slot = slot;

    return { schema: 1, available: true, info: { wifi: wifi, lan: lan }, cell: { ident: ident } };
}

let detailBus = null;

return {
    uulink: {
        snapshot: {
            call: function() {
                return cachedSnapshot();
            }
        },
        details: {
            call: function(request) {
                try {
                    if (!detailBus)
                        detailBus = connect();
                    if (!detailBus)
                        return { schema: 1, available: false };
                    let pending = detailBus.defer('mu300dash', 'status', {}, function(code, status) {
                        replyDetails(request, code == 0 ? onDemandDetails(status) : { schema: 1, available: false });
                    });
                    if (pending)
                        return pending;
                } catch (error) {
                    detailBus = null;
                }
                return { schema: 1, available: false };
            }
        },
        clients: {
            call: function(request) {
                try {
                    if (!detailBus)
                        detailBus = connect();
                    if (!detailBus)
                        return { schema: 1, available: false };
                    let pending = detailBus.defer('mu300dash', 'status', {}, function(code, status) {
                        request.reply(code == 0 ? onDemandClients(status) : { schema: 1, available: false });
                    });
                    if (pending)
                        return pending;
                } catch (error) {
                    detailBus = null;
                }
                return { schema: 1, available: false };
            }
        }
    }
};
