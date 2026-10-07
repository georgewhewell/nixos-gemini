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

Associated scanning is implemented by Linux commit `6edcccd5a1a4e`. At the
time of that check, the Wi-Fi source tree matched between M69 (`c0dbf01b2bdaa`)
and the maintained kernel (`d951c0cadafbb`). The bounded M69 observation does
not qualify a newer kernel as a whole. M69's `iw link` station-information
query still returns `-EOPNOTSUPP`; that association check used the existing
supplicant control socket at `/run/gemini-wifi/ctrl`.

Linux `d25a82d67956d` adds standard cfg80211 station get/dump reporting for the
current AP: received Ethernet byte/packet counts for this association,
connection age, authenticated/associated/authorized flags, and beacon RSSI
only when observed within five seconds. Counters reset with each connection;
other peers and stopped/cancelled connections are rejected. TX completion
statistics and negotiated bitrate are not yet available. RX admission, beacon
ownership/PM behavior, station query tests, the ARM64 object build and full
normal kernel/system builds pass. Device validation is still pending; artifacts
are in `handoff/wifi-station-20261007`. This adds reporting without changing the
scan or join protocol.

The September 30 M51 record separately reports WPA3-SAE/PMF data and three
successful reconnects. Scanning while associated to a WPA3 or 5 GHz network,
longer data/latency tests and sustained coexistence remain unqualified.

Bluetooth LE discovery passed on M45. Pairing, supported profiles and sustained
Wi-Fi/Bluetooth coexistence remain unqualified. GNSS has source and transport
work but no retained successful location fix. No completed FM qualification
is established here. These remain hardware requirements, not exclusions.
