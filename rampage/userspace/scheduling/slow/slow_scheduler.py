"""One allocation, memtester, report, and isolation confirmation round."""

from contextlib import ExitStack
from dataclasses import dataclass
import errno
from typing import Optional

import physmem
from status import TimestampingFacility


@dataclass(frozen=True)
class RoundResult:
    run_id: int
    session_id: int
    pfns: tuple
    memtester: object
    isolated: tuple
    probe_pfns: tuple
    global_pages_before: int
    global_pages_after: Optional[int]
    isolation_errors: tuple = ()
    capacity_exhausted: bool = False
    session_pages_released: Optional[int] = None
    session_pages_held: Optional[int] = None

    @property
    def tested_pfns(self):
        if self.memtester.execution_error:
            return ()
        if self.memtester.tested_indices is None:
            return self.pfns
        return tuple(self.pfns[index] for index in self.memtester.tested_indices)

    @property
    def injection_effective(self):
        injection = self.memtester.injection
        return injection is not None and injection.effective

    @property
    def interception_success(self):
        injection = self.memtester.injection
        if (not self.injection_effective or self.memtester.execution_error or
                self.isolation_errors):
            return False
        return any(entry.index == injection.page_index and
                   entry.byte_offset == injection.byte_offset and
                   entry.error_type == injection.error_type and
                   entry.origin == physmem.ORIGIN_SIMULATED and
                   entry.state == physmem.PAGE_HELD
                   for entry in self.isolated)


class SlowScheduler:
    def __init__(self, device_path="/dev/phys_mem", frame_status=None, retest_time=0,
                 stop_requested=None):
        self.device_path = device_path
        self.frame_status = frame_status
        self.timestamping = TimestampingFacility()
        self.retest_age = self.timestamping.seconds_to_timestamp(retest_time)
        self.stop_requested = stop_requested

    def _eligible_indices(self, pfns, now):
        threshold = now - self.retest_age
        with self.frame_status.locked_records():
            eligible = []
            for index, pfn in enumerate(pfns):
                record = self.frame_status.read_record(pfn)
                last_test = record.last_successful_test
                if record.num_errors or not last_test or last_test <= threshold:
                    eligible.append(index)
            return tuple(eligible)

    def record_frame_results(self, result):
        """Use the same status record layout and timestamps as the PFN scanner."""
        tested = set(result.tested_pfns)
        failed = {result.pfns[finding.byte_offset // physmem.PAGE_SIZE]
                  for finding in result.memtester.failures}
        with self.frame_status.locked_records():
            now = self.timestamping.timestamp()
            for pfn in result.pfns:
                record = self.frame_status.read_record(pfn)
                record.last_claiming_attempt = now
                # The allocation ABI has neither a per-PFN claim source nor its cost.
                record.last_claiming_time_jiffies = 0
                record.last_successful_claiming_method = 0
                if pfn in failed:
                    record.last_failed_test = now
                    record.num_errors += 1
                elif pfn in tested:
                    record.last_successful_test = now
                    record.num_errors = 0
                self.frame_status.write_record(pfn, record)

    def _test_available_batch(self, run_id, page_count, tester, sessions):
        skipped = []
        while True:
            device = sessions.enter_context(physmem.Physmem(self.device_path))
            try:
                session_id = device.allocate(run_id, page_count)
            except OSError as exc:
                if skipped and exc.errno in (errno.ENOSPC, errno.ENOMEM):
                    # Release the pages reserved by the search before the next round.
                    batch = skipped.pop()
                    return batch, skipped
                raise

            page_infos = device.pages()
            pfns = tuple(page.pfn for page in page_infos)
            if len(set(pfns)) != len(pfns):
                raise RuntimeError("driver returned duplicate PFNs")
            tester.physmem_device = device
            if self.frame_status is not None and self.retest_age:
                eligible = self._eligible_indices(pfns, self.timestamping.timestamp())
                result = tester.test(page_infos, eligible)
            else:
                result = tester.test(page_infos)
            batch = device, session_id, pfns, result
            if (result.tested_indices != () or result.execution_error or
                    (self.stop_requested is not None and self.stop_requested())):
                return batch, skipped

            pool = device.status()
            if pool.total_pages + page_count > min(pool.max_total_pages, pool.max_isolated_pages):
                return batch, skipped
            # Keep skipped pages out of the allocator while trying subsequent allocations.
            skipped.append(batch)

    def run_round(self, run_id, page_count, tester, probe=True):
        if page_count < 1:
            raise ValueError("page_count must be positive")
        with physmem.Physmem(self.device_path) as control:
            global_pages_before = control.status().total_pages

        errors = []
        capacity_exhausted = False
        result = None
        finished = None
        reported = {}
        try:
            with ExitStack() as sessions:
                batch, skipped = self._test_available_batch(run_id, page_count, tester, sessions)
                device, session_id, pfns, result = batch
                by_page = {}
                for finding in result.failures:
                    index = finding.byte_offset // physmem.PAGE_SIZE
                    by_page.setdefault(index, []).append(finding)
                for index, findings in by_page.items():
                    unexplained = [finding for finding in findings
                                   if not self._is_simulated(finding, result.injection)]
                    origin = (physmem.ORIGIN_UNKNOWN if unexplained or result.execution_error
                              else physmem.ORIGIN_SIMULATED)
                    finding = (unexplained or findings)[0]
                    try:
                        response = device.report(finding.byte_offset, finding.error_type, origin)
                        if response.state != physmem.PAGE_PENDING:
                            raise RuntimeError("driver did not mark the page pending")
                    except (OSError, RuntimeError) as exc:
                        errors.append(f"report page {index}: {exc}")
                        capacity_exhausted |= getattr(exc, "errno", None) == errno.ENOSPC
                        continue
                    reported[index] = (finding, origin)
                finished = device.finish()
                if finished.released != page_count - len(by_page) or finished.held != len(by_page):
                    errors.append("session release counts disagree with the reported test pages")
                for skipped_device, skipped_session_id, skipped_pfns, _ in skipped:
                    released = skipped_device.finish()
                    if released.released != len(skipped_pfns) or released.held:
                        errors.append(f"could not confirm release of skipped session {skipped_session_id}")
        except OSError as exc:
            if result is None:
                raise
            errors.append(f"finish or close test session: {exc}")

        # The last descriptor and all VMAs have closed before the new query.
        global_pages_after = None
        entries = ()
        probe_pfns = ()
        try:
            with physmem.Physmem(self.device_path) as control:
                global_pages_after = control.status().total_pages
                batch_entries = tuple(control.entries(run_id))
                entries = tuple(entry for entry in batch_entries if entry.session_id == session_id)
            if {entry.index for entry in entries} != reported.keys():
                errors.append("driver isolation records disagree with reports")
            for entry in entries:
                report = reported.get(entry.index)
                if report is None:
                    continue
                finding, origin = report
                if (entry.pfn != pfns[entry.index] or entry.byte_offset != finding.byte_offset or
                        entry.error_type != finding.error_type or entry.origin != origin or
                        entry.state != physmem.PAGE_HELD or entry.map_refs != 0 or
                        entry.module_refs != 1 or entry.page_refcount < 1):
                    errors.append(f"driver did not confirm module-held PFN for page {entry.index}")
            if probe and not errors:
                with physmem.Physmem(self.device_path) as next_round:
                    next_round.allocate(run_id, 1)
                    probe_pfns = (next_round.page(0).pfn,)
                    held_pfns = {entry.pfn for entry in batch_entries if entry.state == physmem.PAGE_HELD}
                    if set(probe_pfns) & held_pfns:
                        errors.append("isolated PFN returned to a new test buffer")
        except OSError as exc:
            errors.append(f"confirm isolation or probe fresh allocation: {exc}")
            capacity_exhausted |= exc.errno == errno.ENOSPC

        return RoundResult(run_id, session_id, pfns, result, entries, probe_pfns,
                           global_pages_before, global_pages_after, tuple(errors),
                           capacity_exhausted,
                           session_pages_released=finished.released if finished else None,
                           session_pages_held=finished.held if finished else None)

    @staticmethod
    def _is_simulated(finding, injection):
        return (injection is not None and finding.error_type == injection.error_type
                and finding.byte_offset == injection.byte_offset
                and finding.side == "A" and injection.after == (injection.before ^ 1)
                and finding.expected == injection.before and finding.observed == injection.after)
