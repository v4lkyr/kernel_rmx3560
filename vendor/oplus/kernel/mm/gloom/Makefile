# SPDX-License-Identifier: GPL-2.0-only
KBUILD_OPTIONS += CONFIG_VIRTUAL_RESERVE_MEMORY=m

KERNEL_SRC ?= lib/module/$(shell uname -r)/build

# osi_healthinfo is built in-tree (kernel/oplus_cpu/sched/sched_info), so its
# symbols are resolved from the kernel's own Module.symvers and no external
# symbol dump is needed.

M ?= $(shell pwd)

modules modules_install clean:
	$(MAKE) -C $(KERNEL_SRC) M=$(M) $(KBUILD_OPTIONS) $(@)
