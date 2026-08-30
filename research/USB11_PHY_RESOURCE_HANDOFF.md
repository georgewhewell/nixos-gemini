# USB11 T-PHY resource ownership

Status: source and artifact review, 2026-08-30.  This is a read-only,
documentation-only finding.  It does not authorize a flash, reboot, or block
device write.

## Finding

The candidate's USB11 failure is a device-tree resource collision, before
MUSB or `r8152` can start.  The retained candidate DT is
`/home/grw/src/nixos-gemini/artifacts/power-preflight-debug-20260830/manual/gemini-platform.dtb`,
SHA-256
`58fa70641900b343c466b815bcadd0cb5269d86df0b4939f436af7c0d2bc6300`.
Read-only `fdtget` reports:

```text
/t-phy@11210000                  reg = 0 11210000 0 1000
/t-phy@11210000/usb-phy@11210800 reg = 0 11210800 0 100
/usb@11200000                    reg = 0 11200000 0 1000
```

The first range is `[0x11210000, 0x11210fff]`; the child range is
`[0x11210800, 0x112108ff]`.  The child is wholly inside the parent's
resource.  The MUSB range is separate; its relationship is a PHY dependency,
not the colliding resource.

The candidate pstore reports the same address and failure:

```text
[    0.740044] phy phy-11210000.t-phy.2: error -EBUSY: can't request region for resource [mem 0x11210800-0x112108ff]
[    0.741475] mtk-tphy 11210000.t-phy: probe with driver mtk-tphy failed with error -16
[    0.742699] probe of 11210000.t-phy returned 16 after 2845 usecs
```

(`/home/grw/src/nixos-gemini/artifacts/p22-recovery-20260830-065400-4074658/pstore-pre:361-363`).
The dependent controller then defers:

```text
[    0.988977] probe of 11200000.usb returned -517 after 20 usecs
[   48.211485] probe of 11200000.usb returned -517 after 21 usecs
```

(`/home/grw/src/nixos-gemini/artifacts/p22-recovery-20260830-065400-4074658/pstore-pre:590,913`).
The same record eventually says `usb-host-net=missing after=60s driver=r8152`
(`/home/grw/src/nixos-gemini/artifacts/p22-recovery-20260830-065400-4074658/pstore-pre:921`),
but that is downstream of the PHY failure.

## Why the ranges collide

The candidate was built from the pinned Linux input at
`/home/grw/src/nixos-gemini/flake.nix:23-29`, revision
`af0259fd02957f1a64437af443c8b586801d9374`.  At that revision, the base DT
declares the parent as `reg = <0 0x11210000 0 0x1000>` and the child as
`reg = <0 0x11210800 0 0x100>`
(`/home/grw/src/linux-gemini-platform@af0259fd:arch/arm64/boot/dts/mediatek/mt6797.dtsi:140-152`).
The selected kernel-built overlay only enables the three nodes; it does not
change either range
(`/home/grw/src/linux-gemini-platform@af0259fd:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-usb11-host.dtso:118-128`).
Nix copies that kernel-built `.dtbo` and composes it into the final DT at
`/home/grw/src/nixos-gemini/nix/mainline.nix:389-396,483-492`.

The upstream T-PHY probe makes the ownership sequence explicit:

```c
sif_res = platform_get_resource(pdev, IORESOURCE_MEM, 0);
tphy->sif_base = devm_ioremap_resource(dev, sif_res);
```

(`/home/grw/src/linux-gemini-platform/drivers/phy/mediatek/phy-mtk-tphy.c:1632-1641`),
then for every child:

```c
retval = of_address_to_resource(child_np, 0, &res);
instance->port_base = devm_ioremap_resource(subdev, &res);
if (IS_ERR(instance->port_base))
	return PTR_ERR(instance->port_base);
```

(`/home/grw/src/linux-gemini-platform/drivers/phy/mediatek/phy-mtk-tphy.c:1652-1682`).
The first call reserves the parent memory range; the second requests the
child range exclusively and returns the observed `-EBUSY` (`-16`) because the
ranges overlap.  This is proven by the driver path plus the exact pstore
error, not inferred from the host-network timeout.

For the V1 USB2 instance, the driver also maps the shared frequency bank from
the parent and the common USB2 PHY bank from the child:

```c
u2_banks->fmreg = tphy->sif_base + SSUSB_SIFSLV_V1_U2FREQ;
u2_banks->com = instance->port_base + SSUSB_SIFSLV_V1_U2PHY_COM;
```

(`/home/grw/src/linux-gemini-platform/drivers/phy/mediatek/phy-mtk-tphy.c:24-30,1111-1116`).
The already-working USB3 T-PHY uses the same ownership shape—a parent size
of `0x800` followed by a child at `+0x800`
(`/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797.dtsi:115-137`).

## MUSB and vendor ownership

The upstream USB11 node consumes the child PHY through
`phys = <&usb11_u2 PHY_TYPE_USB2>`
(`/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797.dtsi:159-169`).
The MUSB glue obtains that PHY at
`/home/grw/src/linux-gemini-platform/drivers/usb/musb/mediatek.c:514-517`,
and its initialization calls `phy_init()` and `phy_power_on()`
(`/home/grw/src/linux-gemini-platform/drivers/usb/musb/mediatek.c:265-303`).
Therefore the pstore's `11200000.usb` `-517` is consistent with waiting for
the failed PHY; it is not evidence that MUSB owns `0x11210800`.

The vendor 3.18 implementation is a different resource model.  Its active
OF path calls `of_iomap(pdev->dev.of_node, 0)` for the controller and
`of_iomap(pdev->dev.of_node, 1)` for the PHY/SIF resource
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/usb11/mt6797/musbfsh_core.c:2402-2418`).
In the retained known-good vendor DTB, the DT node at binary offset
`0x7eaa48` in
`/mnt/Home/src/nixos-gemini-flash-p22-20260829/boot-known-good-kernel.img`
(image SHA-256
`8d86971710128a728804da3a77592832d5f49a969d6d781f10fe454dd472ce22`)
decodes as:

```text
usb1@11200000:   compatible = "mediatek,mt6797-usb11";
                  reg = <0x11200000 0x1000 0x11210000 0x1000>;
usb1p_sif@11210000: compatible = "mediatek,usb1p_sif";
                     reg = <0x11210000 0x10000>;
```

This is legacy vendor DT evidence, not proof of the upstream T-PHY parent /
child ranges.  It does establish that the known-good image used a separate
vendor node/resource arrangement, so it must not be used to justify retaining
the candidate's upstream `0x1000` parent range.

## Smallest correction and validation gate

The smallest DT correction for the observed error is changing only the
upstream parent range from `0x1000` to `0x800` while retaining the child at
`0x11210800 + 0x100`.  The repository's current Linux checkout records that
correction and the separate forced-A-session property in commit
`88d05068e85736d8aadf02c4294e9e6e60a99edf`:

```dts
/* The child port begins at +0x800 and owns its own resource. */
reg = <0 0x11210000 0 0x800>;
```

(`/home/grw/src/linux-gemini-platform:arch/arm64/boot/dts/mediatek/mt6797.dtsi:140-150`;
`mediatek,force-a-session-valid` is at
`arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-usb11-host.dtso:122-125`).
The force-A property is not required to explain or remove `-EBUSY`; it is a
separate runtime behavior, corroborated by the known-good Stage-A log:

```text
[    0.984477] mtk-tphy 11210000.t-phy: u2 phy0: forcing valid A-device session
[    0.985515] musb-hdrc musb-hdrc.1.auto: MUSB HDRC host driver
```

(`/home/grw/src/nixos-gemini/artifacts/stage-a-20260830/device-dmesg-preflash.txt:1113-1114`).

The smallest safe build-time gate is to build the selected kernel overlay
from a source containing the parent-size correction, then assert both
properties before any hardware action:

```text
fdtget -t x gemini-platform.dtb /t-phy@11210000 reg
# 0 11210000 0 800
fdtget -t x gemini-platform.dtb /t-phy@11210000/usb-phy@11210800 reg
# 0 11210800 0 100
```

The existing Nix validation at
`/home/grw/src/nixos-gemini/nix/mainline.nix:489-492` checks node status and
mode, but not resource disjointness.  A successful build proves the DT bytes;
it does not prove Linux probing until a read-only runtime capture reports T-PHY
probe success followed by MUSB probe success.  No flash or reboot is part of
this finding.

## Proven, inferred, unknown

**Proven:** the retained candidate DT has the overlapping parent/child ranges;
the candidate pstore reports the exact child `-EBUSY`; the upstream driver
requests those ranges in parent-then-child order; MUSB depends on the failed
child PHY; and Stage-A logs show T-PHY/MUSB success and forced A-session.

**Inferred:** changing the parent size to `0x800` removes this specific
resource collision.  The inference is directly supported by the driver
ownership path and the already-working `11290000` layout, but still requires a
new build/runtime capture for end-to-end proof.

**Unknown:** the exact upstream Stage-A DT bytes are not retained.  The
appended known-good DTB is the legacy vendor format above, and the Stage-A
runtime DT may have been injected by LK.  This record therefore does not claim
that Stage-A used any particular upstream `reg` property.  It also does not
claim that the parent-size fix alone proves RTL8156 enumeration or network
readiness; those remain subsequent runtime gates.
