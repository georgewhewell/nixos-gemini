#!/usr/bin/env python3
"""Host integration test for gemini-core-parking against a simulated sysfs.

Usage: test-core-parking.py PATH-TO-BINARY

A fake root holds /sys/devices/system/cpu/cpuN/online, /proc/stat,
/proc/loadavg, /dev/input/event0 (a FIFO) and /run/gemini-core-parking.  A simulator thread
advances /proc/stat every 10 ms: each busy thread saturates one online CPU.
"""
import os
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time

BIN = sys.argv[1]
NCPU = 10


class Sim:
    def __init__(self, root):
        self.root = root
        self.threads = 0
        self.counters = [[0, 0] for _ in range(NCPU)]  # busy, idle (ticks)
        self.stop = False
        for cpu in range(NCPU):
            d = f"{root}/sys/devices/system/cpu/cpu{cpu}"
            os.makedirs(d, exist_ok=True)
            if cpu:
                self.set_online(cpu, 1)
        os.makedirs(f"{root}/proc", exist_ok=True)
        os.makedirs(f"{root}/dev/input", exist_ok=True)
        os.makedirs(f"{root}/run/gemini-core-parking", exist_ok=True)
        os.makedirs(f"{root}/sys/class/thermal/thermal_zone0", exist_ok=True)
        with open(f"{root}/sys/class/thermal/thermal_zone0/type", "w") as f:
            f.write("soc-thermal\n")
        self.set_temp(45000)
        # Keep the inode stable, as procfs does across refreshed snapshots.
        self.stat_fd = os.open(f"{root}/proc/stat", os.O_RDWR | os.O_CREAT, 0o600)
        self.loadavg_fd = os.open(f"{root}/proc/loadavg", os.O_RDWR | os.O_CREAT, 0o600)
        self.write_stat()

    def set_temp(self, mc):
        with open(f"{self.root}/sys/class/thermal/thermal_zone0/temp", "w") as f:
            f.write(f"{mc}\n")

    def online_path(self, cpu):
        return f"{self.root}/sys/devices/system/cpu/cpu{cpu}/online"

    def set_online(self, cpu, v):
        with open(self.online_path(cpu), "w") as f:
            f.write(f"{v}\n")

    def online(self):
        out = [0]
        for cpu in range(1, NCPU):
            try:
                with open(self.online_path(cpu)) as f:
                    if f.read(1) == "1":
                        out.append(cpu)
            except OSError:
                pass
        return out

    def write_stat(self):
        online = self.online()
        busy = online[: self.threads]
        lines = ["cpu  0 0 0 0 0 0 0 0 0 0"]
        for cpu in online:
            c = self.counters[cpu]
            if cpu in busy:
                c[0] += 1
            else:
                c[1] += 1
            lines.append(f"cpu{cpu} {c[0]} 0 0 {c[1]} 0 0 0 0 0 0")
        lines.append("intr 0")
        # Replace one fixed-size snapshot in one write, without a truncation
        # window or trailing CPU records when the online set shrinks.
        data = ("\n".join(lines) + "\n").encode()
        assert len(data) <= 4096
        data = data.ljust(4096, b"\n")
        assert os.pwrite(self.stat_fd, data, 0) == len(data)
        loadavg = f"0.00 0.00 0.00 {self.threads + 1}/32 1\n".encode().ljust(128, b"\n")
        assert os.pwrite(self.loadavg_fd, loadavg, 0) == len(loadavg)

    def run(self):
        while not self.stop:
            self.write_stat()
            time.sleep(0.01)


def wait_for(pred, timeout, what):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return time.monotonic() - t0
        time.sleep(0.005)
    raise AssertionError(f"timeout waiting for {what}")


def start(root, *extra):
    log = open(f"{root}/log", "w")
    return subprocess.Popen(
        [BIN, "--root", root, "--period-ms", "20", "--down-hold-ms", "150",
         "--boost-hold-ms", "400", *extra],
        stdout=log, stderr=subprocess.STDOUT)


def stop(p):
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=5) == 0


def main():
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as root:
        sim = Sim(root)
        fifo = f"{root}/dev/input/event0"
        os.mkfifo(fifo)
        # Keep a writer open so the daemon's reader never sees EOF.
        rfd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        wfd = os.open(fifo, os.O_WRONLY)
        t = threading.Thread(target=sim.run)
        t.start()
        try:
            p = start(root, "--pinned", "8,9", "--requires", "8:4")

            # 1. idle: park 7..1 (A72s pinned), never CPU0.
            dt = wait_for(lambda: sim.online() == [0, 8, 9], 15, "idle parking")
            print(f"idle-parked in {dt:.2f}s: {sim.online()}")

            # 2. load: 4 threads -> rush +1, then up to 5 online CPUs.
            sim.threads = 4
            dt = wait_for(lambda: len(sim.online()) >= 4, 2, "rush")
            print(f"first unpark after load in {dt*1000:.0f} ms")
            assert dt < 0.5, dt
            wait_for(lambda: sim.online() == [0, 1, 2, 8, 9], 2, "settle")
            time.sleep(0.5)
            assert sim.online() == [0, 1, 2, 8, 9], sim.online()  # stable

            # 3. load gone -> parks again.
            sim.threads = 0
            wait_for(lambda: sim.online() == [0, 8, 9], 15, "re-park")

            # 4. input boost: 3 managed CPUs within one poll, then decay.
            ev = struct.pack("qqHHi", 0, 0, 1, 30, 1)  # EV_KEY KEY_A down
            os.write(wfd, ev)
            dt = wait_for(lambda: sim.online() == [0, 1, 2, 3, 8, 9], 1, "boost")
            print(f"input boost in {dt*1000:.0f} ms")
            assert dt < 0.3, dt
            wait_for(lambda: sim.online() == [0, 8, 9], 15, "boost decay")
            # EV_SW (lid) does not boost.
            os.write(wfd, struct.pack("qqHHi", 0, 0, 5, 0, 1))
            time.sleep(0.2)
            assert sim.online() == [0, 8, 9], sim.online()

            # 5. hold file: everything online, no parking while it exists.
            hold = f"{root}/run/gemini-core-parking/hold"
            open(hold, "w").close()
            wait_for(lambda: sim.online() == list(range(10)), 1, "hold")
            time.sleep(0.5)
            assert sim.online() == list(range(10))
            os.unlink(hold)
            wait_for(lambda: sim.online() == [0, 8, 9], 15, "after hold")

            # 6. pause file: no writes even under load.
            pause = f"{root}/run/gemini-core-parking/pause"
            open(pause, "w").close()
            sim.threads = 6
            time.sleep(0.4)
            assert sim.online() == [0, 8, 9], sim.online()
            os.unlink(pause)
            wait_for(lambda: len(sim.online()) >= 6, 2, "after pause")
            sim.threads = 0

            # 7. thermal: hot caps at thermal-max (3), clear releases.
            sim.set_temp(99000)
            sim.threads = 8
            wait_for(lambda: "thermal hot" in open(f"{root}/log").read(), 3,
                     "thermal hot")
            wait_for(lambda: sim.online() == [0, 1, 2, 3, 8, 9], 3, "thermal cap")
            time.sleep(0.3)
            assert sim.online() == [0, 1, 2, 3, 8, 9], sim.online()
            sim.set_temp(80000)
            wait_for(lambda: len(sim.online()) >= 8, 3, "thermal clear")
            sim.threads = 0
            wait_for(lambda: sim.online() == [0, 8, 9], 15, "park after thermal")

            # 8. SIGTERM restores every managed CPU.
            stop(p)
            assert sim.online() == list(range(10)), sim.online()

            # 9. requires: CPU4 is onlined before CPU8.  CPU7 is unwritable.
            for cpu in (4, 7, 8):
                sim.set_online(cpu, 0)
            if os.geteuid() != 0:
                os.chmod(sim.online_path(7), 0o444)
            p = start(root, "--order", "1,2,3,8,7", "--requires", "8:4",
                      "--min", "5")
            wait_for(lambda: 8 in sim.online(), 2, "cpu8 with dependency")
            assert 4 in sim.online()
            time.sleep(0.3)
            stop(p)
            with open(f"{root}/log") as f:
                log = f.read()
            assert log.index("cpu4 online") < log.index("cpu8 online"), log
            if os.geteuid() != 0:
                assert "cpu7 not manageable" in log, log
        finally:
            sim.stop = True
            t.join()
            os.close(sim.stat_fd)
            os.close(sim.loadavg_fd)
            os.close(wfd)
            os.close(rfd)
    print("core-parking: pass")


if __name__ == "__main__":
    main()
