#!/bin/sh
set -u

# Gemini-specific host-plane repair.  This script may mutate only the
# interface whose exact gadget MAC is present while the exact Gemini USB
# gadget identity is enumerated.  It never searches for or changes a broad
# class of interfaces.
LOG=$1
STATE=$2
GADGET_MAC=42:00:15:19:82:00
GADGET_USB=0525:a4a2
HOST_ADDRESS=10.15.19.81/24
DEVICE_ROUTE=10.15.19.82/32

log() {
    printf '[%s] %s\n' "$(date -Is)" "$*" >> "$LOG"
}

publish_identity() {
    identity_tmp=$STATE.tmp.$$
    printf 'identity=verified usb=%s mac=%s iface=%s epoch=%s\n' \
        "$GADGET_USB" "$GADGET_MAC" "$iface" "$(date +%s)" > "$identity_tmp"
    mv -f "$identity_tmp" "$STATE"
}

safe_iface() {
    case "$1" in
        ''|*[!A-Za-z0-9_.-]*) return 1 ;;
        *) return 0 ;;
    esac
}

log "watcher=start gadget_mac=$GADGET_MAC usb=$GADGET_USB address=$HOST_ADDRESS route=$DEVICE_ROUTE"
while :; do
    if ! lsusb -d "$GADGET_USB" >/dev/null 2>&1; then
        log "identity=absent usb=$GADGET_USB"
        sleep 1
        continue
    fi

    iface=$(ip -o link show | awk -v mac="$GADGET_MAC" \
        '$0 ~ ("link/ether " mac " ") {sub(/^[0-9]+: /, "", $2); sub(/:$/, "", $2); print $2; exit}')
    if ! safe_iface "$iface" ||
       [ "$(cat "/sys/class/net/$iface/address" 2>/dev/null || true)" != "$GADGET_MAC" ]; then
        log "identity=usb-present exact-mac-interface=absent usb=$GADGET_USB"
        sleep 1
        continue
    fi

    publish_identity
    log "identity=verified usb=$GADGET_USB iface=$iface mac=$GADGET_MAC"
    if ! sudo -n ip link set dev "$iface" up; then
        log "action=link-up result=failed iface=$iface"
    else
        log "action=link-up result=ok iface=$iface"
    fi
    if ! sudo -n ip addr replace "$HOST_ADDRESS" dev "$iface"; then
        log "action=address-replace result=failed iface=$iface address=$HOST_ADDRESS"
    else
        log "action=address-replace result=ok iface=$iface address=$HOST_ADDRESS"
    fi
    # A second 10.15.19.0/24 USB network exists on Trex.  Its equal-cost
    # connected route otherwise wins after this gadget disconnects and
    # re-enumerates.  Reassert an exact route only after both the USB VID:PID
    # and gadget MAC identify the Gemini interface.
    if ! sudo -n ip route replace "$DEVICE_ROUTE" dev "$iface" src "${HOST_ADDRESS%/*}"; then
        log "action=route-replace result=failed iface=$iface route=$DEVICE_ROUTE"
    else
        log "action=route-replace result=ok iface=$iface route=$DEVICE_ROUTE"
    fi
    sleep 1
done
