#!/usr/bin/env python3
"""Exercise the real transformer and refusal without publication."""
from pathlib import Path
import subprocess
import sys
import tempfile

source, resource, cpu8, cpu9, script = map(Path, sys.argv[1:])
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    target = root / 'candidate.dtb'
    def apply(overlays, success):
        before = target.read_bytes()
        result = subprocess.run([sys.executable, str(script), str(target), *map(str, overlays)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert (result.returncode == 0) == success, result.stderr.decode()
        if not success:
            assert target.read_bytes() == before
    target.write_bytes(source.read_bytes())
    apply((resource, cpu8, cpu9), True)
    apply((resource, cpu8, cpu9), False)  # Already active is not a new baseline.
    # Keep CPU9 admission valid while changing an unrelated watchdog property.
    bad_source = root / 'bad.dts'
    bad_source.write_text('/dts-v1/; /plugin/; &cpu9 { enable-method = "mediatek,mt6797-psci"; status = "okay"; }; &watchdog { status = "disabled"; };')
    bad_overlay = root / 'bad.dtbo'
    subprocess.run(['dtc', '-q', '-@', '-I', 'dts', '-O', 'dtb', '-o', str(bad_overlay), str(bad_source)], check=True)
    target.write_bytes(source.read_bytes())
    subprocess.run(['fdtput', '-t', 's', str(target), '/__symbols__', 'cpuclk', '/a72-power'], check=True)
    apply((resource, cpu8, cpu9), False)
    # All A72 statuses now pass; the unrelated delta must still be refused.
    target.write_bytes(source.read_bytes())
    apply((resource, cpu8, bad_overlay), False)
print('PASS real A72 transformer: valid composition, duplicate/wrong-symbol/wrong-overlay refusal without publication')
