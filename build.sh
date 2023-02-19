clear && \
git submodule update --init mkbootimg && \
make LLVM=1 LLVM_IAS=1 gkicustom_defconfig && \
time make LLVM=1 LLVM_IAS=1 -j16 && \
python3 mkbootimg/mkbootimg.py \
--kernel out/arch/arm64/boot/Image.gz \
--ramdisk ramdisk \
--header_version 4 \
--os_version 12.0.0 \
--os_patch_level 2023-08 \
--cmdline '' \
-o gkicustomboot_"$(date +%d%m%Y_%H%M)".img && \
cp gkicustomboot* /mnt/c/Users/Ahmet/Desktop && \
rm gkicustomboot* && rm -rf out/
