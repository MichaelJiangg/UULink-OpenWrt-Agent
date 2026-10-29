# ROADMAP

## Current stage

- `v0.1.0-rc.1` is published as a prerelease at `https://github.com/MichaelJiangg/UULink-OpenWrt-Agent/releases/tag/v0.1.0-rc.1`. The three public assets were downloaded anonymously and matched `SHA256SUMS`; the downloaded `setup.sh --verify-only` accepted the bundle.
- The public README now puts the pinned one-command router install and upgrade path first, and points release reproduction to the tagged source.
- The first U30 Air upgrade attempt passed bundle verification but failed the combined readiness check. The installer restored the previous plugin and ACL; both old hashes and the running service were confirmed afterward. A second diagnostic attempt showed the service, version 1 snapshot, fresh ages, and `details.available=true`, then also restored the previous plugin.
- The failure was traced to a version `grep` that rejected `detailsVersion: 1` at the end of a JSON line. Both install and upgrade checks now parse and compare the numeric value. The corrected bundle passes six offline tests and checksum verification. On the U30 Air, the corrected bundle upgraded the old plugin successfully: service running, `detailsVersion: 1`, snapshot ages 6910/1820 ms, and `details.available=true`.

## Verified locally

- The release builder emits byte-identical archives on repeated builds and includes only the allowlisted agent files.
- `setup.sh --verify-only` accepts the matching archive and rejects a modified one.
- Shell syntax, `SHA256SUMS`, and the six offline release tests pass.

## Pending validation

- Confirm service startup after reboot and verify the App's authenticated `/ubus/` path separately.
- Add the installation entry to the native App after validating the design prototype. The H5 prototype's copy action uses the published `setup.sh` URL and fixed SHA-256.
