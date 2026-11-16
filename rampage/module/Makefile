obj-m := phys_mem.o
phys_mem-y := main.o file_operations.o mmap_phys.o
ccflags-y += -I$(src)/include

VERSION ?= $(shell uname -r)
KDIR ?= /lib/modules/$(VERSION)/build

.PHONY: all module clean
all: module

module:
	@test -s "$(KDIR)/Module.symvers" || { \
	    echo "Missing kernel Module.symvers in $(KDIR). Set KDIR to a compatible kernel build directory." >&2; \
	    exit 1; \
	}
	$(MAKE) -C "$(KDIR)" M="$(CURDIR)" modules

clean:
	$(MAKE) -C "$(KDIR)" M="$(CURDIR)" clean
