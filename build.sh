clear && \
git submodule update --init mkbootimg && \
make LLVM=1 LLVM_IAS=1 audiofix_defconfig && \
time make LLVM=1 LLVM_IAS=1 -j$(nproc --all) && \
python3 mkbootimg/mkbootimg.py \
--kernel out/arch/arm64/boot/Image.gz \
--ramdisk ramdisk \
--header_version 4 \
--os_version 12.0.0 \
--os_patch_level 2025-03 \
--cmdline '' \
-o audiofix_"$(date +%d%m%Y_%H%M)".img && \
cp audiofix* /mnt/c/ && \
rm audiofix* && rm -rf out/
