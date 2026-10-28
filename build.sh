#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0
#
# Standalone build driver for the realme GT Neo 3 (lisaa), MT6895,
# Android 12 (SP1A.210812.016).
#
# Builds the kernel, the in-tree modules and all external modules, stages
# them, and then packs fastboot-flashable images into out/images/ using the
# stock images in stock/ as the layout reference.
#
# No AOSP build environment is needed.  The only external requirement is an
# AOSP clang toolchain (12.x for this kernel); it is not bundled.
#
#   fish:  fish_add_path -g /path/to/clang-r416183b1/bin
#   bash:  export PATH=/path/to/clang-r416183b1/bin:$PATH
#
# Usage:
#   ./build.sh [options]
#
# Options:
#   -j, --jobs N        parallel jobs (default: nproc)
#       --clang-dir DIR use this clang bin directory, no menu
#       --clean         remove out/ before building
#       --reconfig      regenerate out/.config from the defconfig fragments
#       --no-pack       stop after out/dist is populated
#       --check         verify toolchain and host tools, then exit
#       --out DIR       image output directory (default: out/images)
#   -h, --help          show this help
#
# Environment:
#   CLANG_DIR   same as --clang-dir
#   CLANG_ROOT  extra directory to scan for toolchains
#   JOBS        default job count

set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"

OUT=$ROOT/out
export OUT_DIR=$OUT
DIST=$OUT/dist
STAGING=$OUT/staging
IMAGES=$OUT/images
JOBS=${JOBS:-$(nproc)}
CLEAN=0
RECONFIG=0
PACK=1
CHECK=0

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

log() {
	printf '%s\n' "$*"
}

section() {
	printf '\n==> %s\n' "$*"
}

usage() {
	awk 'NR >= 3 && /^#/ { sub(/^# ?/, ""); print; next } NR >= 3 { exit }' "$0"
	exit 0
}

# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

while (($#)); do
	case $1 in
	-j | --jobs)
		[[ $# -ge 2 ]] || die "$1 needs a value"
		JOBS=$2
		shift 2
		;;
	-j*)
		JOBS=${1#-j}
		shift
		;;
	--clang-dir)
		[[ $# -ge 2 ]] || die "$1 needs a value"
		CLANG_DIR=$2
		shift 2
		;;
	--clean)
		CLEAN=1
		shift
		;;
	--reconfig)
		RECONFIG=1
		shift
		;;
	--no-pack)
		PACK=0
		shift
		;;
	--check)
		CHECK=1
		shift
		;;
	--out)
		[[ $# -ge 2 ]] || die "$1 needs a value"
		IMAGES=$2
		shift 2
		;;
	-h | --help)
		usage
		;;
	*)
		die "unknown argument: $1 (try --help)"
		;;
	esac
done

[[ $JOBS =~ ^[0-9]+$ ]] && ((JOBS > 0)) || die "invalid job count: $JOBS"

# ---------------------------------------------------------------------------
# Toolchain selection
# ---------------------------------------------------------------------------

# Print every plausible clang bin directory, deduplicated.
collect_clang_dirs() {
	local -a dirs=()
	local d r
	local -a roots=()

	if [[ -n ${CLANG_DIR:-} ]]; then
		[[ -d $CLANG_DIR ]] || die "CLANG_DIR is not a directory: $CLANG_DIR"
		dirs+=("$CLANG_DIR")
	else
		[[ -n ${CLANG_ROOT:-} ]] && roots+=("$CLANG_ROOT")
		roots+=("$HOME/dev/tools/toolchains/aosp_clang" "$HOME/toolchains" \
			"/opt/android-clang")
		for r in "${roots[@]}"; do
			[[ -d $r ]] || continue
			[[ -x $r/bin/clang ]] && dirs+=("$r/bin")
			for d in "$r"/*/bin; do
				[[ -x $d/clang ]] && dirs+=("$d")
			done
		done
		for d in /usr/lib/llvm-*/bin; do
			[[ -x $d/clang ]] && dirs+=("$d")
		done
		if d=$(command -v clang 2>/dev/null); then
			dirs+=("$(dirname "$(readlink -f "$d")")")
		fi
	fi

	local -A seen=()
	for d in "${dirs[@]}"; do
		r=$(readlink -f "$d")
		[[ -n ${seen[$r]:-} ]] && continue
		seen[$r]=1
		printf '%s\n' "$r"
	done
}

clang_desc() {
	"$1/clang" --version 2>/dev/null | head -1
}

REQUIRED_LLVM=(clang clang++ ld.lld llvm-ar llvm-nm llvm-objcopy
	llvm-objdump llvm-readelf llvm-strip llvm-size)

mapfile -t CLANG_CANDIDATES < <(collect_clang_dirs)
((${#CLANG_CANDIDATES[@]})) || die "no clang found. Put a clang bin directory
in PATH (fish: fish_add_path -g /path/to/clang/bin) or pass --clang-dir DIR."

# Prefer clang 12.x (what this kernel is built with) in the menu/default.
CLANG_PREFERRED=()
CLANG_OTHER=()
for d in "${CLANG_CANDIDATES[@]}"; do
	v=$("$d/clang" -dumpversion 2>/dev/null || echo "?")
	if [[ ${v%%.*} == 12 ]]; then
		CLANG_PREFERRED+=("$d")
	else
		CLANG_OTHER+=("$d")
	fi
done
CLANG_CANDIDATES=("${CLANG_PREFERRED[@]}" "${CLANG_OTHER[@]}")

if ((${#CLANG_CANDIDATES[@]} == 1)); then
	CLANG_BIN=${CLANG_CANDIDATES[0]}
elif [[ -t 0 && -t 1 ]]; then
	log "Available clang toolchains:"
	for i in "${!CLANG_CANDIDATES[@]}"; do
		printf '  %2d) %s\n      %s\n' "$((i + 1))" \
			"${CLANG_CANDIDATES[$i]}" \
			"$(clang_desc "${CLANG_CANDIDATES[$i]}")"
	done
	read -r -p "Select toolchain [1]: " answer
	answer=${answer:-1}
	[[ $answer =~ ^[0-9]+$ ]] && ((answer >= 1 && answer <= ${#CLANG_CANDIDATES[@]})) ||
		die "invalid selection: $answer"
	CLANG_BIN=${CLANG_CANDIDATES[$((answer - 1))]}
else
	CLANG_BIN=${CLANG_CANDIDATES[0]}
	log "note: non-interactive shell, using $CLANG_BIN"
fi

for tool in "${REQUIRED_LLVM[@]}"; do
	[[ -x $CLANG_BIN/$tool ]] || die "missing $tool in $CLANG_BIN"
done

export PATH=$CLANG_BIN:$PATH

CLANG_VER=$("$CLANG_BIN/clang" -dumpversion 2>/dev/null || echo "?")
CLANG_MAJOR=${CLANG_VER%%.*}

section "Environment"
log "Shell:       ${SHELL:-unknown} (driver: bash $BASH_VERSION)"
log "Source:      $ROOT"
log "Toolchain:   $CLANG_BIN"
log "clang:       $(clang_desc "$CLANG_BIN")"
log "ld.lld:      $("$CLANG_BIN/ld.lld" --version 2>/dev/null | head -1)"
log "Jobs:        $JOBS"
log "Output:      $OUT"

if [[ $CLANG_MAJOR != 12 ]]; then
	log ""
	log "warning: clang $CLANG_VER selected; this kernel is built and tested"
	log "         with clang 12 (r416183b / r416183b1). Continuing anyway."
fi

# ---------------------------------------------------------------------------
# Host tools
# ---------------------------------------------------------------------------

HOST_TOOLS=(make python3 bc bison flex perl cpio gzip tar lz4 depmod
	debugfs dumpe2fs e2fsck mke2fs)

MISSING=()
for tool in "${HOST_TOOLS[@]}"; do
	command -v "$tool" >/dev/null 2>&1 || MISSING+=("$tool")
done
if ((${#MISSING[@]})); then
	log ""
	log "missing host tools: ${MISSING[*]}"
	log "Debian/Ubuntu:"
	log "  sudo apt install build-essential bc bison flex libssl-dev python3 \\"
	log "                   perl cpio lz4 kmod e2fsprogs"
	die "install the tools above and retry"
fi

# ---------------------------------------------------------------------------
# Build configuration
# ---------------------------------------------------------------------------

# shellcheck source=build.config.lisaa
. "$ROOT/build.config.lisaa"

for f in $DEFCONFIG_FRAGMENTS; do
	[[ -f $ROOT/$f ]] || die "missing defconfig fragment: $f"
done
for f in boot.img vendor_boot.img vendor_dlkm.img; do
	[[ -f $ROOT/stock/$f ]] || die "missing stock image: stock/$f"
done

if command -v git >/dev/null 2>&1 &&
	git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
	if [[ -n $(git -C "$ROOT" status --porcelain --untracked-files=no) ]]; then
		log ""
		log "warning: working tree has uncommitted changes; the kernel release"
		log "         string will end in '-dirty' (fine for flashing, but not"
		log "         reproducible against a clean build)"
	fi
fi

if ((CHECK)); then
	log ""
	log "environment OK"
	exit 0
fi

MAKE_ARGS=(
	O="$OUT"
	ARCH=arm64
	LLVM=1
	LLVM_IAS=1
	CROSS_COMPILE=aarch64-linux-gnu-
	KCFLAGS="${KCFLAGS:-} ${KCFLAGS_EXTRA}"
	DEPMOD=depmod
)

if ((CLEAN)); then
	section "Cleaning $OUT"
	rm -rf "$OUT"
fi

mkdir -p "$OUT"

# ---------------------------------------------------------------------------
# Kernel configuration
# ---------------------------------------------------------------------------

if ((RECONFIG)) || [[ ! -f $OUT/.config ]]; then
	section "Generating .config"
	MERGED=$OUT/.config.merged
	rm -f "$MERGED"
	# shellcheck disable=SC2086
	ARCH=arm64 KCONFIG_CONFIG=$MERGED \
		scripts/kconfig/merge_config.sh -m -r $DEFCONFIG_FRAGMENTS
	mv "$MERGED" "$OUT/.config"
	make "${MAKE_ARGS[@]}" olddefconfig

	if [[ ${LTO:-} == thin ]]; then
		scripts/config --file "$OUT/.config" \
			-e LTO_CLANG -d LTO_NONE -e LTO_CLANG_THIN \
			-d LTO_CLANG_FULL -e THINLTO
		make "${MAKE_ARGS[@]}" olddefconfig
	fi
else
	section "Reusing existing $OUT/.config (use --reconfig to regenerate)"
fi

# ---------------------------------------------------------------------------
# Kernel and modules
# ---------------------------------------------------------------------------

section "Building kernel"
# shellcheck disable=SC2086
make -j"$JOBS" "${MAKE_ARGS[@]}" $MAKE_GOALS

section "Installing in-tree modules"
rm -rf "$STAGING"
mkdir -p "$STAGING"
make "${MAKE_ARGS[@]}" INSTALL_MOD_PATH="$STAGING" modules_install

if [[ -n ${EXT_MODULES:-} ]]; then
	section "Building external modules"
	for mod in $EXT_MODULES; do
		[[ -d $ROOT/$mod ]] || die "missing external module: $mod"
		mkdir -p "$OUT/$mod"
		log "  $mod"
		make -C "$ROOT/$mod" M="$mod" KERNEL_SRC="$ROOT" \
			"${MAKE_ARGS[@]}"
		make -C "$ROOT/$mod" M="$mod" KERNEL_SRC="$ROOT" \
			"${MAKE_ARGS[@]}" INSTALL_MOD_PATH="$STAGING" \
			INSTALL_HDR_PATH="$OUT/uapi/usr" modules_install
	done
fi

# ---------------------------------------------------------------------------
# Distribution directory
# ---------------------------------------------------------------------------

section "Collecting build artifacts"
rm -rf "$DIST"
mkdir -p "$DIST"
for f in $FILES; do
	if [[ -f $OUT/$f ]]; then
		log "  $f"
		cp -p "$OUT/$f" "$DIST/"
	else
		log "  $f is missing, skipping"
	fi
done

KO_COUNT=0
while IFS= read -r ko; do
	cp -p "$ko" "$DIST/"
	KO_COUNT=$((KO_COUNT + 1))
done < <(find "$STAGING" -type f -name '*.ko' | sort)
log "  $KO_COUNT modules"
((KO_COUNT > 0)) || die "no modules were installed into $STAGING"

# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

if ((PACK)); then
	section "Packing images"
	python3 "$ROOT/tools/pack/pack_images.py" \
		--root "$ROOT" --dist "$DIST" --out "$IMAGES"

	section "Done"
	for img in boot.img vendor_boot.img vendor_dlkm.img vbmeta.img; do
		[[ -f $IMAGES/$img ]] && log "  $IMAGES/$img"
	done
else
	section "Done (images not packed)"
	log "  $DIST"
fi
