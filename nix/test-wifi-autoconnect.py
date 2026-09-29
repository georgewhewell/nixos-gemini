#!/usr/bin/env python3
"""Saved-profile admission and owned-process lifecycle, without radio access."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('wifi', Path(__file__).with_name('wifi-autoconnect.py'))
wifi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wifi)


def scan(ssid=b'test', bssid=b'02:00:00:00:00:01', signal=b'-45.00', frequency=b'2412',
         suites=b'PSK', capabilities=b'16-PTKSA-RC 1-GTKSA-RC (0x000c)'):
    return (b'BSS ' + bssid + b'(on wlan0)\n\tfreq: ' + frequency + b'\n\tsignal: ' + signal
            + b' dBm\n\tSSID: ' + ssid + b'\n\tRSN:\t * Version: 1\n'
            b'\t\t * Group cipher: CCMP\n\t\t * Pairwise ciphers: CCMP\n'
            b'\t\t * Authentication suites: ' + suites + b'\n'
            b'\t\t * Capabilities: ' + capabilities + b'\n\tHT capabilities:\n')


class Profiles(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def profile(self, name='one', password='password', extra='', ssid='74657374'):
        path = self.root / name
        path.write_text('[wifi_test_managed_psk]\nName=test\nSSID=' + ssid + '\n'
                        'Favorite=true\nAutoConnect=true\nPassphrase=' + password + '\n' + extra)
        return path

    def test_derived_and_raw_key(self):
        expected = hashlib.pbkdf2_hmac('sha1', b'password', b'test', 4096, 32).hex()
        self.assertEqual(wifi.read_profile(self.profile()), (b'test', expected, b'password'))
        self.assertEqual(wifi.read_profile(self.profile(password='A' * 64)), (b'test', 'a' * 64, None))

    def test_keyfile_escapes_and_non_ascii_ssid(self):
        path = self.profile(password=r'pass\sword\\x', ssid='00ff5c22')
        ssid, key, _ = wifi.read_profile(path)
        self.assertEqual(ssid, b'\x00\xff\\"')
        self.assertEqual(key, hashlib.pbkdf2_hmac('sha1', b'pass word\\x', ssid, 4096, 32).hex())
        for password in ('short', 'z' * 64, r'password\q', 'password\\'):
            with self.assertRaises(ValueError):
                wifi.read_profile(self.profile(password=password))

    def test_unique_identity_and_credential(self):
        first, duplicate = self.profile(), self.profile('two')
        candidates = wifi.scan_candidates(scan() + scan(bssid=b'02:00:00:00:00:02', signal=b'-30.00'))
        self.assertEqual(wifi.choose_network([first, duplicate], candidates)[2], '02:00:00:00:00:02')
        duplicate = self.profile('two', password='different')
        with self.assertRaises(wifi.Unavailable):
            wifi.choose_network([first, duplicate], candidates)
        with self.assertRaises(wifi.Unavailable):
            wifi.choose_network([first], [])
        first.write_text(first.read_text().replace('AutoConnect=true', 'AutoConnect=false'))
        with self.assertRaises(wifi.Unavailable):
            wifi.choose_network([first], candidates)

    def test_bad_profile_never_selected(self):
        for content in ('[one]\n[two]\n', '[one]\nSSID=x\nSSID=x\n', '[one]\nFavorite=true\nAutoConnect=true\nSSID=zz\n', 'not a keyfile'):
            path = self.root / 'bad'
            path.write_text(content)
            with self.assertRaises(wifi.Unavailable):
                wifi.choose_network([path], wifi.scan_candidates(scan()))

    def test_scan_security_and_band(self):
        self.assertEqual(len(wifi.scan_candidates(scan())), 1)
        for raw in (scan(frequency=b'5180'), scan(frequency=b'2413'),
                    scan().replace(b'Group cipher: CCMP', b'Group cipher: TKIP'),
                    scan().replace(b'Pairwise ciphers: CCMP', b'Pairwise ciphers: TKIP'),
                    scan().replace(b'Pairwise ciphers: CCMP', b'Pairwise ciphers: CCMP-256'),
                    scan().replace(b'Authentication suites: PSK', b'Authentication suites: FT/PSK'),
                    scan().replace(b'Authentication suites: PSK', b'Authentication suites: SAE'),
                    scan().replace(b'(0x000c)', b'MFP-required (0x0040)'),
                    scan(ssid=b'\\xzz'), scan(bssid=b'bad')):
            self.assertEqual(wifi.scan_candidates(raw), [])
        self.assertEqual(wifi.scan_candidates(scan(ssid=b'a\\x00\\xff\\x5c'))[0][0], b'a\x00\xff\\')

    def test_configuration_no_plaintext_or_injection(self):
        ssid, psk, _ = wifi.read_profile(self.profile(password='password'))
        text = wifi.configuration(ssid, psk, '02:00:00:00:00:01', '/run/gemini-wifi/ctrl')
        self.assertNotIn('password', text)
        self.assertIn('ssid=74657374', text)
        self.assertIn('ap_scan=2', text)
        self.assertIn('ieee80211w=0', text)
        for bad in ('02:00:00:00:00:01\nnetwork={', 'xx:00:00:00:00:01'):
            with self.assertRaises(ValueError):
                wifi.configuration(ssid, psk, bad, '/run/gemini-wifi/ctrl')


class Sae(unittest.TestCase):
    """GEMINI_WIFI_SAE=prefer: WPA3-SAE with PMF when the AP offers SAE."""
    profile = Profiles.profile

    def setUp(self):
        Profiles.setUp(self)
        patcher = mock.patch.object(wifi, 'SAE', True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_is_wpa2_only(self):
        with mock.patch.object(wifi, 'SAE', False):
            self.assertEqual(wifi.scan_candidates(scan(suites=b'SAE')), [])
            chosen = wifi.choose_network([self.profile()], wifi.scan_candidates(scan(suites=b'PSK SAE')))
            self.assertFalse(chosen[3])

    def test_transition_and_wpa3_only(self):
        for suites, caps in ((b'PSK SAE', b'MFP-capable (0x008c)'), (b'SAE', b'MFP-required MFP-capable (0x00cc)')):
            candidates = wifi.scan_candidates(scan(suites=suites, capabilities=caps))
            self.assertEqual(len(candidates), 1)
            ssid, secret, bssid, sae = wifi.choose_network([self.profile()], candidates)
            self.assertTrue(sae)
            self.assertEqual(secret, b'password')
            text = wifi.configuration(ssid, secret, bssid, '/run/gemini-wifi/ctrl', sae)
            for line in ('key_mgmt=SAE', 'ieee80211w=2', 'sae_pwe=2', 'group_mgmt=AES-128-CMAC',
                         'sae_password=' + b'password'.hex(), 'ap_scan=1'):
                self.assertIn(line, text)
            self.assertNotIn('password\n', text)
            self.assertNotIn('psk=', text)

    def test_raw_psk_profile_falls_back_or_fails(self):
        raw = self.profile(password='A' * 64)
        self.assertFalse(wifi.choose_network([raw], wifi.scan_candidates(scan(suites=b'PSK SAE')))[3])
        with self.assertRaises(wifi.Unavailable):
            wifi.choose_network([raw], wifi.scan_candidates(scan(suites=b'SAE')))

    def test_sae_configuration_rejects_bad_input(self):
        for secret in (b'short', b'x' * 64, 'a' * 64):
            with self.assertRaises(ValueError):
                wifi.configuration(b'test', secret, '02:00:00:00:00:01', '/run/gemini-wifi/ctrl', True)
        with self.assertRaises(ValueError):
            wifi.configuration(b'test', b'password', '02:00:00:00:00:01', '/run/gemini-wifi/ctrl')


class Lifecycle(unittest.TestCase):
    def test_stop_owned_child_and_reap(self):
        child = mock.Mock()
        child.poll.return_value = None
        wifi.stop_child(child)
        child.terminate.assert_called_once()
        child.wait.assert_called_once_with(timeout=8)
        child.kill.assert_not_called()
        child.reset_mock()
        child.wait.side_effect = [subprocess.TimeoutExpired('private', 8), 0]
        wifi.stop_child(child)
        child.kill.assert_called_once()
        self.assertEqual(child.wait.call_count, 2)

    def test_status_never_returns_private_fields(self):
        with mock.patch.object(wifi, 'run', return_value=b'ssid=private\nbssid=private\nwpa_state=COMPLETED\n'):
            self.assertEqual(wifi.status('wlan0'), 'COMPLETED')
        with mock.patch.object(wifi, 'run', side_effect=subprocess.TimeoutExpired('status', 3)):
            self.assertEqual(wifi.status('wlan0'), '')

    def test_connect_cancel_and_failure_cleanup(self):
        for sequence in ([False, True], [False]):
            with tempfile.TemporaryDirectory() as temporary:
                child = mock.Mock()
                child.poll.return_value = None if len(sequence) == 2 else 1
                with (mock.patch.object(wifi, 'WORK', Path(temporary)),
                      mock.patch.object(wifi, 'STOP') as stop,
                      mock.patch.object(wifi, 'run', return_value=scan()),
                      mock.patch.object(wifi, 'choose_network', return_value=(b'test', 'a' * 64, '02:00:00:00:00:01', False)),
                      mock.patch.object(wifi, 'status', return_value='COMPLETED'),
                      mock.patch.object(wifi.subprocess, 'Popen', return_value=child) as popen):
                    stop.wait.side_effect = sequence
                    if len(sequence) == 2:
                        wifi.connect('wlan0')
                        child.terminate.assert_called_once()
                    else:
                        with self.assertRaises(wifi.Unavailable):
                            wifi.connect('wlan0')
                    self.assertFalse((Path(temporary) / 'wpa.conf').exists())
                    self.assertFalse((Path(temporary) / 'pid').exists())
                    self.assertNotIn('-B', popen.call_args.args[0])
                    self.assertNotIn('a' * 64, ' '.join(popen.call_args.args[0]))


if __name__ == '__main__':
    unittest.main()
