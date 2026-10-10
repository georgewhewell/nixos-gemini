#!/usr/bin/env python3
"""Reject physical swap, writeback, missing paging proof and unsafe recovery."""
import importlib.util
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/file)
    out = importlib.util.module_from_spec(spec); spec.loader.exec_module(out)
    return out


z = module('zram', 'qualify-zram.py')
# Use the shared verifier without importing historical hardware supervisors.
tree = ast.parse((ROOT/'tools/qualify-swap-io.py').read_text())
limits = next(node for node in tree.body if isinstance(node, ast.Assign) and
              any(isinstance(target, ast.Name) and target.id == 'LIMITS' for target in node.targets))
verify = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'verify_probe')
namespace = {'json': json}
exec(compile(ast.Module(body=[limits, verify], type_ignores=[]), 'shared-paging-verifier', 'exec'), namespace)
p = SimpleNamespace(LIMITS=namespace['LIMITS'], verify_probe=namespace['verify_probe'])
CONFIG = b'''CONFIG_ZRAM=y
CONFIG_ZRAM_BACKEND_LZ4=y
CONFIG_ZRAM_DEF_COMP_LZ4=y
# CONFIG_ZRAM_WRITEBACK is not set
# CONFIG_ZSWAP is not set
'''
SWAPS = 'Filename Type Size Used Priority\n/dev/zram0 partition 1890300 1234 5\n'


class Paging(unittest.TestCase):
    def test_kernel_rejects_writeback_zswap_and_missing_zram(self):
        z.verify_config(CONFIG)
        for change in (b'CONFIG_ZSWAP=y\n', b'CONFIG_ZRAM_WRITEBACK=y\n', b'CONFIG_ZRAM=m\n'):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                z.verify_config(CONFIG+change)
        for line in CONFIG.splitlines(keepends=True):
            with self.subTest(missing=line), self.assertRaises(RuntimeError):
                z.verify_config(CONFIG.replace(line, b''))

    def test_only_zram_is_accepted(self):
        self.assertFalse(z.verify_swaps(SWAPS)['flash_swap_active'])
        for bad in (SWAPS.replace('/dev/zram0', '/dev/mmcblk0p34'),
                    SWAPS+'/dev/mmcblk1p2 partition 1048576 0 -1\n',
                    SWAPS+'/swapfile file 1048576 0 -2\n',
                    SWAPS.splitlines()[0]+'\n', SWAPS.replace('1890300', '1024')):
            with self.subTest(raw=bad), self.assertRaises(RuntimeError):
                z.verify_swaps(bad)

    def test_probe_requires_data_readback_limits_and_zero_flash_writes(self):
        service = dict(p.LIMITS, ActiveState='active', SubState='exited', MainPID='0',
                       Result='success', ExecMainCode='1', ExecMainStatus='0', RemainAfterExit='yes')
        result = dict(bytes=134217728, swapped_kib=65536, read_sectors=131072,
                      written_sectors=131072, pattern_verified=True, flash_swap_written_sectors=0)
        z.verify_probe(p, json.dumps(result), service, 0)
        for key, value in (('flash_swap_written_sectors', 1), ('flash_swap_written_sectors', False),
                           ('read_sectors', 0), ('pattern_verified', False)):
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                z.verify_probe(p, json.dumps(dict(result, **{key: value})), service, 0)
        with self.assertRaises(RuntimeError):
            z.verify_probe(p, json.dumps(result), dict(service, MemoryMax='infinity'), 0)

    def test_recovery_guard_stops_before_running_any_remote_command(self):
        context = SimpleNamespace()
        z.install(context)
        runner = SimpleNamespace(qualify=SimpleNamespace(BASELINE={'zswap_shrinker': 'Y'}))
        with mock.patch.object(z, 'policy') as policy:
            with self.assertRaisesRegex(RuntimeError, 'recovery image still enables flash swap'):
                context.baseline_paging(runner, Path('/unused'), {'boot_id': 'unused'})
            policy.assert_not_called()


if __name__ == '__main__':
    unittest.main()
