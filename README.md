# UULink OpenWrt data agent

This agent is independently implemented for U30 Air running OpenWrt. It borrows the idea of sampling on the device and letting clients read a recent cache. No wlmb-server source code or API is used.

The sampler calls the firmware's existing `mu300dash.status` every five seconds and reads the selected interface counters from `/proc/net/dev` every second. It publishes read-only `uulink.snapshot` and `uulink.details` methods through the existing `/ubus/` endpoint. The cache lives only in `/tmp/uulink/`; no new TCP port or credentials are introduced. The snapshot contains the battery, cellular summary, traffic and temperatures needed by UULink. IMEI, IMSI, ICCID, client hostnames and client IP addresses are excluded from the cache. The authenticated `details` method reads IMEI and client host/IP fields from `mu300dash.status` only when the App opens device details; it does not save them.

This reduces client-side reading latency. Cellular values still come from the firmware's `mu300dash.status`, so the agent cannot correct a stale upstream value. The phone still needs to reach the router over its local network; this package does not provide remote access.

The validated target is U30 Air OpenWrt. The installer checks OpenWrt and required services such as `mu300dash`, not the hardware model name. Other devices with those services are outside the verified scope.

## Files

`files/` contains the router files. The ACL source is installed under a separate name to preserve an existing `uulink.json` ACL:

| File | Purpose |
| --- | --- |
| `usr/libexec/uulink/sampler.uc` | Resident sampler and atomic `/tmp` cache writer |
| `usr/share/rpcd/ucode/uulink.uc` | Read-only ubus methods |
| `usr/share/rpcd/acl.d/uulink.json` → `uulink-agent.json` | Independent read-only ACL group for both methods |
| `etc/init.d/uulink` | procd startup and crash restart |

## Release bundle preparation

`build-release.py` creates a deterministic complete tarball, a generated `setup.sh`, and `SHA256SUMS`. The tarball includes only the eight files listed in the build script under `uulink-agent/`, including the MIT license; it does not contain the iOS project, Git history, local credentials, or build output. `release-setup.template.sh` is the source for the generated entry point. From this source directory, build into a new ignored `.build/` folder:

```sh
python3 build-release.py \
  --version v0.1.0-rc.1 \
  --repo MichaelJiangg/UULink-OpenWrt-Agent \
  --output .build/uulink-agent-release/v0.1.0-rc.1
sh .build/uulink-agent-release/v0.1.0-rc.1/setup.sh --verify-only \
  .build/uulink-agent-release/v0.1.0-rc.1/uulink-agent-v0.1.0-rc.1.tar.gz
```

The generated `setup.sh` contains the release version, the version-specific HTTPS bundle URL, and the bundle's SHA-256. It verifies the archive before extracting it, takes a temporary install lock, then explicitly chooses first installation or upgrade from the existing UULink files. An incomplete or unknown installation is refused, including unexpected symbolic links. The generated script can also verify a transferred local bundle; pass its path as the sole argument. It never downloads or executes wlmb-server code. Publish only the three generated files as Release assets after device validation. A private repository Release cannot serve as an anonymous router download.

Once those files are published, users can copy the version-specific command printed by the builder into the router's shell. The command checks the downloaded `setup.sh` against its fixed SHA-256 before executing it; that script then checks the tarball against another fixed SHA-256. This detects changed release assets but is not a signature or an independent trust anchor. Use a computer SSH session; a LuCI web terminal is an option only when already installed. If GitHub is unreachable from the router, transfer the generated `setup.sh` and matching tarball by a trusted local method, verify them against `SHA256SUMS`, then run `sh setup.sh /tmp/uulink-agent-v0.1.0-rc.1.tar.gz`. The entry point uses the same pinned bundle digest for this offline path. No third-party download proxy or TLS bypass is included.

This first release format copies files directly rather than registering an APK/IPK package. A firmware update may remove the service files; do not promise automatic preservation. The source is distributed under the MIT license.

## Installation and validation

Installation changes OpenWrt service files and startup settings. Obtain the device owner's approval before running `install.sh` on the router. The script refuses existing target files, checks for `rpcd-mod-ucode` and other required components plus a working `mu300dash.status`, compiles the ucode sources without executing them, installs the files, restarts rpcd, starts the sampler, and waits for a versioned snapshot with both age values at most 10 seconds plus working on-demand details. If installation fails after files are written, it stops and disables its own service, removes only the files it just installed, and reloads rpcd if it had already been restarted. The new ACL is installed as `uulink-agent.json` with its own `uulink-agent` group; an existing `uulink.json` is left untouched. It does not change the firmware's modem, WiFi, DNS or firewall configuration. Restarting rpcd can invalidate the current `/ubus/` session; clients should log in again before checking the plugin.

Run from a trusted local copy on the U30 Air as root:

```sh
sh install.sh
ubus call uulink snapshot
ubus call uulink details | grep '"available"'
```

After the first successful `mu300dash.status` read, the snapshot response has `schema: 1`, `detailsVersion: 1`, a sanitized `status` object, `rates`, `statusAgeMs` and `rates.ageMs`. The two ages use the router's monotonic clock, so iPhone and router clock differences do not invalidate fresh data. Rate values are initially `null` until two valid counter samples are available. `sampledAtMs` and `statusAtMs` record the last successful status read for diagnostics; rewriting the cache does not advance them. The iOS client requires this plugin version and rejects stale or malformed snapshots instead of reading the old firmware interface directly.

If the router already runs the earlier snapshot-only UULink agent, transfer this updated package to the router and run `sh upgrade.sh` **before installing the new App build**. The upgrade script accepts only the known earlier UULink plugin and ACL hashes, compiles the new plugin first, saves both previous files under `/root/uulink-upgrade.*`, replaces only those two files, restarts `rpcd`, and restores the previous files if the new method fails validation. It refuses unknown files and leaves the separate older `/usr/share/rpcd/acl.d/uulink.json` untouched. The original `install.sh` remains for first-time installation only.

Before using the plugin for production data, verify `ubus call mu300dash status` works locally, the root session can call `uulink.snapshot` and `uulink.details` over `/ubus/`, data age stays within the intended range, the device's battery drain is acceptable, and the service survives a reboot. Firmware updates may need the service files restored; check both ubus methods after every update. Do not expose `/ubus/` or a router management port to the public internet.
