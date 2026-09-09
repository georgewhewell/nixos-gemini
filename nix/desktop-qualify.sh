set -eu
grep -wFq GEMINI_A72_CI9_M38 /proc/cmdline
systemctl is-active --quiet gemini-watchdog-takeover.service gemini-gpu.service gemini-audio.service gemini-connectivity.service
test "$(cat /sys/class/watchdog/watchdog0/state)" = active
test "$(cat /sys/class/tty/tty0/active)" = tty1
mkdir /run/gemini-desktop-check
cat /proc/sys/kernel/random/boot_id > /run/gemini-desktop-check/boot-id
passed=no
finish() {
    dmesg > /run/gemini-desktop-check/kernel-final.txt || :
    if test "$passed" != yes; then
        cp /run/gemini-desktop/weston.log /run/gemini-desktop-check/weston-failed.log 2>/dev/null || :
        cp /run/gemini-desktop/presentation.txt /run/gemini-desktop-check/presentation-failed.txt 2>/dev/null || :
        cp /run/gemini-desktop/buffers.txt /run/gemini-desktop-check/buffers-failed.txt 2>/dev/null || :
        systemctl stop gemini-desktop.service gemini-seatd.service || :
    fi
}
trap finish EXIT
irq_count() {
    awk '$NF == "panfrost-job" { found++; for (i=2; i<=NF && $i ~ /^[0-9]+$/; i++) total += $i } END { if (found != 1) exit 1; print total+0 }' /proc/interrupts
}
terminal_ready() {
    expected_uid=$(id -u gemini)
    for process in /proc/[0-9]*; do
        test "$(readlink "$process/exe" 2>/dev/null)" = "$GEMINI_WESTON_TERMINAL" || continue
        awk -v uid="$expected_uid" '$1 == "Uid:" && $2 == uid && $3 == uid && $4 == uid && $5 == uid { ok=1 } END { exit !ok }' "$process/status" || return 1
        grep -Fq '/gemini-desktop.service' "$process/cgroup" || return 1
        return 0
    done
    return 1
}
gpu=/sys/bus/platform/devices/13040000.gpu
for pass in 1 2; do
    jobs_before=$(irq_count)
    systemctl start gemini-desktop.service
    test "$(cat /sys/class/tty/tty0/active)" = tty7
    systemctl start gemini-desktop-presentation.service
    cp /run/gemini-desktop/presentation.txt /run/gemini-desktop-check/presentation-$pass.txt
    cp /run/gemini-desktop/buffers.txt /run/gemini-desktop-check/buffers-$pass.txt
    cp /run/gemini-desktop/weston.log /run/gemini-desktop-check/weston-$pass.log
    grep -Eq '^desktop-buffers=passed concurrent=3 bytes=[0-9]+ handles=released$' /run/gemini-desktop-check/buffers-$pass.txt
    grep -Fxq 'desktop-presentation=passed mode=device frames=3' /run/gemini-desktop-check/presentation-$pass.txt
    grep -Eq 'GL renderer: Mali-T880.*[Pp]anfrost' /run/gemini-desktop-check/weston-$pass.log
    jobs_after=$(irq_count)
    test "$jobs_after" -gt "$jobs_before"
    count=0
    until terminal_ready; do
        count=$((count + 1))
        test "$count" -lt 50
        sleep 0.1
    done
    echo "pass=$pass job_irq_progress=$((jobs_after - jobs_before)) terminal=running-user-gemini" >> /run/gemini-desktop-check/progress.txt
    if test "$pass" = 1; then
        systemctl stop gemini-desktop.service gemini-seatd.service
        test "$(cat /sys/class/tty/tty0/active)" = tty1
        test "$(systemctl show gemini-desktop.service -p MainPID --value)" = 0
        count=0
        while test "$(cat "$gpu/power/runtime_status")" != suspended; do
            count=$((count + 1))
            test "$count" -lt 50
            sleep 0.1
        done
        cat /sys/kernel/debug/pm_genpd/pm_genpd_summary > /run/gemini-desktop-check/domains-stopped.txt
        for domain in mfg_async mfg mfg_core0 mfg_core1 mfg_core2 mfg_core3; do
            awk -v domain="$domain" '$1 == domain && $2 ~ /^off/ { ok=1 } END { exit !ok }' /run/gemini-desktop-check/domains-stopped.txt
        done
        cat /sys/kernel/debug/dri/0/state > /run/gemini-desktop-check/console-restored.txt
        grep -Fq 'allocated by = [fbcon]' /run/gemini-desktop-check/console-restored.txt
        echo 'console=tty1-restored gpu=all-six-domains-off' >> /run/gemini-desktop-check/progress.txt
    fi
done
dmesg > /run/gemini-desktop-check/kernel.txt
sh "$GEMINI_GPU_LOG_CHECK" /run/gemini-desktop-check/kernel.txt /run/gemini-desktop-check/kernel-scoped.txt
systemctl is-active --quiet gemini-desktop.service gemini-seatd.service gemini-watchdog-takeover.service
test "$(cat /sys/class/watchdog/watchdog0/state)" = active
echo 'desktop=gl-presentation-console-restoration-passed' > /run/gemini-desktop-check/result
passed=yes
