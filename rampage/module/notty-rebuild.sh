#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

make
if grep -q '^phys_mem ' /proc/modules; then
    sudo -A rmmod phys_mem
fi
sudo -A insmod ./phys_mem.ko
echo OK
