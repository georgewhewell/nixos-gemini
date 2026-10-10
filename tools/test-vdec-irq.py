#!/usr/bin/env python3
"""Keep decoder IRQ evidence valid when CPUs park during a hardware trial."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('vdec_irq', Path(__file__).with_name('qualify-vdec-irq.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class IRQEvidence(unittest.TestCase):
    def test_actual_snapshot_retains_events_on_parked_cpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root/'interrupts'
            irq = root/'irq/77'
            irq.mkdir(parents=True)
            (irq/'actions').write_text('16020000.video-codec\n')
            counts = irq/'per_cpu_count'
            counts.write_text('0,0,0,0,0,0,0,0,0,0\n')
            proc.write_text('77: 0 0 0 0 0 0 0 0 0 0 GICv3 240 Level 16020000.video-codec\n')
            script = m.irq_snapshot_script().replace('/proc/interrupts', str(proc)).replace('/sys/kernel/irq', str(root/'irq'))

            def run():
                raw = subprocess.check_output(['sh', '-eu', '-c', script], text=True)
                return m.irq_counter(raw)

            before = run()
            # CPU 8 delivered four pictures, then went offline. Its count
            # disappears from /proc but remains in the possible-CPU vector.
            proc.write_text('77: 0 GICv3 240 Level 16020000.video-codec\n')
            counts.write_text('0,0,0,0,0,0,0,0,4,0\n')
            after = run()
            self.assertEqual(after['total']-before['total'], 4)
            self.assertEqual(len(after['counts']), 10)
            self.assertEqual(after['counter'], 'sysfs-all-possible-cpus')
            proc.write_text(proc.read_text()+'78: 0 GICv3 240 Level 16020000.video-codec\n')
            with self.assertRaises(subprocess.CalledProcessError):
                run()

    def test_foreign_or_malformed_snapshots_cannot_prove_completion(self):
        good = 'irq=77\nactions=16020000.video-codec\ncounts=0,4,0\n'
        for bad in (
            good.replace('16020000.video-codec', 'foreign'),
            good.replace('0,4,0', '0,bad,0'),
            good.replace('0,4,0', ''),
            good.replace('irq=77', 'irq=77:78'),
            good+'counts=4\n',
            'irq=77\ncounts=4\n',
        ):
            with self.subTest(snapshot=bad), self.assertRaises(RuntimeError):
                m.irq_counter(bad)


if __name__ == '__main__':
    unittest.main()
