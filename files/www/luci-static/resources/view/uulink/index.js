'use strict';
'require poll';
'require rpc';
'require view';

var getSnapshot = rpc.declare({ object: 'uulink', method: 'snapshot' });
var getClients = rpc.declare({ object: 'uulink', method: 'clients' });

function object(value) {
	return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function numeric(value) {
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function shown(value) {
	if (value == null || value === '' || typeof value === 'object')
		return '—';
	return String(value);
}

function numberWithUnit(value, unit) {
	var number = numeric(value);
	return number == null ? '—' : String(number) + unit;
}

function bytes(value, perSecond) {
	var number = typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : value;
	if (numeric(number) == null || number < 0)
		return '—';
	if (!Number.isSafeInteger(number) && typeof value === 'string')
		return value + (perSecond ? ' B/s' : ' B');
	var units = perSecond ? ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s'] : ['B', 'KB', 'MB', 'GB', 'TB'];
	var index = 0;
	while (number >= 1000 && index < units.length - 1) {
		number /= 1000;
		index++;
	}
	return (index ? number.toFixed(1) : Math.round(number).toString()) + ' ' + units[index];
}

function age(value) {
	var number = numeric(value);
	return number != null && number >= 0 ? (number / 1000).toFixed(1) + ' 秒' : '—';
}

function fresh(value) {
	var number = numeric(value);
	return number != null && number >= 0 && number <= 10000;
}

function unavailableAgeMessage(value) {
	return numeric(value) != null && value > 10000 ?
		'上次数据已过期，实时值暂不显示。' : '无法确认数据更新时间，实时值暂不显示。';
}

function row(title, value) {
	return E('div', { 'class': 'cbi-value' }, [
		E('label', { 'class': 'cbi-value-title' }, title),
		E('div', { 'class': 'cbi-value-field' }, shown(value))
	]);
}

function section(title, description, rows) {
	var children = [E('h3', {}, title)];
	if (description)
		children.push(E('p', {}, description));
	return E('div', { 'class': 'cbi-section' }, children.concat(rows));
}

function validSnapshot(snapshot) {
	return object(snapshot).schema === 1 && Object.keys(object(object(snapshot).status)).length > 0;
}

function healthText(snapshot) {
	if (!validSnapshot(snapshot))
		return '插件暂未返回可用数据';
	var statusAge = numeric(snapshot.statusAgeMs);
	var ratesAge = numeric(object(snapshot.rates).ageMs);
	if (statusAge == null || ratesAge == null || statusAge < 0 || ratesAge < 0)
		return '无法确认数据更新时间';
	return statusAge <= 10000 && ratesAge <= 10000 ? '数据更新正常' : '数据已过期';
}

function battery(power) {
	if (power.present === false || power.present === 0)
		return '无电池';
	var percent = numeric(power.capacity);
	return percent != null && percent >= 0 && percent <= 100 ? percent + '%' : '—';
}

function uptime(value) {
	var seconds = numeric(value);
	if (seconds == null || seconds < 0)
		return '—';
	return Math.floor(seconds / 86400) + ' 天 ' + Math.floor(seconds % 86400 / 3600) + ' 小时';
}

function overview(snapshot) {
	if (!validSnapshot(snapshot))
		return section('概览', '路由器暂未提供可用快照，请在「设置」查看数据年龄。', []);
	var status = object(snapshot.status);
	var info = object(status.info);
	var power = object(info.power);
	var temps = object(info.temps);
	var rates = object(snapshot.rates);
	return E('div', {}, [
		fresh(snapshot.statusAgeMs) ? section('设备与供电', '只显示设备实际返回的字段。', [
			row('电量', battery(power)),
			row('充电状态', power.status),
			row('芯片温度', numberWithUnit(temps.soc, ' °C')),
			row('CPU 温度', numberWithUnit(temps.cpu, ' °C')),
			row('运行时间', uptime(info.uptime)),
			row('固件版本', info.fw)
		]) : section('设备与供电', unavailableAgeMessage(snapshot.statusAgeMs), []),
		fresh(rates.ageMs) ? section('实时速率', '网速来自设备接口计数，不代表运营商签约速率。', [
			row('下载', bytes(rates.downloadBytesPerSecond, true)),
			row('上传', bytes(rates.uploadBytesPerSecond, true)),
			row('速率数据年龄', age(rates.ageMs))
		]) : section('实时速率', unavailableAgeMessage(rates.ageMs), [])
	]);
}

function network(snapshot) {
	if (!validSnapshot(snapshot))
		return section('网络', '设备未提供可用网络状态。', []);
	if (!fresh(snapshot.statusAgeMs))
		return section('网络', unavailableAgeMessage(snapshot.statusAgeMs), []);
	var status = object(snapshot.status);
	var cell = object(status.cell);
	var fast = object(status.sig);
	var cellValid = cell.error == null;
	var stale = numeric(status.sig_age) != null && status.sig_age > 15;
	var useFast = !stale && fast.error == null && numeric(fast.ts) != null &&
		(numeric(cell.ts) == null || fast.ts >= cell.ts);
	var partial = useFast && fast.partial === true;
	var radio = {
		reg: cellValid ? cell.reg : null,
		sig: cellValid ? cell.sig : null,
		lte: cellValid ? cell.lte : null,
		nr: cellValid ? cell.nr : null
	};
	if (useFast) {
		if (Object.keys(object(fast.reg)).length)
			radio.reg = fast.reg;
		if (!partial) {
			for (var key of ['sig', 'lte', 'nr'])
				if (Object.keys(object(fast[key])).length)
					radio[key] = fast[key];
		}
	}
	var signal = stale ? {} : object(radio.sig);
	var operator = cellValid ? object(cell.operator) : {};
	var qos = cellValid ? object(cell.qos) : {};
	var traffic = object(object(status.info).traffic);
	var children = [
		section('蜂窝网络', '测量值与固件返回一致；缺失时不推测。', [
			row('运营商', operator.name),
			row('网络标识', operator.plmn),
			row('网络制式代码', stale ? null : operator.act),
			row('注册状态代码', stale ? null : object(radio.reg).stat),
			row('LTE 频段', stale ? null : object(radio.lte).band),
			row('5G 频段', stale ? null : object(radio.nr).band),
			row('RSRP', numberWithUnit(signal.rsrp, ' dBm')),
			row('RSRQ', numberWithUnit(signal.rsrq, ' dB')),
			row('SINR', numberWithUnit(signal.sinr, ' dB')),
			row('信号数据年龄', numeric(status.sig_age) == null ? '—' : status.sig_age + ' 秒')
		]),
		section('流量与服务质量', '流量由固件提供，未返回的项目保持空白。', [
			row('今日流量', bytes(traffic.today, false)),
			row('当前账期流量', bytes(traffic.used, false)),
			row('QCI', qos.qci),
			row('签约下行', numberWithUnit(qos.dl, ' Mbps')),
			row('签约上行', numberWithUnit(qos.ul, ' Mbps'))
		])
	];
	if (stale)
		children.unshift(E('div', { 'class': 'alert-message warning' }, '蜂窝数据已超过 15 秒，实时信号与网络状态暂不显示。'));
	return E('div', {}, children);
}

function wifi(snapshot, clientState, requestClients) {
	var wifiInfo = object(object(object(snapshot).status).info);
	var wifiStatus = object(wifiInfo.wifi);
	var count = numeric(wifiStatus.clients_n);
	var children = [fresh(object(snapshot).statusAgeMs) ?
		section('Wi‑Fi', '以下信息来自设备快照；缺失字段显示为「—」。', [
			row('Wi‑Fi 状态', wifiStatus.up === 1 ? '已开启' : wifiStatus.up === 0 ? '已关闭' : '—'),
			row('SSID', wifiStatus.ssid),
			row('信道', wifiStatus.channel),
			row('频段', wifiStatus.band),
			row('带宽', wifiStatus.width),
			row('设备热点在线客户端', count != null && count >= 0 ? count + ' 台' : '—')
		]) : section('Wi‑Fi', unavailableAgeMessage(object(snapshot).statusAgeMs), [])];
	var button = E('button', {
		'type': 'button',
		'class': 'btn cbi-button cbi-button-action',
		'disabled': clientState && clientState.loading ? true : null,
		'click': requestClients
	}, clientState && clientState.loading ? '正在读取…' : '查看设备列表');
	children.push(E('div', { 'class': 'cbi-section' }, [
		E('h3', {}, '设备列表'),
		E('p', {}, '点击后分别读取设备热点客户端和局域网 DHCP 租约；租约表示设备获得过地址，不代表此刻在线。外接 USB 网络的设备可出现在租约中。'),
		button
	]));
	if (clientState && clientState.error)
		children.push(section('读取失败', '设备列表暂不可用，请稍后再试。', []));
	else if (clientState && clientState.unavailable)
		children.push(section('设备列表', '固件未提供设备列表。', []));
	else if (clientState && clientState.wifiClients) {
		children.push(section('设备热点客户端', clientState.wifiClients.length ? '' : '当前没有直接连接设备热点的客户端。', clientState.wifiClients.map(function(client, index) {
			return row('客户端 ' + (index + 1), shown(client.host) + ' · ' + shown(client.ip));
		})));
		children.push(section('局域网 DHCP 租约设备', clientState.lanLeases == null ?
			'固件未提供 DHCP 租约列表。' : clientState.lanLeases.length ?
			'这些设备有未到期的 DHCP 租约，但不一定仍在线。' : '没有未到期的 DHCP 租约。',
			(clientState.lanLeases || []).map(function(client, index) {
				return row('租约 ' + (index + 1), shown(client.host) + ' · ' + shown(client.ip));
			})));
	}
	return E('div', {}, children);
}

function settings(snapshot) {
	var rates = object(object(snapshot).rates);
	var status = object(object(snapshot).status);
	var diagnosis = {
		schema: numeric(object(snapshot).schema),
		statusAgeMs: numeric(object(snapshot).statusAgeMs),
		ratesAgeMs: numeric(rates.ageMs),
		cellAgeSeconds: numeric(status.cell_age),
		signalAgeSeconds: numeric(status.sig_age)
	};
	return E('div', {}, [
		section('插件运行状态', '这里显示读取与缓存健康度，不提供路由器网络或 Wi‑Fi 配置修改。', [
			row('数据状态', healthText(snapshot)),
			row('快照协议版本', object(snapshot).schema),
			row('设备状态数据年龄', age(object(snapshot).statusAgeMs)),
			row('速率数据年龄', age(rates.ageMs))
		]),
		E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, '脱敏诊断'),
			E('p', {}, '仅包含协议版本与数据年龄，不包含 IMEI、客户端地址或登录信息。'),
			E('pre', {}, JSON.stringify(diagnosis, null, 2))
		]),
		E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, '安装与更新'),
			E('p', {}, '查看 UULink 官方发布页中的带校验值安装命令；执行前请确认设备运行 OpenWrt。'),
			E('a', {
				'href': 'https://github.com/MichaelJiangg/UULink-OpenWrt-Agent/releases',
				'target': '_blank',
				'rel': 'noopener noreferrer'
			}, '打开 UULink 发布页')
		])
	]);
}

return view.extend({
	load: function() {
		return L.resolveDefault(getSnapshot(), null);
	},
	render: function(initialSnapshot) {
		var snapshot = initialSnapshot;
		var selected = 'overview';
		var clientState = null;
		var body = E('div');
		var state = E('p', {}, healthText(snapshot));
		var buttons = {};
		var tabs = [
			['overview', '概览'],
			['network', '网络'],
			['wifi', 'Wi‑Fi'],
			['settings', '设置']
		];

		function draw() {
			state.textContent = healthText(snapshot);
			for (var name in buttons)
				buttons[name].className = 'btn cbi-button' + (name === selected ? ' cbi-button-action' : '');
			body.textContent = '';
			body.appendChild(selected === 'overview' ? overview(snapshot) :
				selected === 'network' ? network(snapshot) :
				selected === 'wifi' ? wifi(snapshot, clientState, requestClients) : settings(snapshot));
		}

		function requestClients() {
			clientState = { loading: true };
			draw();
			return getClients().then(function(result) {
				var wifiClients = object(object(result).wifi).clients;
				var lanLeases = object(object(result).lan).list;
				if (object(result).available !== true) {
					clientState = { error: true };
					return;
				}
				if (!Array.isArray(wifiClients)) {
					clientState = { unavailable: true };
					return;
				}
				function safeClients(clients) {
					return clients.slice(0, 256).map(function(client) {
						return { host: object(client).host, ip: object(client).ip };
					});
				}
				clientState = { wifiClients: safeClients(wifiClients),
					lanLeases: Array.isArray(lanLeases) ? safeClients(lanLeases) : null };
			}).catch(function() {
				clientState = { error: true };
			}).then(draw);
		}

		function refresh() {
			return getSnapshot().then(function(result) {
				snapshot = result;
				draw();
			}).catch(function() {
				snapshot = null;
				draw();
			});
		}

		var tabButtons = tabs.map(function(tab) {
			buttons[tab[0]] = E('button', {
				'type': 'button',
				'class': 'btn cbi-button',
				'click': function() { selected = tab[0]; draw(); }
			}, tab[1]);
			return buttons[tab[0]];
		});
		poll.add(refresh, 5);
		draw();
		return E('div', {}, [
			E('h2', {}, 'UULink · 设备数据'),
			E('p', {}, '数据由设备端 UULink 插件采集，页面只读。'),
			state,
			E('div', { 'class': 'cbi-section' }, tabButtons),
			body
		]);
	},
	handleSave: null,
	handleSaveApply: null,
	handleReset: null
});
