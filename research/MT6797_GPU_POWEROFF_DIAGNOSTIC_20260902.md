# MT6797 Panfrost vendor-parity diagnostic — 2026-09-02

## Decisive free evidence

The complete saved failed mainline boot already establishes:

- `gemini-gpu-busclk-hardware-20260902/candidate-runtime/dmesg-and-runtime-readonly.txt:1429`
  reports the Panfrost bus clock at 26000000 Hz;
- lines 1434 and 1436-1438 report `shader_present=0xf l2_present=0x1`,
  followed by shader, tiler, and L2 power-transition timeouts;
- lines 969-984 show SCPSYS and every MFG domain probing, with no
  `Failed to power on/off domain` in the complete log.

A bounded, read-only capture from stock Gemian 3.18.41 is preserved at
`/mnt/Home/src/gemini-gpu-vendor-oracle-20260902`. The exact command output is
in `01-discovery.txt`, `03-vendor-dmesg-full.txt`, `05-gpu-state.txt`,
`06-gpufreq-regulator.txt`, and `07-clock-power-state.txt`; the unfiltered
`sudo -n cat /sys/kernel/debug/clk/clk_summary` output is
`08-clk-summary-full.txt`.

The working vendor clock tree is decisive:

- `08-clk-summary-full.txt:134-136` shows
  `univpll2_d8 -> mfg_52m_sel -> infra_mfg_vcg`, all at 156000000 Hz;
- lines 268-273 show `pg_mfg_async -> pg_mfg -> pg_mfg_core0..3`, all with
  zero prepare/enable counts at idle;
- `09-clk-summary-mfg.txt:4-14` also shows BG3D at 500500000 Hz and every MFG
  gate/domain cleanly off at idle;
- `05-gpu-state.txt:8` identifies the same Mali-T88x MP4 r1p0, and its saved
  core-mask output is 0xf for JS0/1/2 and available cores.

This means the previous “bus-clock” boot was not vendor-equivalent: it enabled
the gate but left `mfg_52m_sel` on its reset/default 26 MHz parent.

Vendor source independently confirms the live state. In
`/nix/store/0km8xgjj4mjjsi7cljjl0bkjmpr1lwfz-source`:

- `.../platform/mt6797/mtk_config_platform.c:645-662` acquires the MFG clocks,
  the `mux-mfg52m` mux, and `mux-univpll2-d8` parent;
- lines 716-724 enable the mux, select `univpll2_d8`, disable the mux, and then
  pulse TOPRGU MFG reset;
- `arch/arm64/boot/dts/mt6797.dtsi:3057-3079` supplies those exact two clock
  handles to the vendor Mali driver.

Mainline already models the same topology:
`drivers/clk/mediatek/clk-mt6797.c:306-310` lists `univpll2_d8` as parent index
1, lines 379-380 define the mux, and line 536 parents `infra_mfg_vcg` from it.

One vendor-only trail remains deliberately outside this candidate: the vendor
power-on callback releases MFG bus protection and writes MFG-top timing/PMU
registers (`mtk_config_platform.c:302-320`), while its power-off callback polls
MFG idle and restores protection (`:361-389`). Vendor dmesg also reports a
G3D_CONFIG DEVAPC event at `03-vendor-dmesg-full.txt:2190-2199`. These are the
next source-level comparison only if the vendor-proven clock parent and reset
do not settle the transition; adding them now would make the boot ambiguous.

No reboot, workload, runtime-PM change, raw MMIO access, partition access, or
other state-changing hardware operation was performed during this capture.

## Smallest one-boot candidate

Linux commit `1158fcd3729634a884e613a8a3e0c9bb3801ba82` contains exactly:

1. the prior TOPRGU reset support;
2. two DT lines selecting `CLK_TOP_UNIVPLL2_D8` for
   `CLK_TOP_MUX_MFG_52M` (`mt6797.dtsi:354-355`);
3. read-only Panfrost snapshots before/after power-off timeouts and exactly one
   bounded 200 ms shader follow-up poll (`panfrost_gpu.c:483-547`).

The follow-up poll runs only after the unchanged 2 ms shader poll times out.
It submits no job and does not alter runtime-PM or SCPSYS policy. Full candidate
`dmesg` supplies the requested SCPSYS failures (if any), present masks, actual
core/bus rates, and the added transition/ready/active/fault state.

Built bundle:

- `/mnt/Home/src/gemini-gpu-poweroff-diagnostic-vendor-clock-20260902`;
- padded p22 SHA-256
  `45323858e1cfbb34e367f65e808f6471b48a2be515e6cfcf76a799588386d2be`;
- raw boot SHA-256
  `48fe19b6d36ee569b7b25e79e886f029e9dfa0b6db5d8027ecf4ae2817306ea1`;
- kernel Image SHA-256
  `dfe7419d1d8eed9c2b2c8b474f2e86ddcbe8c11c2f7ec5e140fa88c9ec6e195b`;
- final DTB SHA-256
  `b994951c29c96a0110145ea6f6d770ebdf8153b7621fedc5dd40975e4c272e49`;
- initramfs SHA-256
  `7613c3fe0adb671fb504eefa6a810f218ed544870382e1b3064f95ee4df6503c`.

`fdtget` confirms the final DTB contains assigned clock `(phandle 6, id 0x22)`
and parent `(phandle 6, id 0x40)`, i.e. the MT6797 MFG-52M mux and
`UNIVPLL2_D8` binding IDs.

Manifest: `research/p22-gpu-poweroff-diagnostic-20260902.manifest`.

Execute the single observe-always-rollback transaction with:

```sh
/home/grw/src/nixos-gemini/research/p22-recovery-harness.sh \
  --manifest /home/grw/src/nixos-gemini-gpu-busclk-20260902/research/p22-gpu-poweroff-diagnostic-20260902.manifest \
  --execute --proof-lease
```

Capture the complete candidate `dmesg` during the lease. Do not access GPU MMIO
from userspace after runtime suspend.

## One-boot decisions

| Observation | Decision |
| --- | --- |
| Bus rate is not 156000000 | Assigned-parent parity did not apply; stop and fix DT/clock setup. |
| Bus is 156 MHz and no shader/tiler/L2 timeout | Vendor-proven reset+bus setup fixed power-off. Keep both; vendor uses both, so no isolation boot is needed. |
| Shader clears only in the extra 200 ms window | The transition is valid but slow; retain the evidence and set the smallest justified timeout. |
| Shader remains transitioning after 200 ms with ready mask 0xf | Clock/reset parity is insufficient; next compare vendor MFG-top preconditions and exact SPM SRAM acknowledge behavior. |
| `PWRTRANS=0` but shader ready remains 0xf | PWROFF was ignored; inspect power override and mask/precondition handling. |
| Shader clears but tiler or L2 alone times out | Diagnose that first later block from its logged ready/transition/active state. |
| Fault status or power/fault IRQ bits are nonzero | Decode the GPU fault before changing sequencing. |
| Any `Failed to power on/off domain mfg*` | Fix the SCPSYS domain model before another Panfrost experiment. |
| Present masks differ from shader 0xf / L2 0x1, or reads are all ones | Stop: register decode/regression, not power timing. |

The transaction always restores accepted p22 baseline SHA-256
`c096e1ee48b0413a2de4f391b846a061928497ba390d471d4507f0c6a0900949`.
