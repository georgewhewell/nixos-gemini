# Reworked-CONSYS lineage port — status

The Gemini kernel work has forked into two lineages that are **not additive**.
Read this before planning any hardware lane; both the GPU and Wi-Fi attempts on
2026-09-03 lost time to discovering it independently.

## The fork

| | baseline `28c47150` (`gemini-platform`, what flake.lock pins) | production `6162ef03` (`integration/post-firstboot-next4-20260902`) |
|---|---|---|
| boots, self-accepts, watchdog owned by stage 2 | yes — this is the installed image | never built |
| `MTK_MT6797_*` Kconfig symbols | 49 | 29 |
| `DVFSP_*`, `BTIF_INVENTORY`, `CONSYS_INVENTORY` | present | absent |
| `dvfsp_handoff` in board DT | 3 refs | 0 refs |
| `PSTORE_GEMINI_*` (console-ramoops checkpoint) | 3 symbols | absent |
| Gen3 WLAN driver + `wifi@180f0000` | absent | present |
| GNSS `GNSS_MTK_CONSYS` | present | present |
| DA9214 legacy provider | absent | present, inside upstream `da9211-regulator.c` under stock `CONFIG_REGULATOR_DA9211` |
| A72 admission gate, camera topology, HEVC, AUXADC | absent | present |

`git diff` over `drivers/soc/mediatek` + `include/linux/soc/mediatek` between
them is **3722 insertions against 18501 deletions** — the production lineage
replaced the CONSYS stack rather than extending it.

Do not try to cherry-pick. The WLAN driver hard-depends on
`mt6797_consys_runtime_controller_wifi_lease`, `..._wifi_session_get/put` and
`mt6797_consys_emi_mpu_wifi_window_open`, none of which the baseline provides.
Their source is `13b666593 soc: mediatek: add MT6797 connectivity lifecycle
stack` — 16483 insertions over 40 files — which conflicts across **34 files and
~340 hunks** on the baseline.

Note `6162ef03` contains the DA9214 work by **rebase, not merge**, so
`git merge-base --is-ancestor e6b3168d 6162ef03` says no while the content is
present. Check content, not ancestry.

## What is already done (commit 363e70d)

`nix/mainline.nix` takes `legacyConsysPlatform`, default **true**. True leaves
every existing profile byte-for-byte unchanged — verified, not assumed: the
accepted baseline still builds to exactly
`c096e1ee48b0413a2de4f391b846a061928497ba390d471d4507f0c6a0900949`, the image
on the board.

False drops the eight assertions that describe the *old platform* rather than a
requirement of the image (BTIF inventory, DVFSP resource owner, the DA9213
provider/observer pair, legacy CONSYS inventory, the GNSS provider symbol its
fragments used to select, and the pstore ledger/checkpoint pair) and pulls in
`nix/mainline-reworked-consys.fragment`, which selects `CONFIG_REGULATOR_DA9211`.

With that, **next4 satisfies every one of the profile's ~89 config assertions
and ~10 DTS source assertions.** Verified by extracting the derivation's real
`configurePhase` and testing each check against the generated `.config`.

## The open blocker

    cd /home/grw/src/nixos-gemini
    nix build -L .#mainlineNixosWifiBundle --override-input linux-gemini \
      "git+file:///home/grw/src/linux-gemini?ref=integration/post-firstboot-next4-20260902&rev=6162ef037030cbc550af0d6d19d37399c94cdd1c"

The kernel derivation exits 1 **immediately after configuration with no
diagnostic output whatsoever**, and `make` never runs — a `--keep-failed` build
directory has no `vmlinux` and an `arch/arm64/boot` containing only
`dts/ install.sh Makefile`.

Ruled out:

- not a failing assertion — extracting the drv's `configurePhase` and replaying
  the whole thing with `bash -x` inside the kept build directory passes, ending
  at `runHook postConfigure`;
- not resource exhaustion — reproduces with `--max-jobs 1 --cores 8` on a host
  with 180 GB free, and produces **zero** `CC` lines either way (so it is not
  the signal-killed-`cc1plus` teardown artefact this project has hit before);
- not a hidden hook — the derivation has only `configurePhase`, `buildPhase`
  and `installPhase`; there is no `postConfigure`/`preBuild`;
- not a shell syntax error introduced by the new `optionalString` gating — the
  extracted phase parses and runs.

Next thing to try: diff the full builder environment (`env-vars` in the kept
build directory) against a *successful* baseline kernel build, since the
configure script itself demonstrably succeeds when run by hand in the same
tree. Suspect something in the stdenv phase list or an `outputChecks`-style
step rather than the kernel recipe.

## Judgement

Adopting the production lineage as trunk is the right direction — it holds all
the hardware value and the Nix side is now solved — but it costs `dvfsp_handoff`
and the pstore checkpoint. The pstore loss is smaller than it first appears:
ramoops only survives failures the board recovers from itself, and recovery from
a hard hang on this device is a physical silver+power cold boot, which wipes
DRAM regardless.
