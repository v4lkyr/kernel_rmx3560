obj-$(CONFIG_OPLUS_FINGERPRINT_COMMON) += oplus_fp_common/

### Capacitive fingerprint sensor
obj-$(CONFIG_OPLUS_FINGERPRINT_FPC) += fpc/

obj-$(CONFIG_OPLUS_FINGERPRINT_EGIS) += egis/

obj-$(CONFIG_OPLUS_FINGERPRINT_SILEAD_OPTICAL) += silead_optical_fp/
obj-$(CONFIG_OPLUS_FINGERPRINT_EGIS_OPTICAL)   += egis_optical_fp/
obj-m += goodix_optical_fp/

### FEATURE MACRO
ccflags-$(CONFIG_OPLUS_FINGERPRINT_NAVIGATION_ENABLE) += -DFP_NAVIGATION_ENABLE
