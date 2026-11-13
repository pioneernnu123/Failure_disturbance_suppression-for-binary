"""One allocation, memtester, report, and isolation confirmation round."""

from dataclasses import dataclass
import errno
from typing import Optional

import physmem


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
    def __init__(self, device_path="/dev/phys_mem"):
        self.device_path = device_path

    def run_round(self, run_id, page_count, tester, probe=True):
        if page_count < 1:
            raise ValueError("page_count must be positive")
        with physmem.Physmem(self.device_path) as control:
            global_pages_before = control.status().total_pages

        errors = []
        capacity_exhausted = False
        result = None
        reported = {}
        try:
            with physmem.Physmem(self.device_path) as device:
                session_id = device.allocate(run_id, page_count)
                page_infos = device.pages()
                pfns = tuple(page.pfn for page in page_infos)
                if len(set(pfns)) != len(pfns):
                    raise RuntimeError("driver returned duplicate PFNs")
                tester.physmem_device = device
                result = tester.test(page_infos)
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
        except OSError as exc:
            if result is None:
                raise
            errors.append(f"close test session: {exc}")

        # The last descriptor and all VMAs have closed before the new query.
        global_pages_after = None
        entries = ()
        probe_pfns = ()
        try:
            with physmem.Physmem(self.device_path) as control:
                global_pages_after = control.status().total_pages
                batch_entries = tuple(control.entries(run_id))
                entries = tuple(entry for entry in batch_entries if entry.session_id == session_id)
            if not result.failures and global_pages_after != global_pages_before:
                errors.append("healthy page release could not be confirmed from the pool count")
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
                           capacity_exhausted)

    @staticmethod
    def _is_simulated(finding, injection):
        return (injection is not None and finding.error_type == injection.error_type
                and finding.byte_offset == injection.byte_offset
                and finding.side == "A" and injection.after == (injection.before ^ 1)
                and finding.expected == injection.before and finding.observed == injection.after)
