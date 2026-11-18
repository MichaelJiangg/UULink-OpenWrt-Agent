# UULink OpenWrt data agent

This agent is independently implemented for U30 Air running OpenWrt. It borrows the idea of sampling on the device and letting clients read a recent cache. No wlmb-server source code or API is used.

The sampler calls the firmware's existing `mu300dash.status` every five seconds and checks `mu300rates.netdev` in its one-second loop. It forwards valid shared `schema:1` B/s values and original sample times. If that extension is absent, it calculates B/s from consecutive raw counters returned by the official `netdev.data` or third-party `mu300rates.rates` RPC. It does not read interface files directly. It publishes read-only `uulink.snapshot`, `uulink.details`, and `uulink.clients` methods through the existing `/ubus/` endpoint. The snapshot cache lives only in `/tmp/uulink/`; no new TCP port or credentials are introduced. The snapshot contains battery, cellular summary, traffic, temperatures, and a bounded Wi-Fi summary. IMEI, IMSI, ICCID, client hostnames and client IP addresses are excluded from the snapshot cache. The authenticated `details` method returns IMEI, Wi-Fi hotspot clients, and unexpired LAN DHCP leases on demand. The LuCI page requests the separate `clients` method on click, which returns only bounded hotspot clients and lease names/IP addresses.

This reduces client-side reading latency. Cellular values still come from the firmware's `mu300dash.status`, so the agent cannot correct a stale upstream value. The phone still needs to reach the router over its local network; this package does not provide remote access.

Traffic summaries keep official `today/used` or third-party `today_used/cycle_used` as raw bytes. Third-party traffic is accepted only when `clock_ok` is true and `0 <= info.ts - traffic.updated_at < 30` seconds. A non-null `available` value must be true or 1. Older summaries without it still undergo the clock checks. `month_used` is a calendar-month count, separate from the active billing cycle. The snapshot carries `unitBase` so local UI can display official traffic with 1024 steps and third-party traffic with 1000 steps. Both firmwares' rates use 1024 steps.

The cache preserves `info.temps.modem` and `info.temps.board` alongside SoC/CPU temperatures from the same five-second firmware status read. It adds no sensor polling, and missing sensors remain missing.

## Rate source selection

The extended no-argument `mu300rates.netdev` response described in [the shared contract](../mu300-backend-rates/CONTRACT.md) takes priority: `schema:1` plus `rates` keyed by interface. It selects `status.info.data_device`, or `sipa_eth0` when the field is absent/empty. The row must be available, valid and at most ten seconds old. Original B/s, sample clocks and exact decimal counter strings are forwarded without recalculation or renewing their age. An unavailable extended row does not trigger a fallback.

Without the extension, the official firmware's `netdev.data` contains the selected interface's `/proc/net/dev` counters. The third-party firmware instead provides `mu300rates.rates` with `rx`, `tx`, `device`, `ifindex`, `boot_id`, and `ts`. Two valid samples of the same interface are required before speed appears. Zero is valid; missing, reset, changed identity, stale, and long-interval samples produce unknown speed. The third-party `ts` comes from `/proc/uptime`, whose clock includes suspend time; only its difference between samples is used, while cache freshness uses the sampler's own monotonic clock. The raw byte counters are never treated as daily or billing-cycle usage.

The first sample, missing interface or invalid/stale row produces null numeric rates and null counters. The empty frame carries current frame times only to keep otherwise valid battery/status readable; old numeric values never receive those times. This candidate leaves the public release assets, version and installation command unchanged. Native provider/consumer verification and a reviewed private upgrade are required before installing the new sampler.

The validated target is U30 Air OpenWrt. The installer checks OpenWrt and required services such as `mu300dash`, not the hardware model name. Other devices with those services are outside the verified scope.

## Files

`files/` contains the router files. The ACL source is installed under a separate name to preserve an existing `uulink.json` ACL:

| File | Purpose |
| --- | --- |
| `usr/libexec/uulink/sampler.uc` | Resident sampler and atomic `/tmp` cache writer |
| `usr/share/rpcd/ucode/uulink.uc` | Read-only ubus methods |
| `usr/share/rpcd/acl.d/uulink.json` → `uulink-agent.json` | Independent read-only ACL group for the three methods |
| `etc/init.d/uulink` | procd startup and crash restart |
| `usr/share/luci/menu.d/luci-app-uulink.json` | Services → UULink menu entry |
| `www/luci-static/resources/view/uulink/index.js` | Read-only Overview, Network, Wi-Fi, and Settings/diagnostics pages |

## Install or upgrade on U30 Air OpenWrt

Connect to the router's local network, open its terminal as `root` (for example, from a computer using SSH), then paste this one command **on the router**:

```sh
wget -O /tmp/uulink-setup.sh https://github.com/MichaelJiangg/UULink-OpenWrt-Agent/releases/download/v0.2.0-rc.1/setup.sh && [ "$(sha256sum /tmp/uulink-setup.sh | cut -d ' ' -f1)" = "4dd8225e5856ec6602828671a0e7e3a77489127851005f0649be449fb417cb7a" ] && sh /tmp/uulink-setup.sh
```

The command above is the published `v0.2.0-rc.1` installer and remains unchanged. It verifies the downloaded installer; the installer verifies the plugin archive and chooses first installation or upgrade of the known earlier UULink agent. Return to UULink to check the plugin after it finishes. The U30 Air upgrade path has been tested on a router, and a locally installed iPhone App has shown connected state, cellular data, battery, and speed through the authenticated `/ubus/` path. First installation, reboot startup, sustained access, and loading time still need device validation. The App does not execute this command itself.

Version `v0.1.0-rc.1` contains the data agent only. The published `v0.2.0-rc.1` prerelease adds four read-only LuCI sections under Services → UULink: Overview, Network, Wi-Fi, and Settings/diagnostics. The Wi-Fi page shows the firmware's reported hotspot status, SSID, channel, band, width, and hotspot client count. On click, it separately lists hotspot clients and unexpired LAN DHCP leases. Leases can include devices reached through an external USB network, but a lease is not proof that a device is currently online. The page neither receives nor displays IMEI or MAC and offers no phone, SMS, router-network, or Wi-Fi configuration actions. On the test U30 Air, the owner confirmed four leases in both LuCI and the locally installed iPhone App.

## Install or upgrade with v0.3.0-rc.6

The separate [`v0.3.0-rc.6` prerelease](https://github.com/MichaelJiangg/UULink-OpenWrt-Agent/releases/tag/v0.3.0-rc.6) was tested on an F50 with third-party OpenWrt firmware. Official U30 Air firmware and V50 await device validation for this build. Run the pinned command from the router terminal as `root`.

```sh
wget -O /tmp/uulink-setup.sh https://github.com/MichaelJiangg/UULink-OpenWrt-Agent/releases/download/v0.3.0-rc.6/setup.sh && [ "$(sha256sum /tmp/uulink-setup.sh | cut -d ' ' -f1)" = "084caa9bb402ed97ff0551f0793daaeaf913687afcef6dfbc0f215a1fd5740e8" ] && sh /tmp/uulink-setup.sh
```

## Release bundle preparation

The local source candidate includes official and third-party traffic and rate compatibility. It preserves `uulink.snapshot` schema 1 and its existing usage/rate keys, adding only optional `status.info.traffic.unitBase`. When status traffic is missing or the third-party firmware explicitly marks it unavailable, the sampler reads the same firmware's existing `mu300dash.traffic_get` and fills only valid missing items. Valid zero counts as a value. The LuCI Network tab displays a known network code as a carrier name when the firmware name is missing. The command above continues to install the published version.

The `v0.3.0-rc.6` candidate maps valid official and third-party firmware IMEIs to the existing `uulink.details` slot fields. If a slot is empty or all-zero after checking firmware status, the authenticated details handler can use a bounded read-only diagnostic request for that slot. The response must match the slot's request sequence. The handler retains a successful diagnostic result in RPC process memory.

An older App using schema 1 can read the updated plugin. The iOS `1.2.0` source tag has been checked against a candidate-shaped snapshot. It reads the same counters and rates and uses its original traffic display base. The App's old first-install entry point detects an existing plugin and leaves it in place. An older App will still install its bundled old package on an empty router, after which the separate new plugin installer can upgrade that known package.

`build-release.py` creates a deterministic complete tarball, a generated `setup.sh`, and `SHA256SUMS`. The current tarball includes only the nine runtime and license files listed in the build script under `uulink-agent/`; the repository README stays outside the tarball so the pinned install command can be updated without changing the bundle digest. The tarball does not contain the iOS project, Git history, local credentials, or build output. `release-setup.template.sh` is the source for the generated entry point. The published `v0.1.0-rc.1` assets were built before its repository README was updated, so the tag does not reproduce those exact asset bytes; this release format corrects that for later versions. To build the current local candidate from this source directory, use a new ignored `.build/` folder:

```sh
python3 build-release.py \
  --version v0.3.0-rc.6 \
  --repo MichaelJiangg/UULink-OpenWrt-Agent \
  --output .build/uulink-agent-release/v0.3.0-rc.6
sh .build/uulink-agent-release/v0.3.0-rc.6/setup.sh --verify-only \
  .build/uulink-agent-release/v0.3.0-rc.6/uulink-agent-v0.3.0-rc.6.tar.gz
```

The generated `setup.sh` contains the release version, the version-specific HTTPS bundle URL, and the bundle's SHA-256. It verifies the archive before extracting it, takes a temporary install lock, then explicitly chooses first installation or upgrade from the existing UULink files. An incomplete or unknown installation is refused, including unexpected symbolic links. The generated script can also verify a transferred local bundle; pass its path as the sole argument. It never downloads or executes wlmb-server code. The current public prerelease contains only its generated `setup.sh`, archive, and `SHA256SUMS` as assets.

The command above checks the downloaded `setup.sh` against its fixed SHA-256 before executing it; that script then checks the tarball against another fixed SHA-256. This detects changed release assets but is not a signature or an independent trust anchor. A LuCI web terminal is an option only when already installed. If GitHub is unreachable from the router, transfer the generated `setup.sh` and matching tarball by a trusted local method, verify them against `SHA256SUMS`, then run `sh setup.sh /tmp/uulink-agent-v0.2.0-rc.1.tar.gz`. The entry point uses the same pinned bundle digest for this offline path. No third-party download proxy or TLS bypass is included.

This release format copies files directly rather than registering an APK/IPK package. A firmware update may remove the service files; do not promise automatic preservation. The source is distributed under the MIT license.

## Installation and validation

Installation changes OpenWrt service files and startup settings. Obtain the device owner's approval before running `install.sh` on the router. The script refuses existing target files, checks for `rpcd-mod-ucode` and other required components plus a working `mu300dash.status`, compiles the ucode sources without executing them, installs the files, restarts rpcd, starts the sampler, and waits for a versioned snapshot with both age values at most 10 seconds plus working on-demand details. If installation fails after files are written, it stops and disables its own service, removes only the files it just installed, and reloads rpcd if it had already been restarted. The new ACL is installed as `uulink-agent.json` with its own `uulink-agent` group; an existing `uulink.json` is left untouched. It does not change the firmware's modem, WiFi, DNS or firewall configuration. Restarting rpcd can invalidate the current `/ubus/` session; clients should log in again before checking the plugin.

For manual source-tree installation, run from a trusted local copy on the U30 Air as root:

```sh
sh install.sh
ubus call uulink snapshot
ubus call uulink details | grep '"available"'
```

After the first successful `mu300dash.status` read, the snapshot response has `schema: 1`, `detailsVersion: 1`, a sanitized `status` object, `rates`, `statusAgeMs` and `rates.ageMs`. The two ages use the router's monotonic clock, so iPhone and router clock differences do not invalidate fresh data. Rate values are initially `null` until two valid counter samples are available. `sampledAtMs` and `statusAtMs` record the last successful status read for diagnostics; rewriting the cache does not advance them. The iOS client requires this plugin version and rejects stale or malformed snapshots instead of reading the old firmware interface directly. The new `clients` method is for LuCI and does not change the iOS `details` contract.

The new candidate `setup.sh` automatically selects the upgrade path for recognized older agents. For manual source-tree upgrades, transfer this package to the router and run `sh upgrade.sh`. Exact F50 `rc.3` and `rc.4` installations update only the RPC handler and restart `rpcd`. Recognized `v0.2.0-rc.1` and private sampler variants also update the sampler and LuCI view and restart `uulink`. The older `v0.1.0-rc.1` path additionally updates the ACL. The script saves replaced files under `/root/uulink-upgrade.*` and restores them if readiness fails. It refuses unknown or partial installations and leaves the separate older `/usr/share/rpcd/acl.d/uulink.json` untouched. The original `install.sh` remains for first-time manual installation only.

Before using the plugin for production data, verify `ubus call mu300dash status` works locally, the root session can call `uulink.snapshot`, `uulink.details`, and `uulink.clients` over `/ubus/`, data age stays within the intended range, the device's battery drain is acceptable, and the service survives a reboot. Firmware updates may need the service files restored; check all three ubus methods after every update. Do not expose `/ubus/` or a router management port to the public internet.
