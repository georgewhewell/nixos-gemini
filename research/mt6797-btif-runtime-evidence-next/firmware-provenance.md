# Gemini MT6797 production WMT firmware and address provenance

Date: 2026-08-30  
Scope: recover the three production WMT inputs and the two four-byte patch
address vectors without touching a device.  This supersedes the narrow claim
in `README.md` that the exact patches were absent from Git: that claim was
false for this repository.

## Result

The exact production inputs are already present in the tracked `blobs/`
directory, introduced in commit `b0ad2bb2317c7b819a09d0e9c657010c50e744bf`.
They are not merely same-named public-image replacements:

| input | tracked source | size | SHA-256 | retained live Gemini match |
|---|---|---:|---|---|
| config | `blobs/WMT_SOC.cfg` | 80 | `f4a59b622a4e0c1470e475ce33f3edae43b27f1fbdeba54dc7cf07503d132880` | yes |
| patch, sequence 1 | `blobs/ROMv3_patch_1_1_hdr.bin` | 46,472 | `5732c0730380e937b48ad169f2805b65e8d4a178265566c5083cb2cc2d249f1e` | yes |
| patch, sequence 2 | `blobs/ROMv3_patch_1_0_hdr.bin` | 210,904 | `450c2b0949cf879217ac9aef81b18b860982f0e69340784b448b54365d8cf630` | yes |

The retained live capture says, verbatim:

> `firmware_sequence=WMT_SOC_cfg_then_ROMv3_patch_1_1_then_ROMv3_patch_1_0`

`artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/live-connectivity-postreboot-20260714.txt:64`

Its three hash records are at `.../live-connectivity-postreboot-20260714.txt:67-69`.
`nixos/firmware.nix:8-20` installs these exact original names from `blobs/`.
Both archived initramfs extractions also compare byte-for-byte equal to those
three tracked inputs:
`artifacts/initramfs-final.BuxCBN/lib/firmware/` and
`artifacts/initramfs-inspect.S2bOMT/lib/firmware/`.

The original ingestion provenance of `b0ad2bb` is not recorded in its commit
message, so the *source medium* from which the initial author acquired the
files is **could not determine**.  Content provenance is closed: the files
equal the independently retained live Gemini measurements above.

## Four-byte discovery/load vectors

The production Android `wmt_launcher` is preserved locally as
`artifacts/wmt-runtime/wmt_launcher` (SHA-256
`79ec10a6cc96642c042a6ae160d838e5b5a9cb63e6447f1761fc6a78000ac8bc`;
also recorded at
`artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/userspace-binary-audit.txt:6-14`).
Static AArch64 inspection establishes its exact construction of the
`WMT_PATCH_INFO` record:

1. It seeks to file offset `0x16`, consumes two single bytes, then reads four
   bytes.  Consequently the four-byte value is file offsets 24--27.  The
   initial seek/read instructions are at binary offsets `0x2118..0x21f0`.
2. It takes the first nibble as patch count and the second as download
   sequence (`0x2244..0x2290`), stores the four bytes at
   `WMT_PATCH_INFO.addRess`, then clears `addRess[0]`
   (`0x2298..0x22b8`) before issuing `WMT_IOCTL_SET_PATCH_INFO`
   (`0x22c0..0x22d4`).
3. The source definition places `addRess[4]` beside `dowloadSeq` and
   `patchName` (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_lib.h:150-154`).
   The kernel copies the submitted record into its patch inventory
   (`.../linux/wmt_dev.c:1029-1065`), returns those four bytes after
   `srh_patch` (`.../core/wmt_ctrl.c:545-557`, `570-588`), and finally copies
   them unchanged into `WMT_PATCH_P_ADDRESS_CMD[12..15]`
   (`.../core/wmt_ic_soc.c:2072-2079`, `2194-2200`).

The authoritative byte vectors, in the order placed on that WMT command, are:

| download sequence | file | raw header bytes 24--27 | launcher operation | `addRess[4]` / WMT command bytes 12--15 |
|---:|---|---|---|---|
| 1 | `ROMv3_patch_1_1_hdr.bin` | `21 00 0a f0` | count `2`, sequence `1`, clear byte 0 | **`00 00 0a f0`** |
| 2 | `ROMv3_patch_1_0_hdr.bin` | `22 00 09 00` | count `2`, sequence `2`, clear byte 0 | **`00 00 09 00`** |

`WMT_PATCH` describes bytes 24--27 as `u4PatchVer`
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_core.h:370-376`).
For this production launcher, that raw header field is also the carrier for
patch count, sequence, and the last three address bytes.  Do **not** infer a
host-endian scalar address from it: the proof is only that the launcher emits
the two byte vectors above verbatim and that the vendor kernel copies them
verbatim into the WMT command.

This is distinct from CONSYS shared EMI.  The DT reservation is a dynamic,
no-map 2 MiB AP allocation (`mt6797.dtsi:329-335`); the vendor stores its
runtime base in `gConEmiPhyBase` and maps a debug/shared subrange
(`mtk_wcn_consys_hw.c:1034-1053`, `1064-1072`).  It is neither a source for
these four bytes nor a valid substitute for them.

## Reproducible read-only validation

Run these from this checkout.  They neither write the repository nor contact
the Gemini.

```sh
set -eu
cd /home/grw/src/nixos-gemini

sha256sum \
  blobs/WMT_SOC.cfg \
  blobs/ROMv3_patch_1_1_hdr.bin \
  blobs/ROMv3_patch_1_0_hdr.bin

for name in WMT_SOC.cfg ROMv3_patch_1_1_hdr.bin ROMv3_patch_1_0_hdr.bin; do
  cmp -s "blobs/$name" "artifacts/initramfs-final.BuxCBN/lib/firmware/$name"
  printf 'final %s: identical\\n' "$name"
  cmp -s "blobs/$name" "artifacts/initramfs-inspect.S2bOMT/lib/firmware/$name"
  printf 'inspect %s: identical\\n' "$name"
done

for name in ROMv3_patch_1_1_hdr.bin ROMv3_patch_1_0_hdr.bin; do
  printf '%s bytes 24..27: ' "$name"
  od -An -v -tx1 -j24 -N4 "blobs/$name" | tr -s ' ' | sed 's/^ //;s/ $//'
done

nix shell 'nixpkgs#pkgsCross.aarch64-multiplatform.buildPackages.binutils' \
  -c aarch64-unknown-linux-gnu-objdump -d \
  --start-address=0x2118 --stop-address=0x22d8 \
  artifacts/wmt-runtime/wmt_launcher
```

The final command is the reproducible static proof for the seek/read,
count/sequence split, first-byte clear, and `SET_PATCH_INFO` ioctl.  It may
fetch an immutable cross-binutils package into the Nix store, but it makes no
repository or device change.

## Primary-source cross-check

The examined vendor source is the public [Gemian 3.18 source at the exact
reviewed revision](https://github.com/gemian/gemini-linux-kernel-3.18/blob/8cfe6596a503612e3332d9c26e292a19525a7f07/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c).
An older public [MediaTek Android kernel source](https://android.googlesource.com/kernel/mediatek/+/refs/heads/android-mediatek-pike-3.10-marshmallow-mr1-wear-release/drivers/misc/mediatek/combo/common/linux/wmt_dev.c)
independently confirms the userspace-to-kernel `WMT_IOCTL_SET_PATCH_INFO`
inventory ABI.  Neither web source establishes the Gemini-specific payload
bytes; that result comes from the hash equality and preserved Gemini launcher
above.

## Activation boundary

This closes the exact production filename, bytes, order, and four-byte
metadata gate **only for these two hashes and the preserved Gemini launcher**.
It does not validate replacement firmware, establish any scalar interpretation
of the byte vectors, or authorise a WMT/BTIF transmit.  All transport, reset,
clock, EMI-ownership, event-acknowledgement, and DT opt-in gates in `README.md`
remain mandatory before a live attempt.
