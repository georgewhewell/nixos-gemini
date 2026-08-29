# Vendor kernel boot diagnosis

Status: 2026-08-29. The rebuilt kernel enters Linux and requests a restart
before initramfs. It is not an LK decompression or Android boot-image failure.

## Proven failure point

- LK decompressed the rebuilt payload and handed `0x40080000` to ATF.
- The AEE/expdb record captured CPU0 PC and LR at
  `0xffffffc0000869e4`.
- In the exact Nix-built `System.map` and `vmlinux`, that address is the final
  infinite loop in `machine_restart`, after the platform restart callback has
  returned.
- Repacking the byte-for-byte working kernel/DTB with the Nix initramfs boots.
  The boot header, fixed addresses, DTB, and initramfs therefore have an
  independent passing test.
- The rebuilt payload ends far below the ramdisk at `0x45000000`; it does not
  overlap it. See `artifacts/lk-analysis/REVERSE_ENGINEERING.md` for the LK
  disassembly and address arithmetic.

The exact caller of `machine_restart` has not yet been captured.

## Ranked causes

1. **Compiler-generated code is the leading testable difference.** The working
   image identifies Debian GCC 6.3.0-18; the failed image used Nix GCC 8.5.
   Its decompressed `Image` grew from `0x13160c0` to `0x1512d60`, about
   2.08 MB. This is a hypothesis to test, not evidence of a known GCC bug.
2. **The build config was confounded.** The failed build also enabled
   `USB_USBNET`/`USB_NET_CDC_NCM` and disabled Anbox. Those options are
   unlikely to trigger a pre-initramfs restart, but they must not be present in
   the compiler comparison.
3. **Nix wrapper hardening is a low-probability control.** ARM64 Kbuild follows
   the wrapper's PIC and strong stack-protector flags with `-fno-pic` and its
   configured stack-protector mode. The static `vmlinux` also has no dynamic
   or GNU_RELRO program headers. Applicable userspace hardening is disabled in
   the normal rows anyway, matching nixpkgs' kernel policy; one comparison row
   deliberately retains it.
4. LK failing to jump, payload placement, and the initramfs are ruled out as
   primary causes by the evidence above.

The source pin
[`51e705e`](https://github.com/gemian/gemini-linux-kernel-3.18/commit/51e705e4e7b1e52a31a79985f7fbbc9e98b59c8c)
is the best-supported public source: it predates the working binary by two days
and the next commit is packaging-only. It is not cryptographically proven to
be the original private build input.

## Controlled build matrix

| Row | Compiler | Config | Wrapper hardening | Purpose |
|-----|----------|--------|-------------------|---------|
| A | Nix GCC 8.5 | exact live config | disabled | clean current-toolchain baseline |
| B | Nix GCC 8.5 | exact live config | retained | isolate Nix wrapper hardening |
| C | Nix GCC 6.5 | exact live config | disabled | approach the working GCC 6.3 build |
| D | Nix GCC 8.5 | live config + NCM, no Anbox | disabled | USB test after a baseline boots |

The flake exposes A-C as `kernelBaselineGcc8`,
`kernelBaselineGcc8Hardened`, and `kernelBaselineGcc6`. Their tiny boot images
are `baselineProbeBootImgGcc8`, `baselineProbeBootImgGcc8Hardened`, and
`baselineProbeBootImgGcc6`. `diagnosticKernelBundle` gathers all three plus the
staged row-D kernel and `usbNcmProbeBootImg`.

Every kernel output includes the generated config, `vmlinux`, `System.map`,
and a `BUILD-MANIFEST` with the source revision, compiler/linker versions,
hardening policy, hashes, and sizes.

The build also unsets generic `NIX_LDFLAGS`. Without that, stdenv adds an
`$out/lib` RPATH to the dynamically linked ARM64 vDSO that Kbuild embeds inside
`Image`; the changing output-store path made otherwise identical rebuilds
differ by 52 bytes. This is not a credible early-restart mechanism, because the
vDSO is consumed during userspace setup, but removing it is required for a
clean comparison. `SOURCE_DATE_EPOCH` and all Kbuild release metadata are fixed
to the known-good build. A forced Nix `--rebuild` of row C reproduces its full
output exactly.

All three rows build successfully. The tracked base config is byte-identical
to the running kernel's `/proc/config.gz`, with SHA-256
`231d8a2ffe7afac3a4cc62c27d0eb6fe8bd9165ebd096e3e3346dd6df35c18f4`.
Kconfig adds only `# CONFIG_ANBOX is not set` while normalizing it; all three
generated configs are otherwise byte-identical and hash to
`c96ca5c8a767b93f59487c9b4a1c3d05c1f47c166f3f9ea9f2b7ffe0f6f1f0fb`.
That added disabled-symbol record has no code-generation effect. With the
known-good release metadata embedded in every row, the output sizes are:

| Image | Compressed kernel | Delta from working | Raw kernel | Delta from working |
|-------|-------------------|--------------------|------------|--------------------|
| working GCC 6.3 | 8,299,080 | - | 20,013,248 | - |
| A: GCC 8.5 | 9,063,128 | +764,048 | 22,060,704 | +2,047,456 |
| B: GCC 8.5 hardened | 9,071,219 | +772,139 | 22,060,704 | +2,047,456 |
| C: GCC 6.5 | 8,293,787 | -5,293 | 19,964,096 | -49,152 |

The striking GCC 6 size agreement is not proof that it boots, but it makes C
the highest-value first hardware probe. Test C, then A to isolate compiler from
config, and B only if hardening remains material. If C boots and A does not,
build a confirmation row with exact Debian Stretch GCC 6.3 and binutils 2.28.
Add row D only after a baseline boots.

For every cold boot, preserve:

- boot image and kernel manifest;
- exact boot slot and result;
- complete UART output, if available;
- expdb/AEE record;
- persistent initramfs marker;
- PC/LR symbolization against that row's `vmlinux` and `System.map`.

Use p30/`boot2` for these tests. Leave the stable default p22 image and recovery
p31 untouched.
