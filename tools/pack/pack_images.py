#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""
Pack the kernel build output into fastboot-flashable images for the
realme GT Neo 3 (MT6895 / Dimensity 8100, device codename ``lisaa``).

The layout is reproduced from the stock Android 12 images that live in
``stock/``:

  boot.img         - our Image.gz + the stock boot ramdisk (unchanged)
  vendor_boot.img  - stock vendor ramdisk with every module replaced by the
                     module built here, our mt6895.dtb wrapped in a DTBO image
  vendor_dlkm.img  - stock ext4 filesystem with every module replaced
  vbmeta.img       - unsigned vbmeta with verity/verification disabled

Everything that is not a module (init, firmware, config files, ...) is taken
from the stock images, so only the pieces that this kernel build produces are
changed.

Usage (from the kernel source tree, i.e. the directory that contains
``stock/`` and ``tools/``):

    ./build.sh                 # build everything and pack
    tools/pack/pack_images.py  # pack only, using an existing out/dist

The build output directory is auto-detected (``out/*/dist``); pass ``--dist``
to override it.  The output is written to ``out/images/``.

The script does not flash anything: it prints the ``fastboot`` commands for
the images it produced.
"""

import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Stock image constants (from avbtool info_image on the images in stock/).
# --------------------------------------------------------------------------

FINGERPRINT = ("alps/hal_mgvi_64_armv82/mgvi_64_armv82:12/"
               "SP1A.210812.016/1741839443840:user/release-keys")

BOOT_PARTITION_SIZE = 67108864
VENDOR_BOOT_PARTITION_SIZE = 67108864
VENDOR_DLKM_PARTITION_SIZE = 56983552

BOOT_SALT = "8835f363ed2fe364115136c74625479a"
VENDOR_BOOT_SALT = "c51d2bf372b5ad9e827d0b9c7619df3f"
VENDOR_DLKM_SALT = ("6c0e0831f8b9dd08b177287fa9cae038cab64a8add23e206"
                    "9556a6a4992777e3")

OS_VERSION = "12.0.0"
OS_PATCH_LEVEL = "2025-03"
SECURITY_PATCH = "2025-03-01"

VENDOR_CMDLINE = "bootopt=64S3,32N2,64N2 buildvariant=user"

# Modules that exist in the stock images but have no source in this tree.
# realme_temp was unloaded on the running phone with no effect, so it is
# intentionally left out.
SKIP_MODULES = {"realme_temp.ko"}

# Timestamp used by the stock (reproducible) build: 2009-01-01 00:00:00 UTC.
STOCK_MTIME = "0x495c0780"

SELINUX_VALUE = b"u:object_r:vendor_file:s0\x00"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def log(msg):
    print(msg, flush=True)


def sh(cmd, capture=False, check=True):
    """Run a command, echoing it unless we only want its output."""
    cmd = [str(c) for c in cmd]
    if not capture:
        log("  $ " + " ".join(cmd))
    return subprocess.run(cmd, check=check, text=True,
                          capture_output=capture)


def find_root(explicit):
    if explicit:
        return Path(explicit).resolve()
    # <root>/tools/pack/pack_images.py
    return Path(__file__).resolve().parents[2]


def stock_dir(root):
    """Directory holding the stock images used as the packing reference."""
    for name in ("stock", "temp"):
        d = root / name
        if all((d / f).is_file() for f in
               ("boot.img", "vendor_boot.img", "vendor_dlkm.img")):
            return d
    sys.exit("error: stock images not found; expected boot.img, "
             "vendor_boot.img and vendor_dlkm.img in stock/")


def find_tool(root, name, extra=()):
    for c in extra:
        if Path(c).is_file():
            return str(c)
    for c in (root / "tools/pack" / name,
              root / "prebuilts/kernel-build-tools/linux-x86/bin" / name,
              root / "build/build-tools/path/linux-x86" / name):
        if c.is_file():
            return str(c)
    w = shutil.which(name)
    if w:
        return w
    sys.exit(f"error: required tool not found: {name}")


def strip_modules(dist_dir, out_dir, objcopy):
    mods = sorted(dist_dir.glob("*.ko"))
    if not mods:
        sys.exit(f"error: no modules in {dist_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"[1/6] stripping {len(mods)} modules with {objcopy}")
    for i, m in enumerate(mods, 1):
        dst = out_dir / m.name
        if dst.exists() and dst.stat().st_mtime >= m.stat().st_mtime:
            continue
        sh([objcopy, "--strip-debug", m, dst], capture=True)
        if i % 100 == 0:
            log(f"       {i}/{len(mods)}")
    return {m.name: out_dir / m.name for m in mods}


def build_index(stripped):
    """Map normalized module name (dashes -> underscores) to built file."""
    return {name.replace("-", "_"): path for name, path in stripped.items()}


def resolve_modules(stock_names, index, where):
    """Pick the built module for every stock module name.

    The stock file name is kept on purpose: modules.load/modules.dep and any
    userspace modprobe call keep working exactly like on the stock ROM.
    """
    resolved, missing = {}, []
    for name in stock_names:
        src = index.get(name.replace("-", "_"))
        if src is None:
            if name not in SKIP_MODULES:
                missing.append(name)
            continue
        resolved[name] = src
    if missing:
        sys.exit(f"error: no built module for {where}: {', '.join(missing)}")
    return resolved


# --------------------------------------------------------------------------
# newc cpio (vendor ramdisk) handling
# --------------------------------------------------------------------------

class CpioEntry:
    __slots__ = ("hdr", "name", "data")

    def __init__(self, hdr, name, data):
        self.hdr = hdr
        self.name = name
        self.data = data


def parse_newc(blob):
    entries, pos = [], 0
    while True:
        if blob[pos:pos + 6] != b"070701":
            sys.exit(f"error: bad cpio magic at offset {pos}")
        hdr = blob[pos:pos + 110]

        def field(off):
            return int(hdr[off:off + 8], 16)

        namesize, filesize = field(94), field(54)
        name = blob[pos + 110:pos + 110 + namesize - 1].decode()
        pos += 110 + namesize
        pos = (pos + 3) & ~3
        data = blob[pos:pos + filesize]
        pos = (pos + filesize + 3) & ~3
        entries.append(CpioEntry(hdr, name, data))
        if name == "TRAILER!!!":
            return entries


def build_newc(entries):
    out = bytearray()
    for e in entries:
        hdr = bytearray(e.hdr)
        hdr[54:62] = b"%08x" % len(e.data)
        out += hdr + e.name.encode() + b"\x00"
        out += b"\x00" * (-len(out) % 4)
        out += e.data
        out += b"\x00" * (-len(out) % 4)
    return bytes(out)


def build_dtbo(dtb, dst, page_size=2048):
    """Wrap one DTB in a DTBO image (same layout as mkdtboimg create)."""
    data = Path(dtb).read_bytes()
    header_size, entry_size = 32, 32
    dt_offset = header_size + entry_size
    total = dt_offset + len(data)
    blob = bytearray()
    blob += struct.pack(">8I", 0xd7b7ab1e, total, header_size, entry_size,
                        1, header_size, page_size, 0)
    blob += struct.pack(">8I", len(data), dt_offset, 0, 0, 0, 0, 0, 0)
    blob += data
    Path(dst).write_bytes(blob)


# --------------------------------------------------------------------------
# depmod metadata
# --------------------------------------------------------------------------

def prefix_dep(text, prefix):
    """Rewrite depmod's relative module paths to absolute ones."""
    lines = []
    for line in text.splitlines():
        if not line.strip():
            continue
        target, _, rest = line.partition(":")
        deps = rest.split()
        out = prefix + target.strip() + ":"
        if deps:
            out += " " + " ".join(prefix + d for d in deps)
        lines.append(out)
    return "\n".join(lines) + "\n"


def filter_load(text, drop=SKIP_MODULES):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(l for l in lines if l not in drop) + "\n"


def validate_metadata(meta, mods, where):
    """modules.load must only name modules that are actually in the image."""
    for key in ("modules.load", "modules.load.recovery"):
        if key not in meta:
            continue
        load = [l.strip() for l in meta[key].splitlines() if l.strip()]
        missing = [m for m in load if m not in mods]
        if missing:
            sys.exit(f"error: {where} {key} references modules that are "
                     f"not present: {', '.join(missing)}")
    for name, text in meta.items():
        for skip in SKIP_MODULES:
            if skip in text:
                sys.exit(f"error: {where} {name} still references {skip}")


def gen_metadata(mods, prefix, release, scratch, depmod, stock_load):
    """Run depmod over exactly the modules of one partition."""
    root = scratch / "depmod" / prefix.strip("/").replace("/", "_")
    if root.exists():
        shutil.rmtree(root)
    moddir = root / "lib/modules" / release
    moddir.mkdir(parents=True)
    for name, src in mods.items():
        shutil.copyfile(src, moddir / name)

    log(f"       depmod over {len(mods)} modules for {prefix}")
    sh([depmod, "-b", root, release], capture=True)

    return {
        "modules.alias": (moddir / "modules.alias").read_text(),
        "modules.dep": prefix_dep((moddir / "modules.dep").read_text(),
                                  prefix),
        "modules.softdep": (moddir / "modules.softdep").read_text(),
        "modules.load": filter_load(stock_load),
    }


# --------------------------------------------------------------------------
# stock image inspection
# --------------------------------------------------------------------------

def debugfs(root, image, command, capture=True):
    return sh([find_tool(root, "debugfs"), "-R", command, image],
              capture=capture).stdout


def stock_dir_listing(root, image, path):
    out = debugfs(root, image, f"ls -l {path}")
    names = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 9 or not parts[0].isdigit():
            continue
        name = parts[-1]
        if name not in (".", ".."):
            names.append(name)
    return names


def stock_dump(root, image, path, dst):
    debugfs(root, image, f"dump {path} {dst}")
    return Path(dst).read_text()


def ext4_data_size(root, image):
    out = sh([find_tool(root, "dumpe2fs"), "-h", image],
             capture=True).stdout
    blocks = int(re.search(r"^Block count:\s+(\d+)", out, re.M).group(1))
    bsize = int(re.search(r"^Block size:\s+(\d+)", out, re.M).group(1))
    return blocks * bsize


# --------------------------------------------------------------------------
# Image builders
# --------------------------------------------------------------------------

def build_boot(root, dist, work, out, unpack, mkbootimg, avbtool):
    log("[3/6] boot.img")
    boot_dir = work / "stock_boot"
    if boot_dir.exists():
        shutil.rmtree(boot_dir)
    boot_dir.mkdir(parents=True)
    sh([sys.executable, unpack, "--boot_img", stock_dir(root) / "boot.img",
        "--out", boot_dir], capture=True)

    raw = work / "boot.raw.img"
    sh([sys.executable, mkbootimg,
        "--header_version", "4",
        "--pagesize", "4096",
        "--kernel", dist / "Image.gz",
        "--ramdisk", boot_dir / "ramdisk",
        "--os_version", OS_VERSION,
        "--os_patch_level", OS_PATCH_LEVEL,
        "-o", raw])

    dst = out / "boot.img"
    shutil.copyfile(raw, dst)
    sh([avbtool, "add_hash_footer",
        "--image", dst,
        "--partition_name", "boot",
        "--partition_size", BOOT_PARTITION_SIZE,
        "--algorithm", "NONE",
        "--salt", BOOT_SALT,
        "--prop", f"com.android.build.boot.fingerprint:{FINGERPRINT}",
        "--prop", "com.android.build.boot.os_version:12",
        "--prop", f"com.android.build.boot.security_patch:{SECURITY_PATCH}"],
       capture=True)
    return dst


def build_vendor_boot(root, dist, work, out, unpack, mkbootimg, avbtool,
                      lz4, ramdisk_mods, ramdisk_meta):
    log("[4/6] vendor_boot.img")
    vdir = work / "stock_vendor_boot"
    if vdir.exists():
        shutil.rmtree(vdir)
    vdir.mkdir(parents=True)
    sh([sys.executable, unpack,
        "--boot_img", stock_dir(root) / "vendor_boot.img",
        "--out", vdir], capture=True)

    cpio_path = work / "vendor_ramdisk.cpio"
    sh([lz4, "-d", "-f", vdir / "vendor_ramdisk00", cpio_path], capture=True)
    entries = parse_newc(cpio_path.read_bytes())

    # Replace module payloads and metadata, drop skipped modules.
    replaced = 0
    for e in entries:
        if not e.name.startswith("lib/modules/"):
            continue
        base = e.name.rsplit("/", 1)[1]
        if e.name.endswith(".ko"):
            if base in SKIP_MODULES:
                continue
            try:
                e.data = ramdisk_mods[base].read_bytes()
            except KeyError:
                sys.exit(f"error: {base} in vendor ramdisk but not built")
            replaced += 1
        elif base in ramdisk_meta:
            e.data = ramdisk_meta[base].encode()

    entries = [e for e in entries if e.name != "lib/modules/realme_temp.ko"]
    log(f"       replaced {replaced} modules in vendor ramdisk")

    new_cpio = work / "vendor_ramdisk_new.cpio"
    new_cpio.write_bytes(build_newc(entries))
    vendor_ramdisk = work / "vendor_ramdisk.lz4"
    sh([lz4, "-l", "-12", "-f", new_cpio, vendor_ramdisk], capture=True)

    dtbo = work / "dtbo.img"
    build_dtbo(dist / "mt6895.dtb", dtbo)

    raw = work / "vendor_boot.raw.img"
    sh([sys.executable, mkbootimg,
        "--header_version", "4",
        "--pagesize", "4096",
        "--vendor_boot", raw,
        "--vendor_ramdisk", vendor_ramdisk,
        "--dtb", dtbo,
        "--vendor_cmdline", VENDOR_CMDLINE,
        "--base", "0x40000000",
        "--kernel_offset", "0",
        "--ramdisk_offset", "0x26f00000",
        "--tags_offset", "0x07c80000",
        "--dtb_offset", "0x07c80000"])

    dst = out / "vendor_boot.img"
    shutil.copyfile(raw, dst)
    sh([avbtool, "add_hash_footer",
        "--image", dst,
        "--partition_name", "vendor_boot",
        "--partition_size", VENDOR_BOOT_PARTITION_SIZE,
        "--algorithm", "NONE",
        "--salt", VENDOR_BOOT_SALT,
        "--prop",
        f"com.android.build.vendor_boot.fingerprint:{FINGERPRINT}"],
       capture=True)
    return dst


def build_vendor_dlkm(root, work, out, avbtool, debugfs_bin, e2fsck,
                      vdlkm_mods, vdlkm_meta):
    log("[5/6] vendor_dlkm.img")
    stock = stock_dir(root) / "vendor_dlkm.img"
    data_size = ext4_data_size(root, stock)
    dst = out / "vendor_dlkm.img"
    with open(stock, "rb") as f, open(dst, "wb") as o:
        remaining = data_size
        while remaining:
            chunk = f.read(min(remaining, 1 << 20))
            if not chunk:
                sys.exit("error: short read from stock vendor_dlkm.img")
            o.write(chunk)
            remaining -= len(chunk)

    stock_files = stock_dir_listing(root, stock, "/lib/modules")
    stock_load = stock_dump(root, stock, "/lib/modules/modules.load",
                            work / "stock_modules.load")

    xval = work / "selinux_xattr.bin"
    xval.write_bytes(SELINUX_VALUE)

    lines = ["cd /lib/modules"]
    # Remove everything first: the stock filesystem only has ~40 free blocks.
    for name in stock_files:
        lines.append(f"rm {name}")

    def emit_write(name, src):
        lines.append(f"write {src} {name}")
        for field, value in (("mode", "0100644"), ("uid", "0"),
                             ("gid", "0"), ("mtime", STOCK_MTIME),
                             ("atime", STOCK_MTIME), ("ctime", STOCK_MTIME),
                             ("crtime", STOCK_MTIME)):
            lines.append(f"sif {name} {field} {value}")
        lines.append(f"ea_set -f {xval} {name} security.selinux")

    for name in stock_files:
        if name in vdlkm_mods:
            emit_write(name, vdlkm_mods[name])
    for name, text in vdlkm_meta.items():
        path = work / f"vdlkm_{name}"
        path.write_text(text)
        emit_write(name, path)

    cmd_file = work / "debugfs_vendor_dlkm.txt"
    cmd_file.write_text("\n".join(lines) + "\n")
    log(f"       rewriting {len(vdlkm_mods)} modules via debugfs")
    sh([debugfs_bin, "-w", "-f", cmd_file, dst], capture=True)

    res = sh([e2fsck, "-fy", dst], capture=True, check=False)
    if res.returncode not in (0, 1, 2):
        sys.exit(f"error: e2fsck failed ({res.returncode})\n{res.stdout}")

    sh([avbtool, "add_hashtree_footer",
        "--image", dst,
        "--partition_name", "vendor_dlkm",
        "--partition_size", VENDOR_DLKM_PARTITION_SIZE,
        "--algorithm", "NONE",
        "--hash_algorithm", "sha256",
        "--salt", VENDOR_DLKM_SALT,
        "--do_not_generate_fec",
        "--prop",
        f"com.android.build.vendor_dlkm.fingerprint:{FINGERPRINT}",
        "--prop", "com.android.build.vendor_dlkm.os_version:12"],
       capture=True)
    return dst, stock_load


def build_vbmeta(work, out, avbtool):
    log("[6/6] vbmeta.img")
    dst = out / "vbmeta.img"
    sh([avbtool, "make_vbmeta_image",
        "--output", dst,
        "--algorithm", "NONE",
        "--flags", "3",
        "--padding_size", "8192"], capture=True)
    return dst


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

def verify(root, out, work, avbtool, debugfs_bin, lz4, unpack, dtb,
           expected_vdlkm, expected_ramdisk):
    log("")
    log("Verifying output images")
    ok = True
    for name, size in (("boot.img", BOOT_PARTITION_SIZE),
                       ("vendor_boot.img", VENDOR_BOOT_PARTITION_SIZE),
                       ("vendor_dlkm.img", VENDOR_DLKM_PARTITION_SIZE),
                       ("vbmeta.img", 8192)):
        path = out / name
        actual = path.stat().st_size
        good = actual == size
        ok &= good
        log(f"  {name:16s} {actual:>10,} bytes  "
            f"{'OK' if good else f'BAD (expected {size:,})'}")

    for name in ("boot.img", "vendor_boot.img", "vendor_dlkm.img"):
        info = sh([avbtool, "info_image", "--image", out / name],
                  capture=True).stdout
        m = re.search(r"^Algorithm:\s+(\S+)", info, re.M)
        alg = m.group(1) if m else "?"
        log(f"  {name:16s} AVB algorithm {alg}")

    listing = stock_dir_listing(root, out / "vendor_dlkm.img", "/lib/modules")
    kos = [n for n in listing if n.endswith(".ko")]
    good = len(kos) == expected_vdlkm
    ok &= good
    log(f"  vendor_dlkm.img  {len(kos)} modules "
        f"(expected {expected_vdlkm}) {'OK' if good else 'BAD'}")
    for meta in ("modules.alias", "modules.dep", "modules.load",
                 "modules.softdep"):
        if meta not in listing:
            log(f"  vendor_dlkm.img  MISSING {meta}")
            ok = False
    if any("realme_temp" in n for n in listing):
        log("  vendor_dlkm.img  contains realme_temp.ko")
        ok = False

    # Unpack the freshly built vendor_boot and inspect its ramdisk.
    vdir = work / "verify_vendor_boot"
    if vdir.exists():
        shutil.rmtree(vdir)
    vdir.mkdir(parents=True)
    sh([sys.executable, unpack, "--boot_img", out / "vendor_boot.img",
        "--out", vdir], capture=True)
    cpio = work / "verify_vendor_ramdisk.cpio"
    sh([lz4, "-d", "-f", vdir / "vendor_ramdisk00", cpio], capture=True)
    entries = parse_newc(cpio.read_bytes())
    rkos = [e.name for e in entries
            if e.name.startswith("lib/modules/") and e.name.endswith(".ko")]
    good = len(rkos) == expected_ramdisk
    ok &= good
    log(f"  vendor_boot.img  {len(rkos)} modules "
        f"(expected {expected_ramdisk}) {'OK' if good else 'BAD'}")
    if any("realme_temp" in e.name for e in entries):
        log("  vendor_boot.img  contains realme_temp.ko")
        ok = False

    # The DTBO section must contain the DTB we just built.
    blob = (vdir / "dtb").read_bytes()
    dtb_off = int.from_bytes(blob[32 + 4:32 + 8], "big")
    dtb_sz = int.from_bytes(blob[32:32 + 4], "big")
    good = blob[dtb_off:dtb_off + dtb_sz] == dtb.read_bytes()
    ok &= good
    log(f"  vendor_boot.img  dtb {'matches' if good else 'MISMATCHES'} "
        f"{dtb}")

    return ok


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="kernel source tree (contains stock/)")
    ap.add_argument("--dist",
                    help="build output directory "
                         "(default: auto-detect out/*/dist)")
    ap.add_argument("--out", default="out/images",
                    help="output directory (default: out/images)")
    ap.add_argument("--work", default="out/images/work",
                    help="scratch directory (default: out/images/work)")
    args = ap.parse_args()

    root = find_root(args.root)
    out = (root / args.out).resolve()
    work = (root / args.work).resolve()

    if args.dist:
        dist = (root / args.dist).resolve()
    else:
        candidates = [d for d in sorted((root / "out").glob("*/dist"))
                      if (d / "Image.gz").is_file()]
        if not candidates:
            sys.exit("error: no out/*/dist with Image.gz; run the build first "
                     "or pass --dist")
        if len(candidates) > 1:
            log(f"warning: multiple dist directories, using {candidates[0]}")
        dist = candidates[0]

    stock = stock_dir(root)
    for p in (dist / "Image.gz", dist / "mt6895.dtb",
              stock / "boot.img", stock / "vendor_boot.img",
              stock / "vendor_dlkm.img"):
        if not p.is_file():
            sys.exit(f"error: missing {p}")

    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    objcopy = find_tool(root, "llvm-objcopy", extra=[
        root / "prebuilts-master/clang/host/linux-x86/clang-r416183b/bin/"
        "llvm-objcopy",
        root.parent / "prebuilts-master/clang/host/linux-x86/"
        "clang-r416183b/bin/llvm-objcopy"])
    depmod = find_tool(root, "depmod")
    lz4 = find_tool(root, "lz4")
    avbtool = find_tool(root, "avbtool")
    e2fsck = find_tool(root, "e2fsck")
    debugfs_bin = find_tool(root, "debugfs")
    mkbootimg = str(root / "tools/pack/mkbootimg.py")
    unpack = str(root / "tools/pack/unpack_bootimg.py")

    release_file = dist.parent / "include/config/kernel.release"
    if not release_file.is_file():
        sys.exit(f"error: missing {release_file}")
    release = release_file.read_text().strip()
    log(f"Kernel release: {release}")

    # 1. Strip the modules (stock modules are stripped as well).
    stripped = strip_modules(dist, work / "stripped", objcopy)
    index = build_index(stripped)

    # 2. Work out which module goes where, using the stock images as the
    #    source of truth for names and locations.
    log("[2/6] collecting stock module lists")
    vdlkm_stock = stock / "vendor_dlkm.img"
    vdlkm_names = [n for n in stock_dir_listing(root, vdlkm_stock,
                                                "/lib/modules")
                   if n.endswith(".ko")]
    vdlkm_mods = resolve_modules(vdlkm_names, index, "vendor_dlkm")

    bdir = work / "stock_boot"
    if not (bdir / "ramdisk").is_file():
        bdir.mkdir(parents=True, exist_ok=True)
        sh([sys.executable, unpack, "--boot_img", stock / "boot.img",
            "--out", bdir], capture=True)
    vdir = work / "stock_vendor_boot"
    if not (vdir / "vendor_ramdisk00").is_file():
        vdir.mkdir(parents=True, exist_ok=True)
        sh([sys.executable, unpack,
            "--boot_img", stock / "vendor_boot.img",
            "--out", vdir], capture=True)

    tmp_cpio = work / "stock_vendor_ramdisk.cpio"
    sh([lz4, "-d", "-f", vdir / "vendor_ramdisk00", tmp_cpio], capture=True)
    stock_entries = parse_newc(tmp_cpio.read_bytes())
    ramdisk_names = [e.name.rsplit("/", 1)[1] for e in stock_entries
                     if e.name.startswith("lib/modules/")
                     and e.name.endswith(".ko")]
    ramdisk_mods = resolve_modules(ramdisk_names, index, "vendor ramdisk")

    stock_ram_meta = {e.name.rsplit("/", 1)[1]: e.data.decode()
                      for e in stock_entries
                      if e.name.startswith("lib/modules/modules.")}

    log(f"       vendor ramdisk: {len(ramdisk_mods)} modules")
    log(f"       vendor_dlkm:    {len(vdlkm_mods)} modules")

    # 3. Regenerate depmod metadata for each partition independently, exactly
    #    like the stock build does (cross-partition deps are handled by
    #    modules.load ordering, not by modules.dep).
    log("[2/6] generating modules.dep/alias/softdep")
    ramdisk_meta = gen_metadata(ramdisk_mods, "/lib/modules/", release,
                                work / "meta_ramdisk", depmod,
                                stock_ram_meta["modules.load"])
    ramdisk_meta["modules.load.recovery"] = filter_load(
        stock_ram_meta["modules.load.recovery"])
    vdlkm_meta = gen_metadata(
        vdlkm_mods, "/vendor_dlkm/lib/modules/", release,
        work / "meta_vdlkm", depmod,
        stock_dump(root, vdlkm_stock, "/lib/modules/modules.load",
                   work / "stock_modules.load"))
    validate_metadata(ramdisk_meta, ramdisk_mods, "vendor ramdisk")
    validate_metadata(vdlkm_meta, vdlkm_mods, "vendor_dlkm")

    build_boot(root, dist, work, out, unpack, mkbootimg, avbtool)
    build_vendor_boot(root, dist, work, out, unpack, mkbootimg, avbtool,
                      lz4, ramdisk_mods, ramdisk_meta)
    build_vendor_dlkm(root, work, out, avbtool, debugfs_bin, e2fsck,
                      vdlkm_mods, vdlkm_meta)
    build_vbmeta(work, out, avbtool)

    if not verify(root, out, work, avbtool, debugfs_bin, lz4, unpack,
                  dist / "mt6895.dtb", len(vdlkm_mods), len(ramdisk_mods)):
        sys.exit("verification failed")

    def shown(path):
        rel = os.path.relpath(path)
        return path if rel.startswith("..") else rel

    log("")
    log(f"Images written to {out}")
    log("")
    log("Flash with:")
    log(f"  fastboot flash boot        {shown(out / 'boot.img')}")
    log(f"  fastboot flash vendor_boot {shown(out / 'vendor_boot.img')}")
    log(f"  fastboot flash vendor_dlkm {shown(out / 'vendor_dlkm.img')}")
    log(f"  fastboot flash vbmeta      {shown(out / 'vbmeta.img')}")
    log("  fastboot reboot")
    log("")
    log("vbmeta.img has verity and verification disabled (flags=3); it is")
    log("required because the new images are not signed with the stock key.")


if __name__ == "__main__":
    main()
