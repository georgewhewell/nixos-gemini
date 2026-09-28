"""Exercise the real client against Weston and a non-responsive socket."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

weston, probe = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix="gemini-desktop-fixture-") as directory:
    env = dict(os.environ, XDG_RUNTIME_DIR=directory, WAYLAND_DISPLAY="wayland-test")
    env.pop("DISPLAY", None)
    for width, fixture, expected in [(540, True, 0), (540, False, 1), (640, True, 1)]:
        with tempfile.TemporaryFile(mode="w+") as log:
            server = subprocess.Popen([
                weston, "-Bheadless", "--renderer=pixman", f"--width={width}",
                "--height=1080", "--scale=2", "--transform=rotate-90",
                "--idle-time=0", "--socket=wayland-test", "--no-config",
            ], env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    if Path(directory, "wayland-test").exists() or server.poll() is not None:
                        break
                    time.sleep(0.05)
                result = subprocess.run([probe] + (["--headless-fixture"] if fixture else []),
                    env=env, text=True, capture_output=True, timeout=20)
                assert result.returncode == expected, (result.returncode, result.stdout, result.stderr)
                if expected == 0:
                    assert "desktop-presentation=passed mode=headless-fixture frames=3" in result.stdout
                    assert result.stdout.count("presented=") == 3
                else:
                    stage = "physical-output-or-input-capabilities" if width == 540 else "output-geometry"
                    assert f"failed={stage}" in result.stderr
                    assert "desktop-presentation=passed" not in result.stdout
                print(f"width={width} fixture={fixture} expected_exit={expected}: PASS")
            finally:
                if server.poll() is None:
                    server.terminate()
                server.wait(timeout=10)
    # Accepting connections alone must not hang the boot qualification.
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(Path(directory, "wayland-stalled")))
        server.listen(1)
        started = time.monotonic()
        result = subprocess.run([probe, "--headless-fixture"],
            env=dict(env, WAYLAND_DISPLAY="wayland-stalled"),
            text=True, capture_output=True, timeout=20)
        assert result.returncode == -signal.SIGALRM, result
        assert 14 <= time.monotonic() - started < 20
        assert "desktop-presentation=passed" not in result.stdout
        print("unresponsive compositor: bounded failure PASS")
