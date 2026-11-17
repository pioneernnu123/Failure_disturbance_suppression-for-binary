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
from itertools import groupby
import json
from pathlib import Path
import re
import signal
import sys
import time

from frame import FrameStatus
from injection_state import DEFAULT_INJECTION_STATE_PATH, write_injection_type
from physmem import PAGE_SIZE
from run_memory_test import serialize_round
from scheduling.slow.slow_scheduler import SlowScheduler
from status import FileBasedConfiguration
from tester.memtester_wrapper import MemtesterWrapper


def parse_memory_size(value):
    """Convert values such as 512M, 2G or 4GiB to bytes."""
    match = re.match(r"^([1-9][0-9]*)\s*([KMGT]?)(?:I?B)?$", value.strip(), re.I)
    if not match:
        raise ValueError("use a size such as 512M, 2G or 4GiB")

    amount = int(match.group(1))
    unit = match.group(2).upper()
    shifts = {"": 0, "K": 10, "M": 20, "G": 30, "T": 40}
    return amount << shifts[unit]


class PrintSchedulerReporting:
    def __init__(self, chunksize, logfile, serdev):
        self.chunksize = chunksize
        self.logfile = logfile
        self.serdev = serdev
        self.started = self.chunk_started = time.monotonic()
        self.frames_tested = self.chunk_frames = 0
        self.tested_pfns = []
        if self.logfile:
            self.logfile.write("---log reset---\n")

    def report_bad_frame(self, pfn):
        if self.serdev:
            self.serdev.write(("bad frame at pfn %08x\n" % pfn).encode("ascii"))
        else:
            print("[WARNING] bad frame at pfn %08x (no serdev)" % pfn, flush=True)

    def report_frame_tested(self, pfn):
        self.frames_tested += 1
        self.chunk_frames += 1
        if self.serdev:
            self.tested_pfns.append(pfn)
        if self.chunksize and self.chunk_frames >= self.chunksize:
            self.print_stats()

    def print_stats(self):
        now = time.monotonic()
        elapsed = now - self.started
        chunk_elapsed = now - self.chunk_started
        if self.chunksize and self.chunk_frames and chunk_elapsed > 0:
            stats = (self.frames_tested, elapsed, self.frames_tested / elapsed,
                     self.chunk_frames, chunk_elapsed, self.chunk_frames / chunk_elapsed)
            if self.logfile:
                self.logfile.write("pass: %d frames %d seconds (%d fps) - "
                                   "chunk: %d frames %d seconds (%d fps)\n" % stats)
            print("Tested %d frames in %ds. fps=%d (this batch: %d in %d s: fps=%d)"
                  % stats, flush=True)
        if self.tested_pfns:
            ranges = []
            for _, pfns in groupby(enumerate(sorted(set(self.tested_pfns))),
                                   key=lambda pair: pair[1] - pair[0]):
                frames = [pfn for _, pfn in pfns]
                ranges.append("%08x-%08x" % (frames[0], frames[-1]))
            self.serdev.write(("tested " + " ".join(ranges) + "\n").encode("ascii"))
            self.tested_pfns.clear()
        self.chunk_frames = 0
        self.chunk_started = now


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run memtester until Ctrl+C.")
    parser.add_argument("-t", "--test-algorithms", choices=["memtester"], default="memtester")
    parser.add_argument("-a", "--allocation-strategy", choices=["slow"], default="slow")
    parser.add_argument("--memtester-args", default="", metavar="ARGS",
                        help="extra memtester arguments, for example \"-i 5\"")
    parser.add_argument("--memtester-inject-type", "--memtester-inject-kind",
                        type=int, choices=range(8), default=0, help="initial injection type")
    parser.add_argument("--memtester-inject-file", default=DEFAULT_INJECTION_STATE_PATH)
    parser.add_argument("--frames-per-check", type=int, default=50,
                        help="number of module pages per memtester invocation")
    parser.add_argument("-f", "--report-frequency", type=int, default=50,
                        help="report performance every N pages (0 disables statistics)")
    parser.add_argument("-r", "--run-time", type=int, default=300,
                        help="duration of each full-mode pass in seconds")
    parser.add_argument("--no-delay", action="store_true",
                        help="do not sleep when every allocated page was tested recently")
    parser.add_argument("-s", "--status_file", type=Path,
                        help="path to the PFN status file")
    parser.add_argument("--retest-time", type=int,
                        help="seconds before retesting a PFN that passed")
    parser.add_argument("--serial", metavar="DEVICE", help="serial device for status output")
    parser.add_argument("--scan-mode", choices=["full", "local"], default="full")
    parser.add_argument("--max-memory", type=parse_memory_size, metavar="SIZE",
                        help="maximum amount tested per local pass, for example 2G")
    parser.add_argument("--logfile", type=Path, help="append batch and round records to this file")
    parser.add_argument("--memtester", type=Path, metavar="PATH")
    options = parser.parse_args(argv)

    if options.report_frequency < 0:
        parser.error("--report-frequency must be nonnegative")
    if options.run_time < 0:
        parser.error("--run-time must be nonnegative")
    if options.retest_time is not None and options.retest_time < 0:
        parser.error("--retest-time must be nonnegative")
    if not 0 < options.frames_per_check < 2**32:
        parser.error("--frames-per-check must be a positive page count")
    if options.scan_mode == "local" and options.max_memory is None:
        parser.error("--scan-mode=local requires --max-memory=SIZE")
    if options.scan_mode == "full" and options.max_memory is not None:
        parser.error("--max-memory requires --scan-mode=local")

    pass_pages = None if options.max_memory is None else options.max_memory // PAGE_SIZE
    log_path = options.logfile
    if log_path is None and options.scan_mode == "local":
        log_path = Path(__file__).with_name("rampage-local.log")
    status_path = options.status_file
    retest_time = options.retest_time
    if options.scan_mode == "local":
        status_path = status_path or "/tmp/rampage_memtest_status_local"
        retest_time = 0 if retest_time is None else retest_time
    else:
        status_path = status_path or "/tmp/memtest_status"
        retest_time = 24 * 60 * 60 if retest_time is None else retest_time

    run_id = time.time_ns()
    status_file = FileBasedConfiguration(status_path, 0, FrameStatus)
    stopped = False

    def request_stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    previous_handler = signal.signal(signal.SIGINT, request_stop)
    attempt = pass_number = 0
    finish = "error"
    try:
        tester = MemtesterWrapper(extra_args=options.memtester_args,
                                  injection_type=options.memtester_inject_type,
                                  injection_state_path=options.memtester_inject_file,
                                  binary=options.memtester, initialize_injection=False)
        minimum_pages = 1 if tester.inject_page is None else tester.inject_page + 1
        if options.memtester_inject_type and tester.inject_page is None:
            parser.error("a nonzero --memtester-inject-type requires an injection page")
        if options.frames_per_check < minimum_pages:
            parser.error("--frames-per-check must include the page selected by -i")
        if pass_pages is not None and pass_pages < minimum_pages:
            parser.error("--max-memory must include the page selected by -i")
        serial_context = nullcontext()
        if options.serial:
            try:
                import serial
            except ImportError:
                parser.error("--serial requires pyserial")
            print("Using serial port %s for status" % options.serial, flush=True)
            serial_context = serial.Serial(options.serial, 115200)
        with serial_context as serdev, status_file.open_sparse(), (
                log_path.open("a", encoding="utf-8", buffering=1)
                if log_path else nullcontext()) as log:
            scheduler = SlowScheduler(frame_status=status_file, retest_time=retest_time,
                                      stop_requested=lambda: stopped)
            write_injection_type(tester.injection_type, tester.injection_state_path)
            if log:
                log.write(json.dumps({"event": "start", "run_id": run_id}) + "\n")
            print(f"RUN_ID={run_id}", flush=True)
            print("Using the 'Slow Blockwise Allocation Scheduler' with 1 test algorithm",
                  flush=True)
            idle_delay = 1
            try:
                while not stopped:
                    if options.scan_mode == "full":
                        print("(loop %d)" % pass_number, flush=True)
                    pass_number += 1
                    reporting = PrintSchedulerReporting(options.report_frequency, log, serdev)
                    deadline = (time.monotonic() + options.run_time
                                if options.scan_mode == "full" and options.run_time else None)
                    remaining = pass_pages
                    seen_pfns = set()
                    while not stopped and (remaining is None or remaining >= minimum_pages):
                        page_count = (options.frames_per_check if remaining is None
                                      else min(options.frames_per_check, remaining))
                        if remaining is not None and 0 < remaining - page_count < minimum_pages:
                            page_count = max(minimum_pages, remaining - minimum_pages)
                        result = scheduler.run_round(run_id, page_count, tester)
                        attempt += 1
                        if log:
                            record = serialize_round(result, "interactive", attempt,
                                                     tester.injection_type, compact=True)
                            record["pass"] = pass_number
                            log.write(json.dumps(record, ensure_ascii=False) + "\n")
                        for entry in result.isolated:
                            reporting.report_bad_frame(entry.pfn)
                        scheduler.record_frame_results(result)
                        if result.memtester.execution_error or result.isolation_errors:
                            for error in (result.memtester.execution_error, *result.isolation_errors):
                                if error:
                                    print(error, file=sys.stderr)
                            return 1
                        tested_pfns = result.tested_pfns
                        for pfn in tested_pfns:
                            reporting.report_frame_tested(pfn)
                        if remaining is not None:
                            remaining -= len(set(tested_pfns) - seen_pfns)
                            seen_pfns.update(tested_pfns)
                        if tested_pfns:
                            idle_delay = 1
                        elif not options.no_delay:
                            print("Nothing happened, sleeping for %d second%s" %
                                  (idle_delay, "" if idle_delay == 1 else "s"), flush=True)
                            wakeup = time.monotonic() + idle_delay
                            while not stopped and time.monotonic() < wakeup:
                                time.sleep(max(0, min(1, wakeup - time.monotonic())))
                            idle_delay = min(idle_delay * 2, 500)
                        if deadline is not None and time.monotonic() >= deadline:
                            break
                    reporting.print_stats()
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
