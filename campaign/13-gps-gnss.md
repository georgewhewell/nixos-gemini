# GNSS over CONSYS/STP

Status: SOURCE EXISTS; GENERIC Linux GNSS and MediaTek client drivers EXIST;
MT6797 live applicability **UNKNOWN**; DT ENABLED **NO**; DEVICE-TESTED **NO**.

Vendor source defines `GPS_TASK_INDX = 2` and routes reads/writes through
`mtk_wcn_stp_send_data`/`receive_data`
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/include/stp_exp.h:45-58`; `drivers/misc/mediatek/connectivity/gps/stp_chrdev_gps.c:140-158,205-225`). Vendor GNSS EMI bookkeeping uses `gConEmiPhyBase + SZ_1M` (`gps_emi.c:77-93`), but that does not establish a usable address, data structure, cache contract, or receiver identity on this device.

The upstream `drivers/gnss/mtk.c` source is not a proof that this CONSYS path
works. No GNSS node or live STP transport is deployed. The former NMEA sample,
multi-constellation claim, CRC/status semantics, and 1 MiB shared-memory layout
are removed.

Next validation: complete the no-radio CONSYS identity gate; prove PIO byte
transport and full STP framing; perform exact WMT GPS function-on with bounded
responses; then register a GNSS client and require checksum-valid NMEA across
repeated open/close and reset recovery.
