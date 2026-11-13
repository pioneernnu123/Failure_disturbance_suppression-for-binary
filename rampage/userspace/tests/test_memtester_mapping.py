"""Protocol and orchestration checks that run without a kernel device."""

import ctypes
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import types
import unittest
from unittest import mock

USERSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(USERSPACE))

import physmem
import main as interactive
import run_memory_test
from injection_state import write_injection_type
from physmem import physmem as protocol
from scheduling.slow.slow_scheduler import RoundResult, SlowScheduler
from tester.memtester_wrapper import (Failure, Injection, MemtesterResult,
                                      MemtesterWrapper)


class ProtocolTests(unittest.TestCase):
    def test_ioctl_layout_is_fixed_width(self):
        structures = (protocol.Allocate, protocol.PageInfo, protocol.Report,
                      protocol.Status, protocol.Entry, protocol.Restore)
        self.assertEqual([ctypes.sizeof(item) for item in structures],
                         [32, 32, 40, 56, 72, 32])
        self.assertEqual(protocol.IOCTL_REPORT, 0xC0284B02)
        self.assertEqual(protocol.IOCTL_ENTRY, 0xC0484B04)

    def test_result_requires_session_and_real_offset(self):
        failures, injection, error = MemtesterWrapper._parse_result(
            "RAMPAGE_RESULT_V3 42 8\nBAD 2 20480 A 100 101\n"
            "INJECT 2 5 20480 100 101\nEND\n", 42, 8, 4096)
        self.assertIsNone(error)
        self.assertEqual(failures, (Failure(2, 20480, "A", 100, 101),))
        self.assertEqual(injection, Injection(2, 5, 20480, 100, 101))
        _, ineffective, error = MemtesterWrapper._parse_result(
            "RAMPAGE_RESULT_V3 42 8\nINJECT 2 5 20480 100 100\nEND\n",
            42, 8, 4096)
        self.assertFalse(ineffective.effective)
        self.assertIsNone(error)
        failures, _, error = MemtesterWrapper._parse_result(
            "RAMPAGE_RESULT_V3 99 8\nINJECT NONE\nEND\n", 42, 8, 4096)
        self.assertFalse(failures)
        self.assertIn("matching session header", error)
        failures, _, error = MemtesterWrapper._parse_result(
            "RAMPAGE_RESULT_V3 42 8\nBAD 2 32768 A 100 101\nINJECT NONE\nEND\n",
            42, 8, 4096)
        self.assertFalse(failures)
        self.assertIn("invalid memtester result", error)

    def test_incomplete_output_preserves_flushed_evidence(self):
        failures, injection, error = MemtesterWrapper._parse_result(
            "RAMPAGE_RESULT_V3 42 8\nINJECT 2 5 20480 100 101\n"
            "BAD 2 20480 A 100 101\nBAD 2 2048", 42, 8, 4096)
        self.assertEqual(failures, (Failure(2, 20480, "A", 100, 101),))
        self.assertTrue(injection.effective)
        self.assertIn("complete session result", error)

    def test_wrapper_passes_session_descriptor_and_distinguishes_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state = str(Path(directory) / "state")
            log = str(Path(directory) / "test.log")
            with tempfile.TemporaryFile() as device_file:
                device = types.SimpleNamespace(
                    session_id=42, run_id=99, page_count=8,
                    dev=lambda: device_file.fileno())
                wrapper = MemtesterWrapper(extra_args="-i 5", injection_type=2,
                                           injection_state_path=state,
                                           physmem_device=device, log_path=log)
                seen = []

                def fake_run(command, *, stdout, stderr, check, pass_fds, start_new_session):
                    self.assertTrue(start_new_session)
                    seen.append((command, pass_fds))
                    result_fd = int(command[command.index("-R") + 1])
                    os.write(result_fd, b"RAMPAGE_RESULT_V3 42 8\n"
                               b"BAD 2 20480 A 100 101\nINJECT 2 5 20480 100 101\nEND\n")
                    return types.SimpleNamespace(returncode=4)

                with mock.patch("tester.memtester_wrapper.subprocess.run", side_effect=fake_run):
                    pages = [types.SimpleNamespace(pfn=100 + i) for i in range(8)]
                    result = wrapper.test(pages)
                self.assertEqual(result.failures, (Failure(2, 20480, "A", 100, 101),))
                self.assertEqual(result.injection.page_index, 5)
                command, passed = seen[0]
                self.assertEqual(command[command.index("-S") + 1], "42")
                self.assertEqual(command[-2:], [f"{8 * physmem.PAGE_SIZE}B", "1"])
                self.assertEqual(set(passed), {device_file.fileno(),
                                               int(command[command.index("-R") + 1])})
                self.assertIn("offset=20480", Path(log).read_text())

    def test_wrapper_reads_latest_type_each_call_with_fixed_page_argument(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryFile() as device_file:
            state_path = Path(directory) / "injection.state"
            page_size = physmem.PAGE_SIZE
            offset = 5 * page_size
            pages = [types.SimpleNamespace(pfn=100 + i) for i in range(8)]
            device = types.SimpleNamespace(
                session_id=42, run_id=99, page_count=8, dev=device_file.fileno)
            wrapper = MemtesterWrapper(extra_args="-i 5", injection_type=0,
                                       injection_state_path=state_path,
                                       physmem_device=device, log_path=Path(directory) / "test.log")
            kinds = []

            def fake_run(command, **kwargs):
                kind = int(command[command.index("-c") + 1])
                kinds.append(kind)
                result_fd = int(command[command.index("-R") + 1])
                self.assertEqual("-i" in command, bool(kind))
                report = "RAMPAGE_RESULT_V3 42 8\n"
                if kind:
                    report += f"INJECT {kind} 5 {offset} 100 101\nBAD {kind} {offset} A 100 101\n"
                else:
                    report += "INJECT NONE\n"
                os.write(result_fd, (report + "END\n").encode())
                return types.SimpleNamespace(returncode={0: 0, 1: 2, 7: 4}[kind])

            with mock.patch("tester.memtester_wrapper.subprocess.run", side_effect=fake_run):
                for update in (None, 1, None, 7, 0):
                    if update is not None:
                        write_injection_type(update, state_path)
                    self.assertIsNone(wrapper.test(pages).execution_error)
            self.assertEqual(kinds, [0, 1, 1, 7, 0])


class SchedulerTests(unittest.TestCase):
    def test_simulated_classification_requires_correlated_evidence(self):
        injection = Injection(2, 5, 20480, 100, 101)
        self.assertTrue(SlowScheduler._is_simulated(Failure(2, 20480, "A", 100, 101), injection))
        self.assertFalse(SlowScheduler._is_simulated(Failure(2, 20480, "B", 100, 101), injection))
        self.assertFalse(SlowScheduler._is_simulated(Failure(2, 20488, "A", 100, 101), injection))
        self.assertFalse(SlowScheduler._is_simulated(Failure(2, 20480, "A", 100, 103), injection))

    def test_session_closes_before_isolation_confirmation(self):
        state = {"session_closed": False, "reports": [], "entries": []}

        class Device:
            def __init__(self, path):
                self.session_id = None
                self.run_id = None
                self.page_count = 0

            def __enter__(self):
                return self

            def __exit__(self, *_):
                if self.session_id == 42:
                    state["session_closed"] = True
                    for offset, kind, origin in state["reports"]:
                        state["entries"].append(types.SimpleNamespace(
                            session_id=42, index=offset // physmem.PAGE_SIZE,
                            pfn=105, byte_offset=offset, error_type=kind,
                            origin=origin, state=physmem.PAGE_HELD, map_refs=0,
                            module_refs=1, page_refcount=1))

            def allocate(self, run_id, count):
                self.run_id, self.page_count = run_id, count
                self.session_id = 42 if count == 8 else 43
                return self.session_id

            def pages(self):
                return [types.SimpleNamespace(pfn=100 + i) for i in range(8)]

            def page(self, index):
                return types.SimpleNamespace(pfn=200)

            def report(self, offset, kind, origin):
                state["reports"].append((offset, kind, origin))
                return types.SimpleNamespace(state=physmem.PAGE_PENDING)

            def entries(self, run_id):
                if not state["session_closed"]:
                    raise AssertionError("queried isolation before closing the test session")
                return iter(state["entries"])

            def status(self):
                return types.SimpleNamespace(total_pages=len(state["entries"]))

        offset = 5 * physmem.PAGE_SIZE
        injected = Failure(2, offset, "A", 100, 101)
        unexplained = Failure(2, offset + 8, "B", 100, 103)
        injection = Injection(2, 5, offset, 100, 101)
        for findings, error, expected in (
                ((injected,), None, (offset, 2, physmem.ORIGIN_SIMULATED)),
                ((injected, unexplained), None, (offset + 8, 2, physmem.ORIGIN_UNKNOWN)),
                ((injected,), "memtester interrupted", (offset, 2, physmem.ORIGIN_UNKNOWN))):
            with self.subTest(findings=findings, error=error):
                state.update(session_closed=False, reports=[], entries=[])
                tester = types.SimpleNamespace(
                    test=lambda pages: MemtesterResult(findings, injection, 4, error))
                with mock.patch.object(physmem, "Physmem", Device):
                    outcome = SlowScheduler("/dev/fake").run_round(99, 8, tester)
                self.assertEqual(outcome.interception_success,
                                 expected[2] == physmem.ORIGIN_SIMULATED)
                self.assertEqual(outcome.probe_pfns, (200,))
                self.assertEqual(state["reports"], [expected])

    def test_effective_but_unconfirmed_injection_counts_in_case_rate(self):
        offset = 5 * physmem.PAGE_SIZE
        baseline = RoundResult(99, 1, (), MemtesterResult((), None, 0), (), (), 0, 0)
        injection = Injection(2, 5, offset, 100, 101)
        failed = RoundResult(99, 2, (), MemtesterResult((), injection, 0), (), (),
                             0, None, ("isolation query failed",))
        detected = Injection(6, 5, offset, 100, 101)
        held = types.SimpleNamespace(index=5, pfn=100, byte_offset=offset,
                                    error_type=6, origin=physmem.ORIGIN_SIMULATED,
                                    state=physmem.PAGE_HELD, map_refs=0, module_refs=1,
                                    page_refcount=1, last_error=0)
        success = RoundResult(99, 3, (), MemtesterResult((), detected, 4), (held,), (), 0, 1)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
                SlowScheduler, "run_round", side_effect=[baseline, failed, success]):
            code = run_memory_test.main(["--run-id", "99", "--case", "3-3-0008",
                                         "--output-dir", directory])
            summary = json.loads((Path(directory) / "summary.json").read_text())
        self.assertEqual(code, 1)
        self.assertEqual(summary["cases"]["3-3-0008"]["valid"], 2)
        self.assertEqual(summary["cases"]["3-3-0008"]["successful"], 1)

    def test_interactive_local_pass_repeats_until_sigint_with_one_run_id(self):
        counts = []
        output = StringIO()

        def fake_round(run_id, page_count, tester):
            counts.append(page_count)
            tester.report_injection(0)
            if len(counts) == 3:
                signal.raise_signal(signal.SIGINT)
            held = (types.SimpleNamespace(index=5, pfn=0x1234, byte_offset=20480,
                                          error_type=1, origin=physmem.ORIGIN_UNKNOWN,
                                          state=physmem.PAGE_HELD, map_refs=0, module_refs=1,
                                          page_refcount=1, last_error=0),)
            return RoundResult(run_id, len(counts), (), MemtesterResult((), None, 0),
                               held if len(counts) == 2 else (), (), 0, 0)

        with tempfile.TemporaryDirectory() as directory, redirect_stdout(output), mock.patch.object(
                SlowScheduler, "run_round", side_effect=fake_round):
            log_path = Path(directory) / "memtester-slow.log"
            state_path = Path(directory) / "injection.state"
            code = interactive.main([
                "-t", "memtester", "--memtester-args=-i 5",
                "--memtester-inject-type=0", "-a", "slow",
                "--frames-per-check=8", "--scan-mode=local",
                f"--max-memory={14 * physmem.PAGE_SIZE}B",
                "--logfile", str(log_path), "--memtester-inject-file", str(state_path)])
            records = [json.loads(line) for line in log_path.read_text().splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual(counts, [8, 6, 8])
        self.assertEqual(records[0]["event"], "start")
        self.assertEqual([record["pass"] for record in records[1:-1]], [1, 1, 2])
        self.assertEqual(records[-1]["event"], "stop")
        self.assertEqual(records[-1]["reason"], "interrupted")
        self.assertEqual(len({record["run_id"] for record in records}), 1)
        console = output.getvalue()
        self.assertEqual(console.count("当前错误类型：None"), 3)
        self.assertIn("Tested 14 frames in", console)
        self.assertIn("[WARNING] bad frame at pfn 00001234 (no serdev)", console)
        self.assertEqual(console.count("RUN_ID="), 1)
        self.assertNotIn("session=", console)
        self.assertNotIn("effective=", console)
        self.assertNotIn("intercepted=", console)


if __name__ == "__main__":
    unittest.main()
