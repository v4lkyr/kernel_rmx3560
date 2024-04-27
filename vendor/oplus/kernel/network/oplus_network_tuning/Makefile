#
# Add for kernel data info send to user space.
#
obj-$(CONFIG_OPLUS_FEATURE_KERNEL_NETWORK_PARA) += oplus_networks_tuning.o
oplus_networks_tuning-objs := oplus_network_tuning.o \
			oplus_tcp_congest_control/oplus_tcp_congest_control.o \
			oplus_tcp_congest_control/oplus_bbr.o \
			oplus_tcp_congest_control/oplus_win_minmax.o \
			oplus_tcp_syn/oplus_tcp_syn.o \
			oplus_dev_check/oplus_dev_check.o

KERNEL_SRC ?= /lib/modules/$(shell uname -r)/build
M ?= $(shell pwd)
modules modules_install clean:
	$(MAKE) -C $(KERNEL_SRC) M=$(M) $(KBUILD_OPTIONS) $(@)