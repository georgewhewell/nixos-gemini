# MT6797 Panfrost bring-up

Status as of 2026-09-03: **not working.** Two blocking defects found and fixed;
a third — the board stops enumerating USB entirely once Panfrost can actually
bind — is open and is the next thing to diagnose.

Kernel work is on `claude/gpu-fixed-opp-overlay-20260903`, branched from
`28c47150` (the revision `p22BaselinePlatformRevision` pins).

## What was already in place

Nothing needed inventing. `mt6797.dtsi` describes `gpu@13040000` as
`mediatek,mt6797-mali` with `CLK_MFG_BG3D` and the four `MFG_CORE0..3` power
domains, panfrost carries a real match for it
(`{ .compatible = "mediatek,mt6797-mali", .data = &mediatek_mt6797_data }`,
whose `pm_domain_names` are exactly `core0..core3`), and the board DT already
routes `mali-supply = <&rt5735_vgpu>` for the single entry of
`default_supplies`. The node was simply left `status = "disabled"`.

## Defect 1 — the composed overlay never existed

`nix/mainline-gpu-fixed-opp.fragment` and the composed-DTB acceptance checks in
`nix/mainline.nix` have both referenced `mt6797-gemini-pda-gpu-fixed-opp.dtbo`
for some time, but that overlay was never committed to linux-gemini. Every
`gpuFixedOppOverlay` profile therefore died in the kernel install phase with

    cp: cannot stat '.../mt6797-gemini-pda-gpu-fixed-opp.dtbo': No such file

The acceptance checks in `nix/mainline.nix` are a precise specification of what
the overlay must produce — read them before writing DT. They require `i2c7` and
`mfgsys` enabled, `gpu@13040000` enabled with `operating-points-v2`, the RT5735
provider at `min == max == 975000` uV with `regulator-boot-on`, and
`/gpu-opp-table/opp-500500000` at `0x1dd50620` Hz.

## Defect 2 — the MFG clock was silently never registered

`clk-mt6797-mfg.c` set `.num_clks = ARRAY_SIZE(mfg_clks)` = 1, but
`CLK_MFG_BG3D` is ID **1**. `__mtk_clk_simple_probe()` sizes the
`clk_hw_onecell_data` array from `num_clks`, so only index 0 was allocated and
the gate was rejected:

    /syscon@13000000: Trying to register duplicate clock ID: 1

**The probe still returned 0**, so the provider existed with no clocks in it and
nothing looked wrong until panfrost failed:

    panfrost 13040000.gpu: get clock failed -2
    panfrost 13040000.gpu: clk init failed -2
    panfrost 13040000.gpu: Fatal error during GPU init

Fixed by sizing with `CLK_MFG_NR`, as the other MediaTek clock drivers do.

## Hardware results

**Boot 1 (overlay only, clock still broken).** Booted, self-accepted, watchdog
held. Proved the DT half is correct: the rail came up at exactly
`vgpu: state=enabled uV=975000`, one OPP, no devfreq — so neither the MFG clock
nor the rail can move during a bind. Panfrost did not bind (defect 2).

**Boot 2 (clock fixed).** The board **stopped enumerating USB entirely** — no
gadget and no preloader for eight minutes. The Trex supervisor could not
recover it, because a board that never presents a preloader offers nothing to
catch, and it required a manual reset. This is consistent with this board's
history of GPU power-off faults.

## Boot 3 — the driver is not the culprit

A third image kept the GPU node enabled and the repaired clock but blacklisted
panfrost's initcall (`initcall_blacklist=panfrost_driver_init`, which `init/main.c`
accumulates per occurrence, so it coexists with the existing A72 entry).  The
intent was to reach a healthy SSH session and bind by hand against a console
streamed off-box.

The board went dark anyway.  Panfrost never binds in that image, so the fault is
**not** in the driver's probe path:

| boot | GPU node | CLK_MFG_BG3D registers | panfrost binds | result |
|------|----------|------------------------|----------------|--------|
| 1    | enabled  | no (the ID-1 bug)      | no             | healthy; rail at 975000 uV, self-accepted |
| 2    | enabled  | yes                    | yes            | board dark |
| 3    | enabled  | yes                    | no             | board dark |

Boots 1 and 3 differ only in whether the clock resolves.  So whatever kills the
board becomes reachable once `CLK_MFG_BG3D` exists, independently of panfrost —
and the rail is exonerated, since boot 1 held it at 975000 uV all session.

Ruled out so far: `mtk-scpsys.c` has no `.sync_state` callback, so the
"sync_state() pending due to 13040000.gpu" line in boot 1 is fw_devlink
bookkeeping and not a power action.  `clk_ignore_unused` is already on the
cmdline in every one of these images.  Still open: `genpd_power_off_unused()`
at `late_initcall_sync` sweeping the unused MFG_CORE0..3 domains (testable with
`pd_ignore_unused`), and anything that touches the BG3D gate once it is
registered.

## Next step

Do not simply retry, and above all do not power-cycle the board before pulling
evidence.  A rollback catcher must write **once** and then disarm; a keeper that
re-arms until the gadget returns will re-intercept every power-on, so the board
can never boot, and the repeated cycles wipe `console-ramoops` — that is how
boot 2's evidence was lost.  Read `/sys/fs/pstore/console-ramoops-0` first:
whether panfrost reset the GPU, which power domain was last touched, and
whether the die was during `pm_runtime` resume. Note the ramoops buffer is
64 KiB and **does wrap** (look for the `<<<RAM_RW>>>` marker), so a late message
being absent is not evidence it never happened.

Only then choose between narrowing the power domains, deferring the first
`pm_runtime` resume out of probe, or holding the rail differently.

## Do not fold this into the accepted baseline

The accepted full-NixOS baseline is identified by `touchscreenActivationOverlay`
or `fgadcActivationOverlay`, and it asserts an explicit negative contract that
the composed default DT leaves MicroSD, the GPU and the radios **disabled**. A
bring-up profile therefore sits beside the baseline — see
`mainlineP22BaselineGpu` — which also leaves `p22BaselinePlatformRevision`
untouched, since that pin is asserted only for those two flags.
