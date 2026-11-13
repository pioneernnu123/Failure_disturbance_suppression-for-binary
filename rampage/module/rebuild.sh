#!/bin/sh
# Build with the module Makefile, then load phys_mem.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

run_as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        echo "This script must be run as root or with sudo installed." >&2
        return 1
    fi
}

if ! make > ./build.log 2>&1; then
    cat ./build.log >&2
    exit 1
fi
cat ./build.log
VERMAGIC=$(modinfo -F vermagic ./phys_mem.ko)
UNDEFINED_SYMBOLS=$(nm -u ./phys_mem.ko)
if printf '%s\n' "$UNDEFINED_SYMBOLS" | grep -E 'mm_page_order|mm_buddy_expand|memory_failure|SetPageHWPoison'; then
    echo "Legacy or memory-failure symbol dependency remains" >&2
    exit 1
fi
echo "Built phys_mem.ko: $VERMAGIC"
{
    date -Is
    uname -a
    printf 'build_release=%s\nrunning_release=%s\n' "${VERMAGIC%% *}" "$(uname -r)"
    printf 'vermagic=%s\n' "$VERMAGIC"
    modinfo -F version ./phys_mem.ko
    sha256sum ./phys_mem.ko
    cc --version | sed -n '1p'
} > ./build-info.txt

if grep -q '^phys_mem ' /proc/modules; then
    echo "Unloading current phys_mem; this fails while isolated pages are held."
    run_as_root rmmod phys_mem
fi
run_as_root insmod ./phys_mem.ko
echo "Loaded phys_mem on the existing kernel."
