#!/usr/bin/env python3
'''
This source code is distributed under the MIT License

Copyright (c) 2010, Jens Neuhalfen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
'''

import argparse
from contextlib import nullcontext
import errno
import json
from pathlib import Path
import re
import signal
import sys
import time

from injection_state import (DEFAULT_INJECTION_STATE_PATH, INJECTION_TYPE_NAMES,
                             write_injection_type)
from physmem import PAGE_SIZE
from run_memory_test import serialize_round
from scheduling.slow.slow_scheduler import SlowScheduler
from tester.memtester_wrapper import MEMTESTER_BIN, MemtesterWrapper


def parse_memory_size(value):
    """Convert values such as 512M, 2G or 4GiB to bytes."""
    match = re.match(r"^([1-9][0-9]*)\s*([KMGT]?)(?:I?B)?$", value.strip(), re.I)
    if not match:
        raise ValueError("use a size such as 512M, 2G or 4GiB")

    amount = int(match.group(1))
    unit = match.group(2).upper()
    shifts = {"": 0, "K": 10, "M": 20, "G": 30, "T": 40}
    return amount << shifts[unit]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run memtester until Ctrl+C.")
    parser.add_argument("-t", "--test-algorithms", choices=["memtester"], default="memtester")
    parser.add_argument("-a", "--allocation-strategy", choices=["slow"], default="slow")
    parser.add_argument("--memtester-args", default="-i 5", metavar="ARGS",
                        help="relative injection page, for example \"-i 5\"")
    parser.add_argument("--memtester-inject-type", "--memtester-inject-kind",
                        type=int, choices=range(8), default=0, help="initial injection type")
    parser.add_argument("--memtester-inject-file", default=DEFAULT_INJECTION_STATE_PATH)
    parser.add_argument("--frames-per-check", type=int, default=50,
                        help="number of module pages per memtester invocation")
    parser.add_argument("--scan-mode", choices=["full", "local"], default="full")
    parser.add_argument("--max-memory", type=parse_memory_size, metavar="SIZE",
                        help="maximum amount tested per local pass, for example 2G")
    parser.add_argument("--logfile", type=Path, help="append batch and round records to this file")
    parser.add_argument("--memtester", type=Path, metavar="PATH")
    options = parser.parse_args(argv)

    if not 0 < options.frames_per_check < 2**32:
        parser.error("--frames-per-check must be a positive page count")
    if options.scan_mode == "local" and options.max_memory is None:
        parser.error("--scan-mode=local requires --max-memory=SIZE")
    if options.scan_mode == "full" and options.max_memory is not None:
        parser.error("--max-memory requires --scan-mode=local")

    tree_binary = Path(__file__).resolve().parent / "../../memtester-master/memtester"
    binary = options.memtester or (tree_binary if tree_binary.is_file() else MEMTESTER_BIN)
    pass_pages = None if options.max_memory is None else options.max_memory // PAGE_SIZE
    log_path = options.logfile
    if log_path is None and options.scan_mode == "local":
        log_path = Path(__file__).with_name("rampage-local.log")

    run_id = time.time_ns()
    scheduler = SlowScheduler()
    stopped = False

    def request_stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    def report_injection(kind):
        print("当前错误类型：%s" % INJECTION_TYPE_NAMES[kind], flush=True)

    previous_handler = signal.signal(signal.SIGINT, request_stop)
    attempt = pass_number = 0
    finish = "error"
    try:
        tester = MemtesterWrapper(extra_args=options.memtester_args,
                                  injection_type=options.memtester_inject_type,
                                  injection_state_path=options.memtester_inject_file,
                                  binary=binary, initialize_injection=False,
                                  report_injection=report_injection)
        minimum_pages = 1 if tester.inject_page is None else tester.inject_page + 1
        if options.memtester_inject_type and tester.inject_page is None:
            parser.error("a nonzero --memtester-inject-type requires an injection page")
        if options.frames_per_check < minimum_pages:
            parser.error("--frames-per-check must include the page selected by -i")
        if pass_pages is not None and pass_pages < minimum_pages:
            parser.error("--max-memory must include the page selected by -i")
        log_context = (log_path.open("a", encoding="utf-8", buffering=1)
                       if log_path else nullcontext())
        with log_context as log:
            write_injection_type(tester.injection_type, tester.injection_state_path)
            if log:
                log.write(json.dumps({"event": "start", "run_id": run_id}) + "\n")
            print(f"RUN_ID={run_id}", flush=True)
            print("Using the 'Slow Blockwise Allocation Scheduler' with 1 test algorithm",
                  flush=True)
            try:
                while not stopped:
                    if options.scan_mode == "full":
                        print("(loop %d)" % pass_number, flush=True)
                    pass_number += 1
                    pass_started = time.monotonic()
                    tested_frames = 0
                    remaining = pass_pages
                    while not stopped and (remaining is None or remaining >= minimum_pages):
                        page_count = (options.frames_per_check if remaining is None
                                      else min(options.frames_per_check, remaining))
                        if remaining is not None and 0 < remaining - page_count < minimum_pages:
                            page_count = max(minimum_pages, remaining - minimum_pages)
                        batch_started = time.monotonic()
                        result = scheduler.run_round(run_id, page_count, tester)
                        finished = time.monotonic()
                        attempt += 1
                        if log:
                            record = serialize_round(result, "interactive", attempt,
                                                     tester.injection_type)
                            record["pass"] = pass_number
                            log.write(json.dumps(record, ensure_ascii=False) + "\n")
                        for entry in result.isolated:
                            print("[WARNING] bad frame at pfn %08x (no serdev)" % entry.pfn,
                                  flush=True)
                        if result.memtester.execution_error or result.isolation_errors:
                            for error in (result.memtester.execution_error, *result.isolation_errors):
                                if error:
                                    print(error, file=sys.stderr)
                            return 1
                        tested_frames += page_count
                        elapsed = finished - pass_started
                        batch_elapsed = finished - batch_started
                        if elapsed > 0 and batch_elapsed > 0:
                            print("Tested %d frames in %ds. fps=%d (this batch: %d in %d s: fps=%d)"
                                  % (tested_frames, elapsed, tested_frames / elapsed,
                                     page_count, batch_elapsed, page_count / batch_elapsed),
                                  flush=True)
                        if remaining is not None:
                            remaining -= page_count
                finish = "interrupted"
            finally:
                if log:
                    log.write(json.dumps({"event": "stop", "run_id": run_id,
                                          "reason": finish, "rounds": attempt}) + "\n")
    finally:
        signal.signal(signal.SIGINT, previous_handler)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        if getattr(exc, "errno", None) == errno.ENOSPC:
            print(f"phys_mem 隔离表或页池容量不足：{exc}", file=sys.stderr)
        else:
            print(f"main.py: {exc}", file=sys.stderr)
        sys.exit(1)
