#!/usr/bin/env python3
"""Reject stale maps, fixture reports, wrong locales and crossed Linux profiles."""
import importlib.util
from pathlib import Path
import tempfile
from unittest import mock
import unittest

spec = importlib.util.spec_from_file_location('recovery', Path(__file__).with_name('qualify-uboot-recovery.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
d = r.desktop_keyboard


class DesktopKeyboard(unittest.TestCase):
    good = ('keymap=gemian-us-v1 combinations=416 modifiers=5 caps-toggle=passed\n'
            'compose=passed accents=8 locale=C.UTF-8\n'
            'desktop-keyboard=passed mode=device seat=seat0 physical-key-press=unobserved\n')

    def test_complete_report_required_and_fixture_never_device_evidence(self):
        d.verify_report(self.good)
        invalid = ['', self.good.splitlines()[0], self.good + 'extra\n']
        invalid += [self.good.replace(a, b) for a, b in (
            ('416', '415'), ('modifiers=5', 'modifiers=0'), ('accents=8', 'accents=7'),
            ('C.UTF-8', 'C'), ('mode=device', 'mode=headless-fixture'),
            ('seat=seat0', 'seat=gemini-keymap-fixture'), ('unobserved', 'passed'))]
        for report in invalid:
            with self.subTest(report=report), self.assertRaises(RuntimeError):
                d.verify_report(report)

    def test_live_locale_and_xkb_root_are_required_without_overrides(self):
        good = 'LANG=C.UTF-8\nLC_CTYPE=C.UTF-8\nXKB_CONFIG_ROOT=' + d.XKB_ROOT + '\n'
        d.verify_environment(good)
        for bad in (good.replace('LANG=C.UTF-8', 'LANG=C'), good + 'LC_ALL=C\n',
                    good + 'LANG=C.UTF-8\n', good.replace(d.XKB_ROOT, '/usr/share/X11/xkb'),
                    '\n'.join(good.splitlines()[:2])):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                d.verify_environment(bad)

    def test_direct_boot_cannot_claim_efi_or_reuse_the_previous_system(self):
        profile = 'desktop-keyboard'
        tree = {'memory/reg': 'same', 'reserved-memory/ccci/reg': 'same'}
        r.verify_handoff_tree(tree, tree, profile)
        for bad in (dict(tree, **{r.HANDOFF_MARKER: b'efi\0'.hex()}),
                    dict(tree, **{'memory/reg': 'changed'}),
                    dict(tree, **{r.KEYBOARD_LAYOUT: b'gemian-us-v1\0'.hex()})):
            with self.assertRaises(RuntimeError): r.verify_handoff_tree(tree, bad, profile)
        self.assertFalse(r.phase_evidence('0x474d10e0', '0x474d10ee', profile)['uboot_execution_proven'])
        self.assertEqual(r.candidate_system({'system': 'old'}, profile), d.SYSTEM)
        self.assertNotEqual(d.SYSTEM, r.persistent_nix.SYSTEM)
        p = r.store_profile_for(profile)
        self.assertEqual(p.system, d.SYSTEM)
        self.assertFalse(p.require_efi)
        self.assertEqual(p.sha, d.STORE_SHA)
        self.assertEqual(r.PROFILES[profile][1], d.BOOT_SHA)
        self.assertEqual(r.files_profile_for(profile), r.entry_dt.files_profile(r.efi_files))
        with self.assertRaises(ValueError): r.store_profile_for('baseline')

    def test_provisioning_retains_direct_boot_and_exact_store_admission(self):
        before = dict(boot_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', gpt_sha256='a' * 64)
        p = r.store_profile_for('desktop-keyboard')
        name = 'mainline-nixos-' + d.STORE_SHA + '.squashfs'
        command = r.efi_linux.upload_command(name, before, d.BOOT_SHA, p)
        self.assertIn('test ! -e /sys/firmware/efi', command)
        self.assertIn('test ! -e /sys/firmware/devicetree/base/chosen/gemini,uboot-handoff', command)
        self.assertIn('(set -C; cat > ', command)
        with self.assertRaises(ValueError):
            r.efi_linux.upload_command(name, before, d.BOOT_SHA, r.store_profile_for('persistent-nix'))

    def test_ordinary_build_checks_the_selected_system_before_building(self):
        class Captured(Exception): pass
        n = r.persistent_nix
        persistence = mock.Mock()
        persistence.run.side_effect = Captured
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(n, 'old_persistence') as old:
            kernel = Path(temporary)
            (kernel / 'kernel.config').write_text('CONFIG_NET_NS=y\n')
            with self.assertRaises(Captured):
                n.evidence([], 'boot', kernel, mock.Mock(), persistence, system=d.SYSTEM, kernel=kernel)
            self.assertEqual(old.call_args.args[-2], d.SYSTEM)
            command = persistence.run.call_args.args[1]
            self.assertIn('test "$(readlink /run/current-system)" = ' + d.SYSTEM, command)
            self.assertNotIn(n.SYSTEM, command)
            self.assertIn('test ! -e /sys/firmware/efi', command)
            with self.assertRaises(ValueError):
                n.evidence([], 'boot', kernel, mock.Mock(), persistence, system='$(false)', kernel=kernel)


if __name__ == '__main__':
    unittest.main()
