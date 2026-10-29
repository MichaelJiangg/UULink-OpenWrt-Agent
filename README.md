# UULink OpenWrt data agent

This agent is independently implemented for U30 Air running OpenWrt. It borrows the idea of sampling on the device and letting clients read a recent cache. No wlmb-server source code or API is used.

The sampler calls the firmware's existing `mu300dash.status` every five seconds and reads the selected interface counters from `/proc/net/dev` every second. It publishes read-only `uulink.snapshot`, `uulink.details`, and `uulink.clients` methods through the existing `/ubus/` endpoint. The cache lives only in `/tmp/uulink/`; no new TCP port or credentials are introduced. The snapshot contains battery, cellular summary, traffic, temperatures, and a bounded Wi-Fi summary. IMEI, IMSI, ICCID, client hostnames and client IP addresses are excluded from the cache. The authenticated `details` method reads IMEI, Wi-Fi hotspot clients, and unexpired LAN DHCP leases from `mu300dash.status` only when the App opens device details; it does not save them. The LuCI page requests the separate `clients` method on click, which returns only bounded hotspot clients and lease names/IP addresses, never IMEI or MAC.

This reduces client-side reading latency. Cellular values still come from the firmware's `mu300dash.status`, so the agent cannot correct a stale upstream value. The phone still needs to reach the router over its local network; this package does not provide remote access.

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

The command verifies the downloaded installer; the installer verifies the plugin archive and chooses first installation or upgrade of the known earlier UULink agent. Return to UULink to check the plugin after it finishes. The U30 Air upgrade path has been tested on a router, and a locally installed iPhone App has shown connected state, cellular data, battery, and speed through the authenticated `/ubus/` path. First installation, reboot startup, sustained access, and loading time still need device validation. The App does not execute this command itself.

Version `v0.1.0-rc.1` contains the data agent only. Version `v0.2.0-rc.1` adds four read-only LuCI sections under Services → UULink: Overview, Network, Wi-Fi, and Settings/diagnostics. The Wi-Fi page shows the firmware's reported hotspot status, SSID, channel, band, width, and hotspot client count. On click, it separately lists hotspot clients and unexpired LAN DHCP leases. Leases can include devices reached through an external USB network, but a lease is not proof that a device is currently online. The page neither receives nor displays IMEI or MAC and offers no phone, SMS, router-network, or Wi-Fi configuration actions. The local U30 Air and iPhone installation showed four leases in both LuCI and the App.

## Release bundle preparation

`build-release.py` creates a deterministic complete tarball, a generated `setup.sh`, and `SHA256SUMS`. The current tarball includes only the nine runtime and license files listed in the build script under `uulink-agent/`; the repository README stays outside the tarball so the pinned install command can be updated without changing the bundle digest. The tarball does not contain the iOS project, Git history, local credentials, or build output. `release-setup.template.sh` is the source for the generated entry point. The published `v0.1.0-rc.1` assets were built before its repository README was updated, so the tag does not reproduce those exact asset bytes; this release format corrects that for later versions. To build the current local candidate from this source directory, use a new ignored `.build/` folder:

```sh
python3 build-release.py \
  --version v0.2.0-rc.1 \
  --repo MichaelJiangg/UULink-OpenWrt-Agent \
  --output .build/uulink-agent-release/v0.2.0-rc.1
sh .build/uulink-agent-release/v0.2.0-rc.1/setup.sh --verify-only \
  .build/uulink-agent-release/v0.2.0-rc.1/uulink-agent-v0.2.0-rc.1.tar.gz
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

The current `setup.sh` automatically selects the upgrade path for the recognized snapshot-only agent and published `v0.1.0-rc.1` agent. For manual source-tree upgrades, transfer this package to the router and run `sh upgrade.sh`. The upgrade script verifies the installed core files before changing anything, installs the LuCI entry, and retains the current data agent when its files already match. If core files need replacement, it saves the previous plugin and ACL under `/root/uulink-upgrade.*`, restarts `rpcd`, and restores them if readiness fails. It refuses unknown or partial installations and leaves the separate older `/usr/share/rpcd/acl.d/uulink.json` untouched. The original `install.sh` remains for first-time manual installation only.

Before using the plugin for production data, verify `ubus call mu300dash status` works locally, the root session can call `uulink.snapshot`, `uulink.details`, and `uulink.clients` over `/ubus/`, data age stays within the intended range, the device's battery drain is acceptable, and the service survives a reboot. Firmware updates may need the service files restored; check all three ubus methods after every update. Do not expose `/ubus/` or a router management port to the public internet.
