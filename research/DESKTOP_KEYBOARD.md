# Compact Gemini desktop keyboard, 2026-10-04

The new `mainlineNixosKeysBundle` / `gemini-mainline-keys` configuration extends
the ordinary-build-qualified Nix system with the compact Gemini US layout.
It uses the same kernel, drivers and device tree. Accepted M69 and the previous
EFI/Nix bundle and manager paths remain unchanged; this is an opt-in qualification image.

## Source and behavior

`nix/keyboard/gemini-symbols` is the exact captured Gemian file
`/gemian/usr/share/X11/xkb/symbols/planet_vndr/gemini`, SHA-256
`56baafdde43da9e3d66474f231a9bfd9d8d9fda40cd4c4af939ae1251db426cb`.
Its installed package copyright notice is retained as `nix/keyboard/COPYING`.
The reference keycodes file has SHA-256
`fc712134de609b50e0600c251d52a0fd2e3ffd5002215f8513f663c177773e3e`.
The original capture manifest is in
`handoff/gemini-keyboard-source-20261004/manifest.json`.

The package adds the vendor symbols to the pinned xkeyboard-config 2.48 data.
Weston selects `planet_vndr/gemini(us)` using that package's `XKB_CONFIG_ROOT`.
Fn uses the physical Left Meta position as an XKB level selector; it does not
activate the Logo modifier. Both Shift keys, Ctrl, Alt and Fn retain their
transitions. Fn+Tab toggles Caps Lock, Fn+arrows provide navigation, and
Fn+Shift+digits provide function keys. The map also supplies Unicode, dead
accents and desktop action keysyms. Application bindings for those actions
are a separate concern from emitting the correct keysym.

The candidate session sets `LANG` and `LC_CTYPE` to `C.UTF-8`. The initial live
M69 inspection found `LANG=C` and a generic-US keymap. The AArch64 client
correctly rejected that live map with `failed=layout-name`, then a fresh
health/identity check confirmed unchanged healthy M69
`58169ffb-952a-478a-ad72-59595d939729`. No compositor restart or input injection
was used. Evidence is in `handoff/desktop-keyboard-host-checks/baseline-probe.*`.

## What the checks establish

The client subscribes to the actual Wayland seat and parses the serialized
keymap Weston sends over `wl_keyboard`. It needs no surface, focus or keypress.
It verifies all 52 matrix keycodes across eight Shift/Fn/Caps combinations,
five modifier-key transitions, Fn+Tab locking/unlocking, and composition of
all eight mapped dead accents with `e` through libxkbcommon's locale tables.
This validates the application's delivered map and composition data; it does
not claim that a person pressed every physical key.

The reference header is regenerated independently from the captured Gemian
symbols and original keycodes. The generator checks its complete set of 52
keycodes against the pinned hardware-qualified U-Boot matrix before resolving
all 416 expected keysyms. The deployed map instead uses the current XKB rules
and keycodes, so the comparison checks that integration as well.

Host fixtures run the real Weston compositor with a test-only keyboard seat.
They accept the Gemini map and reject generic US, a damaged Fn mapping, a
fixture presented as device evidence, and a missing seat. A stalled compositor
is bounded by the client's ten-second alarm. Native AddressSanitizer and
UndefinedBehaviorSanitizer runs pass the same cases. The fixture module is
not included in the device system. All 112 recovery/qualification regressions
also pass, including rejection of crossed stores, systems and fixture reports.

The NixOS desktop qualification invokes the client alongside the existing
presentation check, including the stop/start cycle that verifies console and
GPU restoration. The candidate cannot self-accept if that service fails.
The host runner additionally checks the live compositor environment, the
startup report, exact source/checker hashes and a fresh unprivileged client.

## Pinned candidate and trial

Build and read-only preflight:

```sh
nix build .#mainlineNixosKeysBundle --out-link ../handoff/desktop-keyboard-linux
python3 tools/qualify-uboot-recovery.py --profile desktop-keyboard --out NEW_DIRECTORY
```

The executed trial adds `--execute`; the established mtkclient supervisor owns
both p22 writes, readbacks, reboots and recovery. This is a direct-Linux trial,
so EFI/U-Boot execution markers are rejected. It also requires the selected
system's ordinary unprivileged sandboxed Nix build and retention after rescue.
The current DT-bearing EFI publication, both older entries and their default
backups are verified before, during and after the trial. No boot-file default,
GPT or filesystem geometry changes are part of this profile.

- Bundle: `/nix/store/6jpccw7ghs043p0wsickd0k4jdnqcg6g-gemini-mainline-nixos-bundle`.
- System: `/nix/store/mdfyb9m4vczl0lnvlzjz1jn3jjlp8n3h-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade`.
- p22 SHA-256: `ac9b5091f5410a9e988128197770922396dd27e8aec7fb06cd0149505d7cdf49`.
- Store SHA-256: `31b4db06c615de5036c513b69ba4e9da887a688ead3e2698fd368ec28242ab6c`, 427,036,672 bytes.
- Kernel: `/nix/store/j0h3y2s1yal2sc7v1026c5hp0vn45xry-gemini-mainline-efi-nix-kernel-7.1.3`.
- Checker: `/nix/store/a2smp6m2irx68hmapp1k4l9l3j1iv45y-gemini-desktop-keyboard-check-aarch64-unknown-linux-gnu-1`.
- Checker executable SHA-256: `008c71ed4f1f87e69b9a95550bdf0c934d862c22f7446b3e4ad5ceba29ff1303`.

The complete AArch64 system build and
`handoff/desktop-keyboard-preflight-01` pass. Host build, fixture, sanitizer and
regression evidence is in `handoff/desktop-keyboard-host-checks`.
The completed hardware trial result is recorded below. The trial
archives nine exact qualification sources and their hashes. Seven earlier
Linux/bootloader artifact paths have been independently rechecked unchanged.


Candidate boot `763b46f8-ab02-4306-8b58-ad6ce8c7f3a3` passed
`handoff/desktop-keyboard-01`'s candidate checks. Both the startup client and a
fresh unprivileged client received the real Weston's `default` seat keymap:
416 combinations, five modifier mappings, Caps toggling and all eight accent
compositions passed. The live compositor environment had the expected XKB
root and both UTF-8 locale variables. The complete display/console/GPU
qualification, Linux service health, selected CPU provenance and both A72s
also passed. No physical key actuation was claimed.

The same candidate completed an ordinary unprivileged sandboxed daemon build.
Its output was
`/nix/store/b9armv8b79prchpd35fkwb351djah5vq-gemini-daemon-acc3205b3d71497f8abbd9be0f44885f`,
with proof SHA-256
`e27fb8a7ea0a121d798beacccc4f98dac9924befcb8cd17741f35413dd2bef9a`.
The published EFI entry and both preceding entry/payload sets remained intact.

Automatic recovery restored healthy direct M69 boot
`67ed08d7-2e44-44ca-a561-8b7714b377a3`, with unchanged GPT/p22/p30/p31 hashes.
The final audit held both flash locks and verified all nine ordinary build
outputs, their proof bytes, home GC roots and registered database identities.
No writer remains active. The candidate is qualified, but has not replaced
installed M69 or the published EFI default. Input work is now set aside at
the owner's request while the broader bring-up status is reviewed.
