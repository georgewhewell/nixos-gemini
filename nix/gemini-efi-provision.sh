# Sourced by the one-shot initramfs after store verification, before loop setup.
# fail(), provision_abort() and restore_store_readonly() belong to /init.
efi_verify_stores() {
    efi_count=0
    while read -r efi_sha efi_bytes efi_name; do
        efi_file=/mnt/gemian/nixos/$efi_name
        [ ! -L /mnt/gemian/nixos ] && [ -d /mnt/gemian/nixos ] || return 1
        [ -f "$efi_file" ] && [ ! -L "$efi_file" ] || return 1
        [ "$(stat -c %s "$efi_file")" = "$efi_bytes" ] || return 1
        [ "$(sha256sum "$efi_file" | cut -d' ' -f1)" = "$efi_sha" ] || return 1
        efi_count=$((efi_count + 1))
    done < /etc/gemini-efi-protected-stores.manifest
    [ "$efi_count" -eq 2 ]
}
efi_provision_boot_files() {
    read -r efi_archive_sha efi_archive_size < /etc/gemini-efi-archive.meta
    efi_verified="efi-files=verified sha256=$efi_archive_sha size=$efi_archive_size"
    # Reboots can reuse a complete, byte-verified publication without writes.
    if /bin/gemini-efi-publish verify /mnt/gemian /run/efi-files.tree /etc/gemini-efi-files.manifest; then
        printf '%s\n' "$efi_verified" > /run/efi-boot-files.verified
        return 0
    fi
    kill -0 "$watchdog_pid" 2>/dev/null || fail "efi-files-watchdog-missing"
    # This hook must never run after a store loop has been attached.
    for efi_loop in /sys/block/loop*/loop/backing_file; do
        [ ! -f "$efi_loop" ] || [ -z "$(cat "$efi_loop")" ] || fail "efi-files-loop-busy"
    done
    efi_verify_stores || fail "efi-files-protected-store-before"
    [ ! -e /run/efi-boot-files.upload ] && [ ! -L /run/efi-boot-files.upload ] \
        || fail "efi-files-stale-upload"
    [ ! -e /run/efi-boot-files.ready ] || fail "efi-files-stale-ready"
    printf '%s\n' "efi-files=required sha256=$efi_archive_sha size=$efi_archive_size" \
        > /run/efi-boot-files.required
    log "efi-files=waiting sha256=$efi_archive_sha size=$efi_archive_size p29=ro"
    efi_attempt=0
    efi_ready="efi-files=ready sha256=$efi_archive_sha size=$efi_archive_size"
    while [ "$efi_attempt" -lt 600 ]; do
        [ "$(cat /run/efi-boot-files.ready 2>/dev/null)" = "$efi_ready" ] && break
        efi_attempt=$((efi_attempt + 1))
        sleep 1
    done
    [ "$efi_attempt" -lt 600 ] || fail "efi-files-upload-timeout"
    [ -f /run/efi-boot-files.upload ] && [ ! -L /run/efi-boot-files.upload ] \
        || fail "efi-files-upload-missing"
    [ "$(stat -c %s /run/efi-boot-files.upload)" = "$efi_archive_size" ] \
        || fail "efi-files-upload-size"
    [ "$(sha256sum /run/efi-boot-files.upload | cut -d' ' -f1)" = "$efi_archive_sha" ] \
        || fail "efi-files-upload-hash"
    mkdir /run/efi-files.tree || fail "efi-files-stage-exists"
    # The archive's exact hash is embedded in this initramfs. The builder only
    # emits the five named regular files, with no links or traversal paths.
    tar -xf /run/efi-boot-files.upload -C /run/efi-files.tree || fail "efi-files-extract"
    # Do not start a filesystem transaction close to the recovery deadline.
    grep -qx 'format=gemini-unattended-recovery-lease-v1' /run/unattended-recovery.lease-deadline \
        || fail "efi-files-lease-format"
    grep -qx 'clock=monotonic-uptime-seconds' /run/unattended-recovery.lease-deadline \
        || fail "efi-files-lease-clock"
    efi_deadline=$(sed -n 's/^deadline=//p' /run/unattended-recovery.lease-deadline)
    efi_now=$(awk '{ sub(/\..*/, "", $1); print $1; exit }' /proc/uptime)
    case "$efi_deadline:$efi_now" in *[!0-9:]*|:*|*:) fail "efi-files-lease-value" ;; esac
    [ $((efi_deadline - efi_now)) -ge 120 ] || fail "efi-files-lease-short"
    umount /mnt/gemian || fail "efi-files-ro-unmount"
    mount -t ext4 -o rw,nosuid,nodev,noexec "$p29" /mnt/gemian \
        || provision_abort "efi-files-rw-mount"
    efi_mount=$(awk '$2 == "/mnt/gemian" { print $1 ":" $3 ":" $4; exit }' /proc/mounts)
    case ",$efi_mount," in
        *,${p29}:ext4:rw,*) ;;
        *) provision_abort "efi-files-rw-contract" ;;
    esac
    case ",$efi_mount," in
        *,noload,*|*,norecovery,*) provision_abort "efi-files-journal-disabled" ;;
    esac
    efi_available=$(df -Pk /mnt/gemian | awk 'NR == 2 { print $4 }')
    [ "$efi_available" -ge $((efi_archive_size / 1024 + 8192)) ] \
        || provision_abort "efi-files-space"
    /bin/gemini-efi-publish install /mnt/gemian /run/efi-files.tree /etc/gemini-efi-files.manifest \
        || provision_abort "efi-files-publication"
    efi_verify_stores || provision_abort "efi-files-protected-store-after"
    restore_store_readonly || fail "efi-files-ro-restore"
    /bin/gemini-efi-publish verify /mnt/gemian /run/efi-files.tree /etc/gemini-efi-files.manifest \
        || fail "efi-files-readback"
    printf '%s\n' "$efi_verified" > /run/efi-boot-files.verified
    log "$efi_verified p29=ro,noload"
}
efi_provision_boot_files
