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

## Next step

Do not simply retry. The failing boot's `console-ramoops` survives a rollback,
so read `/sys/fs/pstore/console-ramoops-0` first and find how far the bind got:
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
