#!/usr/bin/env python3
"""Reject leaked/stale GNSS reports and failed power cleanup before promotion."""
import copy
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('gnss_wrapper', Path(__file__).with_name('test-gnss-desktop.py'))
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)
gnss = wrapper.gnss
remote = {'__name__': 'fixture'}
exec(gnss.REMOTE_CODE, remote)


def good_report():
    return dict(schema=1, result='passed', error='none', opened=True, closed=True, errno=0,
                lna_before_users=0, lna_before_enabled=0, lna_during_users=1, lna_during_enabled=1,
                lna_after_users=0, lna_after_enabled=0, taint_before=0, taint_after=0,
                read_window_seconds=10, read_window_complete=True, boot_identity_preserved=True,
                system_identity_preserved=True, receiver_commands_sent=0,
                receiver_protocol_qualified=False, position_qualified=False, bytes=0,
                printable_bytes=0, nmea_shapes=0, nmea_checksum_valid=0,
                nmea_valid_fix_flags=0, elapsed_ms=10000)


class Evidence(unittest.TestCase):
    def test_scalar_schema_requires_cleanup_and_leaves_zero_data_unqualified(self):
        good = good_report()
        self.assertEqual(gnss.verify_report(json.dumps(good)), good)
        wrong = dict(lna_before_users=1, lna_before_enabled=1, lna_during_users=0,
                     lna_during_enabled=0, lna_after_users=1, lna_after_enabled=1,
                     closed=False, errno=5, taint_after=1, boot_identity_preserved=False,
                     system_identity_preserved=False, read_window_complete=False,
                     receiver_protocol_qualified=True, position_qualified=True,
                     read_window_seconds=11, elapsed_ms=9999, bytes=-1, printable_bytes=1,
                     nmea_checksum_valid=1, nmea_valid_fix_flags=1)
        for key, value in (*wrong.items(), ('lna_during_users', True)):
            bad = dict(good, **{key: value})
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                gnss.verify_report(json.dumps(bad))
        for key in good:
            bad = copy.copy(good); del bad[key]
            with self.subTest(missing=key), self.assertRaises(RuntimeError):
                gnss.verify_report(json.dumps(bad))
        with self.assertRaises(RuntimeError):
            gnss.verify_report(json.dumps(dict(good, raw='forbidden')))

    def test_fragmented_nmea_binary_noise_checksum_and_memory_bound(self):
        def sentence(body):
            checksum = 0
            for byte in body:
                checksum ^= byte
            return b'$' + body + b'*' + f'{checksum:02X}'.encode() + b'\r\n'
        valid = sentence(b'GPRMC,,A,,,,,,,,,')
        warning = sentence(b'GPRMC,,V,,,,,,,,,')
        for split in range(len(valid) + 1):
            metadata = remote['StreamMetadata']()
            metadata.feed(b'\0\xff' + valid[:split]); metadata.feed(valid[split:] + warning)
            self.assertEqual(metadata.counts['nmea_shapes'], 2)
            self.assertEqual(metadata.counts['nmea_checksum_valid'], 2)
            self.assertEqual(metadata.counts['nmea_valid_fix_flags'], 1)
            metadata.feed(valid.replace(b'A', b'V'))
            self.assertEqual(metadata.counts['nmea_checksum_valid'], 2)
            metadata.feed(b'$' + b'A' * 300)
            self.assertLessEqual(len(metadata.pending), 256)
            self.assertTrue(all(type(value) is int for value in metadata.counts.values()))

    def observe_fixture(self, during=(1, 1), read_error=False, changed_identity=False):
        clock = SimpleNamespace(now=0)
        class Selector:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def register(self, fd, events): self.fd = fd
            def select(self, seconds):
                if read_error: return [(self.fd, 1)]
                clock.now += seconds
                return []
        class DevicePath:
            def __init__(self, path): self.path = path
            def read_text(self):
                assert self.path == '/proc/sys/kernel/tainted'
                return '0'
            def resolve(self): return SimpleNamespace(name='mt6797-gnss')
        identities = [None, remote['CheckError']('identity_changed') if changed_identity else None]
        with mock.patch.dict(remote, Path=DevicePath,
                             identity=mock.Mock(side_effect=identities),
                             lna_state=mock.Mock(side_effect=[(0, 0), during, (0, 0)])), \
                mock.patch.object(remote['time'], 'monotonic', side_effect=lambda: clock.now), \
                mock.patch.object(remote['selectors'], 'DefaultSelector', Selector), \
                mock.patch.object(remote['os'], 'stat', return_value=SimpleNamespace(st_mode=stat.S_IFCHR)), \
                mock.patch.object(remote['os'], 'open', return_value=17) as opened, \
                mock.patch.object(remote['os'], 'close') as closed, \
                mock.patch.object(remote['os'], 'read', side_effect=OSError(5, 'fixture')):
            record = remote['observe']('fixture', 'fixture')
        opened.assert_called_once()
        closed.assert_called_once_with(17)
        self.assertEqual(record['lna_after_users'], 0)
        self.assertEqual(record['lna_after_enabled'], 0)
        return record

    def test_actual_observer_balances_fd_on_success_and_failures(self):
        good = self.observe_fixture()
        gnss.verify_report(json.dumps(good))
        for options in (dict(during=(0, 0)), dict(read_error=True), dict(changed_identity=True)):
            failed = self.observe_fixture(**options)
            self.assertEqual(failed['result'], 'failed')
            self.assertTrue(failed['closed'])
            with self.assertRaises(RuntimeError): gnss.verify_report(json.dumps(failed))

    def test_two_cycles_precede_desktop_checks_and_failure_blocks_return(self):
        for failed_cycle in (None, 2):
            calls = []
            runner = SimpleNamespace(backend=SimpleNamespace(MTK=None, MTK_RTC='existing-writer'),
                                     qualify=SimpleNamespace(save=mock.Mock()),
                                     persistence=SimpleNamespace(run=mock.Mock(return_value='GNSS_DESKTOP_IDENTITY_PASS\n')))
            def candidate(*args): calls.append('base'); return {'boot_id': 'fixture'}
            runner.candidate_return = candidate
            def cycle(*args):
                number = args[-1]; calls.append(number)
                if number == failed_cycle: raise RuntimeError('fixture cycle failure')
                return good_report()
            def check(name):
                def run(*args): calls.append(name); return {'result': 'passed'}
                return run
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'kernel.config').write_text('CONFIG_GNSS=y\nCONFIG_GNSS_MTK_CONSYS=m\n'
                    'CONFIG_MTK_MT6797_CONSYS_INVENTORY=m\nCONFIG_REGULATOR_FIXED_VOLTAGE=y\n')
                with mock.patch.object(wrapper, 'base_configure', return_value=runner), \
                        mock.patch.object(wrapper.p, 'KERNEL', root), \
                        mock.patch.object(wrapper.gnss, 'evidence', side_effect=cycle), \
                        mock.patch.object(wrapper.desktop, 'bluetooth_evidence', side_effect=check('bt')), \
                        mock.patch.object(wrapper.desktop.network, 'network_evidence', side_effect=check('nm')):
                    configured = wrapper.configure()
                    if failed_cycle:
                        with self.assertRaises(RuntimeError): configured.candidate_return([], {}, root, 'fixture')
                        self.assertEqual(calls, ['base', 1, 2])
                        runner.persistence.run.assert_not_called()
                    else:
                        self.assertEqual(configured.candidate_return([], {}, root, 'fixture'), {'boot_id': 'fixture'})
                        self.assertEqual(calls, ['base', 1, 2, 'bt', 'nm'])
                        runner.persistence.run.assert_called_once()
            self.assertIs(wrapper.p.preflight, wrapper.desktop.boot.base_preflight)
            self.assertIs(wrapper.p.finish, wrapper.desktop.boot.base_finish)
            for source in ('tools/test-gnss-desktop.py', 'tools/gnss-stream-evidence.py',
                           'tools/test-network-audio-desktop.py', 'tools/networkmanager-scan-evidence.py'):
                self.assertIn(source, wrapper.p.EXTRA_EXECUTED_SOURCES)


if __name__ == '__main__':
    unittest.main()
