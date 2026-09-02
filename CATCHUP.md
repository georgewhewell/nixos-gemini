# Gemini mainline bring-up handoff

Snapshot: 2026-08-31 09:15 CEST.  This is a live handoff to a Codex running
on `trex`.  Three delegated workers are intentionally still running, so their
branches and artifacts may advance after this snapshot.  Inspect the current
worktrees and Trex units before repeating work.

## 09:37 CEST authoritative update

Wi-Fi W1 firmware READY passed in one exact p22-only hardware cycle.  This
supersedes the 09:15 timeout diagnosis and every earlier current-p22 hash:

```text
current p22 SHA-256:
3f3cfbc0df2c96d715d0dd079cec34e36294b042f85454ba9d0afe487f358618

Linux: eaa7505dbddc50acc20302662adc98d11b2564d2
Nix:   c6937dc6c80a1b7d841523b54ed9234ae55ee0bd
stage: /mnt/Home/src/w1-firmware-forensic-p22-candidate-20260831-v1-stage
capture: /mnt/Home/src/w1-firmware-forensic-p22-one-shot-20260831-v1/captures/p22-one-shot-20260831-093439-400282
```

Flash Tool invoked once, wrote only partition `boot`/p22, returned success,
and the complete 16 MiB postflash readback byte-matched the candidate.  The
predecessor capture remains exact `d07891e...f99dd`; no retry or rollback ran.
The decisive W1 telemetry was:

```text
function-enable: IOEx 0x00 -> 0x02, IORx 0x02
driver-own: ret=0, polls=8, requests=1, WHLPCR last=0x00000100
config sections 0/1: ret=0, exact ACK sequence/status, three polls each
IDLM: 5840/5840 and 8992/8992 bytes
EMI: sections 2/3 copied (0x50e20 and 0xff70), close ret=0
WIFI_START: ret=0
READY: ret=0, WCIR raw=0x00300279, polls=5
post-ready: WHISR=0x82, all release counts zero
cleanup: IOEx restored to zero; PALDO causal=0 cleanup=0 fatal=0
```

WMT14/RF calibration, gadget SSH, RTL SSH, pstore and watchdog also passed.
This proves the MT6797 Wi-Fi firmware/portal/EMI/start/READY path.  It does
**not** yet prove IRQ delivery, a netdev, association or traffic: the image
deliberately requested no Wi-Fi IRQ and fenced every client.  The Wi-Fi lane
has moved directly to the exact post-READY NIC-capability command/event and a
fresh IRQ source, with a maintained wlan/netdev as the target.

## 09:15 CEST authoritative update

The current p22 remains the W1 safe-fail image at
`d07891e271ca3f331a61a0175787b629823eacb999d1d83aa73f9cb6b29f99dd`.
After the host reboot, the board again booted that image, exposed the gadget
through Trex, and reported CPUs `0-7` online.  The initramfs deliberately
expired its userspace watchdog lease at 139 seconds; the 31-second MTK
watchdog then reset the board and the `0525:a4a2` USB gadget re-enumerated.
That is a fresh unattended-reset proof, not a missing watchdog feeder.

The W1 timeout comparison is now sharper.  The exact vendor Gen3 source is
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/wlan/gen3/nic/nic_pwr_mgt.c:147-223`.
Its real driver-own loop permits 2048 ms, sleeps 900--1000 us, and rewrites
`WHLPCR_FW_OWN_REQ_CLR` every 256 iterations.  The W1 candidate instead used
only 256 x 8 us.  The Wi-Fi worker is mirroring the vendor loop exactly and
adding stage/register evidence before preparing a second candidate; no second
flash has been authorized yet.

IXOO upstream was refreshed to exact tip
`4c1143012226586dc13b24eb1042422f1b4dfa69`.  Their preceding hardware run
crossed isolation but stopped at the SRAM binder/result boundary with
`-EPROTO`; CPU8 remained offline and PSCI `CPU_ON` was not reached.  The new
tip only deploys an SRAM/P28 diagnostic on IXOO's own boot2 and awaits a
physical boot.  Our A72 worker is rebuilding from that evidence against the
current recovery/network/display baseline.  On this device the rule remains
strictly p22 only: never copy IXOO's p30 deployment target.

Cellular v8 is staged, dormant and unflashed at
`/mnt/Home/src/md1-lk-handoff-p22-candidate-20260831-v8` (Linux
`767e75c3acc22c055c54d19f7ac0616459ccf6cd`).  It adds a source-shaped secure
EMI-MPU provider which captures SMC status and irreversibly fatal-latches any
attempted partial transaction.  The final config intentionally leaves this
and the MD1 fence disabled.  It is a safety substrate, not a viable modem yet;
the lane continues on the exact boot-vector/reset/power/clock/CCIF ownership
sequence.

## 09:00 CEST authoritative update

This update supersedes every older `current p22` statement.  Bluetooth G2f
first passed one isolated hardware cycle from GNSS-v2, proving PALDO,
BT `FUNC_CTRL` on/off, bounded private-H4 Reset and Read Local Version, and
clean shutdown/fence.  Its capture is:

```text
/mnt/Home/src/g2f-bt-p22-candidate-20260831-v1/captures/p22-one-shot-20260831-054320-106996
Bluetooth p22 SHA-256: 18749fe32257bd45bfca461dee7137086dcb6d25842510cb3b826f5ee03ee2c4
```

Wi-Fi W1 was then attempted exactly once.  The write/readback and recovery
path passed, but the radio milestone safely failed before firmware READY:

```text
current p22 SHA-256:
d07891e271ca3f331a61a0175787b629823eacb999d1d83aa73f9cb6b29f99dd

candidate: /mnt/Home/src/w1-firmware-ready-candidate-20260831-v4-stage
capture:   /mnt/Home/src/w1-firmware-ready-p22-one-shot-20260831-v4/captures/p22-one-shot-20260831-085702-293795
Linux tip: 4f790caaf0272835f53c84ca45da778cc153035b
Nix tip:   6bb595741608b6cc8ce0aa59c0533103844d3f61
```

The common path and W0 still passed (`WMT14`, RF-cal, and WCIR
`0x00100279 ready=0`).  W1 returned `-ETIMEDOUT` about 7 ms after the W0
observation and fenced/reset cleanly; both SSH paths and watchdog recovery
returned.  No IRQ or netdev was claimed.  In the exact built source, the only
timeouts early enough to fit this observation are function-enable IORx and
driver-own; DOWNLOAD_CONFIG acknowledgement and READY each have roughly
one-second bounded polls.  This is a strong narrowing, not yet a confirmed
stage.  The active Wi-Fi lane is adding causal stage/register/cleanup logs
before any second attempt, while the hardware lane maps every return path and
performs no write.

## 05:40 CEST authoritative update

This update supersedes every older statement below about the current p22
image or GNSS being untested.  The corrected GNSS-v2 candidate completed one
and only one p22-only write, with no retry and no rollback:

```text
current p22 SHA-256:
366db0043b21c3f1d124138fc3830511a648d8d14d1669c2e780a033148f2c47

Linux tip: c88b14542158de2cad0bd68ede1a55d0d834fb15
Nix tip:   d5dff08e2e1af0a62531f32a19068aa72e83cb1e
candidate: /mnt/Home/src/gnss-p22-candidate-20260831-v2-pinctrl
capture:   /mnt/Home/src/gnss-p22-candidate-20260831-v2-pinctrl/captures/p22-one-shot-20260831-053523-55814
```

Flash Tool returned success and exact 16 MiB p22 readback passed.  Both
gadget and RTL SSH returned, and unattended recovery remained healthy.  The
decisive hardware output was:

```text
WMT14 result=0
G2d GNSS probe passed: GPIO69 LNA init/on/off and GPS FUNC_CTRL on/off acknowledged; bootstrap will fence/reset
G2d RF calibration event: len=378 prefix=00 01
```

The supported GPIO69 mux/output-only pinctrl correction therefore resolves
the earlier `-ENOTSUPP` failure.  This proves the bounded GNSS power/control
path and cleanup acknowledgement; it does not yet prove UART data or a
position fix.  The hardware lane has moved directly to the bounded Bluetooth
G2f HCI Reset/Read Local Version candidate, with its new manifest required to
name the current p22 hash above.

## 05:22 CEST authoritative update

This update supersedes the older W0-v5/v6 and "GNSS untested" statements
later in this document.  The current p22 image is corrected W0-v7:

```text
current p22 SHA-256:
c1fbdaf692f319583f9a32d7d6cb0f0f70077769f966e66cd1922fef353b006e

Linux tip: 12140b6291e1d25f0d707572849117a70499d116
Nix tip:   0d6eb1bde143ee112b01fb39a7ea9ce27cb7d92c
candidate: /mnt/Home/src/w0-hif-p22-candidate-20260831-v7
capture:   /mnt/Home/src/w0-hif-p22-candidate-20260831-v7/captures/p22-one-shot-20260831-051843-11232
```

The single p22-only write and exact readback passed.  Gadget and RTL SSH both
returned.  Decisive hardware output was:

```text
WMT14 result=0
G2d RF calibration event: len=378 prefix=00 01
WCIR raw=0x100279 chip=0x0279 rev=0 por=1 ready=0
G2d passed; bootstrap will fence/reset
```

Thus CONSYS, the GEN3 CMD53 HIF portal and field-wise WCIR decoder are
hardware-proven.  Wi-Fi is not a network interface yet: the active W1 lane is
implementing the vendor's split RAM-code download, including the later
sections written through the 512 KiB CONSYS EMI window after a temporary MPU
permission change, followed by bounded firmware-start/IRQ/READY evidence.

GNSS also received one isolated hardware test before W0-v7:

```text
candidate SHA: 0135afa346c67ecd7673a72f6320f228b681cb6456534e6e369a9bfe93268f9e
capture: /mnt/Home/src/nixos-gemini-gnss-p22-hardware/artifacts/mainline-consys-g2d-gnss-p22/captures-w0v6-gnss-0135afa/p22-one-shot-20260831-050132-3772610
result: G2d GNSS causal stage gnss-lna-init failed: -524
cleanup: LNA-low=-524 FUNC_CTRL-off-attempted=0 result=0
```

This was safe and decisive: no GPS FUNC_CTRL-on was transmitted.  Mainline
MT6797 pinctrl currently exposes MODE/DIR/DI/DO only, while the experimental
GNSS states requested unsupported slew-rate and bias-disable operations.  The
active hardware lane is removing only those unsupported properties, retaining
GPIO69 pinmux plus output-low/high, and rebuilding before any retest.

The host rebooted after those cycles and killed the original workers; three
new Terra workers were recreated from preserved state.  Current lane names
are `wifi_firmware_bringup`, `cellular_md1_bringup`, and
`radio_hardware_test`.  Cellular has advanced to Linux `592c5840d` and Nix
`10e1562`: it encodes a fail-closed RMPU/remap diagnostic plan based on the
vendor order, but has not powered or released MD1 and has not touched modem
partitions.

## Mission and priorities

The goal is full usable mainline Linux/NixOS hardware support for the Planet
Computers Gemini PDA (MediaTek MT6797), not a collection of compile-only
stubs.  The present critical path is:

1. Wi-Fi, Bluetooth, GNSS, then cellular/MD1.
2. A Cortex-A72 CPU8 hardware proof to shorten later build/test cycles.
3. Integrate every hardware-proven lane into the maintained Linux tree and
   flake.
4. Return to lower-priority platform gaps (touch, audio, power, sensors,
   camera and GPU) without polishing irrelevant MicroSD/FM work first.

Research must use primary source with exact file/line evidence.  An explicit
unknown is better than an invented answer.  Do not use Gemini research for
this campaign; Luna/Terra have been materially more reliable.

## Non-negotiable safety boundary

- Experimental boot writes are **p22 only** (`boot`, exactly 16 MiB,
  PARTUUID `fbc2c131-6392-4217-b51e-548a6edb03d0`).
- Never raw-write or reformat p29, write p30/p31, or modify the bootloader,
  GPT, or modem partitions p13-p16.  The owner delegated Gemini hardware
  stewardship on 2026-09-02; ordinary deployment may add a uniquely named,
  hash-verified file inside the existing p29 filesystem only through a
  no-clobber transaction that leaves all existing files intact.
- p13-p16 may be read for evidence only.
- Use one-entry `Download Only`; no automatic retry and no automatic rollback.
- Resolve the live eMMC partition, size, PARTNAME/PARTUUID and current SHA-256
  immediately before every write.
- Keep watchdog, pstore, gadget Ethernet, BROM capture and the Trex network
  watcher in every experimental image.
- A failed proof must be bounded, instrumented, cleaned up where possible and
  fenced/reset.  Do not turn a proof into a permanent client merely because it
  compiled.

Locked flash inputs:

```text
/mnt/Home/src/nixos-gemini-flash-p22-20260829/Gemini_NixOS_boot_only.txt
  sha256 19f5d2cba03310e744056036fb9805dfc4686b54e2c25e08d532895efd6650f8
/mnt/Home/src/nixos-gemini-flash-p22-20260829/download-only-strix-4.xml
  sha256 90eec878d01866f37f927f0e6d1d768517a758790d818d6252091fca7b212605
```

The proven orchestrator is:

```text
/mnt/Home/src/nixos-gemini-g2e-pio-build-src/research/p22-one-shot-no-rollback.sh
```

It is written to run on the old development host: it hard-codes a
`ProxyCommand` through Trex and `/home/grw/.ssh/id_ed25519`.  Do **not** run it
unchanged from Trex (that would recursively SSH to Trex).  Either continue to
invoke it on the old host, or make and review a Trex-local variant that keeps
all of its exact target/hash/scatter/XML/lock/session checks.  Do not weaken
Dropbear authentication or casually copy private keys as a shortcut.

## Live device truth

The last completed hardware cycle was the Wi-Fi W0 v5 probe:

```text
current p22 SHA-256:
9b28c67b12b992336ef5b6be28658ea68dfca99b68e95125681b4a3aaf934771

candidate/run:
/mnt/Home/src/w0-p22-candidate-20260831-v5
/mnt/Home/src/w0-p22-candidate-20260831-v5/p22-one-shot-20260831-042214-3661100

RESULT:
p22-readback=PASS sha256=9b28c67b12b992336ef5b6be28658ea68dfca99b68e95125681b4a3aaf934771
```

Flash Tool returned `Download Succeeded`, exact p22 readback passed, and both
gadget and RTL Ethernet were reachable after boot.  The image remains the
default p22 image until a later explicitly verified write replaces it.

The common CONSYS path still passed on this boot:

```text
WMT14 result=0
WMT14 event[0] ... op=0x14 len=378 ...
G2d RF calibration event: len=378 prefix=00 01
```

The W0-specific observation then failed:

```text
G2d Wi-Fi WCIR phase failed: -19
error -ENODEV: G2d probe controller start or post-patch stage failed
```

Live `/proc/device-tree` proved there was no Wi-Fi HIF node.  Source inspection
then found two exact defects in v5: the observer searched case-sensitive
`mediatek,WIFI`, while vendor `mt6797.dtsi:3775-3781` uses
`mediatek,wifi`, and the mainline/overlay DT did not describe
`wifi@180f0000` at all.  This is a DT/discovery failure, not evidence that the
radio is dead.

Trex USB/gadget facts:

```text
USB ID:       0525:a4a2
product:      Gemini-L-DA921x-Bind
host MAC:     42:00:15:19:82:00
device MAC:   42:00:15:19:82:01
Trex address: 10.15.19.81/24
device:       10.15.19.82/24
usual iface:  enp232s0f4u2
RTL path:     device 192.168.23.70 (when DHCP is current)
```

The device intentionally cycles gadget -> MediaTek preloader `0e8d:2000` ->
gadget during unattended recovery.  A temporarily absent interface is not a
brick.  The exact identity-guarded watcher is:

```text
/mnt/Home/src/nixos-gemini-g2e-pio-build-src/research/trex-gadget-net-watcher.sh
```

Several old watcher processes are currently accumulated on Trex.  Keep one
identity-checked watcher alive during hardware work; clean duplicates only
after proving which process/log belongs to the active cycle.

## Immediate Wi-Fi continuation

The v6 fix is implemented in clean isolated branches:

```text
Linux worktree: /mnt/Home/src/linux-gemini-w0-hif-node-fix
branch:         codex/w0-hif-node-fix
tip:            3e8205a3acf614e4ce6927f4fdb561930978dcd1

Nix worktree:   /mnt/Home/src/nixos-gemini-w0-hif-node-fix
branch:         codex/w0-hif-node-fix
tip:            0d6eb1bde143ee112b01fb39a7ea9ce27cb7d92c
```

The Linux commit corrects the compatible, adds the disabled exact
`wifi@180f0000` portal to the experimental overlay, and logs all early HIF
discovery/resource failures.  The Nix profile alone changes its status to
`okay` and validates compatible/status/reg; non-W0 profiles leave it disabled.

Trex cannot use worktrees whose `.git` files point back to the old host's
`/home/grw/src`.  Exact plain exports were therefore made:

```text
/mnt/Home/src/linux-gemini-w0-hif-node-fix-source-v6
/mnt/Home/src/nixos-gemini-w0-hif-node-fix-source-v6
```

The Trex build completed successfully:

```text
terminal unit: w0-hif-v6-build-archive.service (ExecMainStatus=0)
bundle store:  /nix/store/07dzmvdga30smj4x1cik8blvabrqkcdl-...-bundle
out-link:      /mnt/Home/src/mainline-wifi-w0-hif-p22-bundle-v6
durable stage: /mnt/Home/src/w0-hif-p22-candidate-20260831-v6
padded SHA:    4b61421020c2c5e17373e5a6564aa2ef83dbfd55435f43c2808229f30d065990
size:          16777216
DTB SHA:       3194af8d2ac9b394ea08468653855bfd2a7fe2e94adeaa8f9546fbbe44c3596b
```

The store path was verified and the files copied byte-for-byte to the durable
stage.  A review-only manifest is prepared at:

```text
/mnt/Home/src/w0-hif-p22-candidate-20260831-v6/p22-one-shot-no-rollback.manifest
```

It expects the current v5 p22 hash, but it has not been dry-run or executed
because the gadget was between recovery windows while this handoff was being
written.  Recheck the completed journal if needed:

```sh
systemctl --user status w0-hif-v6-build-archive.service --no-pager
journalctl --user -u w0-hif-v6-build-archive.service --no-pager -n 100
```

If the artifact disappears or verification later contradicts this snapshot,
inspect the journal before deciding whether to rerun.  The exact rerun is:

```sh
cd /mnt/Home/src/nixos-gemini-w0-hif-node-fix-source-v6
nix build -L .#mainlineConsysG2dWifiW0Bundle \
  --override-input linux-gemini-next \
  path:/mnt/Home/src/linux-gemini-w0-hif-node-fix-source-v6 \
  --out-link /mnt/Home/src/mainline-wifi-w0-hif-p22-bundle-v6
```

Next: inspect the staged DT/cmdline/config and manifest, dry-run against the
live device, then perform one p22 cycle.  The decisive next log is a real
`WCIR raw=...` (expected vendor chip identity `0x00000279`, ready bit still
zero before Wi-Fi RAM firmware).  Do not skip straight to firmware if portal
setup still fails.

## Common CONSYS result already hardware-proven

The tested branch is:

```text
/mnt/Home/src/linux-gemini-g2e-pio-streaming-fix
codex/mt6797-g2e-pio-streaming-fix
```

Important commits:

```text
0d8ff90fa stream BTIF PIO RX rather than imposing an artificial 256-byte total
239ab1f1c harden G2d VCN33 cleanup
0202f4801 trace G2d RF-cal WMT
770cca2d0 accept bounded MT6797 RF-cal events
```

This branch is pushed to the `george` fork.  Hardware proved the vendor's
opcode `0x14` RF-cal event is 378 bytes.  Vendor `wmt_core.c` deliberately does
not compare its content; our original exact two-byte matcher caused the false
timeout.  `770cca2d0` accepts the bounded complete event while copying only the
two-byte prefix.  It passed on two independent boots.

The consolidated radio branch is clean at:

```text
/mnt/Home/src/linux-gemini-radio-p22-consolidated
codex/radio-p22-consolidated
bc9816bb33288135e6eda1d167cab24affcfa4e3
```

It contains G2d, isolated W0, GNSS, G2e/G2f Bluetooth proof code and the H4
collector.  `82aa8edf5` fixes partial PALDO/FUNC_CTRL mutation cleanup;
`bc9816bb3` restores the lifecycle-locked, address-equal full-WMT lease
predicate.  These proof clients are not yet a normal radio subsystem and must
stay separately gated.

## Active delegated lanes (leave them running)

### Cellular / MD1 (Terra)

```text
Linux: /mnt/Home/src/linux-gemini-md1-cellular-candidate
branch: codex/mt6797-md1-cellular-candidate
clean tip: 8bb7b9830e3910899573306f2f8e5925639cb311

Nix: /mnt/Home/src/nixos-gemini-md1-cellular-candidate
branch: codex/mt6797-md1-cellular-candidate
clean tip: b59f714601c49114742fa212e5bad90d5de7d492
```

Achieved: atomic-output v4/v5/v6 `md1_chk` parsing, LK-v2 tag/modem/shared
layout parsing, negative KUnit coverage, and a DT+module-gated **read-only** LK
handoff probe.  It validates `/chosen`, proves table/MD1/shared ranges are
contained by `mediatek,ccci` reserved memory, maps only the no-map LK table,
validates the header contract, then unmaps.  It does not touch p13-p16,
MPU/remap, clocks/power/reset, CCIF/CLDMA/DMA or MD1 release.

The Nix profile exports `mainlineMd1LkHandoffProbe*`, evaluates successfully
and preserves eMMC, gadget/RTL, key-only SSH, pstore, display/audio/power/input
observation and watchdog recovery.  It excludes CONSYS/GPU/touch/FGADC/SD
activation.  Its original manifest p22 precondition `637944...` is stale;
replace it with the current `9b28c67b...934771` only after rebuilding and live
preflight.

The plain-source Trex build completed successfully with:

```sh
cd /mnt/Home/src/nixos-gemini-md1-cellular-candidate-build
nix build --no-link --print-build-logs \
  --override-input linux-gemini-next \
  path:/mnt/Home/src/linux-gemini-md1-cellular-candidate-nixsrc \
  .#mainlineMd1LkHandoffProbeBundle
```

Verified outputs (not flashed):

```text
bundle:
/nix/store/wkjhckz19lja4cj22jn0yixc1jxpa9h0-...-md1-lk-handoff-bundle

padded p22 image:
/nix/store/idagycpxjwdv5kiqhh9947f32rd0zjkc-...-md1-lk-handoff-padded.img
size 16777216
SHA-256 d922d45dbe80e76f976bc41978381e2e5be3938ce7cf9af4ab167d6e1f2afce1

durable review stage:
/mnt/Home/src/md1-lk-handoff-p22-candidate-20260831-v1

raw image SHA-256:
a57457d8d3efcf4b1acbbebf8d18e5d90b1991db554c8bff5b1f88e47737845d
```

Nix-store verification, byte-identical durable staging, Android
header/padding, deployment config, exact cmdline gate, composed DT gates and
initramfs evidence routing all passed.  `FLASH-REVIEW-MANIFEST.md` in the stage
supersedes the stale build-manifest precondition with current p22
`9b28c67b...934771` and explicitly prohibits generic executor use.  No flash
is authorized.  The worker is continuing to the source-backed MPU/remap stage
with MD1 still fenced.

Live read-only modem evidence:

```text
p13 0x1800000 f3d514f0cdcdfb2addbf70b9dbf9cbd0e41ea646eb342eb759bbc4f215f2d0cf
p14 0x0400000 2b0d7322d0df0fabf957f38f215822eba3c134d75a30faae2965996dc4c42829
p15 0x0300000 756070f69e02249f5478e978b03214eb17aa30adfec591cffe9af8748507ce95
p16 0x0500000 dc0c3cbe5b2401919239af49ea6e0a610e5e7bea9bc155cf82a9655434e77750
```

p13 is an MTK `md1rom` container, not a padded partition containing a
discoverable `CHECK_HEADER`; LK supplies distinct `md1_chk` and `md1img`
records.  Do not scan/write the partition based on the earlier assumption.
After the metadata probe, the next real blocker is the exact source-backed EMI
MPU/remap contract, then bounded MD1 power/release/CCIF, then minimal CCCI/CLDMA
control or AT.  The mandate is a viable cellular candidate, not merely a parser.

### GNSS

```text
Linux: /mnt/Home/src/linux-gemini-gnss-p22-hardware
branch/tip: codex/gnss-p22-hardware efd548d52

Nix: /mnt/Home/src/nixos-gemini-gnss-p22-hardware
branch/tip: codex/gnss-p22-hardware 60783c0dcdb34f2b6c38c05288b5805522a72a88

Trex exports:
/mnt/Home/src/linux-gemini-gnss-p22-hardware-trex-src
/mnt/Home/src/nixos-gemini-gnss-p22-hardware-trex-src

bundle link:
/mnt/Home/src/nixos-gemini-gnss-p22-hardware-trex-src/result-gnss-p22

durable image:
/mnt/Home/src/nixos-gemini-gnss-p22-hardware/artifacts/mainline-consys-g2d-gnss-p22/boot-padded-p22.img

padded image SHA-256:
0135afa346c67ecd7673a72f6320f228b681cb6456534e6e369a9bfe93268f9e
```

The isolated G2d+GNSS bundle built successfully.  It implements exact GPS
FUNC_CTRL type 2, GPIO69 LNA init/low/high sequencing, no invented GPS_SYNC,
and compensates uncertain FUNC_CTRL-on with bounded LNA-low + GPS-off before
the outer fence/reset.  W0 and Bluetooth gates are absent.  The worker copied
current p22 read-only and verified its exact `9b28c67b...934771` hash.  That
copy is evidence only: do not add automatic rollback or a second Flash Tool
invocation.  A briefly committed generic rollback manifest was recognized as
violating this campaign boundary and deleted by corrective commit `60783c0d`;
use only the proven one-shot/no-rollback path.  The current image also
changed the SSH host key, so use the pinned authorized key with the proven
ephemeral known-host policy rather than accepting an unverified key.  The
GNSS image has not been hardware-tested and must not be called a receiver yet;
after the function proof, a durable STP GNSS endpoint and checksum-valid NMEA
are still required.

### Bluetooth G2e/G2f

```text
Linux: /mnt/Home/src/linux-gemini-g2f-p22-candidate
branch/tip: codex/g2f-p22-candidate 2611387bbe1850fb42bdc16479afc72d5d409f2e

Nix: /mnt/Home/src/nixos-gemini-g2f-p22-candidate
branch/tip: codex/g2f-p22-candidate f3197fbd719a5c58d3b6885990b80664c122aee1

G2e bundle: /mnt/Home/src/mainline-g2e-bt-function-p22-bundle-v1
G2f bundle: /mnt/Home/src/mainline-g2f-bt-hci-proof-p22-bundle-v1

durable G2e image:
/mnt/Home/src/g2e-bt-p22-candidate-20260831-v1/boot-padded-p22.img
SHA-256 f4988a1e15707121741471d40e65f88f4a32b018ae9e6047134fbde77e91198d

durable G2f image:
/mnt/Home/src/g2f-bt-p22-candidate-20260831-v1/boot-padded-p22.img
SHA-256 18749fe32257bd45bfca461dee7137086dcb6d25842510cb3b826f5ee03ee2c4
```

Both bundles built successfully.  G2e is exact PALDO + WMT opcode 6
`{00,01}` then `{00,00}`.  G2f adds H4 Reset `01 03 0c 00` with exact 7-byte
Command Complete and Read Local Version `01 01 10 00` with exact 15-byte
success.  The H4 collector covers fragmentation, coalescing, async packets,
oversize/malformed data, timeout/late RX/fencing and >256-byte ACL.
`2611387b` requires the live private lease and fences the collector on every
transmit/wait/status failure.

The worker is staging and verifying durable images.  Hardware order is G2e
first, then G2f only if G2e cleanup/result is understood.  Neither registers a
normal HCI device or proves user-visible Bluetooth yet.

## A72 CPU8 lane

This lane is built and waiting behind radio hardware cycles:

```text
worktree: /mnt/Home/src/linux-gemini-platform-a72-reviewed
branch:   codex/a72-cpu8-reviewed
clean commits:
  3a7991555 admission compatibility chain
  70b14902c watchdog takeover
  f7da950c1 pstore evidence
  a86ad3dd1 pstore interfaces
  0b0f067b5 register admission DTB

candidate: /mnt/Home/src/a72-cpu8-reviewed-boot.img
size:      16777216
SHA-256:   29d9d26926e61accd78c55e29836e47d0333ee2435c4e3d2440715f5347fbb54
```

Full Trex `vmlinux`, `Image.gz` and admission DTB builds passed; the DT has the
platform/DVFSP/admission nodes and cmdline uses `maxcpus=8`.  CPU9 remains
disabled/vetoed.  This image has **not** been flashed and CPU8 has no runtime
proof.  Before testing, rebuild/integrate it against the latest retained radio
and recovery substrate rather than blindly overwriting current p22 with a
stale composition.

## Other platform status

Use these claims conservatively; `campaign/00-roadmap-and-status.md` and the
radio chapters are older than the G2d/W0 work and contain stale p22 hashes and
obsolete “no CONSYS” claims.

| Track | Best current evidence | Remaining work |
|---|---|---|
| Boot/recovery | Mainline 7.1.3 Android-v0 p22 image repeatedly boots; pstore, watchdog/BROM, gadget SSH and exact p22 readback work. | Integrate branches cleanly; preserve unattended recovery. |
| eMMC | Samsung DF4064 58.2 GiB enumerates with p1-p33; bounded reads work; p22 writes/readback proven. | Normal NixOS root/storage policy; never use p29-p31 as scratch. |
| USB gadget | `g_ether` at 10.15.19.82 and key-only Dropbear work. | Maintain across integrated image; clean duplicate host watchers. |
| Right USB host/Ethernet | MUSB host and RTL8156/RTL USB NIC path have enumerated and carried SSH/iperf traffic. | Dynamic Type-C/PD/role handling and broader devices. |
| Display | DRM/DSI/fb bound and the user physically saw the panel image. | Integrate latest radio/CPU work without regression; backlight/power/suspend polish. |
| Touch | NT36772 identity (`1-0062`, trim `00 00 03 72 66 03`) and input device were observed in a bounded overlay test. | Physical touch events and safe normal-image activation. |
| Thermal | MT6797 thermal driver/raw reading works (about 46 C in an earlier capture). | Calibration/load/suspend validation. |
| Audio | Source/DT work exists; do not claim physical audio from enumeration. | Physical codec/routing/playback/capture test. |
| Power/battery/keys/Hall | Observation/probe work exists. | Device-tested charging, gauge, input, suspend/resume. |
| GPU | Experimental work exists but was explicitly put behind radios. | Revisit after radio/CPU critical path; no current functional Panfrost claim. |
| Camera/ISP | Not enabled. | Major later lane. |
| Wi-Fi/BT/GNSS/cellular | See active lanes above. | Functional network/HCI/NMEA/modem endpoints remain the goal. |

## Repository topology and traps

- Maintained Linux tree: `/home/grw/src/linux-gemini-platform`, branch
  `gemini-platform`, last common pushed base `da6e93b0...`.  Preserve its
  `.pre` material and do not mass-clean it.
- Maintained Nix tree: `/home/grw/src/nixos-gemini`, current base `20c029d`.
  It is intentionally dirty with user campaign/question files, `.gitignore`
  changes and the vendor submodule.  Do not reset/delete unrelated work.
- Trex sees `/mnt/Home/src`; it does not see the old host's `/home/grw/src`.
  A linked worktree on `/mnt/Home` can still have `.git` pointing into
  `/home/grw/src`, causing libgit2 errors on Trex.  Use a real Trex clone or an
  exact `git archive` plain source export for Nix path inputs.
- Nix flakes see only Git-tracked files when consuming a Git worktree.  `git
  add` new source files before building, or use a deliberate plain export and
  record its hash.
- Shell is zsh: do not rely on Bash word splitting, and unmatched globs abort.
- Never use `/tmp`; it is tmpfs and these machines reboot.
- There is a known empty object warning in a shared alternate under
  `/home/grw/src/linux-gemini-push/.git/objects/d5/...`.  Do not broad-fsck or
  delete it while unrelated worktrees depend on the object store.
- Do not trust process names or stale state files alone.  Poll the exact
  systemd invocation/session, journal and artifact path.

## Recommended resume order on Trex

1. Read this file, `AGENTS.md`, current `git status`, all three active lane
   worktrees, and `systemctl --user status w0-hif-v6-build-archive.service`.
2. Finish and verify W0 v6.  Do one exact p22 cycle only after live preflight.
3. Interpret the real WCIR value.  If W0 succeeds, advance immediately toward
   IRQ + Wi-Fi RAM firmware + bounded firmware-alive proof; do not spend a
   cycle polishing W0.
4. In parallel, keep the MD1 worker moving beyond metadata toward source-backed
   remap/power/CCIF and a minimal AT/control endpoint.
5. Hardware-test staged GNSS and Bluetooth separately; preserve common G2d in
   each, never combine unknown proof gates merely to save a reboot.
6. Rebase/integrate the CPU8 admission work into a current Nix candidate and
   obtain runtime CPU8 evidence; keep CPU9 off.
7. Cherry-pick only hardware-proven, reviewed commits into maintained Linux
   and Nix branches, then run a combined regression image covering display,
   eMMC, gadget, RTL host, watchdog/pstore and the newly proven radio pieces.

Do not mistake “candidate built” for “hardware enabled.”  The campaign has a
strong recovery substrate and a now-proven common CONSYS/WMT pipeline; the
remaining job is to turn the separately gated proofs into stable Linux
endpoints, one decisive hardware result at a time.
