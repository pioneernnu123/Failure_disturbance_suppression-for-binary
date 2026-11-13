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
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ACCOUNT=$1
GROUP=physmem-test
if ! getent group "$GROUP" >/dev/null; then
    groupadd --system "$GROUP"
fi
usermod -a -G "$GROUP" "$ACCOUNT"
make -C "$ROOT/memtester-master" clean
make -C "$ROOT/memtester-master" test-injection-offsets
make -C "$ROOT/memtester-master"
(cd "$ROOT/memtester-master" && python3 test_rampage_fd.py)
install -m 0755 "$ROOT/memtester-master/memtester" /usr/local/bin/memtester
APP=/opt/failure-disturbance/app
install -d -m 0750 -o root -g "$GROUP" "$APP" "$APP/physmem" \
    "$APP/scheduling" "$APP/scheduling/slow" "$APP/tester"
for file in main.py run_memory_test.py phys_memctl.py injection_state.py injection_control.py; do
    install -m 0640 -o root -g "$GROUP" "$ROOT/rampage/userspace/$file" "$APP/$file"
done
for file in __init__.py physmem.py mmapwrapper.py; do
    install -m 0640 -o root -g "$GROUP" \
        "$ROOT/rampage/userspace/physmem/$file" "$APP/physmem/$file"
done
install -m 0640 -o root -g "$GROUP" \
    "$ROOT/rampage/userspace/scheduling/__init__.py" "$APP/scheduling/__init__.py"
for file in __init__.py slow_scheduler.py; do
    install -m 0640 -o root -g "$GROUP" \
        "$ROOT/rampage/userspace/scheduling/slow/$file" "$APP/scheduling/slow/$file"
done
for file in __init__.py scanner_baseclass.py memtester_wrapper.py no_inject.py; do
    install -m 0640 -o root -g "$GROUP" \
        "$ROOT/rampage/userspace/tester/$file" "$APP/tester/$file"
done
install -m 0750 -o root -g "$GROUP" \
    "$ROOT/rampage/userspace/phys_memctl" "$APP/phys_memctl"
for file in build-info.txt build.log; do
    if [ -f "$ROOT/rampage/module/$file" ]; then
        install -m 0640 -o root -g "$GROUP" "$ROOT/rampage/module/$file" "$APP/$file"
    fi
done
printf '%s\n' 'KERNEL=="phys_mem", GROUP="physmem-test", MODE="0660"' \
    > /etc/udev/rules.d/70-phys-mem.rules
udevadm control --reload-rules
udevadm trigger --name-match=phys_mem || true
if [ -e /dev/phys_mem ]; then
    chgrp "$GROUP" /dev/phys_mem
    chmod 0660 /dev/phys_mem
fi
echo "Installed for $ACCOUNT. Start a new login session to use group $GROUP."
