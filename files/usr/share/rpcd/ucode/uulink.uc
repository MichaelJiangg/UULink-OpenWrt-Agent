'use strict';

import { readfile } from 'fs';
import { connect } from 'ubus';

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

function onDemandDetails(status) {
    if (type(status) != 'object' || type(status.info) != 'object')
        return { schema: 1, available: false };

    let wifi = sanitizedWifi(status.info.wifi);
    let lan = sanitizedLan(status.info.lan);

    let cell = type(status.cell) == 'object' ? status.cell : {};
    let sourceIdent = cell.error == null && type(cell.ident) == 'object' ? cell.ident : {};
    let ident = {};
    for (let field in ['imei1', 'imei2', 'imei']) {
        let value = sourceIdent[field];
        if (type(value) == 'string' && match(value, /^[0-9]{15}$/) != null)
            ident[field] = value;
    }
    if (sourceIdent.slot == 0 || sourceIdent.slot == 1)
        ident.slot = sourceIdent.slot;

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
                        request.reply(code == 0 ? onDemandDetails(status) : { schema: 1, available: false });
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
