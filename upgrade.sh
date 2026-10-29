#!/bin/sh
set -eu

if [ "$(id -u)" != 0 ] || [ ! -r /etc/openwrt_release ]; then
    echo 'Run as root on the U30 Air OpenWrt system.' >&2
    exit 1
fi
if ! command -v ucode >/dev/null 2>&1 ||
   ! command -v ubus >/dev/null 2>&1 ||
   ! command -v sha256sum >/dev/null 2>&1; then
    echo 'Required ucode, ubus, or sha256sum command is missing.' >&2
    exit 1
fi

base=$(CDPATH= cd "$(dirname "$0")" && pwd)
plugin_source="$base/files/usr/share/rpcd/ucode/uulink.uc"
acl_source="$base/files/usr/share/rpcd/acl.d/uulink.json"
plugin_target='/usr/share/rpcd/ucode/uulink.uc'
acl_target='/usr/share/rpcd/acl.d/uulink-agent.json'
if [ ! -f "$plugin_source" ] || [ ! -f "$acl_source" ] ||
   [ ! -f "$plugin_target" ] || [ ! -f "$acl_target" ] ||
   [ -L "$plugin_target" ] || [ -L "$acl_target" ] ||
   [ ! -r /usr/lib/rpcd/ucode.so ] ||
   ! ubus list | grep -qx uulink ||
   ! ubus call mu300dash status >/dev/null 2>&1; then
    echo 'The installed UULink agent or its OpenWrt prerequisites are unavailable.' >&2
    exit 1
fi

ucode -c -o /dev/null "$plugin_source"
agent_ready() {
    /etc/init.d/uulink status >/dev/null 2>&1 || return 1
    snapshot=$(ubus -t 5 call uulink snapshot 2>/dev/null) || return 1
    version=$(printf '%s\n' "$snapshot" | sed -n 's/.*"detailsVersion"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
    [ "$version" = 1 ] || return 1
    status_age=$(printf '%s\n' "$snapshot" | sed -n 's/.*"statusAgeMs"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
    rates_age=$(printf '%s\n' "$snapshot" | sed -n 's/.*"ageMs"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
    case "$status_age:$rates_age" in *[!0-9:]*|:*|*:) return 1 ;; esac
    [ "$status_age" -le 10000 ] && [ "$rates_age" -le 10000 ] || return 1
    ubus -t 5 call uulink details 2>/dev/null | grep -Eq '"available"[[:space:]]*:[[:space:]]*true'
}

wait_agent_ready() {
    attempt=0
    while [ "$attempt" -lt 20 ]; do
        if agent_ready; then
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 1
    done
    return 1
}

diagnose_agent() {
    if /etc/init.d/uulink status >/dev/null 2>&1; then
        echo 'Validation: sampler=running' >&2
    else
        echo 'Validation: sampler=unavailable' >&2
    fi
    ubus -v list uulink >&2 || true
    if snapshot=$(ubus -t 5 call uulink snapshot 2>/dev/null); then
        version=$(printf '%s\n' "$snapshot" | sed -n 's/.*"detailsVersion"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
        status_age=$(printf '%s\n' "$snapshot" | sed -n 's/.*"statusAgeMs"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
        rates_age=$(printf '%s\n' "$snapshot" | sed -n 's/.*"ageMs"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
        echo "Validation: snapshot=returned version=${version:-missing} statusAgeMs=${status_age:-missing} ratesAgeMs=${rates_age:-missing}" >&2
    else
        echo 'Validation: snapshot=call-failed' >&2
    fi
    if details=$(ubus -t 5 call uulink details 2>/dev/null); then
        if printf '%s\n' "$details" | grep -Eq '"available"[[:space:]]*:[[:space:]]*true'; then
            available=true
        elif printf '%s\n' "$details" | grep -Eq '"available"[[:space:]]*:[[:space:]]*false'; then
            available=false
        else
            available=missing
        fi
        echo "Validation: details=returned available=$available" >&2
    else
        echo 'Validation: details=call-failed' >&2
    fi
}

source_plugin_hash=$(sha256sum "$plugin_source" | cut -d ' ' -f 1)
source_acl_hash=$(sha256sum "$acl_source" | cut -d ' ' -f 1)
installed_plugin_hash=$(sha256sum "$plugin_target" | cut -d ' ' -f 1)
installed_acl_hash=$(sha256sum "$acl_target" | cut -d ' ' -f 1)
if [ "$installed_plugin_hash" = "$source_plugin_hash" ] &&
   [ "$installed_acl_hash" = "$source_acl_hash" ]; then
    if agent_ready; then
        echo 'UULink agent is already up to date.'
        exit 0
    fi
    /etc/init.d/rpcd restart
    if wait_agent_ready; then
        echo 'UULink agent is up to date; rpcd was restarted to load it.'
        exit 0
    fi
    echo 'UULink files are current, but the agent is unavailable after rpcd restart.' >&2
    diagnose_agent
    exit 1
fi
if [ "$installed_plugin_hash" != 'e8d4cab08b853be6d0c343feba9f537c2739e80911faf0a79cbd52f4d44c34fc' ] ||
   [ "$installed_acl_hash" != 'afc7a8e75862a4e4ccd1b8b0e7dbded28f24bb4de458c6ba40c06d3ad7911d84' ]; then
    echo 'Unrecognized installed UULink files; nothing was changed.' >&2
    exit 1
fi

backup=$(mktemp -d /root/uulink-upgrade.XXXXXX)
cp -p "$plugin_target" "$backup/uulink.uc"
cp -p "$acl_target" "$backup/uulink-agent.json"
completed=no
restore_on_failure() {
    result=$?
    trap - 0 1 2 3 15
    if [ "$completed" != yes ]; then
        restored=yes
        cp -p "$backup/uulink.uc" "$plugin_target" || restored=no
        cp -p "$backup/uulink-agent.json" "$acl_target" || restored=no
        /etc/init.d/rpcd restart || true
        if [ "$restored" = yes ]; then
            echo "Upgrade failed; previous files restored from $backup" >&2
        else
            echo "Upgrade failed; automatic restore incomplete. Backups are in $backup" >&2
        fi
    fi
    exit "$result"
}
trap restore_on_failure 0
trap 'exit 1' 1 2 3 15

cp "$plugin_source" "$plugin_target"
cp "$acl_source" "$acl_target"
chmod 0644 "$plugin_target" "$acl_target"
/etc/init.d/rpcd restart

if wait_agent_ready; then
    completed=yes
    echo "UULink agent upgraded. Previous files saved in $backup"
    exit 0
fi
echo 'The upgraded UULink agent did not pass readiness checks.' >&2
diagnose_agent
exit 1
