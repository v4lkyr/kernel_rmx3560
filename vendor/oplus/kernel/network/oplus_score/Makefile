#
# Add for kernel data info send to user space.
#
obj-$(CONFIG_OPLUS_FEATURE_DATA_EVAL) += oplus_score.o

KERNEL_SRC ?= /lib/modules/$(shell uname -r)/build
M ?= $(shell pwd)
modules modules_install clean:
	$(MAKE) -C $(KERNEL_SRC) M=$(M) $(KBUILD_OPTIONS) $(@)