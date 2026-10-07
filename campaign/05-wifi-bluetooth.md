# Connectivity: Wi-Fi, Bluetooth and GNSS

Updated 2026-10-07. The earlier source-only CONSYS/BTIF notes described initial
bring-up and no longer describe the maintained system. Use
[HARDWARE_STATUS.md](../research/HARDWARE_STATUS.md) for the overall completion
status; a working radio transport is not proof of every radio feature.

Wi-Fi is running on recovered M69 with a saved WPA2-PSK/CCMP profile. A bounded
passive scan while associated on 2412 MHz returned 13 BSS records across
2.4 and 5 GHz. The same BSSID, association and IP remained after the scan;
all 30 gateway pings during the observation succeeded. Scan-time maximum
latency was about 465 ms, so zero packet loss is not a latency qualification.
The nl80211 event monitor retained scan start/finish without a disconnect.
Evidence: `handoff/wifi-associated-scan-20261007/result.json`, `findings.md`
and `final-health.txt` in the shared workspace.

Associated scanning is implemented by Linux commit `6edcccd5a1a4e`. The Wi-Fi
source tree is identical between M69 (`c0dbf01b2bdaa`) and the maintained
kernel (`d951c0cadafbb`); the bounded M69 observation does not qualify the newer
kernel as a whole. An `iw link` station-information query still returns
`-EOPNOTSUPP`; the association check uses the supplicant's existing control
socket at `/run/gemini-wifi/ctrl`.

The September 30 M51 record separately reports WPA3-SAE/PMF data and three
successful reconnects. Scanning while associated to a WPA3 or 5 GHz network,
longer data/latency tests and sustained coexistence remain unqualified.

Bluetooth LE discovery passed on M45. Pairing, supported profiles and sustained
Wi-Fi/Bluetooth coexistence remain unqualified. GNSS has source and transport
work but no retained successful location fix. No completed FM qualification
is established here. These remain hardware requirements, not exclusions.
