"""Version 3 of /dev/phys_mem for session-owned test pages."""

import ctypes
import mmap
import os

from .mmapwrapper import MmapWrapper


PROTOCOL_VERSION = 3
PAGE_SIZE = mmap.PAGESIZE
PAGE_ACTIVE = 1
PAGE_PENDING = 2
PAGE_HELD = 3
PAGE_RELEASED = 4
ORIGIN_UNKNOWN = 0
ORIGIN_SIMULATED = 1
RESTORE_SIMULATED_ONLY = 1


class Allocate(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("num_pages", ctypes.c_uint32),
                ("run_id", ctypes.c_uint64), ("session_id", ctypes.c_uint64),
                ("page_size", ctypes.c_uint32), ("reserved", ctypes.c_uint32)]


class PageInfo(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("index", ctypes.c_uint32),
                ("session_id", ctypes.c_uint64), ("pfn", ctypes.c_uint64),
                ("state", ctypes.c_uint32), ("reserved", ctypes.c_uint32)]


class Report(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("index", ctypes.c_uint32),
                ("session_id", ctypes.c_uint64), ("byte_offset", ctypes.c_uint64),
                ("error_type", ctypes.c_uint32), ("origin", ctypes.c_uint32),
                ("state", ctypes.c_uint32), ("reserved", ctypes.c_uint32)]


class Status(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
                ("run_id", ctypes.c_uint64), ("held", ctypes.c_uint32),
                ("simulated", ctypes.c_uint32), ("unknown", ctypes.c_uint32),
                ("released", ctypes.c_uint32), ("pending", ctypes.c_uint32),
                ("active_sessions", ctypes.c_uint32), ("total_pages", ctypes.c_uint32),
                ("max_total_pages", ctypes.c_uint32),
                ("max_isolated_pages", ctypes.c_uint32),
                ("max_isolation_records", ctypes.c_uint32)]


class Entry(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("cursor", ctypes.c_uint32),
                ("run_id", ctypes.c_uint64), ("session_id", ctypes.c_uint64),
                ("pfn", ctypes.c_uint64), ("byte_offset", ctypes.c_uint64),
                ("index", ctypes.c_uint32), ("error_type", ctypes.c_uint32),
                ("origin", ctypes.c_uint32), ("state", ctypes.c_uint32),
                ("map_refs", ctypes.c_uint32), ("module_refs", ctypes.c_uint32),
                ("page_refcount", ctypes.c_uint32),
                ("last_error", ctypes.c_int32)]


class Restore(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("flags", ctypes.c_uint32),
                ("run_id", ctypes.c_uint64), ("released", ctypes.c_uint32),
                ("retained", ctypes.c_uint32), ("failed", ctypes.c_uint32),
                ("skipped", ctypes.c_uint32)]


def _iowr(number, structure):
    return 0xC0000000 | (ctypes.sizeof(structure) << 16) | (ord("K") << 8) | number


IOCTL_ALLOCATE = _iowr(0, Allocate)
IOCTL_PAGE = _iowr(1, PageInfo)
IOCTL_REPORT = _iowr(2, Report)
IOCTL_STATUS = _iowr(3, Status)
IOCTL_ENTRY = _iowr(4, Entry)
IOCTL_RESTORE = _iowr(5, Restore)


def _ioctl(fd, command, value):
    import fcntl
    data = bytearray(bytes(value))
    fcntl.ioctl(fd, command, data, True)
    return type(value).from_buffer_copy(data)


class Physmem:
    def __init__(self, device="/dev/phys_mem"):
        self.device_name = device
        self.fd = None
        self.run_id = None
        self.session_id = None
        self.page_count = 0

    def __enter__(self):
        self.dev()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def dev(self):
        if self.fd is None:
            self.fd = os.open(self.device_name, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
        return self.fd

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def allocate(self, run_id, page_count):
        if self.session_id is not None:
            raise RuntimeError("this session already owns test pages")
        if not 0 < run_id < 2**64 or not 0 < page_count < 2**32:
            raise ValueError("run_id and page_count must be positive")
        result = _ioctl(self.dev(), IOCTL_ALLOCATE,
                        Allocate(PROTOCOL_VERSION, page_count, run_id))
        if result.page_size != PAGE_SIZE or result.num_pages != page_count:
            raise RuntimeError("phys_mem page size or allocation count mismatch")
        self.run_id = run_id
        self.session_id = result.session_id
        self.page_count = page_count
        return result.session_id

    def page(self, index):
        if self.session_id is None or not 0 <= index < self.page_count:
            raise ValueError("page index is outside this session")
        return _ioctl(self.dev(), IOCTL_PAGE,
                      PageInfo(PROTOCOL_VERSION, index, self.session_id))

    def pages(self):
        return [self.page(i) for i in range(self.page_count)]

    def report(self, byte_offset, error_type, origin=ORIGIN_UNKNOWN):
        if self.session_id is None or not 0 <= byte_offset < self.page_count * PAGE_SIZE:
            raise ValueError("failure offset is outside this session")
        index = byte_offset // PAGE_SIZE
        return _ioctl(self.dev(), IOCTL_REPORT,
                      Report(PROTOCOL_VERSION, index, self.session_id,
                             byte_offset, error_type, origin))

    def mmap(self):
        if self.session_id is None:
            raise RuntimeError("allocate pages before mapping")
        return MmapWrapper(mmap.mmap(self.dev(), self.page_count * PAGE_SIZE,
                                    mmap.MAP_SHARED,
                                    mmap.PROT_READ | mmap.PROT_WRITE))

    def status(self, run_id=0):
        return _ioctl(self.dev(), IOCTL_STATUS, Status(PROTOCOL_VERSION, 0, run_id))

    def entries(self, run_id=0):
        cursor = 0
        while True:
            try:
                entry = _ioctl(self.dev(), IOCTL_ENTRY,
                               Entry(PROTOCOL_VERSION, cursor, run_id))
            except OSError as exc:
                if exc.errno == 2:  # ENOENT means end of the table.
                    break
                raise
            cursor = entry.cursor
            yield entry

    def restore(self, run_id):
        if not 0 < run_id < 2**64:
            raise ValueError("run_id must be the actual nonzero batch number")
        return _ioctl(self.dev(), IOCTL_RESTORE,
                      Restore(PROTOCOL_VERSION, RESTORE_SIMULATED_ONLY, run_id))

    def configure(self, requested_pfns):
        raise RuntimeError("arbitrary-PFN claiming was removed; use allocate(run_id, pages)")

    def mark_pfn_bad(self, bad_pfn):
        raise RuntimeError("PFN poisoning was removed; use report(byte_offset, type, origin)")
