obj-m := phys_mem.o
phys_mem-y := main.o file_operations.o mmap_phys.o
ccflags-y += -I$(src)/include

KDIR ?= /lib/modules/$(shell uname -r)/build

.PHONY: all clean
all:
	@test -s "$(KDIR)/Module.symvers" || { \
	    echo "Missing kernel Module.symvers in $(KDIR). Set KDIR to a compatible kernel build directory." >&2; \
	    exit 1; \
	}
	$(MAKE) -C "$(KDIR)" M="$(CURDIR)" modules

clean:
	$(MAKE) -C "$(KDIR)" M="$(CURDIR)" clean
