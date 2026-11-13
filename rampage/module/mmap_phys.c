#include <linux/errno.h>
#include <linux/fs.h>
#include <linux/mm.h>
#include <linux/version.h>

#include "phys_mem_int.h"

static void phys_mem_vma_open(struct vm_area_struct *vma)
{
	struct phys_mem_session *session = vma->vm_private_data;

	mutex_lock(&phys_mem_lock);
	session->map_refs++;
	mutex_unlock(&phys_mem_lock);
}

static void phys_mem_vma_close(struct vm_area_struct *vma)
{
	struct phys_mem_session *session = vma->vm_private_data;

	mutex_lock(&phys_mem_lock);
	if (WARN_ON(!session->map_refs)) {
		mutex_unlock(&phys_mem_lock);
		return;
	}
	session->map_refs--;
	mutex_unlock(&phys_mem_lock);
}

static const struct vm_operations_struct phys_mem_vm_ops = {
	.open = phys_mem_vma_open,
	.close = phys_mem_vma_close,
};

int phys_mem_mmap(struct file *file, struct vm_area_struct *vma)
{
	struct phys_mem_session *session = file->private_data;
	unsigned long length = vma->vm_end - vma->vm_start;
	unsigned int i;
	int ret = 0;

	mutex_lock(&phys_mem_lock);
	if (!session->pages || session->allocating || session->map_refs ||
	    vma->vm_pgoff || length != (unsigned long)session->num_pages * PAGE_SIZE ||
	    !(vma->vm_flags & VM_SHARED) || !(vma->vm_flags & VM_WRITE) ||
	    (vma->vm_flags & VM_EXEC)) {
		ret = -EINVAL;
		goto out;
	}
	for (i = 0; i < session->num_pages; i++) {
		if (session->pages[i].state != PHYS_MEM_PAGE_ACTIVE) {
			ret = -EBUSY;
			goto out;
		}
	}
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 3, 0)
	vma->vm_flags |= VM_DONTCOPY | VM_DONTEXPAND | VM_DONTDUMP | VM_MIXEDMAP;
	vma->vm_flags &= ~VM_MAYEXEC;
#else
	vm_flags_set(vma, VM_DONTCOPY | VM_DONTEXPAND | VM_DONTDUMP | VM_MIXEDMAP);
	vm_flags_clear(vma, VM_MAYEXEC);
#endif
	for (i = 0; i < session->num_pages; i++) {
		ret = vm_insert_page(vma, vma->vm_start + (unsigned long)i * PAGE_SIZE,
				     session->pages[i].page);
		if (ret)
			goto out;
	}
	vma->vm_ops = &phys_mem_vm_ops;
	vma->vm_private_data = session;
	session->map_refs = 1; /* The initial VMA does not call ->open. */
out:
	mutex_unlock(&phys_mem_lock);
	return ret;
}
