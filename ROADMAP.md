# ROADMAP

## Current stage

- The local `v0.2.0-rc.1` candidate is installed on the U30 Air for validation, but is not publicly released. It adds `uulink.clients`, bounded Wi-Fi summary fields, on-demand LAN DHCP leases, and a LuCI entry under Services → UULink with four read-only sections: Overview, Network, Wi-Fi, and Settings/diagnostics. The currently public `v0.1.0-rc.1` remains a data-agent-only release.
- `v0.1.0-rc.1` is published as a prerelease at `https://github.com/MichaelJiangg/UULink-OpenWrt-Agent/releases/tag/v0.1.0-rc.1`. The three public assets were downloaded anonymously and matched `SHA256SUMS`; the downloaded `setup.sh --verify-only` accepted the bundle.
- The public README now puts the pinned one-command router install and upgrade path first, and points release reproduction to the tagged source.
- The first U30 Air upgrade attempt passed bundle verification but failed the combined readiness check. The installer restored the previous plugin and ACL; both old hashes and the running service were confirmed afterward. A second diagnostic attempt showed the service, version 1 snapshot, fresh ages, and `details.available=true`, then also restored the previous plugin.
- The failure was traced to a version `grep` that rejected `detailsVersion: 1` at the end of a JSON line. Both install and upgrade checks now parse and compare the numeric value. The corrected bundle passes six offline tests and checksum verification. On the U30 Air, the corrected bundle upgraded the old plugin successfully: service running, `detailsVersion: 1`, snapshot ages 6910/1820 ms, and `details.available=true`.

## Verified locally

- The current iOS App was built for and installed on the paired iPhone 17 Pro. It displayed connected state, cellular data, battery and speed from OpenWrt. Its hotspot client count is `0`, matching firmware status; the router has `usb0` but no wireless interface or hostapd object. The same firmware status reports four unexpired LAN DHCP leases. The App now displays the separate lease list: the user confirmed four entries on the iPhone. The complete iOS simulator suite passed 311/311 after the LAN lease change.
- The local router upgrade passed `ucode -c` for both sources, started the service, registered `snapshot`, `details`, and `clients`, and reported status/rate ages 2344/310 ms plus four LAN leases. The user opened all four LuCI sections and saw the four leases. The upgrade script printed `sh: missing ]` from a malformed preliminary init-hash comparison even though the later upgrade/readiness checks succeeded; the source script is fixed, and a device recheck with the fixed bundle returned `UULink agent is already up to date.` without replacing the plugin.
- The final local release candidate in `.build/uulink-agent-release/v0.2.0-rc.1-reproducible-20261030/` passes nine offline tests, shell and JavaScript syntax checks, `SHA256SUMS`, and `setup.sh --verify-only`. It excludes the repository README from the router archive so a pinned installation command can be updated without changing the bundle digest. This final archive has not been installed; its runtime files match the locally tested version, while the `upgrade.sh` init-hash guard is corrected.
- The separate public-repository staging checkout rebuilt the same tarball, `setup.sh`, and `SHA256SUMS` byte for byte from its source. Its README has the pinned `v0.2.0-rc.1` command, and local release notes are prepared. The owner authorized publication after the device's idempotent check; the new tag and release are pending.
- The release builder emits byte-identical archives on repeated builds and includes only the allowlisted agent files.
- `setup.sh --verify-only` accepts the matching archive and rejects a modified one.
- Shell syntax, `SHA256SUMS`, and all nine current offline tests pass.

## Pending validation

- Publish the owner-approved `v0.2.0-rc.1` prerelease and verify the assets anonymously. First installation and failure rollback have not been exercised on a fresh device. The firmware reports `0` direct hotspot clients and four valid LAN DHCP leases for this USB-network setup; leases are not proof of current online status.
- Confirm service startup after reboot, sustained App access through authenticated `/ubus/`, loading time, and power impact. The iPhone screenshot is a successful single-session connection check, not a sustained or timed validation.
- Add the installation entry to the native App after validating the design prototype. The H5 prototype's copy action uses the published `setup.sh` URL and fixed SHA-256.
