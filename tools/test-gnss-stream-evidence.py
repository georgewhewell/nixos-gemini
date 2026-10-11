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
    return dict(schema=2, result='passed', error='none', opened=True, closed=True, errno=0,
                lna_before_users=0, lna_before_enabled=0, lna_during_users=1, lna_during_enabled=1,
                lna_after_users=0, lna_after_enabled=0, taint_before=0, taint_after=0,
                read_window_seconds=10, read_window_complete=True, boot_identity_preserved=True,
                system_identity_preserved=True, receiver_commands_sent=0,
                receiver_protocol_qualified=False, position_qualified=False, bytes=0,
                printable_bytes=0, nmea_shapes=0, nmea_checksum_valid=0,
                nmea_valid_fix_flags=0, elapsed_ms=10000, native_gnss_module_present=True,
                matching_platform_child_present=True, driver_bound=True, class_registered=True,
                gnss_node_present=True,
                **{phase: dict.fromkeys(gnss.RX_COUNTS, 0) for phase in gnss.RX_PHASES})


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
                     nmea_checksum_valid=1, nmea_valid_fix_flags=1,
                     **{key: False for key in gnss.REGISTRATION})
        for key, value in (*wrong.items(), ('lna_during_users', True),
                           ('native_gnss_module_present', 1)):
            bad = dict(good, **{key: value})
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                gnss.verify_report(json.dumps(bad))
        for key in good:
            bad = copy.copy(good); del bad[key]
            with self.subTest(missing=key), self.assertRaises(RuntimeError):
                gnss.verify_report(json.dumps(bad))
        with self.assertRaises(RuntimeError):
            gnss.verify_report(json.dumps(dict(good, raw='forbidden')))

    def test_receive_schema_rejects_missing_malformed_and_regressed_counts(self):
        good = good_report()
        for phase in gnss.RX_PHASES:
            for value in (None, [], dict(raw='forbidden'),
                          {**good[phase], 'extra': 0}):
                bad = copy.deepcopy(good); bad[phase] = value
                with self.subTest(phase=phase, value=value), self.assertRaises(RuntimeError):
                    gnss.verify_report(json.dumps(bad))
            for key in gnss.RX_COUNTS:
                for value in (-1, 1 << 64, True, '0', None):
                    bad = copy.deepcopy(good); bad[phase][key] = value
                    with self.subTest(phase=phase, key=key, value=value), self.assertRaises(RuntimeError):
                        gnss.verify_report(json.dumps(bad))
                bad = copy.deepcopy(good); del bad[phase][key]
                with self.assertRaises(RuntimeError): gnss.verify_report(json.dumps(bad))
        for key in gnss.RX_COUNTS:
            for earlier in gnss.RX_PHASES[:-1]:
                bad = copy.deepcopy(good); bad[earlier][key] = 1
                with self.subTest(earlier=earlier, key=key), self.assertRaises(RuntimeError):
                    gnss.verify_report(json.dumps(bad))
        with self.assertRaises(RuntimeError):
            gnss.verify_report(json.dumps(dict(good, schema=1)))
        # Counters from separate owners are not a joint atomic snapshot.
        different = copy.deepcopy(good)
        for phase in gnss.RX_PHASES:
            different[phase]['admitted'] = 7
        self.assertEqual(gnss.verify_report(json.dumps(different)), different)

    def test_actual_counter_reader_requires_owners_bounds_and_preserved_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            consys = root / 'sys/devices/platform/consys'
            endpoint = consys / 'gnss'
            gdev = root / 'sys/class/gnss/gnss0'
            for path in (endpoint, gdev, root / 'sys/bus/platform/drivers/mt6797-gnss',
                         root / 'sys/bus/platform/drivers/mt6797-consys'):
                path.mkdir(parents=True)
            (gdev / 'device').symlink_to(endpoint)
            (endpoint / 'driver').symlink_to(root / 'sys/bus/platform/drivers/mt6797-gnss')
            (consys / 'driver').symlink_to(root / 'sys/bus/platform/drivers/mt6797-consys')
            rx = endpoint / 'rx_delivery'; stp = consys / 'gnss_rx_frames'
            rx.write_text('admitted=1 inactive=2 rejected=3\n'); stp.write_text('4\n')
            with mock.patch.dict(remote, Path=lambda path: root / path.lstrip('/')):
                reader = remote['RxCounters']()
                self.assertEqual(reader.snapshot(), dict(crc_valid_task2=4, admitted=1,
                                                         inactive=2, rejected=3))
                stp.write_text('5\n')
                self.assertEqual(reader.snapshot()['crc_valid_task2'], 5)
                stp.write_text('4\n')
                with self.assertRaisesRegex(remote['CheckError'], 'counter_regressed'):
                    reader.snapshot()
                stp.write_text('5\n')
                for value in ('', '-1\n', f'{1 << 64}\n', '1\nraw\n', '0' * 193):
                    stp.write_text(value)
                    with self.subTest(value=value[:30]), self.assertRaises(remote['CheckError']):
                        reader.snapshot()
                stp.write_text('5\n')
                for value in ('admitted=1 inactive=2\n', 'admitted=1 inactive=2 rejected=-1\n',
                              'admitted=1 inactive=2 rejected=3 raw=1\n'):
                    rx.write_text(value)
                    with self.assertRaises(remote['CheckError']): reader.snapshot()
                rx.write_text('admitted=1 inactive=2 rejected=3\n')
                with mock.patch.object(reader, 'owner_identity', return_value=('replacement',)):
                    with self.assertRaisesRegex(remote['CheckError'], 'counter_owner_changed'):
                        reader.snapshot()
                stp.unlink()
                with self.assertRaises(FileNotFoundError): remote['RxCounters']()

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

    def observe_fixture(self, during=(1, 1), read_error=False, changed_identity=False,
                        missing_node=False, missing_counters=False, counter_failure=False):
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
        registration = {key: True for key in gnss.REGISTRATION}
        if missing_node: registration['gnss_node_present'] = False
        counters = mock.Mock()
        snapshots = [dict.fromkeys(gnss.RX_COUNTS, 0) for _ in gnss.RX_PHASES]
        if counter_failure: snapshots[1] = remote['CheckError']('counter_regressed')
        counters.snapshot.side_effect = snapshots
        with mock.patch.dict(remote, Path=DevicePath,
                             registration_state=lambda record: record.update(registration),
                             RxCounters=mock.Mock(return_value=counters, side_effect=
                                 FileNotFoundError(2, 'fixture') if missing_counters else None),
                             identity=mock.Mock(side_effect=identities),
                             lna_state=mock.Mock(side_effect=[(0, 0), during, (0, 0)])), \
                mock.patch.object(remote['time'], 'monotonic', side_effect=lambda: clock.now), \
                mock.patch.object(remote['selectors'], 'DefaultSelector', Selector), \
                mock.patch.object(remote['os'], 'stat', return_value=SimpleNamespace(st_mode=stat.S_IFCHR),
                    side_effect=FileNotFoundError(2, 'fixture') if missing_node else None), \
                mock.patch.object(remote['os'], 'open', return_value=17) as opened, \
                mock.patch.object(remote['os'], 'close') as closed, \
                mock.patch.object(remote['os'], 'read', side_effect=OSError(5, 'fixture')):
            record = remote['observe']('fixture', 'fixture')
        if missing_node or missing_counters:
            opened.assert_not_called()
            closed.assert_not_called()
        else:
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

    def test_counter_failure_prevents_open_or_still_closes_an_open_endpoint(self):
        missing = self.observe_fixture(missing_counters=True)
        self.assertFalse(missing['opened'])
        self.assertEqual(missing['result'], 'failed')
        failed = self.observe_fixture(counter_failure=True)
        self.assertTrue(failed['opened'])
        self.assertTrue(failed['closed'])
        self.assertEqual(failed['error'], 'counter_regressed')
        self.assertEqual(failed['result'], 'failed')
        for record in (missing, failed):
            with self.assertRaises(RuntimeError): gnss.verify_report(json.dumps(record))

    def test_registration_flags_survive_missing_devnode_without_open(self):
        record = self.observe_fixture(missing_node=True)
        self.assertEqual(record['errno'], 2)
        self.assertEqual(record['error'], 'os_error')
        self.assertFalse(record['opened'])
        self.assertFalse(record['closed'])
        self.assertFalse(record['gnss_node_present'])
        self.assertTrue(all(record[key] for key in gnss.REGISTRATION[:-1]))
        self.assertTrue(all(type(record[key]) is bool for key in gnss.REGISTRATION))
        with self.assertRaises(RuntimeError): gnss.verify_report(json.dumps(record))

    def test_registration_matches_compatible_in_memory_and_requires_native_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('sys/module/gnss_mtk_consys', 'sys/class/gnss/gnss0',
                         'sys/bus/platform/drivers/mt6797-gnss', 'dev'):
                (root / name).mkdir(parents=True)
            (root / 'dev/gnss0').touch()
            for name, compatible in (('native', b'mediatek,mt6797-gnss\0'),
                                      ('other', b'mediatek,unrelated\0')):
                device = root / 'sys/bus/platform/devices' / name
                (device / 'of_node').mkdir(parents=True)
                (device / 'of_node/compatible').write_bytes(compatible)
            device = root / 'sys/bus/platform/devices/native'
            driver = device / 'driver'
            driver.symlink_to(root / 'sys/bus/platform/drivers/mt6797-gnss')
            def snapshot():
                record = {key: False for key in gnss.REGISTRATION}
                with mock.patch.dict(remote, Path=lambda path: root / path.lstrip('/')):
                    remote['registration_state'](record)
                self.assertEqual(set(record), set(gnss.REGISTRATION))
                self.assertTrue(all(type(value) is bool for value in record.values()))
                return record
            self.assertTrue(all(snapshot().values()))
            (root / 'sys/bus/platform/drivers/mt6797-gnss').rmdir()
            self.assertFalse(snapshot()['driver_bound'])
            driver.unlink()
            self.assertFalse(snapshot()['driver_bound'])
            (device / 'of_node/compatible').write_bytes(b'mediatek,unrelated\0')
            self.assertFalse(snapshot()['matching_platform_child_present'])
            (root / 'dev/gnss0').unlink()
            self.assertFalse(snapshot()['gnss_node_present'])

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
            self.assertIs(wrapper.p.preflight, wrapper.desktop.boot.boot_preflight)
            self.assertIs(wrapper.p.finish, wrapper.desktop.boot.boot_finish)
            for source in ('tools/test-gnss-desktop.py', 'tools/gnss-stream-evidence.py',
                           'tools/test-network-audio-desktop.py', 'tools/networkmanager-scan-evidence.py'):
                self.assertIn(source, wrapper.p.EXTRA_EXECUTED_SOURCES)


if __name__ == '__main__':
    unittest.main()
