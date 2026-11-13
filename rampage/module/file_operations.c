#include <linux/atomic.h>
#include <linux/capability.h>
#include <linux/errno.h>
#include <linux/fs.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/vmalloc.h>

#include "phys_mem_int.h"

static atomic64_t next_session_id = ATOMIC64_INIT(0);

static int phys_mem_open(struct inode *inode, struct file *file)
{
	struct phys_mem_session *session;

	session = kzalloc(sizeof(*session), GFP_KERNEL);
	if (!session)
		return -ENOMEM;
	session->session_id = atomic64_inc_return(&next_session_id);
	mutex_lock(&phys_mem_lock);
	list_add_tail(&session->link, &phys_mem_sessions);
	mutex_unlock(&phys_mem_lock);
	file->private_data = session;
	return 0;
}

/* Called under phys_mem_lock, after the last VMA has closed. */
void phys_mem_release_session(struct phys_mem_session *session)
{
	unsigned int i;

	WARN_ON_ONCE(session->map_refs);
	for (i = 0; i < session->num_pages; i++) {
		struct phys_mem_test_page *test = &session->pages[i];
		struct phys_mem_isolation *entry;

		if (!test->page)
			continue;
		if (test->state != PHYS_MEM_PAGE_PENDING) {
			__free_page(test->page);
			phys_mem_total_pages--;
			continue;
		}
		/* REPORT reserved both capacities before setting PENDING. */
		if (WARN_ON(phys_mem_records >= max_isolation_records ||
			    phys_mem_held >= max_isolated_pages)) {
			/* Never return a reported bad page to the allocator. */
			continue;
		}
		entry = &phys_mem_table[phys_mem_records++];
		WARN_ON_ONCE(page_mapped(test->page));
		entry->page = test->page;
		entry->run_id = session->run_id;
		entry->session_id = session->session_id;
		entry->pfn = page_to_pfn(test->page);
		entry->byte_offset = test->byte_offset;
		entry->index = i;
		entry->error_type = test->error_type;
		entry->origin = test->origin;
		entry->state = PHYS_MEM_PAGE_HELD;
		__module_get(THIS_MODULE); /* Refuse normal rmmod while held. */
		phys_mem_pending--;
		phys_mem_held++;
		pr_info("phys_mem: module-held run=%llu session=%llu index=%u pfn=%#llx origin=%u\n",
			(unsigned long long)entry->run_id,
			(unsigned long long)entry->session_id, i,
			(unsigned long long)entry->pfn,
			entry->origin);
	}
	kvfree(session->pages);
	session->pages = NULL;
	session->num_pages = 0;
}

static int phys_mem_release(struct inode *inode, struct file *file)
{
	struct phys_mem_session *session = file->private_data;

	mutex_lock(&phys_mem_lock);
	phys_mem_release_session(session);
	list_del(&session->link);
	mutex_unlock(&phys_mem_lock);
	kfree(session);
	return 0;
}

static long phys_mem_allocate_ioctl(struct phys_mem_session *session,
				    void __user *arg)
{
	struct phys_mem_allocate req;
	struct phys_mem_test_page *pages;
	unsigned int i;
	int ret = 0;

	if (copy_from_user(&req, arg, sizeof(req)))
		return -EFAULT;
	if (req.version != PHYS_MEM_PROTOCOL_VERSION || req.reserved ||
	    !req.run_id || !req.num_pages || req.num_pages > max_session_pages)
		return -EINVAL;

	mutex_lock(&phys_mem_lock);
	if (session->pages) {
		ret = -EBUSY;
		goto out;
	}
	/* Reserve a quarantine slot for every live test page. */
	if (req.num_pages > max_isolation_records - phys_mem_records -
			    (phys_mem_total_pages - phys_mem_held) ||
	    req.num_pages > max_isolated_pages - phys_mem_total_pages ||
	    req.num_pages > max_total_pages - phys_mem_total_pages) {
		ret = -ENOSPC;
		goto out;
	}
	pages = kvcalloc(req.num_pages, sizeof(*pages), GFP_KERNEL);
	if (!pages) {
		ret = -ENOMEM;
		goto out;
	}
	for (i = 0; i < req.num_pages; i++) {
		pages[i].page = alloc_page(GFP_KERNEL | __GFP_ZERO);
		if (!pages[i].page) {
			ret = -ENOMEM;
			goto rollback;
		}
		pages[i].state = PHYS_MEM_PAGE_ACTIVE;
	}
	session->pages = pages;
	session->num_pages = req.num_pages;
	session->run_id = req.run_id;
	session->allocating = true;
	phys_mem_total_pages += req.num_pages;
	req.session_id = session->session_id;
	req.page_size = PAGE_SIZE;
	mutex_unlock(&phys_mem_lock);
	ret = copy_to_user(arg, &req, sizeof(req)) ? -EFAULT : 0;
	mutex_lock(&phys_mem_lock);
	if (ret) {
		phys_mem_release_session(session);
		session->run_id = 0;
	}
	session->allocating = false;
	goto out;
rollback:
	while (i)
		__free_page(pages[--i].page);
	kvfree(pages);
out:
	mutex_unlock(&phys_mem_lock);
	return ret;
}

static long phys_mem_page_ioctl(struct phys_mem_session *session,
				void __user *arg)
{
	struct phys_mem_page_info req;
	int ret = 0;

	if (copy_from_user(&req, arg, sizeof(req)))
		return -EFAULT;
	if (req.version != PHYS_MEM_PROTOCOL_VERSION || req.reserved)
		return -EINVAL;
	mutex_lock(&phys_mem_lock);
	if (!session->pages || session->allocating ||
	    req.session_id != session->session_id ||
	    req.index >= session->num_pages) {
		ret = -EINVAL;
		goto out;
	}
	req.pfn = page_to_pfn(session->pages[req.index].page);
	req.state = session->pages[req.index].state;
out:
	mutex_unlock(&phys_mem_lock);
	if (ret)
		return ret;
	return copy_to_user(arg, &req, sizeof(req)) ? -EFAULT : 0;
}

static long phys_mem_report_ioctl(struct phys_mem_session *session,
				  void __user *arg)
{
	struct phys_mem_report req;
	struct phys_mem_test_page *test;
	int ret = 0;

	if (copy_from_user(&req, arg, sizeof(req)))
		return -EFAULT;
	if (req.version != PHYS_MEM_PROTOCOL_VERSION || req.reserved ||
	    !req.error_type || req.error_type > 255 ||
	    req.origin > PHYS_MEM_ORIGIN_SIMULATED)
		return -EINVAL;
	mutex_lock(&phys_mem_lock);
	if (!session->pages || session->allocating ||
	    req.session_id != session->session_id ||
	    req.index >= session->num_pages ||
	    req.byte_offset / PAGE_SIZE != req.index) {
		ret = -EINVAL;
		goto out;
	}
	test = &session->pages[req.index];
	if (test->state == PHYS_MEM_PAGE_PENDING) {
		/* A conflicting report must never make the page restorable. */
		if (req.origin == PHYS_MEM_ORIGIN_UNKNOWN ||
		    test->byte_offset != req.byte_offset ||
		    test->error_type != req.error_type)
			test->origin = PHYS_MEM_ORIGIN_UNKNOWN;
		req.state = test->state;
		goto out;
	}
	if (phys_mem_held + phys_mem_pending >= max_isolated_pages ||
	    phys_mem_records + phys_mem_pending >= max_isolation_records) {
		ret = -ENOSPC;
		goto out;
	}
	test->byte_offset = req.byte_offset;
	test->error_type = req.error_type;
	test->origin = req.origin;
	test->state = PHYS_MEM_PAGE_PENDING;
	phys_mem_pending++;
	req.state = test->state;
out:
	mutex_unlock(&phys_mem_lock);
	if (ret)
		return ret;
	return copy_to_user(arg, &req, sizeof(req)) ? -EFAULT : 0;
}

static long phys_mem_status_ioctl(void __user *arg)
{
	struct phys_mem_status req;
	struct phys_mem_session *session;
	unsigned int i;

	if (copy_from_user(&req, arg, sizeof(req)))
		return -EFAULT;
	if (req.version != PHYS_MEM_PROTOCOL_VERSION || req.reserved)
		return -EINVAL;
	mutex_lock(&phys_mem_lock);
	req.held = req.simulated = req.unknown = req.released = 0;
	req.pending = req.active_sessions = 0;
	for (i = 0; i < phys_mem_records; i++) {
		struct phys_mem_isolation *entry = &phys_mem_table[i];
		if (req.run_id && entry->run_id != req.run_id)
			continue;
		if (entry->state == PHYS_MEM_PAGE_HELD) {
			req.held++;
			if (entry->origin == PHYS_MEM_ORIGIN_SIMULATED)
				req.simulated++;
			else
				req.unknown++;
		} else if (entry->state == PHYS_MEM_PAGE_RELEASED) {
			req.released++;
		}
	}
	list_for_each_entry(session, &phys_mem_sessions, link) {
		if (!session->pages ||
		    (req.run_id && session->run_id != req.run_id))
			continue;
		req.active_sessions++;
		for (i = 0; i < session->num_pages; i++)
			if (session->pages[i].state == PHYS_MEM_PAGE_PENDING)
				req.pending++;
	}
	req.total_pages = phys_mem_total_pages;
	req.max_total_pages = max_total_pages;
	req.max_isolated_pages = max_isolated_pages;
	req.max_isolation_records = max_isolation_records;
	mutex_unlock(&phys_mem_lock);
	return copy_to_user(arg, &req, sizeof(req)) ? -EFAULT : 0;
}

static long phys_mem_entry_ioctl(void __user *arg)
{
	struct phys_mem_entry req;
	unsigned int i;
	__u64 run_id;
	int ret = -ENOENT;

	if (copy_from_user(&req, arg, sizeof(req)))
		return -EFAULT;
	if (req.version != PHYS_MEM_PROTOCOL_VERSION)
		return -EINVAL;
	run_id = req.run_id;
	mutex_lock(&phys_mem_lock);
	for (i = req.cursor; i < phys_mem_records; i++) {
		struct phys_mem_isolation *entry = &phys_mem_table[i];
		if (run_id && entry->run_id != run_id)
			continue;
		req.cursor = i + 1;
		req.run_id = entry->run_id;
		req.session_id = entry->session_id;
		req.pfn = entry->pfn;
		req.byte_offset = entry->byte_offset;
		req.index = entry->index;
		req.error_type = entry->error_type;
		req.origin = entry->origin;
		req.state = entry->state;
		req.map_refs = entry->page && page_mapped(entry->page);
		req.module_refs = entry->page ? 1 : 0;
		req.page_refcount = entry->page ? page_count(entry->page) : 0;
		req.last_error = entry->last_error;
		ret = 0;
		break;
	}
	mutex_unlock(&phys_mem_lock);
	if (ret)
		return ret;
	return copy_to_user(arg, &req, sizeof(req)) ? -EFAULT : 0;
}

static long phys_mem_restore_ioctl(void __user *arg)
{
	struct phys_mem_restore req;
	struct phys_mem_session *session;
	unsigned int i;

	if (!capable(CAP_SYS_ADMIN))
		return -EPERM;
	if (copy_from_user(&req, arg, sizeof(req)))
		return -EFAULT;
	if (req.version != PHYS_MEM_PROTOCOL_VERSION || !req.run_id ||
	    req.flags != PHYS_MEM_RESTORE_SIMULATED_ONLY)
		return -EINVAL;
	mutex_lock(&phys_mem_lock);
	list_for_each_entry(session, &phys_mem_sessions, link) {
		if (session->pages && session->run_id == req.run_id) {
			mutex_unlock(&phys_mem_lock);
			return -EBUSY;
		}
	}
	req.released = req.retained = req.failed = req.skipped = 0;
	for (i = 0; i < phys_mem_records; i++) {
		struct phys_mem_isolation *entry = &phys_mem_table[i];
		if (entry->run_id != req.run_id)
			continue;
		if (entry->state == PHYS_MEM_PAGE_RELEASED) {
			req.skipped++;
			continue;
		}
		if (entry->origin != PHYS_MEM_ORIGIN_SIMULATED) {
			req.retained++;
			continue;
		}
		if (!entry->page || page_mapped(entry->page) ||
		    page_count(entry->page) != 1) {
			entry->last_error = entry->page ? -EBUSY : -EINVAL;
			req.failed++;
			continue;
		}
		__free_page(entry->page);
		entry->page = NULL;
		entry->state = PHYS_MEM_PAGE_RELEASED;
		entry->last_error = 0;
		phys_mem_held--;
		phys_mem_total_pages--;
		module_put(THIS_MODULE);
		req.released++;
	}
	mutex_unlock(&phys_mem_lock);
	return copy_to_user(arg, &req, sizeof(req)) ? -EFAULT : 0;
}

static long phys_mem_ioctl(struct file *file, unsigned int cmd,
			   unsigned long arg)
{
	struct phys_mem_session *session = file->private_data;
	void __user *user_arg = (void __user *)arg;

	switch (cmd) {
	case PHYS_MEM_IOC_ALLOCATE:
		return phys_mem_allocate_ioctl(session, user_arg);
	case PHYS_MEM_IOC_PAGE:
		return phys_mem_page_ioctl(session, user_arg);
	case PHYS_MEM_IOC_REPORT:
		return phys_mem_report_ioctl(session, user_arg);
	case PHYS_MEM_IOC_STATUS:
		return phys_mem_status_ioctl(user_arg);
	case PHYS_MEM_IOC_ENTRY:
		return phys_mem_entry_ioctl(user_arg);
	case PHYS_MEM_IOC_RESTORE:
		return phys_mem_restore_ioctl(user_arg);
	default:
		return -ENOTTY;
	}
}

struct file_operations phys_mem_fops = {
	.owner = THIS_MODULE,
	.open = phys_mem_open,
	.release = phys_mem_release,
	.unlocked_ioctl = phys_mem_ioctl,
	.mmap = phys_mem_mmap,
};
