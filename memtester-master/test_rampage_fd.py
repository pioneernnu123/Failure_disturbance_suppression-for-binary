#!/usr/bin/env python3
# //LZU CHANGE
"""Smoke-test RAMpage's inherited-fd mode on a disposable file mapping."""

import os
from pathlib import Path
import subprocess
import struct
import tempfile


def run_case(binary, injection_type, page_mask=None):
    page_size = os.sysconf("SC_PAGE_SIZE")
    page_count = 8
    offset = 5 * page_size
    with tempfile.TemporaryFile() as mapped, tempfile.TemporaryFile(mode="w+t") as result:
        mapped.truncate(page_count * page_size)
        command = [
            str(binary), "-F", str(mapped.fileno()),
            "-R", str(result.fileno()), "-S", "42",
            "-c", str(injection_type),
        ]
        if injection_type:
            command += ["-i", "5"]
        if page_mask:
            command += ["-P", page_mask]
        command += ["%dB" % (page_count * page_size), "1"]
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            pass_fds=(mapped.fileno(), result.fileno()),
        )
        result.seek(0)
        lines = result.read().splitlines()
        valid = (len(lines) >= 3 and lines[0] == "RAMPAGE_RESULT_V4 42 8"
                 and "Stuck Address (batch)" in completed.stdout
                 and lines[-1] == "END CHECKED")
        if injection_type and valid and len(lines) == 5:
            injected = lines[2].split()
            bad = lines[3].split()
            preserved, = struct.unpack("@L", os.pread(mapped.fileno(), struct.calcsize("@L"), offset))
            target_output = completed.stdout.partition("Page 6/8:")[2].partition("Page 7/8:")[0]
            before_injection = target_output.partition("RAMPAGE_INJECTION")[0]
            valid = (lines[1] == "PRECHECK 5" and len(bad) == 6
                     and bad[:4] == ["BAD", str(injection_type), str(offset), "A"]
                     and len(injected) == 6 and injected[:4] ==
                     ["INJECT", str(injection_type), "5", str(offset)]
                     and (int(injected[4]) ^ 1) == int(injected[5])
                     and bad[4:] == injected[4:]
                     and preserved == int(injected[5])
                     and target_output.count("Stuck Address") == (2 if injection_type == 1 else 1)
                     and "RAMPAGE_INJECTION" in target_output
                     and "16-bit Writes" in before_injection
                     and "Page 8/8" in completed.stdout
                     and completed.returncode == (2 if injection_type == 1 else 4))
        elif valid:
            valid = (not injection_type
                     and lines == ["RAMPAGE_RESULT_V4 42 8", "INJECT NONE", "END CHECKED"]
                     and completed.returncode == 0)
        if page_mask:
            for index, chosen in enumerate(page_mask):
                valid &= ((f"Page {index + 1}/{page_count}:" in completed.stdout) == (chosen == "1"))
                if chosen == "0":
                    valid &= os.pread(mapped.fileno(), page_size, index * page_size) == bytes(page_size)
        if not valid:
            raise AssertionError(
                "RAMpage fd test failed: command=%r rc=%d report=%r output=%s"
                % (command, completed.returncode, lines, completed.stdout[-2000:])
            )


if __name__ == "__main__":
    binary = Path(__file__).with_name("memtester").resolve()
    if not binary.is_file():
        raise SystemExit("Build memtester in this directory before running the test")
    run_case(binary, 0)
    for injection_type in range(1, 8):
        run_case(binary, injection_type)
    run_case(binary, 7, "10000111")
    print("RAMpage inherited-fd smoke test: OK")
