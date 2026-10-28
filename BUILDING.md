# Building for the realme GT Neo 3 (lisaa)

This tree is self-contained: no AOSP build environment, no `build/build.sh`,
no `build.config.oplus6895`.  Everything needed to build the kernel, the
modules and the flashable images lives here, except the clang toolchain.

## Requirements

* Linux x86-64, bash, `make`
* AOSP clang **12.x** (r416183b or r416183b1).  Not bundled.
* Host tools: `bc bison flex perl python3 cpio gzip tar lz4 kmod e2fsprogs`

Debian/Ubuntu:

```
sudo apt install build-essential bc bison flex libssl-dev python3 \
                 perl cpio lz4 kmod e2fsprogs
```

## Quick start

Put the toolchain in `PATH`:

```
# fish
fish_add_path -g /path/to/clang-r416183b1/bin

# bash
export PATH=/path/to/clang-r416183b1/bin:$PATH
```

Then:

```
./build.sh
```

The script prints the detected shell, clang path and version, and the job
count.  If more than one clang is found it lists them and asks which one to
use; clang 12.x is listed first.  Non-interactive runs pick the first
candidate (use `--clang-dir DIR` to be explicit).

Useful options:

| Option | Meaning |
|---|---|
| `-j N` | parallel jobs (default `nproc`) |
| `--clang-dir DIR` | use this toolchain, no menu |
| `--clean` | remove `out/` first |
| `--reconfig` | regenerate `out/.config` from the defconfig fragments |
| `--check` | only verify toolchain and host tools |
| `--no-pack` | stop after `out/dist` |
| `--out DIR` | image output directory (default `out/images`) |

## Output

```
out/
├── dist/                 Image.gz, mt6895.dtb, vmlinux, System.map,
│                         vmlinux.symvers, modules.builtin*, 864 *.ko
├── staging/lib/modules/  installed module tree (unstripped)
└── images/
    ├── boot.img          67,108,864 B
    ├── vendor_boot.img   67,108,864 B
    ├── vendor_dlkm.img   56,983,552 B
    └── vbmeta.img        8,192 B
```

## What gets built

* `Image.gz` from the merged config: `gki_defconfig` + `mgk_64_k510_defconfig`
  + `kernel/configs/oplus6895.config`, ThinLTO, clang/LLD.
* In-tree modules (`make modules`).
* External modules listed in `EXT_MODULES` in `build.config.lisaa`
  (MediaTek connectivity/GPU, OPPO/realme modules, `fpsgo`, `msync2_frd`).
* 864 modules in total, all from this build (no stock/prebuilt modules).

## How the images are made

`tools/pack/pack_images.py` treats the stock images in `stock/` as the layout
reference and replaces only what this build produces:

* `boot.img` – our `Image.gz` + the stock boot ramdisk (unchanged).
* `vendor_boot.img` – stock vendor ramdisk with all 260 modules replaced
  (stock names, stock `modules.load` order) and our `mt6895.dtb` wrapped in a
  DTBO image (the same layout `mkdtboimg create --page_size=2048` produces).
* `vendor_dlkm.img` – stock ext4 skeleton with all 287 modules replaced,
  `depmod` metadata regenerated with the `/vendor_dlkm/lib/modules` prefix.
* `vbmeta.img` – unsigned, verity and verification disabled (`--flags 3`).

AVB footers are regenerated with the stock salts, sizes and properties, but
unsigned (`--algorithm NONE`) because the vendor private key is unavailable.
The bootloader must be unlocked.

`realme_temp.ko` exists in the stock images but has no source here; it is
intentionally omitted from both the images and `modules.load`.

## Flashing

```
fastboot flash boot        out/images/boot.img
fastboot flash vendor_boot out/images/vendor_boot.img
fastboot flash vendor_dlkm out/images/vendor_dlkm.img
fastboot flash vbmeta      out/images/vbmeta.img
fastboot reboot
```

`dtbo.img` is not touched (our DTB is inside `vendor_boot.img`).

To restore stock, flash the images from the stock ROM package, including its
signed `vbmeta.img`.

## Known differences from stock

| Item | Stock | This build |
|---|---|---|
| AVB signatures | SHA256_RSA2048 | unsigned (`NONE`), `vbmeta` flags=3 |
| `vendor_dlkm` FEC | present | omitted (`fec` tool unavailable) |
| `vendor_dlkm` free space | 41 blocks | similar; superblock timestamps differ |
| AVB release string | `avbtool 1.2.0` | `avbtool 1.4.0` |
| DTB ADSP `system` region | `0x900000` | `0xa00000` (matches this config) |
| `realme_temp.ko` | present | omitted |

Everything else (partition sizes, header fields, cmdline, ramdisk contents,
module names/order/dependencies, SELinux labels) matches stock.

## Reproducibility notes

* Building with a dirty git tree makes the kernel release string end in
  `-dirty`, which changes the module vermagic.  That is fine for flashing
  (kernel and modules come from the same build) but the images will not match
  a clean build.  Commit first if you care about reproducibility.
* A clean re-run reproduces `boot.img`, `vendor_boot.img` and `vbmeta.img`
  byte-for-byte.  `vendor_dlkm.img` differs only in filesystem timestamps.
* After changing the kernel, always rebuild *all* modules and repack; do not
  mix modules from different builds (vermagic/CRCs will not match).
