# MT6797 Wi-Fi W1 firmware READY result — 2026-08-31

This is a bounded hardware result for the Gen3 firmware download/start path.
It is not a Wi-Fi interface, an IRQ proof, or a networking claim.

## Immutable capture

- Capture:
  `/mnt/Home/src/w1-firmware-forensic-p22-one-shot-20260831-v1/captures/p22-one-shot-20260831-093439-400282`
- Predecessor p22, captured in `preflash-p22.img`:
  `d07891e271ca3f331a61a0175787b629823eacb999d1d83aa73f9cb6b29f99dd`
- Candidate and 16 MiB `postflash-p22.img`:
  `3f3cfbc0df2c96d715d0dd079cec34e36294b042f85454ba9d0afe487f358618`
- The postflash image byte-matches the staged `boot-padded-p22.img`; the one
  p22-only Flash Tool transaction completed with `flash_rc=0`.
- `p22-readback.log` records the full-device SHA-256 readback.  The preserved
  16 MiB `postflash-p22.img`, `preflash-p22.img`, Flash Tool, pstore, gadget,
  RTL, and Trex watcher logs remain in that capture directory.

## Observed causal sequence

`w1-diag-wmt-wcir-watchdog.log` has SHA-256
`a2ff1b40b4718175fb24ee5da0ab297ab2ff6badfd2725ffcb793837d5d4baf0`.
The common precondition passed (`WMT14 result=0`, RF calibration event and
WCIR `0x100279`, chip `0x0279`, READY clear).  W1 then reported:

- function enable: IOEx `0x0 -> 0x2`, IORx `0x2`;
- vendor-shaped driver ownership: success after eight polls and one OWN_CLR;
- encrypted sections 0 and 1: acknowledged, then exact IDLM totals
  `5840/5840` and `8992/8992` bytes;
- temporary 512 KiB CONSYS EMI window: open, section 2 copy `0x50e20`,
  section 3 copy `0xff70`, close — all successful;
- Wi-Fi Start sequence 3, then `READY raw=0x300279 polls=5`;
- post-ready status `WHISR=0x82` with all eight release counts clear;
- IOEx and PALDO cleanup successful (`causal=0`, `cleanup=0`, `fatal=0`).

This follows the vendor startup order in
`drivers/misc/mediatek/connectivity/wlan/gen3/nic/nic_pwr_mgt.c:262-389`:
driver ownership, polling firmware download, Wi-Fi Start, READY, status/TX
resource reset and only then interrupt enable.

## Boundary for W2

No Wi-Fi IRQ was requested in this boot (`/proc/interrupts` has no Wi-Fi IRQ
consumer) and no netdev/cfg80211 object was registered.  W2 must use a fresh,
source-backed normal command/event after the post-READY status clear; stale
`WHISR=0x82` is not an IRQ proof.
