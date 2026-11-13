#ifndef PHYS_MEM_H
#define PHYS_MEM_H

#include <linux/ioctl.h>
#include <linux/types.h>

/* All fields have fixed widths so RISC-V userspace and the module agree. */
#define PHYS_MEM_PROTOCOL_VERSION 3
#define PHYS_MEM_IOC_MAGIC 'K'

#define PHYS_MEM_PAGE_ACTIVE   1
#define PHYS_MEM_PAGE_PENDING  2
#define PHYS_MEM_PAGE_HELD     3
#define PHYS_MEM_PAGE_RELEASED 4

#define PHYS_MEM_ORIGIN_UNKNOWN   0
#define PHYS_MEM_ORIGIN_SIMULATED 1
#define PHYS_MEM_RESTORE_SIMULATED_ONLY 1

struct phys_mem_allocate {
	__u32 version;
	__u32 num_pages;
	__u64 run_id;
	__u64 session_id; /* output */
	__u32 page_size;  /* output */
	__u32 reserved;
};

struct phys_mem_page_info {
	__u32 version;
	__u32 index;
	__u64 session_id;
	__u64 pfn;         /* output */
	__u32 state;       /* output */
	__u32 reserved;
};

struct phys_mem_report {
	__u32 version;
	__u32 index;
	__u64 session_id;
	__u64 byte_offset;
	__u32 error_type;
	__u32 origin;
	__u32 state;       /* output */
	__u32 reserved;
};

struct phys_mem_status {
	__u32 version;
	__u32 reserved;
	__u64 run_id;      /* zero queries all runs */
	__u32 held;
	__u32 simulated;
	__u32 unknown;
	__u32 released;
	__u32 pending;
	__u32 active_sessions;
	__u32 total_pages;
	__u32 max_total_pages;
	__u32 max_isolated_pages;
	__u32 max_isolation_records;
};

struct phys_mem_entry {
	__u32 version;
	__u32 cursor;      /* input: zero or previous output; output: next */
	__u64 run_id;      /* input: zero for all runs; output: matching run */
	__u64 session_id;
	__u64 pfn;
	__u64 byte_offset;
	__u32 index;
	__u32 error_type;
	__u32 origin;
	__u32 state;
	__u32 map_refs;    /* nonzero if the held page is still user-mapped */
	__u32 module_refs; /* one while held, zero after restore */
	__u32 page_refcount;
	__s32 last_error;  /* negative errno from the last restore attempt */
};

struct phys_mem_restore {
	__u32 version;
	__u32 flags;
	__u64 run_id;
	__u32 released;
	__u32 retained;
	__u32 failed;
	__u32 skipped;
};

#define PHYS_MEM_IOC_ALLOCATE _IOWR(PHYS_MEM_IOC_MAGIC, 0, struct phys_mem_allocate)
#define PHYS_MEM_IOC_PAGE     _IOWR(PHYS_MEM_IOC_MAGIC, 1, struct phys_mem_page_info)
#define PHYS_MEM_IOC_REPORT   _IOWR(PHYS_MEM_IOC_MAGIC, 2, struct phys_mem_report)
#define PHYS_MEM_IOC_STATUS   _IOWR(PHYS_MEM_IOC_MAGIC, 3, struct phys_mem_status)
#define PHYS_MEM_IOC_ENTRY    _IOWR(PHYS_MEM_IOC_MAGIC, 4, struct phys_mem_entry)
#define PHYS_MEM_IOC_RESTORE  _IOWR(PHYS_MEM_IOC_MAGIC, 5, struct phys_mem_restore)

#endif
