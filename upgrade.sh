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
ucode -c -o /dev/null "$sampler_source"
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
ui_state=missing
if [ "$menu_present" = yes ]; then
    installed_menu_hash=$(sha256sum "$menu_target" | cut -d ' ' -f 1)
    installed_view_hash=$(sha256sum "$view_target" | cut -d ' ' -f 1)
    if [ "$installed_menu_hash" = "$source_menu_hash" ] && [ "$installed_view_hash" = "$source_view_hash" ]; then
        ui_state=current
    elif [ "$installed_view_hash" = 'ac01be903348c8ee4d78d587e65c58d74d07d480bc0421fa3c358e79c66241df' ]; then
        ui_state=published_v02
    else
        # A complete but otherwise unknown LuCI page is backed up and replaced below.
        ui_state=unknown
    fi
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
published_v02_plugin_hash='7e6cdea1ff8345f7d8b6bb7588b1a58c9102fc8065ce42f407cb23d86d47f7df'
core_mode=unknown
if [ "$installed_plugin_hash" = "$source_plugin_hash" ] &&
   [ "$installed_acl_hash" = "$source_acl_hash" ] &&
   [ "$installed_sampler_hash" = "$source_sampler_hash" ]; then
    [ "$ui_state" = current ] || {
        echo 'Incomplete UULink version; nothing was changed.' >&2
        exit 1
    }
    core_mode=current
elif { [ "$installed_plugin_hash" = 'e8d4cab08b853be6d0c343feba9f537c2739e80911faf0a79cbd52f4d44c34fc' ] &&
       [ "$installed_acl_hash" = 'afc7a8e75862a4e4ccd1b8b0e7dbded28f24bb4de458c6ba40c06d3ad7911d84' ]; } ||
     { [ "$installed_plugin_hash" = 'd72bae01a6def9c8c1d77182ee6a2f8a4f6e9f645a089345e8076d774b32cbfa' ] &&
       [ "$installed_acl_hash" = 'a48da02515324a58194f9222213e9f2ea588307f1afe185f7fe389a2e7633e45' ]; }; then
    if [ "$installed_sampler_hash" != '69d37cbfcc6663afc1cdfde5d571aa31bed704b8876173b3666e889d5e905c98' ] ||
       [ "$ui_state" != missing ]; then
        echo 'Unrecognized installed UULink sampler; nothing was changed.' >&2
        exit 1
    fi
    core_mode=full
elif { [ "$installed_plugin_hash" = "$published_v02_plugin_hash" ] ||
       [ "$installed_plugin_hash" = '2ebd073415907ba43f11af2ab1e211d1e825fe7765abfe93f2b1a8176f44de24' ]; } &&
     [ "$installed_acl_hash" = 'dbf929c6b8fa3f76f5ac4b82adb58828cf6ec70ab3421aeedebea92cc63eef41' ] &&
     [ "$installed_acl_hash" = "$source_acl_hash" ]; then
    # An exact rc.3 or rc.4 installation only needs the updated details RPC.
    if [ "$ui_state" = current ] &&
       [ "$installed_init_hash" = 'a114381c48c14277406e8de06ff1b469eb40125530fa29d703d29fff8bcb09f3' ] &&
       [ "$installed_menu_hash" = '628e11d667c3c68d3982fd2a35f79db4fe45aba3b1fab64b634a0b6c1d3b3159' ] &&
       [ "$installed_view_hash" = '9517214620c0dd6bf819ee24c1975314f36701c1808630762b98472e5828b827' ] &&
       [ "$installed_sampler_hash" = 'f817b1c9dc34d0767372355091f6ae02195a2941429c66b57245c7898cc0ca3c' ] &&
       [ "$installed_sampler_hash" = "$source_sampler_hash" ]; then
        core_mode=rpc
    elif [ "$installed_plugin_hash" = "$published_v02_plugin_hash" ] && [ "$ui_state" = published_v02 ]; then
        case "$installed_sampler_hash" in
            a408a9e330cf2ed56ef7d68a70f0998cd1f9cd3dbe6ebddb460fd606b30d7a10|\
            84ae744755fa8ed4fca22ed0b203593770ef50d5b7b0e719b4c8908b3212bffa|\
            85602207f701a0efd7eca4413a44eaf25ba594ce38645f0b59078384745aa0df)
                core_mode=legacy ;;
        esac
    fi
fi

# A structurally complete but otherwise unknown build is still replaceable: every file that gets
# overwritten is backed up first and restored if the readiness checks fail.
if [ "$core_mode" = unknown ] &&
   [ -f "$plugin_target" ] && [ ! -L "$plugin_target" ] &&
   [ -f "$acl_target" ] && [ ! -L "$acl_target" ] &&
   [ -f /usr/libexec/uulink/sampler.uc ] && [ ! -L /usr/libexec/uulink/sampler.uc ] &&
   [ -f /etc/init.d/uulink ] && [ ! -L /etc/init.d/uulink ]; then
    core_mode=full
fi

if [ "$core_mode" = unknown ]; then
    echo 'Unrecognized installed UULink files; nothing was changed.' >&2
    exit 1
fi

if [ "$core_mode" = current ]; then
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

backup=$(mktemp -d /root/uulink-upgrade.XXXXXX)
cp -p "$plugin_target" "$backup/uulink.uc"
if [ "$core_mode" != rpc ]; then
    cp -p /usr/libexec/uulink/sampler.uc "$backup/sampler.uc"
fi
if [ "$core_mode" = full ]; then
    cp -p "$acl_target" "$backup/uulink-agent.json"
fi
if [ "$ui_state" = published_v02 ]; then
    cp -p "$view_target" "$backup/index.js"
elif [ "$ui_state" = unknown ]; then
    cp -p "$menu_target" "$backup/menu.json"
    cp -p "$view_target" "$backup/index.js"
fi
completed=no
core_replaced=no
ui_added=no
ui_replaced=no
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
        elif [ "$ui_replaced" = yes ]; then
            if [ -f "$backup/menu.json" ]; then
                cp -p "$backup/menu.json" "$menu_target" || restored=no
            fi
            cp -p "$backup/index.js" "$view_target" || restored=no
            clear_luci_cache || restored=no
        fi
        if [ "$core_replaced" = yes ]; then
            cp -p "$backup/uulink.uc" "$plugin_target" || restored=no
            if [ "$core_mode" != rpc ]; then
                cp -p "$backup/sampler.uc" /usr/libexec/uulink/sampler.uc || restored=no
            fi
            if [ "$core_mode" = full ]; then
                cp -p "$backup/uulink-agent.json" "$acl_target" || restored=no
            fi
            if [ "$core_mode" != rpc ]; then
                /etc/init.d/uulink restart || restored=no
            fi
            /etc/init.d/rpcd restart || restored=no
        fi
        if [ "$restored" = yes ]; then
            if [ "$core_replaced" = yes ]; then
                echo "Upgrade failed; previous files restored from $backup" >&2
            elif [ "$ui_replaced" = yes ]; then
                echo "LuCI page update failed; previous page restored from $backup" >&2
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
if [ "$ui_state" = published_v02 ]; then
    ui_replaced=yes
    cp "$view_source" "$view_target"
    chmod 0644 "$view_target"
    [ "$(sha256sum "$view_target" | cut -d ' ' -f 1)" = "$source_view_hash" ]
fi
if [ "$ui_state" = unknown ]; then
    ui_replaced=yes
    cp "$menu_source" "$menu_target"
    cp "$view_source" "$view_target"
    chmod 0644 "$menu_target" "$view_target"
    [ "$(sha256sum "$menu_target" | cut -d ' ' -f 1)" = "$source_menu_hash" ]
    [ "$(sha256sum "$view_target" | cut -d ' ' -f 1)" = "$source_view_hash" ]
fi
core_replaced=yes
cp "$plugin_source" "$plugin_target"
chmod 0644 "$plugin_target"
[ "$(sha256sum "$plugin_target" | cut -d ' ' -f 1)" = "$source_plugin_hash" ]
if [ "$core_mode" != rpc ]; then
    cp "$sampler_source" /usr/libexec/uulink/sampler.uc
    chmod 0644 /usr/libexec/uulink/sampler.uc
fi
if [ "$core_mode" = full ]; then
    cp "$acl_source" "$acl_target"
    chmod 0644 "$acl_target"
fi
if [ "$core_mode" != rpc ]; then
    /etc/init.d/uulink restart
fi
/etc/init.d/rpcd restart

if wait_agent_ready; then
    completed=yes
    if { [ "$ui_added" = yes ] || [ "$ui_replaced" = yes ]; } && ! clear_luci_cache; then
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
