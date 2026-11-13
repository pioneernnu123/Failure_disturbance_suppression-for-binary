#include <linux/device.h>
#include <linux/fs.h>
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/vmalloc.h>
#include <linux/version.h>

#include "phys_mem_int.h"

DEFINE_MUTEX(phys_mem_lock);
LIST_HEAD(phys_mem_sessions);
struct phys_mem_isolation *phys_mem_table;
unsigned int phys_mem_records;
unsigned int phys_mem_held;
unsigned int phys_mem_pending;
unsigned int phys_mem_total_pages;

unsigned int max_session_pages = 512;
unsigned int max_total_pages = 4096;
unsigned int max_isolated_pages = 1024;
unsigned int max_isolation_records = 8192;
module_param(max_session_pages, uint, 0444);
module_param(max_total_pages, uint, 0444);
module_param(max_isolated_pages, uint, 0444);
module_param(max_isolation_records, uint, 0444);
MODULE_PARM_DESC(max_session_pages, "Maximum pages in one test session");
MODULE_PARM_DESC(max_total_pages, "Maximum pages allocated by the module");
MODULE_PARM_DESC(max_isolated_pages, "Maximum simultaneously held or pending pages");
MODULE_PARM_DESC(max_isolation_records, "Maximum isolation records including restored pages");

static dev_t phys_mem_devno;
static struct cdev phys_mem_cdev;
static struct class *phys_mem_class;
static struct device *phys_mem_device;

#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 4, 0)
static char *phys_mem_devnode(struct device *dev, umode_t *mode)
#else
static char *phys_mem_devnode(const struct device *dev, umode_t *mode)
#endif
{
	if (mode)
		*mode = 0600;
	return NULL;
}

static int __init phys_mem_init(void)
{
	int ret;

	if (!max_session_pages || !max_total_pages || !max_isolated_pages ||
	    !max_isolation_records || max_session_pages > max_total_pages ||
	    max_isolated_pages > max_total_pages ||
	    max_isolation_records < max_isolated_pages ||
	    max_isolation_records > 65536)
		return -EINVAL;

	phys_mem_table = kvcalloc(max_isolation_records,
				   sizeof(*phys_mem_table), GFP_KERNEL);
	if (!phys_mem_table)
		return -ENOMEM;

	ret = alloc_chrdev_region(&phys_mem_devno, 0, 1, "phys_mem");
	if (ret)
		goto err_table;

	cdev_init(&phys_mem_cdev, &phys_mem_fops);
	phys_mem_cdev.owner = THIS_MODULE;
	ret = cdev_add(&phys_mem_cdev, phys_mem_devno, 1);
	if (ret)
		goto err_region;

#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 4, 0)
	phys_mem_class = class_create(THIS_MODULE, "phys_mem");
#else
	phys_mem_class = class_create("phys_mem");
#endif
	if (IS_ERR(phys_mem_class)) {
		ret = PTR_ERR(phys_mem_class);
		goto err_cdev;
	}
	phys_mem_class->devnode = phys_mem_devnode;
	phys_mem_device = device_create(phys_mem_class, NULL, phys_mem_devno,
					NULL, "phys_mem");
	if (IS_ERR(phys_mem_device)) {
		ret = PTR_ERR(phys_mem_device);
		goto err_class;
	}
	pr_info("phys_mem: protocol %u, page size %lu, module-held isolation\n",
		PHYS_MEM_PROTOCOL_VERSION, (unsigned long)PAGE_SIZE);
	return 0;

err_class:
	class_destroy(phys_mem_class);
err_cdev:
	cdev_del(&phys_mem_cdev);
err_region:
	unregister_chrdev_region(phys_mem_devno, 1);
err_table:
	kvfree(phys_mem_table);
	return ret;
}

static void __exit phys_mem_exit(void)
{
	/* Each held page owns a module reference; normal unload cannot get here. */
	WARN_ON(phys_mem_held || phys_mem_pending ||
		!list_empty(&phys_mem_sessions));
	device_destroy(phys_mem_class, phys_mem_devno);
	class_destroy(phys_mem_class);
	cdev_del(&phys_mem_cdev);
	unregister_chrdev_region(phys_mem_devno, 1);
	kvfree(phys_mem_table);
}

MODULE_LICENSE("GPL");
MODULE_AUTHOR("LZU DSLAB");
MODULE_DESCRIPTION("Session-owned test pages with module-held isolation");
MODULE_VERSION("3.0");
module_init(phys_mem_init);
module_exit(phys_mem_exit);
