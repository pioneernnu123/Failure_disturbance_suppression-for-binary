"""Run memtester against the pages owned by one phys_mem device session."""

from __future__ import annotations

from dataclasses import dataclass
import getopt
import os
import shlex
import signal
import struct
import subprocess
import tempfile
import time

import physmem
from injection_state import (DEFAULT_INJECTION_STATE_PATH, INJECTION_TYPE_NAMES, read_injection_type,
                             validate_injection_type, write_injection_type)
from tester.scanner_baseclass import ScannerBaseclass


MEMTESTER_BIN = os.environ.get("RAMPAGE_MEMTESTER", "/usr/local/bin/memtester")
MEMTESTER_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "memtester_execution_details.log")
WORD_LIMIT = 1 << (8 * struct.calcsize("@L"))


@dataclass(frozen=True)
class Failure:
    error_type: int
    byte_offset: int
    side: str
    expected: int
    observed: int


@dataclass(frozen=True)
class Injection:
    error_type: int
    page_index: int
    byte_offset: int
    before: int
    after: int

    @property
    def effective(self):
        return self.before != self.after


@dataclass(frozen=True)
class MemtesterResult:
    failures: tuple
    injection: Injection | None
    returncode: int | None
    execution_error: str | None = None
    tested_indices: tuple | None = None


class MemtesterWrapper(ScannerBaseclass):
    @staticmethod
    def name():
        return "memtester (session-owned pages)"

    @staticmethod
    def shortname():
        return "memtester"

    def __init__(self, reporting=None, extra_args="", injection_type=None,
                 injection_state_path=DEFAULT_INJECTION_STATE_PATH,
                 physmem_device=None, log_path=MEMTESTER_LOG_PATH, binary=None,
                 initialize_injection=True, report_injection=None):
        super().__init__(reporting)
        self.injection_type = validate_injection_type(
            0 if injection_type is None else injection_type)
        self.injection_state_path = injection_state_path
        self.physmem_device = physmem_device
        self.log_path = log_path
        self.binary = binary
        self.report_injection = report_injection
        args = shlex.split(extra_args) if isinstance(extra_args, str) else list(extra_args)
        try:
            flags, positional = getopt.getopt(args, "i:c:u")
        except getopt.GetoptError as exc:
            raise ValueError(f"invalid --memtester-args: {exc}") from exc
        if positional:
            raise ValueError("--memtester-args cannot override the session size or loop count")
        flags = dict(flags)
        page = int(flags.get("-i", "-1"))
        self.inject_page = page if page >= 0 else None
        self.extra_args = ["-u"] if "-u" in flags else []
        if initialize_injection:
            write_injection_type(self.injection_type, self.injection_state_path)

    @staticmethod
    def _parse_result(text, session_id, page_count, page_size):
        lines = text.split("\n")
        legacy = lines[0] == f"RAMPAGE_RESULT_V3 {session_id} {page_count}"
        if not legacy and lines[0] != f"RAMPAGE_RESULT_V4 {session_id} {page_count}":
            return (), None, "memtester result has no matching session header"
        failures = []
        injection = None
        prechecked_page = None
        seen_inject = False
        complete = False
        error = "rebuild memtester to enable injection precheck and batch address verification" if legacy else None
        # The final element is either empty or an interrupted, unflushed line.
        for line in lines[1:-1]:
            parts = line.split()
            try:
                if complete:
                    raise ValueError
                if len(parts) == 6 and parts[0] == "BAD":
                    error_type, offset = int(parts[1]), int(parts[2])
                    expected, observed = map(int, parts[4:])
                    if (not 1 <= error_type <= 255 or
                            not 0 <= offset < page_count * page_size or
                            parts[3] not in ("A", "B") or
                            not 0 <= expected < WORD_LIMIT or
                            not 0 <= observed < WORD_LIMIT or expected == observed):
                        raise ValueError
                    failures.append(Failure(error_type, offset, parts[3], expected, observed))
                elif len(parts) == 2 and parts[0] == "PRECHECK":
                    page = int(parts[1])
                    if (legacy or seen_inject or prechecked_page is not None or
                            not 0 <= page < page_count or
                            any(finding.byte_offset // page_size == page for finding in failures)):
                        raise ValueError
                    prechecked_page = page
                elif parts == ["INJECT", "NONE"] and not seen_inject:
                    seen_inject = True
                elif len(parts) == 6 and parts[0] == "INJECT" and not seen_inject:
                    kind, page, offset, before, after = map(int, parts[1:])
                    if (not 1 <= kind <= 7 or not 0 <= page < page_count or
                            offset // page_size != page or
                            not 0 <= before < WORD_LIMIT or not 0 <= after < WORD_LIMIT):
                        raise ValueError
                    injection = Injection(kind, page, offset, before, after)
                    seen_inject = True
                    if not legacy and prechecked_page != page:
                        error = error or "memtester injection has no matching target precheck"
                elif parts == ["END", "CHECKED"] and seen_inject:
                    complete = True
                elif legacy and parts == ["END"] and seen_inject:
                    complete = True
                else:
                    raise ValueError
            except ValueError:
                if error is None:
                    error = f"invalid memtester result line: {line}"
        if error is None and (not complete or lines[-1]):
            error = "memtester did not return a complete session result"
        return tuple(failures), injection, error

    def test(self, page_infos, eligible_indices=None):
        device = self.physmem_device
        if device is None or device.session_id is None or not page_infos:
            raise RuntimeError("memtester needs an allocated phys_mem session")
        page_size = physmem.PAGE_SIZE
        if len(page_infos) != device.page_count:
            raise RuntimeError("page count differs from the device session")
        if self.inject_page is not None and self.inject_page >= len(page_infos):
            raise ValueError("-i page index is outside the allocated buffer")

        self.injection_type = read_injection_type(self.injection_state_path, self.injection_type)
        kind = self.injection_type
        if kind and self.inject_page is None:
            raise ValueError("choose an injection page with -i PAGE")
        tested_indices = None
        if eligible_indices is not None:
            selected = set(eligible_indices)
            if kind:
                selected.add(self.inject_page)
            if not selected:
                return MemtesterResult((), None, None, tested_indices=())
            if len(selected) < len(page_infos):
                tested_indices = tuple(sorted(selected))
        if self.report_injection is not None:
            self.report_injection(kind)

        with tempfile.TemporaryFile(mode="w+t", encoding="ascii", errors="replace") as result_file:
            mapped_fd = device.dev()
            result_fd = result_file.fileno()
            # The session's current injection type takes precedence over a legacy -c.
            command = [str(self.binary or MEMTESTER_BIN), *self.extra_args,
                       "-F", str(mapped_fd), "-R", str(result_fd),
                       "-S", str(device.session_id), "-c", str(kind)]
            if kind:
                command += ["-i", str(self.inject_page)]
            if tested_indices is not None:
                command += ["-P", "".join("1" if index in selected else "0"
                                          for index in range(len(page_infos)))]
            command += [f"{len(page_infos) * page_size}B", "1"]
            with open(self.log_path, "a", encoding="utf-8") as log:
                log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} run={device.run_id} "
                          f"session={device.session_id} ===\n")
                log.write(f"Injection type: {kind} ({INJECTION_TYPE_NAMES[kind]})\n")
                log.write(f"PFNs: {', '.join(hex(page.pfn) for page in page_infos)}\n")
                log.write(f"Command: {' '.join(command)}\n")
                log.flush()
                # The child briefly inherits the terminal process group before setsid().
                # Defer Ctrl+C until the active test has exited.
                previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
                try:
                    completed = subprocess.run(command, stdout=log,
                                               stderr=subprocess.STDOUT, check=False,
                                               pass_fds=(mapped_fd, result_fd), start_new_session=True)
                except OSError as exc:
                    error = f"could not execute memtester: {exc}"
                    log.write(error + "\n")
                    return MemtesterResult((), None, None, error)
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
                result_file.seek(0)
                failures, injection, error = self._parse_result(
                    result_file.read(), device.session_id, len(page_infos), page_size)
                expected_status = ((2 if any(f.error_type == 1 for f in failures) else 0) |
                                   (4 if any(f.error_type != 1 for f in failures) else 0))
                if completed.returncode not in (0, 2, 4, 6):
                    error = f"memtester execution failed ({completed.returncode})" + (
                        f": {error}" if error else "")
                elif completed.returncode != expected_status:
                    error = error or "memtester exit status disagrees with failure records"
                if tested_indices is not None and any(
                        finding.byte_offset // page_size not in selected for finding in failures):
                    error = error or "memtester reported a page excluded by the retest interval"
                if not kind and injection is not None:
                    error = "unexpected injection in no-injection test"
                if kind and injection is not None:
                    if injection.error_type != kind or injection.page_index != self.inject_page:
                        error = "memtester injection differs from requested type/page"
                for finding in failures:
                    page = page_infos[finding.byte_offset // page_size]
                    log.write(f"Failure type={finding.error_type} "
                              f"offset={finding.byte_offset} side={finding.side} "
                              f"PFN={page.pfn:#x} expected={finding.expected:#x} "
                              f"observed={finding.observed:#x}\n")
                log.write(f"Injection: {injection!r}\n")
                if error:
                    log.write(f"Execution error: {error}\n")
                return MemtesterResult(failures, injection, completed.returncode, error,
                                       tested_indices)


ScannerBaseclass.register(MemtesterWrapper)
