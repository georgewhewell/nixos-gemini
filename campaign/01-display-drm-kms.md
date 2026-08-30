# Display and DRM/KMS

Status: SOURCE EXISTS; GENERIC UPSTREAM DRIVER EXISTS; MT6797 APPLICABILITY
PROVEN for the SoC display blocks; DT ENABLED **NO**; DEVICE-TESTED **UNKNOWN**.

The current DRM driver has an MT6797 match and selects the twelve-component
`mt6797_mtk_ddp_main` path
(`/home/grw/src/linux-gemini-push/drivers/gpu/drm/mediatek/mtk_drm_drv.c:125-138,355-365`). The DSI driver also has an MT6797 match (`mtk_dsi.c:1312-1321`). Those lines establish reusable source and SoC applicability, not a panel link.

Vendor evidence identifies a 1080x2160, four-lane NT36672 panel and reset/TE
GPIO descriptions (`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/aeon6797_6m_n.dts:1043-1102`; panel parameters are explicit in `drivers/misc/mediatek/lcm/aeon_nt36672_fhd_dsi_vdo_x600_xinli/aeon_nt36672_fhd_dsi_vdo_x600_xinli.c:656-704`). This is board-wiring evidence only. It does not prove that the panel name, timings, bias controller, or power sequence can be expressed safely in current DRM.

The SoC display nodes are disabled in the shared DT
(`/home/grw/src/linux-gemini-push/arch/arm64/boot/dts/mediatek/mt6797.dtsi:851-1000`), and the Gemini board file has no panel node. The former “full pipeline” and `modetest` acceptance claim is removed.

Next validation: add only a reviewed panel binding and overlay; boot from the
recovery slot; capture component binding, regulator/clock errors, and one
physical mode-set. A successful driver probe without pixels is not
DEVICE-TESTED.
