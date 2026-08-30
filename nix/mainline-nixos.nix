{
  buildPkgs,
  crossPkgs,
  ixoo-kernel,
  kernel,
  serviceabilityDtb,
  squashfs,
  nixosToplevel,
  authorizedKeys,
  bq2589xPreflight,
  unattendedRecovery ? false,
}: let
  # A p22 rollback is useful only while its exact userspace payload still
  # exists.  Derive the p29 filename from the immutable Nix store path so a
  # new bundle can only be staged next to an older payload, never over it.
  # The basename already ends in .squashfs.
  storeFileName =
    "mainline-nixos-${builtins.baseNameOf (toString squashfs)}";

  initramfs = buildPkgs.runCommand "gemini-mainline-nixos-initramfs.cpio.gz" {
    nativeBuildInputs = [buildPkgs.cpio buildPkgs.gzip];
    busybox = crossPkgs.pkgsStatic.busybox;
    dropbear = crossPkgs.pkgsStatic.dropbear;
    rtlFirmware = buildPkgs.linux-firmware;
  } ''
    mkdir -p root/bin root/dev root/etc root/mnt/gemian root/mnt/nixos \
      root/lib/firmware/rtl_nic root/proc root/root/.ssh root/run \
      root/sys/fs/pstore
    cp "$busybox/bin/busybox" root/bin/busybox
    cp "$dropbear/bin/dropbear" root/bin/dropbear
    cp "$dropbear/bin/dropbearkey" root/bin/dropbearkey
    cp ${bq2589xPreflight} root/bin/bq2589x-preflight
    cp "$rtlFirmware/lib/firmware/rtl_nic/rtl8156b-2.fw" \
      root/lib/firmware/rtl_nic/rtl8156b-2.fw
    test "$(sha256sum root/lib/firmware/rtl_nic/rtl8156b-2.fw | cut -d' ' -f1)" = \
      5a3b21e27305876af8eac4b9bd11a821487b338e4ac1b58b8be8d23467d3f91f
    cp ${authorizedKeys} root/root/.ssh/authorized_keys
    chmod 0700 root/root root/root/.ssh
    chmod 0600 root/root/.ssh/authorized_keys
    cat > root/etc/passwd <<'PASSWD'
    root:*:0:0:root:/root:/bin/sh
    PASSWD
    cat > root/etc/group <<'GROUP'
    root:x:0:
    GROUP
    cat > root/etc/shells <<'SHELLS'
    /bin/sh
    SHELLS
    cat > root/etc/hostname <<'HOSTNAME'
    gemini-mainline-stage1
    HOSTNAME

    cat > root/bin/usb-net <<'USB_NET'
    #!/bin/busybox sh
    export PATH=/bin
    attempt=0
    while [ ! -e /sys/class/net/usb0 ] && [ "$attempt" -lt 30 ]; do
      attempt=$((attempt + 1))
      sleep 1
    done
    [ -e /sys/class/net/usb0 ] || exit 1
    ip link set usb0 up
    ip address replace 10.15.19.82/24 dev usb0
    echo "<6>GEMINI_MAINLINE_NIXOS: usb0=ready address=10.15.19.82/24" > /dev/kmsg 2>/dev/null || true
    USB_NET

    cat > root/bin/ssh-server <<'SSH_SERVER'
    #!/bin/busybox sh
    export PATH=/bin
    hostname gemini-mainline-stage1 2>/dev/null || true
    key=/run/dropbear-ed25519-host-key
    dropbearkey -t ed25519 -f "$key" > /run/dropbear-keygen.log 2>&1 || exit 1
    exec dropbear \
      -F -E -s -j -k -m -K 30 -T 4 \
      -P /run/dropbear.pid -p 22 -r "$key" \
      >> /run/dropbear.log 2>&1
    SSH_SERVER

    cat > root/init <<'INIT'
    #!/bin/busybox sh
    export PATH=/bin
    /bin/busybox --install -s /bin

    mount -t devtmpfs -o nosuid,mode=0755 devtmpfs /dev
    mkdir -p /dev/pts
    mount -t devpts -o nosuid,noexec,mode=0620 devpts /dev/pts 2>/dev/null || true
    mount -t proc -o nosuid,nodev,noexec proc /proc
    mount -t sysfs -o nosuid,nodev,noexec sysfs /sys
    mount -t tmpfs -o nosuid,nodev,mode=0755 tmpfs /run
    mount -t pstore -o ro,nosuid,nodev,noexec pstore /sys/fs/pstore 2>/dev/null || true
    exec </dev/console >/dev/console 2>&1

    log() {
      echo "GEMINI_MAINLINE_NIXOS: $*"
      echo "GEMINI_MAINLINE_NIXOS: $*" >> /run/stage1.log 2>/dev/null || true
      echo "<6>GEMINI_MAINLINE_NIXOS: $*" > /dev/kmsg 2>/dev/null || true
    }
    fail() {
      log "stage1=failed reason=$* ssh=retained port=22"
      while :; do sleep 3600; done
    }

    start_watchdog_lease() {
      watchdog_device=
      attempt=0
      while [ -z "$watchdog_device" ] && [ "$attempt" -lt 10 ]; do
        for candidate in /dev/watchdog /dev/watchdog0; do
          if [ -c "$candidate" ]; then
            watchdog_device=$candidate
            break
          fi
        done
        [ -n "$watchdog_device" ] || sleep 1
        attempt=$((attempt + 1))
      done
      [ -n "$watchdog_device" ] || fail "watchdog-device-missing"

      /bin/watchdog -F -t 10 -T 31 "$watchdog_device" \
        > /run/watchdog.log 2>&1 &
      watchdog_pid=$!
      sleep 1
      kill -0 "$watchdog_pid" 2>/dev/null \
        || fail "watchdog-open-failed"
      echo "$watchdog_pid" > /run/unattended-recovery.watchdog-owner
      log "watchdog=petting device=$watchdog_device pid=$watchdog_pid lease=90s handoff=stage1"

      # /run is moved into the new root, so this supervisor survives
      # switch_root and follows whichever petter owns the watchdog.  Mark the
      # lease expired before killing: a racing Stage-2 takeover must observe
      # the marker and refuse to reopen the device.  Re-read the owner for a
      # few seconds to close the remaining PID-file handoff race.
      (
        sleep 90
        if [ "$(cat /run/unattended-recovery.accepted 2>/dev/null || true)" != \
             "unattended_recovery=healthy" ]; then
          : > /run/unattended-recovery.lease-expired
          log "unattended_recovery=lease-expired watchdog_userspace=stopped watchdog_reset_expected=31s"
          pass=0
          while [ "$pass" -lt 5 ]; do
            owner_pid=$(cat /run/unattended-recovery.watchdog-owner 2>/dev/null || true)
            case "$owner_pid" in
              *[!0-9]*) ;;
              *)
                [ -n "$owner_pid" ] \
                  && kill -KILL "$owner_pid" 2>/dev/null || true
                ;;
            esac
            pass=$((pass + 1))
            sleep 1
          done
        fi
      ) &
    }

    @START_WATCHDOG@
    /bin/bq2589x-preflight &
    log "power_observe_preflight=started mode=sysfs-and-dmesg-only watchdog_lease=unchanged"
    /bin/usb-net &
    /bin/ssh-server &
    log "stage1=entered p29=ro,noload store-compression=gzip"

    attempt=0
    while [ ! -b /dev/mmcblk0p29 ] && [ "$attempt" -lt 30 ]; do
      attempt=$((attempt + 1))
      sleep 1
    done
    [ -b /dev/mmcblk0p29 ] || fail "p29-missing"
    mount -t ext4 -o ro,noload,nosuid,nodev,noexec /dev/mmcblk0p29 /mnt/gemian \
      || fail "p29-mount"
    mounted=$(awk '$2 == "/mnt/gemian" { print $1 ":" $3 ":" $4; exit }' /proc/mounts)
    log "p29=mounted observed=''${mounted:-unknown}"

    store_image=/mnt/gemian/nixos/@STORE_FILE@
    [ -f "$store_image" ] || fail "store-image-missing"
    expected=@STORE_SHA256@
    actual=$(sha256sum "$store_image" | awk '{print $1}')
    [ "$actual" = "$expected" ] || fail "store-image-hash expected=$expected actual=$actual"
    log "store-image=verified sha256=$actual"
    [ -r /mnt/gemian/etc/ssh/ssh_host_ed25519_key ] || fail "persistent-host-key-missing"

    mount -t tmpfs -o mode=0755,size=768M tmpfs /mnt/nixos || fail "tmpfs-root"
    mkdir -p \
      /mnt/nixos/dev /mnt/nixos/etc /mnt/nixos/gemian \
      /mnt/nixos/nix/store /mnt/nixos/nix/var/nix/gcroots \
      /mnt/nixos/nix/var/nix/profiles /mnt/nixos/nix/var/nix/temproots \
      /mnt/nixos/proc /mnt/nixos/run /mnt/nixos/sys /mnt/nixos/tmp /mnt/nixos/var
    loopdev=$(losetup -f 2>/dev/null) || fail "loop-device-missing"
    losetup "$loopdev" "$store_image" || fail "loop-attach"
    mount -t squashfs -o ro,nodev "$loopdev" /mnt/nixos/nix/store \
      || fail "squashfs-mount"

    pointer=/mnt/nixos/nix/store/.gemini-system
    [ -s "$pointer" ] || fail "system-pointer-missing"
    system_basename=$(cat "$pointer")
    [ "$system_basename" = "@SYSTEM_BASENAME@" ] \
      || fail "system-pointer-mismatch observed=$system_basename"
    nixos_system=/nix/store/$system_basename
    nixos_init=$nixos_system/init
    [ -x "/mnt/nixos$nixos_init" ] || fail "nixos-init-missing"
    log "store=mounted system=$nixos_system"

    mount --move /mnt/gemian /mnt/nixos/gemian || fail "move-gemian"
    mount --move /proc /mnt/nixos/proc || fail "move-proc"
    mount --move /sys /mnt/nixos/sys || fail "move-sys"
    mount --move /dev /mnt/nixos/dev || fail "move-dev"
    mount --move /run /mnt/nixos/run || fail "move-run"
    mkdir -p /mnt/nixos/tmp
    mount -t tmpfs -o mode=1777 tmpfs /mnt/nixos/tmp || fail "tmpfs-tmp"
    ln -s "$nixos_system" /mnt/nixos/run/current-system

    echo "GEMINI_MAINLINE_NIXOS: stage1=switch-root system=$nixos_system" \
      > /mnt/nixos/run/stage1-handoff
    if [ -s /mnt/nixos/run/dropbear.pid ]; then
      kill "$(cat /mnt/nixos/run/dropbear.pid)" 2>/dev/null || true
      sleep 1
    fi
    exec switch_root /mnt/nixos "$nixos_init"
    INIT

    substituteInPlace root/init \
      --replace-fail @STORE_FILE@ ${storeFileName} \
      --replace-fail @STORE_SHA256@ "$(sha256sum ${squashfs} | cut -d' ' -f1)" \
      --replace-fail @SYSTEM_BASENAME@ "$(basename ${nixosToplevel})" \
      --replace-fail @START_WATCHDOG@ ${
        if unattendedRecovery
        then "start_watchdog_lease"
        else ":"
      }
    ${if unattendedRecovery then ''
      grep -a -Fq watchdog "$busybox/bin/busybox"
      grep -Fq 'start_watchdog_lease' root/init
      grep -Fq 'unattended-recovery.watchdog-owner' root/init
    '' else ''
      ! grep -Fq '^    start_watchdog_lease$' root/init
    ''}
    bash -n root/init
    chmod 0755 root/init root/bin/usb-net root/bin/ssh-server \
      root/bin/bq2589x-preflight \
      root/bin/dropbear root/bin/dropbearkey
    find root -exec touch -h -d @0 {} +
    (
      cd root
      find . -print0 | sort -z | cpio --null --create --format=newc \
        --owner=0:0 --reproducible --quiet
    ) | gzip -n -9 > "$out"
  '';

  bootImg = buildPkgs.runCommand "gemini-mainline-nixos.boot.img" {
    nativeBuildInputs = [buildPkgs.python3];
  } ''
    python3 ${ixoo-kernel}/experiments/2026-07-12-boot-contract-recovery/scripts/build-android-boot-v0.py \
      --kernel ${kernel}/Image.gz \
      --ramdisk ${initramfs} \
      --dtb ${serviceabilityDtb}/gemini.dtb \
      --dtb-mode append \
      --lk-android8 \
      --page-size 2048 \
      --kernel-addr 0x40200000 \
      --ramdisk-addr 0x45000000 \
      --second-addr 0x40f00000 \
      --tags-addr 0x44000000 \
      --cmdline "bootopt=64S3,32N2,64N2" \
      --output "$out"
    test "$(od -An -tx1 -N 8 "$out" | tr -d '[:space:]')" = 414e44524f494421
    test "$(stat -c %s "$out")" -le 16777216
  '';

  paddedBootImg = buildPkgs.runCommand "gemini-mainline-nixos-padded.img" {} ''
    cp --no-preserve=mode ${bootImg} "$out"
    truncate -s 16777216 "$out"
    test "$(stat -c %s "$out")" -eq 16777216
  '';

  bundle = buildPkgs.runCommand "gemini-mainline-nixos-bundle" {} ''
    mkdir -p "$out"
    ln -s ${kernel} "$out/kernel"
    ln -s ${serviceabilityDtb}/gemini.dtb "$out/gemini-usb11-host.dtb"
    ln -s ${squashfs} "$out/${storeFileName}"
    ln -s ${initramfs} "$out/initramfs.cpio.gz"
    ln -s ${bootImg} "$out/boot-raw.img"
    ln -s ${paddedBootImg} "$out/boot-padded-p22.img"
    {
      echo "target=Gemini default p22 plus unique p29 /nixos/${storeFileName}"
      echo "store-file=${storeFileName}"
      echo "store-sha256=$(sha256sum ${squashfs} | cut -d' ' -f1)"
      echo "store-size=$(stat -c %s ${squashfs})"
      echo "kernel=$(basename ${kernel})"
      echo "system=${nixosToplevel}"
      echo "p29=ext4 ro,noload after store installation"
      echo "squashfs=compression gzip; mount read-only"
      echo "left-port=MTU3 gadget usb0 10.15.19.82/24"
      echo "right-port=USB11 MUSB multipoint host PIO; FUSB301 VBUS; r8152 built-in; DHCP in NixOS"
      echo "right-port-firmware=rtl_nic/rtl8156b-2.fw sha256=5a3b21e27305876af8eac4b9bd11a821487b338e4ac1b58b8be8d23467d3f91f"
      echo "ssh=stage1 Dropbear key-only all IPv4; stage2 OpenSSH key-only all IPv4"
      echo "unattended-recovery=${
        if unattendedRecovery
        then "stage1-to-stage2-owner-handoff; lease=90s; timeout=31s; acceptance=external"
        else "none"
      }"
      echo "power-observe-preflight=BQ2589x sysfs+dmesg read-only; watchdog lease unchanged"
      sha256sum \
        ${kernel}/Image ${kernel}/Image.gz \
        ${serviceabilityDtb}/gemini.dtb \
        ${squashfs} ${initramfs} ${bootImg} ${paddedBootImg}
      stat -c '%n size=%s' ${squashfs} ${initramfs} ${bootImg} ${paddedBootImg}
    } > "$out/MANIFEST"
  '';
in {
  inherit initramfs bootImg paddedBootImg bundle;
}
