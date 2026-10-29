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
if [ ! -r /www/cgi-bin/luci ] || [ ! -d /usr/share/luci/menu.d ] ||
   [ ! -d /www/luci-static/resources/view ]; then
    echo 'LuCI entry point, menu directory, or view resources are missing; nothing was changed.' >&2
    exit 1
fi

base=$(CDPATH= cd "$(dirname "$0")" && pwd)
init_source="$base/files/etc/init.d/uulink"
sampler_source="$base/files/usr/libexec/uulink/sampler.uc"
plugin_source="$base/files/usr/share/rpcd/ucode/uulink.uc"
acl_source="$base/files/usr/share/rpcd/acl.d/uulink.json"
menu_source="$base/files/usr/share/luci/menu.d/luci-app-uulink.json"
view_source="$base/files/www/luci-static/resources/view/uulink/index.js"
plugin_target='/usr/share/rpcd/ucode/uulink.uc'
acl_target='/usr/share/rpcd/acl.d/uulink-agent.json'
menu_target='/usr/share/luci/menu.d/luci-app-uulink.json'
view_target='/www/luci-static/resources/view/uulink/index.js'
if [ ! -f "$init_source" ] || [ ! -f "$sampler_source" ] ||
   [ ! -f "$plugin_source" ] || [ ! -f "$acl_source" ] ||
   [ ! -f "$menu_source" ] || [ ! -f "$view_source" ] ||
   [ -L "$init_source" ] || [ -L "$sampler_source" ] ||
   [ -L "$plugin_source" ] || [ -L "$acl_source" ] ||
   [ -L "$menu_source" ] || [ -L "$view_source" ] ||
   [ ! -f "$plugin_target" ] || [ ! -f "$acl_target" ] ||
   [ -L "$plugin_target" ] || [ -L "$acl_target" ] ||
   [ ! -f /etc/init.d/uulink ] || [ -L /etc/init.d/uulink ] ||
   [ ! -f /usr/libexec/uulink/sampler.uc ] || [ -L /usr/libexec/uulink/sampler.uc ] ||
   [ ! -r /usr/lib/rpcd/ucode.so ] ||
   ! ubus list | grep -qx uulink ||
   ! ubus call mu300dash status >/dev/null 2>&1; then
    echo 'The installed UULink agent or its OpenWrt prerequisites are unavailable.' >&2
    exit 1
fi

ucode -c -o /dev/null "$plugin_source"
installed_init_hash=$(sha256sum /etc/init.d/uulink | cut -d ' ' -f 1)
source_init_hash=$(sha256sum "$init_source" | cut -d ' ' -f 1)
if [ "$installed_init_hash" != "$source_init_hash" ]; then
    echo 'Unrecognized installed UULink service; nothing was changed.' >&2
    exit 1
fi
menu_present=no
view_present=no
if [ -e "$menu_target" ] || [ -L "$menu_target" ]; then
    [ -f "$menu_target" ] && [ ! -L "$menu_target" ] || {
        echo 'Unrecognized UULink LuCI menu target; nothing was changed.' >&2
        exit 1
    }
    menu_present=yes
fi
if [ -e "$view_target" ] || [ -L "$view_target" ]; then
    [ -f "$view_target" ] && [ ! -L "$view_target" ] || {
        echo 'Unrecognized UULink LuCI view target; nothing was changed.' >&2
        exit 1
    }
    view_present=yes
fi
if [ "$menu_present" != "$view_present" ]; then
    echo 'Incomplete UULink LuCI page; nothing was changed.' >&2
    exit 1
fi
source_menu_hash=$(sha256sum "$menu_source" | cut -d ' ' -f 1)
source_view_hash=$(sha256sum "$view_source" | cut -d ' ' -f 1)
if [ "$menu_present" = yes ] &&
   { [ "$(sha256sum "$menu_target" | cut -d ' ' -f 1)" != "$source_menu_hash" ] ||
     [ "$(sha256sum "$view_target" | cut -d ' ' -f 1)" != "$source_view_hash" ]; }; then
    echo 'Unrecognized installed UULink LuCI page; nothing was changed.' >&2
    exit 1
fi

agent_ready() {
    /etc/init.d/uulink status >/dev/null 2>&1 || return 1
    [ -r "$menu_target" ] && [ -r "$view_target" ] || return 1
    snapshot=$(ubus -t 5 call uulink snapshot 2>/dev/null) || return 1
    version=$(printf '%s\n' "$snapshot" | sed -n 's/.*"detailsVersion"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
    [ "$version" = 1 ] || return 1
    status_age=$(printf '%s\n' "$snapshot" | sed -n 's/.*"statusAgeMs"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
    rates_age=$(printf '%s\n' "$snapshot" | sed -n 's/.*"ageMs"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
    case "$status_age:$rates_age" in *[!0-9:]*|:*|*:) return 1 ;; esac
    [ "$status_age" -le 10000 ] && [ "$rates_age" -le 10000 ] || return 1
    ubus -t 5 call uulink details 2>/dev/null | grep -Eq '"available"[[:space:]]*:[[:space:]]*true' || return 1
    clients=$(ubus -t 5 call uulink clients 2>/dev/null) || return 1
    printf '%s\n' "$clients" | grep -Eq '"available"[[:space:]]*:[[:space:]]*true' || return 1
    printf '%s\n' "$clients" | grep -Eq '"clients"[[:space:]]*:[[:space:]]*\['
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
    if clients=$(ubus -t 5 call uulink clients 2>/dev/null); then
        if printf '%s\n' "$clients" | grep -Eq '"available"[[:space:]]*:[[:space:]]*true' &&
           printf '%s\n' "$clients" | grep -Eq '"clients"[[:space:]]*:[[:space:]]*\['; then
            echo 'Validation: clients=available' >&2
        else
            echo 'Validation: clients=unavailable' >&2
        fi
    else
        echo 'Validation: clients=call-failed' >&2
    fi
}

source_plugin_hash=$(sha256sum "$plugin_source" | cut -d ' ' -f 1)
source_acl_hash=$(sha256sum "$acl_source" | cut -d ' ' -f 1)
source_sampler_hash=$(sha256sum "$sampler_source" | cut -d ' ' -f 1)
installed_plugin_hash=$(sha256sum "$plugin_target" | cut -d ' ' -f 1)
installed_acl_hash=$(sha256sum "$acl_target" | cut -d ' ' -f 1)
installed_sampler_hash=$(sha256sum /usr/libexec/uulink/sampler.uc | cut -d ' ' -f 1)
core_current=no
if [ "$installed_plugin_hash" = "$source_plugin_hash" ] &&
   [ "$installed_acl_hash" = "$source_acl_hash" ] &&
   [ "$installed_sampler_hash" = "$source_sampler_hash" ]; then
    core_current=yes
elif { [ "$installed_plugin_hash" = 'e8d4cab08b853be6d0c343feba9f537c2739e80911faf0a79cbd52f4d44c34fc' ] &&
       [ "$installed_acl_hash" = 'afc7a8e75862a4e4ccd1b8b0e7dbded28f24bb4de458c6ba40c06d3ad7911d84' ]; } ||
     { [ "$installed_plugin_hash" = 'd72bae01a6def9c8c1d77182ee6a2f8a4f6e9f645a089345e8076d774b32cbfa' ] &&
       [ "$installed_acl_hash" = 'a48da02515324a58194f9222213e9f2ea588307f1afe185f7fe389a2e7633e45' ]; }; then
    if [ "$installed_sampler_hash" != '69d37cbfcc6663afc1cdfde5d571aa31bed704b8876173b3666e889d5e905c98' ]; then
        echo 'Unrecognized installed UULink sampler; nothing was changed.' >&2
        exit 1
    fi
    core_current=no
else
    echo 'Unrecognized installed UULink files; nothing was changed.' >&2
    exit 1
fi

if [ "$core_current" = yes ] && [ "$menu_present" = yes ]; then
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

backup=''
if [ "$core_current" = no ]; then
    backup=$(mktemp -d /root/uulink-upgrade.XXXXXX)
    cp -p /usr/libexec/uulink/sampler.uc "$backup/sampler.uc"
    cp -p "$plugin_target" "$backup/uulink.uc"
    cp -p "$acl_target" "$backup/uulink-agent.json"
fi
completed=no
core_replaced=no
ui_added=no
clear_luci_cache() {
    rm -f /tmp/luci-indexcache /tmp/luci-indexcache.* /tmp/luci-modulecache/* 2>/dev/null
}
restore_on_failure() {
    result=$?
    trap - 0 1 2 3 15
    if [ "$completed" != yes ]; then
        restored=yes
        if [ "$ui_added" = yes ]; then
            rm -f "$menu_target" "$view_target" || restored=no
            clear_luci_cache || restored=no
        fi
        if [ "$core_replaced" = yes ]; then
            cp -p "$backup/sampler.uc" /usr/libexec/uulink/sampler.uc || restored=no
            cp -p "$backup/uulink.uc" "$plugin_target" || restored=no
            cp -p "$backup/uulink-agent.json" "$acl_target" || restored=no
            /etc/init.d/uulink restart || restored=no
            /etc/init.d/rpcd restart || restored=no
        fi
        if [ "$restored" = yes ]; then
            if [ "$core_replaced" = yes ]; then
                echo "Upgrade failed; previous files restored from $backup" >&2
            else
                echo 'LuCI page installation failed; newly added files were removed.' >&2
            fi
        else
            echo "Upgrade failed; automatic restore incomplete. Backup location: ${backup:-none}" >&2
        fi
    fi
    exit "$result"
}
trap restore_on_failure 0
trap 'exit 1' 1 2 3 15

if [ "$menu_present" = no ]; then
    mkdir -p "$(dirname "$menu_target")" "$(dirname "$view_target")"
    ui_added=yes
    cp "$menu_source" "$menu_target"
    cp "$view_source" "$view_target"
    chmod 0644 "$menu_target" "$view_target"
    [ "$(sha256sum "$menu_target" | cut -d ' ' -f 1)" = "$source_menu_hash" ]
    [ "$(sha256sum "$view_target" | cut -d ' ' -f 1)" = "$source_view_hash" ]
fi
if [ "$core_current" = no ]; then
    core_replaced=yes
    cp "$sampler_source" /usr/libexec/uulink/sampler.uc
    cp "$plugin_source" "$plugin_target"
    cp "$acl_source" "$acl_target"
    chmod 0644 /usr/libexec/uulink/sampler.uc "$plugin_target" "$acl_target"
    /etc/init.d/uulink restart
    /etc/init.d/rpcd restart
fi

if wait_agent_ready; then
    completed=yes
    if [ "$ui_added" = yes ] && ! clear_luci_cache; then
        echo 'UULink is ready, but LuCI cache cleanup failed; the menu may remain stale.' >&2
    fi
    if [ "$core_replaced" = yes ]; then
        echo "UULink agent upgraded. Previous files saved in $backup"
    else
        echo 'UULink LuCI page installed; the existing data agent was unchanged.'
    fi
    exit 0
fi
echo 'The upgraded UULink agent did not pass readiness checks.' >&2
diagnose_agent
exit 1
