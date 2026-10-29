#!/bin/sh
set -eu

version='@VERSION@'
bundle_url='@BUNDLE_URL@'
bundle_sha256='@BUNDLE_SHA256@'

verify_only=no
if [ "${1-}" = '--verify-only' ]; then
    verify_only=yes
    shift
fi
if [ "$#" -gt 1 ]; then
    echo "Usage: sh setup.sh [--verify-only] [local-bundle.tar.gz]" >&2
    exit 2
fi

for command in mktemp sha256sum tar; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Required command is missing: $command" >&2
        exit 1
    fi
done

workdir=$(mktemp -d /tmp/uulink-setup.XXXXXX)
lock_owned=no
lockdir='/tmp/uulink-agent-install.lock'
cleanup() {
    if [ "$lock_owned" = yes ]; then
        rmdir "$lockdir" || true
    fi
    case "$workdir" in
        /tmp/uulink-setup.*) rm -rf "$workdir" ;;
    esac
}
trap cleanup 0
trap 'exit 1' 1 2 3 15

bundle="$workdir/uulink-agent.tar.gz"
if [ "$#" -eq 1 ]; then
    if [ ! -r "$1" ]; then
        echo "Cannot read local bundle: $1" >&2
        exit 1
    fi
    cp "$1" "$bundle"
else
    if ! command -v wget >/dev/null 2>&1; then
        echo 'wget is missing; transfer the release bundle to the router and pass its path to setup.sh.' >&2
        exit 1
    fi
    echo "Downloading UULink agent $version..."
    wget -O "$bundle" "$bundle_url"
fi

actual_sha256=$(sha256sum "$bundle")
actual_sha256=${actual_sha256%% *}
if [ "$actual_sha256" != "$bundle_sha256" ]; then
    echo 'UULink bundle SHA-256 mismatch; nothing was installed.' >&2
    exit 1
fi

tar -tzf "$bundle" > "$workdir/contents"
while IFS= read -r path; do
    case "$path" in
        uulink-agent/*) ;;
        *) echo "Unexpected bundle path: $path" >&2; exit 1 ;;
    esac
    case "$path" in
        *'/../'*|*'/..'|*'/./'*|*'/.'|*'//'*)
            echo "Unsafe bundle path: $path" >&2
            exit 1
            ;;
    esac
done < "$workdir/contents"
tar -xzf "$bundle" -C "$workdir"

source="$workdir/uulink-agent"
for path in install.sh upgrade.sh files/etc/init.d/uulink \
            files/usr/libexec/uulink/sampler.uc \
            files/usr/share/rpcd/acl.d/uulink.json \
            files/usr/share/rpcd/ucode/uulink.uc \
            files/usr/share/luci/menu.d/luci-app-uulink.json \
            files/www/luci-static/resources/view/uulink/index.js; do
    if [ ! -f "$source/$path" ] || [ -L "$source/$path" ]; then
        echo "Required bundle file is missing: $path" >&2
        exit 1
    fi
done

if [ "$verify_only" = yes ]; then
    echo "UULink agent $version bundle verified; no system files were changed."
    exit 0
fi

if [ "$(id -u)" != 0 ] || [ ! -r /etc/openwrt_release ] ||
   ! command -v ubus >/dev/null 2>&1; then
    echo 'Run as root on OpenWrt with ubus available.' >&2
    exit 1
fi

if ! mkdir "$lockdir" 2>/dev/null; then
    echo 'Another UULink installation is running, or its temporary lock remains; no system files were changed.' >&2
    exit 1
fi
lock_owned=yes

existing=0
for path in /etc/init.d/uulink /usr/libexec/uulink/sampler.uc \
            /usr/share/rpcd/ucode/uulink.uc \
            /usr/share/rpcd/acl.d/uulink-agent.json; do
    if [ -e "$path" ] || [ -L "$path" ]; then
        existing=$((existing + 1))
    fi
done
ui_existing=0
for path in /usr/share/luci/menu.d/luci-app-uulink.json \
            /www/luci-static/resources/view/uulink/index.js; do
    if [ -e "$path" ] || [ -L "$path" ]; then
        ui_existing=$((ui_existing + 1))
    fi
done

if [ "$existing" -eq 0 ] && [ "$ui_existing" -eq 0 ] && ! ubus list | grep -qx uulink; then
    echo 'Installing UULink agent...'
    sh "$source/install.sh"
elif [ "$existing" -eq 4 ] && { [ "$ui_existing" -eq 0 ] || [ "$ui_existing" -eq 2 ]; } &&
     ubus list | grep -qx uulink; then
    echo 'Checking or upgrading the installed UULink agent...'
    sh "$source/upgrade.sh"
else
    echo 'An incomplete or unrecognized UULink installation is present; no system files were changed.' >&2
    exit 1
fi
