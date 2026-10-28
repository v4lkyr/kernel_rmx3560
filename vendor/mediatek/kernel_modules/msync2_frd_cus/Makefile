all:
	$(MAKE) -C $(KERNEL_SRC) M=$(M) modules $(KBUILD_OPTIONS)

modules_install:
	$(MAKE) M=$(M) -C $(KERNEL_SRC) modules_install

clean:
	$(MAKE) -C $(KERNEL_SRC) M=$(M) clean

ccflags-y += \
	     -I$(srctree)/include/ \

obj-m += msync2_frd.o
msync2_frd-y += src/msync2_main.o
msync2_frd-y += src/mtk_disp_msync.o