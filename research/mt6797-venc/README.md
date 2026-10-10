# MT6797 encoder resource diagnostic

`resource-probe.c` is an original GPL-2.0-only, command-free bring-up module.
It is not an encoder implementation. Its interface facts come from the public
MT6797 register table, public Linux clock/device-tree definitions and the
resource ownership established by the decoder diagnostics. See the
[interface ledger](../mt6797-video-interface.json) for source provenance.

Build `mt6797_venc_resource_probe.ko` with Kbuild against the matching configured
candidate kernel. The probe borrows the disabled encoder node's VENC power
domain after binding its private platform device and obtains encoder/bus clock
references from the public VENC clock provider. Larb3 remains owned by its real
SMI supplier, which already serves JPEG on Gemini. It requires the
Gemini board and a disabled encoder node; it does not configure IOMMU ports or allocate
DMA storage. It snapshots only the documented encoder chip-enable, dynamic
clock and local clock-control registers at offsets `0xec`, `0xf4` and `0xfc`.
It writes no encoder registers and releases its clock and power votes before
exposing the cached result.

In a supervisor-owned experimental boot, load the module, read
`/sys/bus/platform/devices/mt6797-venc-resource-probe/result`, and unload it
normally. Successful compilation alone does not qualify resource access.
Neither register snapshots nor a successful power cycle qualify video encoding.
The frame-programming contract is still missing from the examined public
documentation and GPL resource drivers; no proprietary codec source, library
or firmware is used here.

The first hardware attempt in trial 34 rejected an assumption that larb3 was
disabled, returning EBUSY before encoder register access. Trial 35 qualifies the corrected resource ownership: both clock APIs report
325 MHz, global clock status is `0x11`, chip-enable is zero, local DCM is one,
and local gate control is `0xffffffff`. Power-vote release, normal unload and
supervisor/recovery/audit pass. These are command-free resource observations,
with no encoded output or hardware frame command.
