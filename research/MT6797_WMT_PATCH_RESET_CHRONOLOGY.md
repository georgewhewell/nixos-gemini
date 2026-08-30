# MT6797 WMT patch/reset transaction chronology

Date: 2026-08-30
Scope: read-only audit of the vendor MT6797 (Gemini `0x0279`) source and the
current `/mnt/Home/src/linux-gemini-wmt-firmware-runtime` implementation. No
Linux, firmware, device, or hardware state was changed.

## Verdict

For the vendor build audited here, `CFG_WMT_MULTI_PATCH` is enabled
(`wmt_ic_soc.c:68-82`). The proven transaction is:

```
patch 0: full address -> partial address -> every body fragment -> WMT RESET 0x07 + ACK
patch 1: full address -> partial address -> every body fragment -> WMT RESET 0x07 + ACK
```

It is not “both patches, then one reset”. The production Gemini evidence names
the two inputs, in order, as `ROMv3_patch_1_1_hdr.bin` then
`ROMv3_patch_1_0_hdr.bin` (`research/mt6797-btif-runtime-evidence-next/
firmware-provenance.md:17-25,67-70`). The source does not itself contain those
filenames: the vendor patch-search/controller supplies each `index + 1`
(`wmt_ic_soc.c:2066-2087`).

The current runtime diff implements the same per-image reset placement: its
loop calls address, body, then opcode `0x07` for each manifest entry
(`/mnt/Home/src/linux-gemini-wmt-firmware-runtime/drivers/soc/mediatek/
mt6797-consys-wmt-patch.c:246-283`). Its hardware-free KUnit vector asserts
eight transactions and reset packets at positions 3 and 7
(`.../mt6797-consys-wmt-patch.c:520-590`).

## Exact reset and patch acknowledgements

The vendor constants are:

> `static UINT8 WMT_RESET_CMD[] = { 0x01, 0x07, 0x01, 0x00, 0x04 };`
> `static UINT8 WMT_RESET_EVT[] = { 0x02, 0x07, 0x01, 0x00, 0x00 };`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/
common/common_main/core/wmt_ic_soc.c:122-128`

For each image, `mtk_wcn_soc_patch_dwn(index)` obtains the selected image
(`:2066-2092`), removes the 28-byte `WMT_PATCH` header and uses 1000-byte
fragments (`:2094-2146`), selects the MT6797 patch-RAM address fields
(`:2162-2169`), then requires an exact address reply
(`:2171-2192`). Each fragment is sent and its exact `WMT_PATCH_EVT` is checked
(`:2222-2288`). That function does **not** reset the chip. The caller does:

> `for (patch_index = 0; patch_index < patch_num; patch_index++) {`
> `    iRet = mtk_wcn_soc_patch_dwn(patch_index);`
> `    ...`
> `    iRet = wmt_core_init_script(init_table_3, osal_array_size(init_table_3));`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/
common/common_main/core/wmt_ic_soc.c:1079-1091`

`init_table_3` is exactly the reset script for this configuration:

> `INIT_CMD(WMT_RESET_CMD, WMT_RESET_EVT, "wmt reset"),`

`.../core/wmt_ic_soc.c:719-724` (the optional BT port-2 entry is disabled by
`CFG_WMT_BT_PORT2 0` at `:60`).

## Full-STP continuity

Before patching, the vendor BTIF path queries default options, sets STP
options, enables host BTIF full mode, waits 10 ms, and queries full options
(`wmt_ic_soc.c:1008-1044`). The multi-patch loop then invokes patch and reset
using `wmt_core_tx()`/`wmt_core_rx()`; it contains no STP close, mode change,
or renegotiation (`wmt_ic_soc.c:1079-1091`; patch exchange
`:2171-2288`). The reset script itself is only this strict command/event
exchange:

> `iRet = wmt_core_tx(script[i].cmd, script[i].cmdSz, &u4Res, MTK_WCN_BOOL_FALSE);`
> `iRet = wmt_core_rx(evtBuf, script[i].evtSz, &u4Res);`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/
common/common_main/core/wmt_core.c:634-655`

Thus source proves that the host does not tear down or renegotiate STP between
the two resets. It strongly supports full-STP continuity, and the current
runtime deliberately keeps one opaque full-STP lease for the manifest
(`/mnt/Home/src/linux-gemini-wmt-firmware-runtime/include/linux/soc/mediatek/
mt6797-consys-wmt-patch.h:16-25`). However, I could not determine from these
sources whether the firmware's internal handling of opcode `0x07` has any
transient STP side effect, or independently prove on live hardware that the
second patch receives a valid full-STP window. Treat continuity as source-
inferred, not a live timing proof.

## ACK, retry, and recovery ownership

There are three distinct layers; they must not be collapsed into “retry the
patch”.

1. **WMT command ACK and wait.** `wmt_core_init_script()` stops on a transmit
   error/length mismatch, receive error/length mismatch, or exact event
   mismatch, and returns `-1` unless every script entry completed
   (`wmt_core.c:634-680`). The receive path requires STP open and waits for
   `WMT_LIB_RX_TIMEOUT` (`wmt_ctrl.c:262-291`); the timeout is 2000 ms and
   `MAX_EACH_WMT_CMD` is 3000 ms (`core/include/wmt_lib.h:64-90`). In the
   current runtime, `mtk_wmt_receive()` is the exact opcode/data/length matcher
   and `mtk_wmt_transaction()` is the single-flight waiter
   (`/mnt/Home/src/linux-gemini-wmt-firmware-runtime/drivers/soc/mediatek/
   mtk-wmt.c:132-178,240-351`).

2. **STP ACK and retained-frame retry.** The vendor STP timeout sends four
   `0x7f` bytes, resends retained frames from the last acknowledged sequence,
   and increments retry state (`stp_core.c:663-705`). At the retry limit it
   stops the timer and enters firmware-assert/whole-chip-reset handling
   (`stp_core.c:707-750`). The current session mirrors the resync and retained
   frame resend (`/mnt/Home/src/linux-gemini-wmt-firmware-runtime/drivers/soc/
   mediatek/mt6797-consys-stp-session.c:376-415`), with the 180-ms interval
   named in `include/linux/soc/mediatek/mt6797-consys-stp-session.h:20,87,144-146`.

3. **Whole-manifest ownership and recovery.** Vendor `mtk_wcn_soc_patch_dwn()`
   has no patch-level retry loop: a failed address, fragment, or event exits
   the current image (`wmt_ic_soc.c:2171-2308`), and the outer loop returns
   `-7` for patch failure or `-8` for reset-script failure
   (`wmt_ic_soc.c:1080-1090`). The only explicit vendor transmit retry is in
   `wmt_core_tx()`, and only when zero bytes were written: at most three retries
   with 360 ms delay (`wmt_core.c:331-355`). It does not retry an already
   partially accepted patch.

   The current runtime likewise does not retry a failed patch transaction. Its
   bootstrap arms the STP retry owner around each WMT operation, but documents
   that the vendor sends each patch command once and fails the sequence on
   error (`/mnt/Home/src/linux-gemini-wmt-firmware-runtime/drivers/soc/
   mediatek/mt6797-btif-stp-bootstrap.c:304-327`). A transport error or timeout
   sets `reset_required` in the WMT owner (`.../mtk-wmt.c:208-238`); the patch
   stage explicitly does not call `mtk_wmt_reset()` and leaves recovery to the
   bootstrap (`.../mt6797-consys-wmt-patch.c:332-375`).

## Proven, inferred, and unknown

**Proven.** With `CFG_WMT_MULTI_PATCH=1`, reset opcode `0x07` follows every
successful patch image, including the first and second. The reset command and
event bytes are exact. Patch fragments and their ACKs precede each reset. The
current runtime's manifest loop and KUnit vector encode this same ordering.
The vendor's host-side path remains open/full-STP between iterations.

**Inferred.** The second image is expected to use the same full-STP transport
window because no host-side STP teardown or reconfiguration occurs and the
current implementation holds one opaque full-STP lease. The observed Gemini
firmware order is `1_1` then `1_0`, but the vendor source delegates filename
selection/order to the patch-search owner.

**Unknown.** I could not determine from static source whether firmware emits
any extra asynchronous event around reset, whether opcode `0x07` internally
resets only the WMT/CONSYS MCU or also affects STP state, or whether a specific
ROMv3 patch build requires a delay not represented in the source. I also could
not establish a live trace of both reset ACKs in this audit.

## Smallest safe next gate

The existing packet-vector KUnit is the smallest non-hardware gate: require
exactly two `address -> all fragments -> reset` groups, exact reset bytes and
events, and a failure test proving that a reset timeout stops before the next
image. Do not retry the entire manifest after a reset timeout: patch RAM state
is then ambiguous. The safe owner is to fence the full-STP/WMT lease and invoke
a separately reviewed whole-CONSYS recovery/rebootstrap path. A hardware
acceptance test, when authorized, should capture both exact reset ACKs and the
absence of an STP mode transition; it must stop/fence on the first timeout and
must not activate any radio function.
