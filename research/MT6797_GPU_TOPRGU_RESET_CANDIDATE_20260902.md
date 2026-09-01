# MT6797 GPU TOPRGU reset candidate — 2026-09-02

## Scope

This candidate changes one hardware variable on top of the failed bus-clock
oracle: it pulses the MT6797 TOPRGU MFG reset for 1 microsecond during Panfrost
initialization. The 26 MHz bus clock, 500.5 MHz single OPP, 975 mV supply,
SCPSYS domains, and Panfrost PM flow are unchanged.

The Linux source is commit
`41e669babd391ff601e4763c9497e78fdd699306`, based directly on bus-clock
candidate `e4c56ce743ac605f70da0b88d44a9b6307cfd76c`. Its four reviewable commits
are:

- `0889c4735` — require the MT6797 MFG reset in the GPU binding;
- `db9295bab` — preserve the MT6797 1-microsecond pulse in the reset provider;
- `4cee08082` — request an initial reset from the MT6797 Panfrost compatible;
- `41e669b9a` — connect the GPU node to TOPRGU reset ID 2.

## Source audit

The vendor MT6797 Midgard platform source implements `toprgu_mfg_reset()` in
`drivers/misc/mediatek/gpu/gpu_mali/mali_midgard/mali-r12p1/drivers/gpu/arm/midgard/platform/mt6797/mtk_config_platform.c`.
It asserts MFG reset, delays 1 microsecond, and deasserts it during
`mtk_platform_init()`, before the first power-on callback.

Mainline already defines the same reset as `MT6797_TOPRGU_MFG_SW_RST` (ID 2)
and registers the `mediatek,mt6797-wdt` TOPRGU reset controller. That provider
already implements the reset framework's `.reset()` operation, but previously
asserted and deasserted with no delay. The candidate makes its MT6797 reset
operation preserve the vendor-backed 1-microsecond pulse width.

Panfrost already acquires an optional exclusive reset array. A boolean
compatible quirk now requests `reset_control_reset()` during MT6797
initialization and requires a real reset control. The provider owns the pulse
timing; the consumer owns the fact that this GPU needs an initial reset. This
also permits Panfrost's later exclusive assert/deassert runtime-PM operations
without mixing the forbidden shared-reset APIs.

## Build and static validation

- Each Linux commit passes `scripts/checkpatch.pl --strict --codespell`; the
  host has no codespell dictionary, but checkpatch reports zero errors,
  warnings, and checks.
- `dt_binding_check` for `arm,mali-midgard.yaml` passes with dtschema and
  yamllint.
- The composed `mt6797-gemini-pda-gpu-fixed-opp.dtb` builds with
  `CHECK_DTBS=y`. It adds no reset-related schema diagnostic. The command still
  reports pre-existing MT6797 SPI, PMIC, OPP-node-name, reserved-memory, and
  DVFSP schema diagnostics.
- The full Nix GPU fixed-OPP bundle builds successfully from the local Linux
  tree. Its validation proves the composed GPU reset cells equal the watchdog
  phandle plus reset ID 2 and pins the provider-owned 1-microsecond `.reset()`
  path plus the Panfrost reset-on-init request.

Exact output identities:

- padded p22: `9fe995447aae6c63ddf472e4d4dfafb239ecfed5a3809810ed3c3e7e01bc2113`;
- raw boot image: `85196dc27f54e6121778744f07c32a0670106547dad42991c51505882024cdc0`;
- kernel Image: `1de638e155b6153a4de3b16b06c2e59a0ea909139d06023e0aa533798e4d0d16`;
- base DTB: `3dc86d81b4b0a28f8814250f4b2376acc7ac6662d6220eab294b008e32babeb6`;
- composed serviceability DTB:
  `7d61ae2a447680ae071dd12fc8ac5d7d78484052cd6fc9f2c9702da60dfaf315`.

The bundle is available through `result-gpu-toprgu-v2` in this worktree. No
hardware mutation was performed while building or validating it.

## Hardware gate

If this candidate is later assigned a hardware lease, use the audited
observe-always-rollback p22 runner and the same immutable p30/p31 gates as the
bus-clock oracle. Before any runtime-PM write or Panfrost job, require all of
the following from the exact candidate boot:

1. exact candidate p22, p30, and p31 readbacks;
2. the expected core and bus clock rates and Mali-T880 identity;
3. no shader, tiler, or L2 power-transition timeout through the first idle
   transition.

Any timeout fails the gate. DRM registration is enumeration, not rendering
proof. The runner must restore and read back exact Stage A regardless of the
candidate result.
