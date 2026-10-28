# Image packing tools

`pack_images.py` builds the fastboot-flashable images from `out/dist` and the
stock images in `stock/`.  It is device-specific and is invoked by
`build.sh`; it can also be run on its own:

```
tools/pack/pack_images.py --dist out/dist --out out/images
```

Bundled third-party tools (kept here so no AOSP checkout is needed):

| File | Origin | License |
|---|---|---|
| `mkbootimg.py` | AOSP `system/tools/mkbootimg` | Apache-2.0 |
| `unpack_bootimg.py` | AOSP `system/tools/mkbootimg` | Apache-2.0 |
| `avbtool` | AOSP `external/avb` (1.4.0) | MIT-style (see file header) |

The DTBO image for `vendor_boot.img` is generated in-process by
`pack_images.py` (same layout as `mkdtboimg create --page_size=2048`), so
`mkdtboimg.py` is not required.

Host tools used at runtime: `lz4`, `depmod`, `debugfs`, `dumpe2fs`,
`e2fsck`, plus `llvm-objcopy` from the selected clang toolchain.

Note: `avbtool` 1.4.0 records `avbtool 1.4.0` in the AVB release string,
whereas the stock images were made with 1.2.0.  This is the only difference
in the generated boot/vendor_boot/vbmeta images; it is metadata and does not
affect verification or booting.
