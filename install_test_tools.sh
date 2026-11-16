#!/bin/sh
# Run on the target server: sudo sh ./install_test_tools.sh AUTHORIZED_ACCOUNT
set -eu
if [ "$#" -ne 1 ] || ! id "$1" >/dev/null 2>&1; then
    echo "Usage: sudo sh ./install_test_tools.sh AUTHORIZED_ACCOUNT" >&2
    exit 2
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer with sudo." >&2
    exit 1
fi
ACCOUNT=$1
GROUP=physmem-test
if ! getent group "$GROUP" >/dev/null; then
    groupadd --system "$GROUP"
fi
usermod -a -G "$GROUP" "$ACCOUNT"
printf '%s\n' 'KERNEL=="phys_mem", GROUP="physmem-test", MODE="0660"' \
    > /etc/udev/rules.d/70-phys-mem.rules
udevadm control --reload-rules
udevadm trigger --name-match=phys_mem || true
if [ -e /dev/phys_mem ]; then
    chgrp "$GROUP" /dev/phys_mem
    chmod 0660 /dev/phys_mem
fi
echo "Authorized $ACCOUNT to access /dev/phys_mem."
