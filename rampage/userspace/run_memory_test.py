#!/usr/bin/env python3
"""Run the four acceptance cases on fresh phys_mem sessions under one RUN_ID."""

import argparse
from dataclasses import asdict
import errno
import json
import platform
from pathlib import Path
import sys
import time

from scheduling.slow.slow_scheduler import SlowScheduler
from tester import memtester_wrapper
from tester.memtester_wrapper import MemtesterWrapper


CASES = {
    "3-3-0006": [1] * 5,
    "3-3-0007": [3, 4, 5],
    "3-3-0008": [2, 6],
    "3-3-0009": [7] * 5,
}


def serialize_round(result, case_id, attempt, injection_type):
    return {
        "case": case_id,
        "attempt": attempt,
        "run_id": result.run_id,
        "session_id": result.session_id,
        "injection_type": injection_type,
        "pfns": list(result.pfns),
        "injection": (asdict(result.memtester.injection)
                      if result.memtester.injection else None),
        "failures": [asdict(item) for item in result.memtester.failures],
        "isolated": [{"index": item.index, "pfn": item.pfn,
                      "byte_offset": item.byte_offset,
                      "error_type": item.error_type, "origin": item.origin,
                      "state": item.state, "map_refs": item.map_refs,
                      "module_refs": item.module_refs,
                      "page_refcount": item.page_refcount,
                      "last_error": item.last_error}
                     for item in result.isolated],
        "probe_pfns": list(result.probe_pfns),
        "global_pages_before": result.global_pages_before,
        "global_pages_after": result.global_pages_after,
        "memtester_exit_code": result.memtester.returncode,
        "execution_error": result.memtester.execution_error,
        "isolation_errors": list(result.isolation_errors),
        "capacity_exhausted": result.capacity_exhausted,
        "effective": result.injection_effective,
        "intercepted": result.interception_success,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=int, default=None,
                        help="unique nonzero batch number; generated if omitted")
    parser.add_argument("--pages", type=int, default=8)
    parser.add_argument("--inject-page", type=int, default=5)
    parser.add_argument("--device", default="/dev/phys_mem")
    parser.add_argument("--memtester", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--case", choices=["all", *CASES], default="all")
    parser.add_argument("--retry-ineffective", type=int, default=3)
    args = parser.parse_args(argv)
    run_id = (args.run_id if args.run_id is not None
              else time.time_ns() & ((1 << 63) - 1))
    if not 0 < run_id < 2**64 or args.pages <= args.inject_page or args.inject_page < 0:
        parser.error("RUN_ID must be positive and --pages must include --inject-page")
    if args.retry_ineffective < 0:
        parser.error("--retry-ineffective must be nonnegative")
    if args.memtester:
        memtester_wrapper.MEMTESTER_BIN = args.memtester
    output_dir = Path(args.output_dir or (Path.home() / "failure-disturbance-runs" / str(run_id))).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    if summary_path.exists():
        parser.error("summary.json already exists; use a new output directory for another run")
    scheduler = SlowScheduler(args.device)
    summary = {"run_id": run_id, "pages_per_round": args.pages,
               "injection_page": args.inject_page, "baseline": None,
               "kernel": platform.uname()._asdict(),
               "module_version": (Path("/sys/module/phys_mem/version").read_text().strip()
                                  if Path("/sys/module/phys_mem/version").exists()
                                  else "unavailable"),
               "build_info": (Path(__file__).with_name("build-info.txt").read_text()
                              if Path(__file__).with_name("build-info.txt").exists()
                              else "unavailable"),
               "memtester": memtester_wrapper.MEMTESTER_BIN,
               "cases": {}, "rounds": []}

    def save():
        temporary = summary_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        temporary.replace(summary_path)

    def round_once(case_id, attempt, injection_type):
        state_path = output_dir / f"{case_id}-{attempt:02d}.state"
        log_path = output_dir / f"{case_id}-{attempt:02d}.log"
        try:
            tester = MemtesterWrapper(
                extra_args=(f"-i {args.inject_page}" if injection_type else ""),
                injection_type=injection_type,
                injection_state_path=str(state_path),
                log_path=str(log_path))
            result = scheduler.run_round(run_id, args.pages, tester)
            record = serialize_round(result, case_id, attempt, injection_type)
        except (OSError, RuntimeError, ValueError) as exc:
            record = {"case": case_id, "attempt": attempt, "run_id": run_id,
                      "injection_type": injection_type, "session_id": None,
                      "effective": False, "intercepted": False,
                      "execution_error": str(exc), "isolation_errors": [],
                      "capacity_exhausted": getattr(exc, "errno", None) == errno.ENOSPC}
        record["log"] = log_path.name
        summary["rounds"].append(record)
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\nRound result\n")
            json.dump(record, log, ensure_ascii=False, indent=2)
            log.write("\n")
        print(f"{case_id} attempt={attempt} session={record['session_id']} "
              f"effective={record['effective']} intercepted={record['intercepted']} "
              f"log={log_path}", flush=True)
        return record

    print(f"RUN_ID={run_id} output={output_dir}", flush=True)
    save()
    baseline = round_once("baseline", 1, 0)
    summary["baseline"] = baseline
    save()
    if baseline["execution_error"] or baseline["isolation_errors"]:
        raise RuntimeError(f"baseline execution or page release failed, see {baseline['log']}")
    if baseline["failures"] or baseline["isolated"]:
        raise RuntimeError("no-injection baseline found a bad page; inspect its log")

    selected = CASES if args.case == "all" else {args.case: CASES[args.case]}
    for case_id, kinds in selected.items():
        valid = successful = attempts = 0
        stop_reason = None
        max_attempts = len(kinds) + args.retry_ineffective
        while valid < len(kinds) and attempts < max_attempts:
            kind = kinds[valid]
            attempts += 1
            record = round_once(case_id, attempts, kind)
            if record["effective"]:
                valid += 1
                successful += int(record["intercepted"])
            elif not record["execution_error"] and not record["isolation_errors"]:
                record["ineffective_reason"] = (
                    "no injection event" if record["injection"] is None
                    else "observed value did not change after the injection")
            else:
                stop_reason = f"no confirmed injection and round failed, see {record['log']}"
            if record["capacity_exhausted"]:
                stop_reason = f"module capacity exhausted, see {record['log']}"
            rate = successful / valid if valid else 0.0
            passed = valid == len(kinds) and rate >= 0.95 and stop_reason is None
            summary["cases"][case_id] = {
                "required_valid": len(kinds), "valid": valid,
                "successful": successful, "attempts": attempts,
                "interception_rate": rate, "passed": passed,
                "stop_reason": stop_reason,
            }
            save()
            if stop_reason:
                print(stop_reason, file=sys.stderr)
                return 1
        print(f"{case_id}: {successful}/{valid} valid, pass={passed}", flush=True)
    return 0 if all(case["passed"] for case in summary["cases"].values()) else 1


def cli():
    try:
        return main()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"run_memory_test: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(cli())
