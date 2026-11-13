#ifndef PHYS_MEM_INT_H
#define PHYS_MEM_INT_H

#include <linux/cdev.h>
#include <linux/list.h>
#include <linux/mm.h>
#include <linux/mutex.h>

#include "phys_mem.h"

struct phys_mem_test_page {
	struct page *page;
	__u64 byte_offset;
	__u32 error_type;
	__u32 origin;
	__u32 state;
};

struct phys_mem_session {
	struct list_head link;
	__u64 session_id;
	__u64 run_id;
	struct phys_mem_test_page *pages;
	__u32 num_pages;
	__u32 map_refs;
	bool allocating;
};

struct phys_mem_isolation {
	struct page *page; /* NULL after a successful restore */
	__u64 run_id;
	__u64 session_id;
	__u64 pfn;
	__u64 byte_offset;
	__u32 index;
	__u32 error_type;
	__u32 origin;
	__u32 state;
	__s32 last_error;
};

extern struct mutex phys_mem_lock;
extern struct list_head phys_mem_sessions;
extern struct phys_mem_isolation *phys_mem_table;
extern unsigned int phys_mem_records;
extern unsigned int phys_mem_held;
extern unsigned int phys_mem_pending;
extern unsigned int phys_mem_total_pages;
extern unsigned int max_session_pages;
extern unsigned int max_total_pages;
extern unsigned int max_isolated_pages;
extern unsigned int max_isolation_records;
extern struct file_operations phys_mem_fops;

int phys_mem_mmap(struct file *file, struct vm_area_struct *vma);
void phys_mem_release_session(struct phys_mem_session *session);

#endif
