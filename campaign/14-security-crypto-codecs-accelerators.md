# Crypto, RNG and secure-world boundaries

Status: GENERIC crypto/RNG APIs and several accelerator drivers EXIST; MT6797
EIP-93 identity/applicability **UNKNOWN**; DT ENABLED **NO**; DEVICE-TESTED
**NO**.

The current tree contains generic SafeXcel EIP-93 bindings and drivers (the
binding describes the generic IP and SoC-specific compatible requirement at
`/home/grw/src/linux-gemini-push/Documentation/devicetree/bindings/crypto/inside-secure,safexcel-eip93.yaml:7-14,30-43`), but no MT6797
Gemini DT node or match proving that the vendor address `0x10210000` is that
IP. A generic driver source is not evidence of clocks, IRQ polarity, register
layout, firmware needs, TRNG quality, or secure-world key isolation.

The old fixed address/IRQ node, algorithm list, AES throughput target, TRNG
physics and TrustZone guarantees are removed. No crypto MMIO node should be
enabled from the vendor address alone.

Next validation: identify the block from an authoritative MT6797 register map
and live resource inventory; establish reset/clock ownership; then use Linux
crypto self-tests with known vectors. Any secure-world claim requires a cited
secure monitor/TEE contract, not inference from the presence of eFuses.
