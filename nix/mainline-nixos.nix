{
  buildPkgs,
  crossPkgs,
  ixoo-kernel,
  kernel,
  serviceabilityDtb,
  nixosToplevel,
  authorizedKeys,
  unattendedRecovery ? false,
  displayActivation ? false,
  stage1PersistentHostKey ? false,
  watchdogLeaseSeconds ? 90,
  kernelLeaseSelfAcceptToken ? null,
  stage2BaselineAcceptScript ? null,
  leaseSelfAcceptToken ? null,
  # The registered store and home live on p32; swap is RAM-only zram.
  persistentStorage,
}:
assert builtins.isInt watchdogLeaseSeconds;
assert builtins.isBool displayActivation;
assert kernelLeaseSelfAcceptToken == null || builtins.match "gemini-baseline-lease-v1-[0-9a-f]{64}" kernelLeaseSelfAcceptToken != null;
assert leaseSelfAcceptToken == null || builtins.match "gemini-baseline-lease-v1-[0-9a-f]{64}" leaseSelfAcceptToken != null;
assert kernelLeaseSelfAcceptToken == leaseSelfAcceptToken;
assert (stage2BaselineAcceptScript == null) == (leaseSelfAcceptToken == null);
assert leaseSelfAcceptToken == null || builtins.any
  (line:
    line == "export GEMINI_BASELINE_ACCEPT_TOKEN=${leaseSelfAcceptToken}"
    || line == "export GEMINI_BASELINE_ACCEPT_TOKEN='${leaseSelfAcceptToken}'")
  (buildPkgs.lib.splitString "\n" stage2BaselineAcceptScript);
assert watchdogLeaseSeconds > 30;
assert !displayActivation || unattendedRecovery;
assert persistentStorage != null;
assert builtins.match "[A-Za-z0-9_-]+" persistentStorage.dataLabel != null;
let
  bootMountOptions = "ro,nosuid,nodev,noexec";
  bootMountPolicy = "ro";
  # Stage-1 shell, spliced into the INIT heredoc below.  Nix does not strip
  # indentation from interpolated text, so it is written at its final
  # column.
  storageFunctions = ''
    mount_persistent_storage() {
      node=/sys/class/block/''${emmc_device##*/}p32
      data=''${emmc_device}p32
      persist=/mnt/nixos/persist
      grep -Fqx 'PARTNAME=userdata' "$node/uevent" || fail "persist-partition"
      label=$(dumpe2fs -h "$data" 2>/dev/null | sed -n 's/^Filesystem volume name: *//p')
      [ "$label" = ${persistentStorage.dataLabel} ] || fail "persist-label"
      e2fsck -p "$data" > /run/persist-fsck.log 2>&1
      rc=$?
      [ "$rc" -lt 4 ] || fail "persist-fsck rc=$rc"
      mkdir -p "$persist"
      mount -t ext4 -o rw,nosuid,nodev,noatime "$data" "$persist" || fail "persist-mount"
      for dir in home nixos nixos/nix nixos/nix/store nixos/nix/var; do
        [ -d "$persist/$dir" ] && [ ! -L "$persist/$dir" ] || fail "persist-layout missing=$dir"
      done
      [ -s "$persist/nixos/nix/var/nix/db/db.sqlite" ] || fail "persist-database"
      mount --bind "$persist/nixos/nix/store" /mnt/nixos/nix/store || fail "persist-store"
      mount --bind "$persist/nixos/nix/var" /mnt/nixos/nix/var || fail "persist-state"
      mkdir -p /mnt/nixos/home
      mount --bind "$persist/home" /mnt/nixos/home || fail "persist-home"
      log "persist=mounted device=$data fsck_rc=$rc store=persistent"
    }

  '';
  initramfs = buildPkgs.runCommand "gemini-mainline-nixos-initramfs.cpio.gz" {
    nativeBuildInputs = [buildPkgs.cpio buildPkgs.gzip];
    busybox = crossPkgs.pkgsStatic.busybox;
    dropbear = crossPkgs.pkgsStatic.dropbear;
    e2fsprogs = crossPkgs.pkgsStatic.e2fsprogs.bin;
    rtlFirmware = buildPkgs.linux-firmware;
  } ''
    mkdir -p root/bin root/dev root/etc root/mnt/gemian root/mnt/nixos \
      root/lib/firmware/rtl_nic root/proc root/root/.ssh root/run \
      root/sys/fs/pstore
    cp "$busybox/bin/busybox" root/bin/busybox
    cp "$dropbear/bin/dropbear" root/bin/dropbear
    cp "$dropbear/bin/dropbearkey" root/bin/dropbearkey${buildPkgs.lib.optionalString stage1PersistentHostKey ''

    cp "$dropbear/bin/dropbearconvert" root/bin/dropbearconvert''}
    cp ${./unattended-recovery-lease-record.sh} \
      root/bin/unattended-recovery-lease-record
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

    cat > root/bin/usb-host-net-udhcpc <<'USB_HOST_NET_UDHCPC'
    #!/bin/busybox sh
    export PATH=/bin
    interface=''${interface:-}
    case "$interface" in
      ""|*[!A-Za-z0-9._-]*) exit 1 ;;
    esac
    ip_value=''${ip:-}
    case "$ip_value" in
      ""|*[!0-9./]*) exit 1 ;;
    esac
    subnet=''${subnet:-24}
    case "$subnet" in
      *[!0-9.]*) exit 1 ;;
    esac
    case "''${1:-}" in
      deconfig)
        ip addr flush dev "$interface" 2>/dev/null || true
        ;;
      bound|renew)
        ip link set "$interface" up
        ip addr flush dev "$interface" 2>/dev/null || true
        ip addr replace "$ip_value/$subnet" dev "$interface"
        for gateway in ''${router:-}; do
          case "$gateway" in *[!0-9.]*) continue ;; esac
          ip route replace default via "$gateway" dev "$interface"
          break
        done
        echo "GEMINI_MAINLINE_NIXOS: usb-host-net=ready iface=$interface address=$ip_value/$subnet action=$1 usb=''${USB_HOST_USB:-unknown}" \
          >> /run/stage1.log 2>/dev/null || true
        ;;
      *) exit 1 ;;
    esac
    USB_HOST_NET_UDHCPC

    cat > root/bin/usb-host-net <<'USB_HOST_NET'
    #!/bin/busybox sh
    export PATH=/bin
    attempt=0
    host_if=
    usb_vid=
    usb_pid=
    while [ "$attempt" -lt 60 ] && [ -z "$host_if" ]; do
      for net in /sys/class/net/*; do
        [ -e "$net" ] || continue
        name=''${net##*/}
        [ "$name" != usb0 ] || continue
        driver=$(readlink -f "$net/device/driver" 2>/dev/null || true)
        case "$driver" in
          */r8152)
            host_if=$name
            usb_path=$(readlink -f "$net/device" 2>/dev/null || true)
            while [ -n "$usb_path" ] && [ "$usb_path" != / ]; do
              if [ -r "$usb_path/idVendor" ] && [ -r "$usb_path/idProduct" ]; then
                usb_vid=$(cat "$usb_path/idVendor")
                usb_pid=$(cat "$usb_path/idProduct")
                break
              fi
              parent=''${usb_path%/*}
              [ "$parent" != "$usb_path" ] || break
              usb_path=$parent
            done
            break
            ;;
        esac
      done
      [ -n "$host_if" ] || { attempt=$((attempt + 1)); sleep 1; }
    done
    if [ -z "$host_if" ]; then
      echo "GEMINI_MAINLINE_NIXOS: usb-host-net=missing after=60s driver=r8152" \
        >> /run/stage1.log 2>/dev/null || true
      exit 1
    fi
    if [ "$usb_vid" != 0bda ] || [ "$usb_pid" != 8156 ]; then
      echo "GEMINI_MAINLINE_NIXOS: usb-host-net=failed iface=$host_if driver=r8152 usb=''${usb_vid:-unknown}:''${usb_pid:-unknown}" \
        >> /run/stage1.log 2>/dev/null || true
      exit 1
    fi
    ip link set "$host_if" up || exit 1
    export USB_HOST_USB=$usb_vid:$usb_pid
    exec udhcpc -f -t 5 -T 3 -A 10 -i "$host_if" -s /bin/usb-host-net-udhcpc
    USB_HOST_NET

    cat > root/bin/ssh-server <<'SSH_SERVER'
    #!/bin/busybox sh
    export PATH=/bin
    hostname gemini-mainline-stage1 2>/dev/null || true
    key=/run/dropbear-ed25519-host-key
    ${if stage1PersistentHostKey then ''
    # Reuse the already trusted key without changing the on-disk original.
    # The init process mounts p29 independently; wait for that exact mount.
    attempt=0
    while [ ! -r /mnt/gemian/etc/ssh/ssh_host_ed25519_key ]; do
      attempt=$((attempt + 1))
      [ "$attempt" -lt 60 ] || exit 1
      sleep 1
    done
    umask 077
    dropbearconvert openssh dropbear /mnt/gemian/etc/ssh/ssh_host_ed25519_key \
      "$key" > /run/dropbear-keygen.log 2>&1 || exit 1
    '' else ''dropbearkey -t ed25519 -f "$key" > /run/dropbear-keygen.log 2>&1 || exit 1''}
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

    # The kernel may number the eMMC mmcblk0 or mmcblk1 depending on which
    # other MMC host registered first. Resolve it by the board's fixed
    # 11230000.mmc controller lineage, and fail closed on ambiguity.
    resolve_emmc_device() {
      controller=
      for candidate in \
        /sys/devices/platform/11230000.mmc \
        /sys/devices/platform/*/11230000.mmc \
        /sys/devices/platform/*/*/11230000.mmc; do
        [ -d "$candidate" ] || continue
        resolved=$(readlink -f "$candidate" 2>/dev/null || true)
        [ -n "$resolved" ] || continue
        if [ -n "$controller" ] && [ "$controller" != "$resolved" ]; then
          return 1
        fi
        controller=$resolved
      done
      [ -n "$controller" ] || return 1
      found=
      for node in /sys/class/block/mmcblk*; do
        [ -e "$node" ] || continue
        name=''${node##*/}
        case "$name" in
          mmcblk[0-9]*) suffix=''${name#mmcblk}; case "$suffix" in *[!0-9]*|"") continue ;; esac ;;
          *) continue ;;
        esac
        [ ! -e "$node/partition" ] || continue
        parent=$(readlink -f "$node/device" 2>/dev/null || true)
        matched=no
        while [ -n "$parent" ] && [ "$parent" != / ]; do
          if [ "$parent" = "$controller" ]; then
            matched=yes
            break
          fi
          next_parent=''${parent%/*}
          [ "$next_parent" != "$parent" ] || break
          parent=$next_parent
        done
        if [ "$matched" = yes ]; then
          [ -z "$found" ] || return 1
          found=/dev/''${node##*/}
        fi
      done
      [ -n "$found" ] || return 1
      printf '%s\n' "$found"
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
      if ! /bin/unattended-recovery-lease-record @WATCHDOG_LEASE_SECONDS@; then
        : > /run/unattended-recovery.lease-expired
        log "stage1=failed reason=watchdog-lease-deadline-record-failed watchdog_userspace=stopped watchdog_reset_expected=31s"
        kill -KILL "$watchdog_pid" 2>/dev/null || true
        while :; do sleep 3600; done
      fi
      log "watchdog=petting device=$watchdog_device pid=$watchdog_pid lease=@WATCHDOG_LEASE_SECONDS@s deadline=monotonic handoff=stage1-to-stage2-enforcer"

      # Stage 2 reconstructs this enforcement loop from the monotonic
      # deadline after switch_root.  Keep a separate Stage-1 timer as well:
      # a failed early boot may never reach Stage 2, and switch_root can
      # terminate initramfs background jobs.
      (
        sleep @WATCHDOG_LEASE_SECONDS@
        if [ "$(cat /run/unattended-recovery.accepted 2>/dev/null || true)" != \
             "unattended_recovery=healthy" ]; then
          : > /run/unattended-recovery.lease-expired
          log "unattended_recovery=lease-expired watchdog_userspace=stopped watchdog_reset_expected=31s reason=stage1-deadline-reached"
          pass=0
          while [ "$pass" -lt 5 ]; do
            owner_pid=$(cat /run/unattended-recovery.watchdog-owner 2>/dev/null || true)
            case "$owner_pid" in
              *[!0-9]*) ;;
              *)
                owns_watchdog=
                for fd in /proc/"$owner_pid"/fd/*; do
                  [ -e "$fd" ] || [ -L "$fd" ] || continue
                  target=$(readlink "$fd" 2>/dev/null || true)
                  case "$target" in
                    /dev/watchdog|/dev/watchdog0) owns_watchdog=yes ;;
                  esac
                done
                [ "$owns_watchdog" = yes ] \
                  && kill -KILL "$owner_pid" 2>/dev/null || true
                ;;
            esac
            pass=$((pass + 1))
            sleep 1
          done
        fi
      ) &
    }

    ${storageFunctions}activate_display() {
      # The locked 28c4715 platform requests the DSI IRQ before registering
      # the MIPI host. Release the one-way MMSYS gate only after the watchdog
      # petter and its lease are live, so a synchronous panel probe remains
      # inside the recovery envelope.
      display_gate=/sys/devices/platform/14000000.syscon/activate_drm
      attempt=0
      while [ ! -w "$display_gate" ] && [ "$attempt" -lt 30 ]; do
        attempt=$((attempt + 1))
        sleep 1
      done
      [ -w "$display_gate" ] || fail "display-activation-gate-missing"
      printf '%s\n' 1 > "$display_gate" || fail "display-activation-write"
      printf '%s\n' \
        'display=activated gate=14000000.syscon/activate_drm dsi_irq=pre-host-registration' \
        > /run/gemini-display-activation
      log "display=activated gate=14000000.syscon/activate_drm dsi_irq=pre-host-registration"
    }

    @START_WATCHDOG@
    @ACTIVATE_DISPLAY@
    /bin/usb-net &
    /bin/usb-host-net &
    /bin/ssh-server &
    log "stage1=entered p29=${bootMountPolicy} store=persistent"

    emmc_device=$(resolve_emmc_device 2>/dev/null || true)
    attempt=0
    while [ -z "$emmc_device" ] && [ "$attempt" -lt 30 ]; do
      attempt=$((attempt + 1))
      sleep 1
      emmc_device=$(resolve_emmc_device 2>/dev/null || true)
    done
    [ -n "$emmc_device" ] || fail "p29-missing"
    p29="''${emmc_device}p29"
    [ -b "$p29" ] || fail "p29-missing"
    mount -t ext4 -o ${bootMountOptions} "$p29" /mnt/gemian \
      || fail "p29-mount"
    mounted=$(awk '$2 == "/mnt/gemian" { print $1 ":" $3 ":" $4; exit }' /proc/mounts)
    log "p29=mounted observed=''${mounted:-unknown}"

    [ -r /mnt/gemian/etc/ssh/ssh_host_ed25519_key ] || fail "persistent-host-key-missing"

    mount -t tmpfs -o mode=0755,size=768M tmpfs /mnt/nixos || fail "tmpfs-root"
    mkdir -p \
      /mnt/nixos/dev /mnt/nixos/etc /mnt/nixos/gemian \
      /mnt/nixos/nix/store /mnt/nixos/nix/var/nix/gcroots \
      /mnt/nixos/nix/var/nix/profiles /mnt/nixos/nix/var/nix/temproots \
      /mnt/nixos/proc /mnt/nixos/run /mnt/nixos/sys /mnt/nixos/tmp /mnt/nixos/var
    mount_persistent_storage
    # Use the standard NixOS init= boot option. Never evaluate command-line
    # text as shell, and reject ambiguous or non-store paths.
    nixos_init=
    for argument in $(cat /proc/cmdline); do
      case "$argument" in
        init=*)
          [ -z "$nixos_init" ] || fail "multiple-init-options"
          nixos_init=''${argument#init=}
          ;;
      esac
    done
    printf '%s\n' "$nixos_init" | grep -Eq '^/nix/store/[0-9a-z]{32}-[A-Za-z0-9.+_-]+/init$' \
      || fail "invalid-nixos-init"
    nixos_system=''${nixos_init%/init}
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
    printf '%s\n' "$nixos_system" > /mnt/nixos/run/gemini-lease-expected-system

    echo "GEMINI_MAINLINE_NIXOS: stage1=switch-root system=$nixos_system" \
      > /mnt/nixos/run/stage1-handoff
    if [ -s /mnt/nixos/run/dropbear.pid ]; then
      kill "$(cat /mnt/nixos/run/dropbear.pid)" 2>/dev/null || true
      sleep 1
    fi
    exec switch_root /mnt/nixos "$nixos_init"
    INIT

    substituteInPlace root/init \
      --replace-fail @WATCHDOG_LEASE_SECONDS@ ${toString watchdogLeaseSeconds} \
      --replace-fail @START_WATCHDOG@ ${
        if unattendedRecovery
        then "start_watchdog_lease"
        else ":"
      } \
      --replace-fail @ACTIVATE_DISPLAY@ ${
        if displayActivation
        then "activate_display"
        else ":"
      }
    ${if unattendedRecovery then ''
      grep -a -Fq watchdog "$busybox/bin/busybox"
      grep -Fq 'start_watchdog_lease' root/init
      grep -Fq 'unattended-recovery.watchdog-owner' root/init
      grep -Fq 'unattended-recovery-lease-record' root/init
      grep -Fq 'gemini-lease-expected-system' root/init
      grep -Fq 'clock=monotonic-uptime-seconds' root/bin/unattended-recovery-lease-record
    '' else ''
      ! grep -Fq '^    start_watchdog_lease$' root/init
    ''}
    ${if displayActivation then ''
      grep -Fq 'display_gate=/sys/devices/platform/14000000.syscon/activate_drm' root/init
      grep -Fq 'display=activated gate=14000000.syscon/activate_drm dsi_irq=pre-host-registration' root/init
      # Nix strips the common heredoc indentation, so match the substituted
      # call sites exactly rather than assuming they retain source whitespace.
      activation_line=$(grep -n -Fx 'activate_display' root/init | tail -n 1 | cut -d: -f1)
      watchdog_line=$(grep -n -Fx 'start_watchdog_lease' root/init | tail -n 1 | cut -d: -f1)
      test "$watchdog_line" -lt "$activation_line"
    '' else ''
      ! grep -Fq 'display_gate=/sys/devices/platform/14000000.syscon/activate_drm' root/init
    ''}
    cp "$e2fsprogs/bin/e2fsck" "$e2fsprogs/bin/dumpe2fs" root/bin/
    # The persistent store is mounted before selecting the generation.
    # No flash resume or swap setup belongs in the normal initramfs.
    ! grep -Fq /sys/power/resume root/init
    mount_line=$(grep -n -F 'mount -t ext4 -o ${bootMountOptions} "$p29" /mnt/gemian' root/init | tail -n 1 | cut -d: -f1)
    persist_line=$(grep -n -Fx 'mount_persistent_storage' root/init | tail -n 1 | cut -d: -f1)
    switch_line=$(grep -n -F 'exec switch_root' root/init | tail -n 1 | cut -d: -f1)
    test -n "$mount_line" && test -n "$persist_line"
    test "$persist_line" -lt "$switch_line"
    bash -n root/init
    bash -n root/bin/usb-host-net root/bin/usb-host-net-udhcpc \
      root/bin/unattended-recovery-lease-record
    chmod 0755 root/init root/bin/usb-net root/bin/usb-host-net \
      root/bin/usb-host-net-udhcpc root/bin/ssh-server \
      root/bin/unattended-recovery-lease-record \
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
    python3 ${./check-service-milestone.py} ${kernel} ${nixosToplevel} \
      ${buildPkgs.kmod}/bin/modprobe ${../tools/check-gnome-cross-runtime.py}
    grep -Fqx CONFIG_CMDLINE_EXTEND=y ${kernel}/kernel.config
    cmdline="bootopt=64S3,32N2,64N2 init=${nixosToplevel}/init $(cat ${nixosToplevel}/kernel-params)"
    # Retained LK reads only the first 512-byte Android command-line field.
    test "''${#cmdline}" -lt 512
    ${buildPkgs.lib.optionalString (leaseSelfAcceptToken != null) ''
      test "$(sed -n 's/^CONFIG_CMDLINE="\(.*\)"$/\1/p' ${kernel}/kernel.config \
        | tr ' ' '\n' \
        | grep -Fxc 'gemini.baseline_lease_capability=${leaseSelfAcceptToken}')" -eq 1
    ''}
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
      --cmdline "$cmdline" \
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
    ln -s ${nixosToplevel} "$out/system"
    ln -s ${initramfs} "$out/initramfs.cpio.gz"
    ln -s ${bootImg} "$out/boot-raw.img"
    ln -s ${paddedBootImg} "$out/boot-padded-p22.img"
    {
      echo "target=Gemini p22 bootloader, p29 EFI files, p32 Nix store"
      echo "store=persistent"
      echo "store-root=/persist/nixos"
      echo "kernel=$(basename ${kernel})"
      echo "system=${nixosToplevel}"
      echo "p29=ext4 ${bootMountPolicy} after store installation"
      echo "left-port=MTU3 gadget usb0 10.15.19.82/24"
      echo "right-port=USB11 MUSB multipoint host PIO; FUSB301 VBUS; r8152 built-in; DHCP in Stage1 and NixOS"
      echo "right-port-firmware=rtl_nic/rtl8156b-2.fw sha256=5a3b21e27305876af8eac4b9bd11a821487b338e4ac1b58b8be8d23467d3f91f"
      echo "ssh=stage1 Dropbear key-only all IPv4; stage2 OpenSSH key-only IPv4 and IPv6"
      echo "display-activation=${if displayActivation then "stage1 watchdog-gated 14000000.syscon/activate_drm; DSI IRQ before host registration" else "none"}"
      echo "touchscreen-activation=NT36772 I2C4/0x62 explicit profile component"
      echo "fgadc-activation=MT6351 calibrated 0x28 OSR8 explicit profile component"
      echo "microsd-dt-status=$(${buildPkgs.dtc}/bin/fdtget ${serviceabilityDtb}/gemini.dtb /mmc@11240000 status)"
      echo "audio=ALSA default and UCM routes; playback/capture qualification explicit; acoustic validation pending"
      echo "consys-dt-status=$(${buildPkgs.dtc}/bin/fdtget ${serviceabilityDtb}/gemini.dtb /consys@18070000 status)"
      echo "wifi-dt-status=$(${buildPkgs.dtc}/bin/fdtget ${serviceabilityDtb}/gemini.dtb /consys@18070000/wifi@180f0000 status)"
      echo "gpu-dt-status=$(${buildPkgs.dtc}/bin/fdtget ${serviceabilityDtb}/gemini.dtb /gpu@13040000 status)"
      echo "unattended-recovery=${
        if unattendedRecovery
        then "stage1-deadline-to-stage2-enforcer; lease=${toString watchdogLeaseSeconds}s; timeout=31s; acceptance=${if leaseSelfAcceptToken == null then "external-exact" else "baseline-self-accept-v1"}"
        else "none"
      }"
      echo "store-provision=disabled"
      echo "persistent-storage=p32 ${persistentStorage.dataLabel} for /home and registered /nix; RAM-only zram swap"
      sha256sum \
        ${kernel}/Image ${kernel}/Image.gz \
        ${serviceabilityDtb}/gemini.dtb \
        ${initramfs} ${bootImg} ${paddedBootImg}
      stat -c '%n size=%s' ${initramfs} ${bootImg} ${paddedBootImg}
    } > "$out/MANIFEST"
  '';
in {
  inherit initramfs bootImg paddedBootImg bundle leaseSelfAcceptToken;
}
