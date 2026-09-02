# Cellular modem (MD1, CCCI and CLDMA)

Status: MAINLINE CANDIDATE BUILDS; DEVICE-TESTED **NO**. The candidate is
default-off and the physically disconnected Gemini must not be used until its
battery connector is repaired. The installed physical SIM is expired, so
registration and data service are not immediate acceptance gates.

## Source-derived service path

The kernel candidate owns MD1 lifecycle, seven CLDMA rings and IRQ/NAPI, CCCI
HS1/HS2, a standard `WWAN_PORT_AT`, and standard raw-IP WWAN links. It does not
expose Android CCCI ioctls or label CCCI as MBIM/QMI. All `eccci/` evidence
paths below are relative to
`gemini-linux-kernel-3.18/drivers/misc/mediatek/`:

- `eccci/port_cfg.c:43-50` and `eccci/ccci_core.h:570-583` statically map the
  primary UART2/MUX service to CCCI RX/TX channels 10/12 on queue 1. No dynamic
  service discovery was found.
- `eccci/port_proxy.c:1636-1659` performs the second EMI step after HS1 decode
  and before the runtime reply. `eccci/mt6797/ccci_platform.c:579-605` proves
  this is the final CHECK_HEADER region 2 / EMI region 13 permission.
- `ccci_util/ccci_util_lib_load_img.c:729-873` is the vendor
  `request_firmware()` fallback for MD/DSP/ARM7. Lines 923-946 and 1005-1019
  define the optional 512-byte wrapper; lines 424-449 bind the trailing
  CHECK_HEADER size. `eccci/modem_cldma.c:2064-2108` loads required auxiliaries
  before MPU, power and release.

The new loader accepts only explicit `firmware-name` values from an explicit
Nix firmware package. It validates wrapper, CHECK_HEADER v4-v6, MD identity,
reserved-memory bounds, split-image offsets/sizes and overlap, then re-proves
reset-held state after firmware acquisition immediately before copying. Both
the DT property and the read-only kernel parameter are independently gated.
No firmware filenames or blobs have been guessed, so this path remains off.

HS1 runs in process context and completes the irreversible region-13 SET before
publishing runtime data. Duplicate/invalid HS1, the bounded HS2 timeout, WDT,
CLDMA error or stage-two failure quiesces transport and latches lifecycle
failure until platform reset. The source does not prove an in-boot recovery
sequence which can safely reverse power, remap and secure MPU state.

## SIM and eSIM boundary

The vendor SIM switch proves only physical pinctrl routing:
`drivers/misc/mediatek/ssw/ssw_single_v2/sim_switch.c:168-193` binds both SIM
interfaces to MD1. Searches of the vendor and Gemian oFono/ConnMan/RIL sources
found no EID, eUICC profile, LPA or provisioning operation. Gemini eUICC
presence therefore cannot be determined.

The optional Nix profile uses upstream `lpac` 2.3.0's AT backend, not a private
protocol. That backend tests 3GPP `AT+CCHO`, `AT+CCHC` and `AT+CGLA` before APDU
traffic (`lpac/driver/apdu/at.c:65-94`). `gemini-euicc probe` runs `lpac chip
info` as the runtime EID/capability test; `list`, `download` and `enable` map to
the corresponding lpac profile commands. The wrapper owns exactly one WWAN AT
device, temporarily stops ModemManager, and restores it on every exit. A failed
probe establishes no eUICC claim and preserves ordinary physical-SIM fallback.
Every transaction is bounded because lpac 2.3.0's AT receive loop does not
terminate on EOF; the default is 45 seconds for capability probes and 900
seconds for profile operations, capped at one hour by `GEMINI_EUICC_TIMEOUT`.

## Hardware acceptance still required

After repair and explicit coordination, one bounded pass must establish: exact
firmware filenames/digests, cold-load and LK-handoff paths, CLDMA IRQ polarity,
HS1/HS2, AT command/response, physical-SIM visibility, raw IPv4/IPv6, WDT
quiesce, and reset-based recovery. Only then should `lpac chip info` be tried;
profile download or enable is never an eUICC-presence probe.
