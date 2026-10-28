# Stock images (packing reference)

These are the unmodified Android 12 images of the realme GT Neo 3
(MT6895 / Dimensity 8100, device codename `lisaa`), build
`SP1A.210812.016` / `1741839443840` (`user/release-keys`).

`tools/pack/pack_images.py` uses them as the layout reference: partition
sizes, boot header fields, AVB salts/properties, the boot/vendor ramdisks and
the `vendor_dlkm` ext4 skeleton are all taken from here.  Only the kernel,
the device tree and the kernel modules are replaced with the ones built from
this tree.

| File | Size | SHA-256 |
|---|---|---|
| `boot.img` | 67,108,864 | `efc45a8871919824de0d4002a8a31e8035a2e85aee1e43a1ab02b0b1aabc002e` |
| `vendor_boot.img` | 67,108,864 | `f919a50e87f0ab09c722e9f8a228d138748bb489eefbfd987d66b709bc1a228c` |
| `vendor_dlkm.img` | 56,983,552 | `2b688a69f497905a975ae0d905a7f9e64c5eaecb137dce09a78ab5c0faa8fc5b` |
| `vbmeta.img` | 8,192 | `5f773dd10681658887c25604335fe97af268d2828ea86fe9ce45626477a758e1` |

`vbmeta.img` is kept for reference only; the packer generates a new one with
verity and verification disabled (`--flags 3`), because the new images are not
signed with the vendor's private key.

These files contain proprietary vendor code.  They are not redistributable;
keep them in a private repository and do not publish this directory.
