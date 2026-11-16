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

make

{
    uname -a
    modinfo ./phys_mem.ko
} > ./build-info.txt

if grep -q '^phys_mem ' /proc/modules; then
    run_as_root rmmod phys_mem
fi
run_as_root insmod ./phys_mem.ko
echo OK
