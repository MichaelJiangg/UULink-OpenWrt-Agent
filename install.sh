#!/bin/sh
set -eu

if [ "$(id -u)" != 0 ]; then
    echo 'Run as root on the U30 Air OpenWrt system.' >&2
    exit 1
fi
if [ ! -r /etc/openwrt_release ] || ! command -v ucode >/dev/null 2>&1 ||
   ! command -v ubus >/dev/null 2>&1 ||
   ! ubus list | grep -qx mu300dash ||
   ! ubus call mu300dash status >/dev/null 2>&1; then
    echo 'Required OpenWrt, ucode, ubus, or mu300dash component is missing.' >&2
    exit 1
fi
if [ ! -r /usr/lib/rpcd/ucode.so ]; then
    echo 'Required rpcd-mod-ucode plugin loader is missing.' >&2
    exit 1
fi
if ubus list | grep -qx uulink; then
    echo 'The uulink ubus object already exists.' >&2
    exit 1
fi

base=$(CDPATH= cd "$(dirname "$0")" && pwd)
files='etc/init.d/uulink usr/libexec/uulink/sampler.uc usr/share/rpcd/ucode/uulink.uc'
acl_source='usr/share/rpcd/acl.d/uulink.json'
acl_target='/usr/share/rpcd/acl.d/uulink-agent.json'
for file in $files; do
    if [ ! -f "$base/files/$file" ]; then
        echo "Missing source: $file" >&2
        exit 1
    fi
    if [ -e "/$file" ] || [ -L "/$file" ]; then
        echo "Existing target: /$file" >&2
        exit 1
    fi
done
if [ ! -f "$base/files/$acl_source" ]; then
    echo "Missing source: $acl_source" >&2
    exit 1
fi
if [ -e "$acl_target" ] || [ -L "$acl_target" ]; then
    echo "Existing target: $acl_target" >&2
    exit 1
fi

ucode -c -o /dev/null "$base/files/usr/libexec/uulink/sampler.uc"
ucode -c -o /dev/null "$base/files/usr/share/rpcd/ucode/uulink.uc"

completed=no
wrote_files=no
rpcd_restarted=no
restore_on_failure() {
    result=$?
    trap - 0 1 2 3 15
    if [ "$completed" != yes ] && [ "$wrote_files" = yes ]; then
        restored=yes
        if [ -e /etc/init.d/uulink ]; then
            /etc/init.d/uulink stop >/dev/null 2>&1 || true
            /etc/init.d/uulink disable >/dev/null 2>&1 || true
        fi
        for file in $files; do
            rm -f "/$file" || restored=no
        done
        rm -f "$acl_target" || restored=no
        if [ "$rpcd_restarted" = yes ]; then
            /etc/init.d/rpcd restart || restored=no
        fi
        if [ "$restored" = yes ]; then
            echo 'Initial install failed; newly installed UULink files were removed.' >&2
        else
            echo 'Initial install failed; automatic cleanup was incomplete. Check UULink service files.' >&2
        fi
    fi
    exit "$result"
}
trap restore_on_failure 0
trap 'exit 1' 1 2 3 15

for file in $files; do
    mkdir -p "$(dirname "/$file")"
    wrote_files=yes
    cp "$base/files/$file" "/$file"
    chmod 0644 "/$file"
done
mkdir -p "$(dirname "$acl_target")"
wrote_files=yes
cp "$base/files/$acl_source" "$acl_target"
chmod 0644 "$acl_target"
chmod 0755 /etc/init.d/uulink

rpcd_restarted=yes
/etc/init.d/rpcd restart
/etc/init.d/uulink enable
/etc/init.d/uulink start

agent_ready() {
    /etc/init.d/uulink status >/dev/null 2>&1 || return 1
    ubus list | grep -qx uulink || return 1
    snapshot=$(ubus -t 5 call uulink snapshot 2>/dev/null) || return 1
    version=$(printf '%s\n' "$snapshot" | sed -n 's/.*"detailsVersion"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
    [ "$version" = 1 ] || return 1
    status_age=$(printf '%s\n' "$snapshot" | sed -n 's/.*"statusAgeMs"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
    rates_age=$(printf '%s\n' "$snapshot" | sed -n 's/.*"ageMs"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
    case "$status_age:$rates_age" in *[!0-9:]*|:*|*:) return 1 ;; esac
    [ "$status_age" -le 10000 ] && [ "$rates_age" -le 10000 ] || return 1
    ubus -t 5 call uulink details 2>/dev/null | grep -Eq '"available"[[:space:]]*:[[:space:]]*true'
}

attempt=0
while [ "$attempt" -lt 20 ]; do
    if agent_ready; then
        completed=yes
        echo 'UULink agent installed. Snapshot and on-demand details are available.'
        exit 0
    fi
    attempt=$((attempt + 1))
    sleep 1
done
if ! ubus list | grep -qx uulink; then
    echo 'Files installed, but the uulink ubus object is not available. Check rpcd logs.' >&2
    exit 1
fi
echo 'The uulink object is present, but its current snapshot or details method is unavailable. Check service logs.' >&2
exit 1
