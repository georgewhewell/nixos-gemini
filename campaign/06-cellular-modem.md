# Cellular modem (MD1, CCCI and CLDMA)

Status: native MT6797 CCCI/CLDMA transport is installed in accepted image116
(Linux revision `477538930f3d819c19a93bd27ad72f76b721979d`). The modem completes
HS1/HS2 and reaches READY, then its watchdog fires. Cellular service, SIM/eUICC
access, SMS delivery and voice calls remain unqualified.

CCCI is MediaTek's Cross-Core Communication Interface between the application
processor and modem. The native kernel driver owns CCCI framing, DMA and modem
lifetime, and exposes standard Linux WWAN AT and network interfaces. The eSIM
GUI should use lpac's generic AT/APDU transport with ModemManager ownership;
CCCI does not belong in the GUI.

The installed driver removes a failed AT port and wakes existing descriptors
with standard HUP/ERR; image116 hardware observation confirms that boundary.
The native SIM electrical maps and disabled-PBM DBM initialization are installed.
The protected cold owner now selects the declared SIM state and claims all six
pins, preserving the observed public board configuration. The WWAN core keeps
removed-port open count at zero when old descriptors close. These repairs do not
establish the watchdog cause or eUICC routing.

The current implementation is in `drivers/net/wwan/mediatek/mtk_mt6797_ccci.c`,
`mtk_ccci_common.c`, the native `drivers/soc/mediatek/mt6797-md1-*` owners and
`arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts` in the single
[Linux source tree](https://github.com/georgewhewell/linux-gemini/tree/gemini-7.2.9).
Calls, Spacebar and callaudiod are already in the normal image.

Remaining work: resolve the modem watchdog, establish eUICC APDU routing, integrate
and qualify the generic AT GUI/transport, and finish the modem speech-control and
duplex audio lifetime. AT availability and ModemManager's SIM-missing fallback
do not establish physical card absence or a selected SIM slot.

Keep current installation evidence and unfinished work in
[the cellular status record](../research/sms-voice-integration-20261011.json)
and [hardware status](../research/HARDWARE_STATUS.md); this campaign page is an
entry point, not a separate test history.
