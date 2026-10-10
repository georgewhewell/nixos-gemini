#!/usr/bin/env python3
"""Check credential privacy, byte-exact SSIDs and preservation of user edits."""
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'profiles', Path(__file__).with_name('networkmanager-import-wifi.py'))
profiles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profiles)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.source, self.destination = root / 'connman', root / 'profiles'

    def profile(self, name, ssid='546573742057694669', secret='Secret123', automatic='true'):
        path = self.source / f'wifi_{name}_managed_psk' / 'settings'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'[wifi_{name}]\nFavorite=true\nAutoConnect={automatic}\n'
                        f'SSID={ssid}\nPassphrase={secret}\n')
        return path

    def run_import(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            profiles.import_profiles(self.source, self.destination)
        return output.getvalue()

    def test_private_credentials_and_byte_exact_ssid(self):
        self.profile('valid', ssid='ff005c3b20', secret=r'Secret\s123')
        log = self.run_import()
        output, = self.destination.glob('*.nmconnection')
        text = output.read_text()
        psk = hashlib.pbkdf2_hmac('sha1', b'Secret 123', bytes.fromhex('ff005c3b20'), 4096, 32).hex()
        self.assertIn('ssid=255;0;92;59;32;', text)
        self.assertIn(f'psk={psk}\n', text)
        self.assertIn('[ipv6]\nmethod=auto', text)
        self.assertNotIn('Secret', log + text)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)

    def test_repeat_import_preserves_desktop_edits_and_source(self):
        source = self.profile('valid')
        original = source.read_bytes()
        self.run_import()
        self.assertEqual(source.read_bytes(), original)
        output, = self.destination.glob('*.nmconnection')
        output.write_text('edited in GNOME\n')
        self.profile('valid', secret='Replacement123')
        self.assertIn('Imported 0', self.run_import())
        self.assertEqual(output.read_text(), 'edited in GNOME\n')
        self.assertIn('Replacement123', source.read_text())
        self.assertIn(b'Secret123', original)

    def test_rejects_manual_malformed_and_oversized_profiles_without_secrets(self):
        self.profile('manual', automatic='false')
        self.profile('bad_ssid', ssid='private-network')
        self.profile('bad_escape', secret=r'Secret\q123')
        self.profile('short_secret', secret='secret')
        self.profile('trailing_escape', secret='Secret123\\')
        oversized = self.profile('large')
        oversized.write_text('PrivatePayload' * 6000)
        log = self.run_import()
        self.assertEqual(list(self.destination.glob('*.nmconnection')), [])
        self.assertNotIn('Secret', log)
        self.assertNotIn('PrivatePayload', log)

    def test_raw_psk_is_not_hashed_again(self):
        self.profile('raw', secret='AB' * 32)
        self.run_import()
        output, = self.destination.glob('*.nmconnection')
        self.assertIn('psk=' + 'ab' * 32, output.read_text())


if __name__ == '__main__':
    unittest.main()
