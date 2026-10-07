#!/usr/bin/env python3
"""Exercise generation installation and failure recovery without a block device."""
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('installer', Path(__file__).resolve().parents[1]/'nix/gemini-boot-install.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def info(data):
    return dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())


class Volume:
    """Record mount transitions; publication still uses the real filesystem."""
    def __init__(self, path):
        self.path, self.rw, self.writes = path, False, 0

    def require(self, writable=False):
        if self.rw != writable:
            raise RuntimeError('Unexpected mount state')

    @contextmanager
    def writable(self):
        self.require()
        self.writes += 1
        self.rw = True
        try:
            yield
        finally:
            self.rw = False


class Installation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.package, self.target = self.base/'package', self.base/'target'
        self.package.mkdir(); self.target.mkdir()
        self.volume = Volume(self.target)
        original_temporary = tempfile.TemporaryDirectory
        patch = mock.patch.object(m.tempfile, 'TemporaryDirectory',
                                  side_effect=lambda **kw: original_temporary(**dict(kw, dir=self.base)))
        patch.start(); self.addCleanup(patch.stop)
        self.store = self.base/'system.squashfs'
        self.store.write_bytes(b'new system store')
        identity = 'a'*64
        directory = 'EFI/Gemini/'+identity
        entry = 'gemini-'+identity+'.conf'
        self.files = {
            m.MANAGER: b'new manager', directory+'/linux.efi': b'linux',
            directory+'/initrd.cpio.gz': b'initrd', directory+'/gemini.dtb': b'dtb',
            'loader/entries/'+entry: (f'title NixOS Gemini\nlinux /{directory}/linux.efi\n'
                                    f'initrd /{directory}/initrd.cpio.gz\ndevicetree /{directory}/gemini.dtb\n').encode(),
            m.CONFIG: ('default '+entry+'\ntimeout 8\n').encode(),
        }
        self.manifest = dict(payload_identity=identity, entry=entry,
                             store=dict(info(self.store.read_bytes()), system='/nix/store/'+'b'*32+'-system'))
        self.manifest['store']['file'] = 'mainline-nixos-'+self.manifest['store']['sha256']+'.squashfs'
        self.build_package()
        for name, data in {m.MANAGER: b'old manager', m.CONFIG: b'default old.conf\n',
                           'loader/entries/old.conf': b'old entry', 'nixos/old.squashfs': b'old store'}.items():
            path = self.target/name
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        self.old = self.snapshot()

    def build_package(self):
        self.manifest['files'] = {name: info(data) for name, data in self.files.items()}
        with tarfile.open(self.package/'boot-files.tar', 'w') as archive:
            for name, data in self.files.items():
                member = tarfile.TarInfo(name); member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        self.manifest['archive'] = info((self.package/'boot-files.tar').read_bytes())
        (self.package/'manifest.json').write_text(json.dumps(self.manifest))
        (self.package/'files.manifest').write_text(''.join(
            f"{info(data)['sha256']} {len(data)} {name}\n" for name, data in self.files.items()))

    def snapshot(self):
        return {str(p.relative_to(self.target)): p.read_bytes() for p in self.target.rglob('*') if p.is_file()}

    def install(self, **kw):
        return m.install(self.package, self.volume, **dict(store_image=self.store, **kw))

    def test_install_and_retry_preserve_older_generation(self):
        result = self.install()
        self.assertTrue(result['changed']); self.assertTrue(result['read_only'])
        self.assertFalse(self.volume.rw); self.assertEqual(self.volume.writes, 1)
        self.assertEqual((self.target/'nixos'/self.manifest['store']['file']).read_bytes(), self.store.read_bytes())
        for name, data in self.old.items():
            path = self.target/name
            if name in (m.CONFIG, m.MANAGER):
                path = path.with_name(path.name+'.gemini-backup-'+info(data)['sha256'])
            self.assertEqual(path.read_bytes(), data)
        for name, data in self.files.items():
            self.assertEqual((self.target/name).read_bytes(), data)
        before = self.snapshot()
        self.assertFalse(self.install()['changed'])
        self.assertFalse(self.install(check=True)['changed'])
        self.assertEqual(before, self.snapshot()); self.assertEqual(self.volume.writes, 1)

    def test_missing_or_changed_store_rejected_before_remount(self):
        for source in (None, self.store):
            if source: source.write_bytes(b'wrong store')
            with self.assertRaises(ValueError): m.install(self.package, self.volume, source)
            self.assertEqual(self.old, self.snapshot()); self.assertEqual(self.volume.writes, 0)

    def test_wrong_existing_payload_and_store_preserved(self):
        for name in ('nixos/'+self.manifest['store']['file'], next(n for n in self.files if n.endswith('linux.efi'))):
            with self.subTest(name=name):
                path = self.target/name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'owner file'); before = self.snapshot()
                with self.assertRaisesRegex(ValueError, 'differs'): self.install()
                self.assertEqual(before, self.snapshot()); self.assertEqual(self.volume.writes, 0)
                path.unlink()

    def test_bad_archive_and_cross_generation_entry_rejected_before_remount(self):
        with (self.package/'boot-files.tar').open('ab') as stream: stream.write(b'corruption')
        with self.assertRaisesRegex(ValueError, 'archive content'): self.install()
        entry_name = 'loader/entries/'+self.manifest['entry']
        self.files[entry_name] = self.files[entry_name].replace(b'linux /EFI/', b'linux /another/')
        self.build_package()
        with self.assertRaisesRegex(ValueError, 'own payload'): self.install()
        self.assertEqual(self.old, self.snapshot()); self.assertEqual(self.volume.writes, 0)

    def test_symlink_destination_rejected_before_remount(self):
        outside = self.base/'outside'; outside.mkdir()
        (self.target/'EFI/Gemini').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlink'): self.install()
        self.assertEqual(list(outside.iterdir()), []); self.assertEqual(self.volume.writes, 0)

    def test_insufficient_space_preserves_generations(self):
        with mock.patch.object(m.shutil, 'disk_usage', return_value=SimpleNamespace(free=1)):
            with self.assertRaisesRegex(RuntimeError, 'space'): self.install()
        self.assertEqual(self.old, self.snapshot()); self.assertEqual(self.volume.writes, 0)

    def test_interrupted_store_copy_restores_readonly_and_cleans_owned_file(self):
        real_copy = m.shutil.copyfileobj
        def copy(src, dst, *args):
            if src.name == str(self.store):
                dst.write(b'partial'); raise OSError('copy failed')
            return real_copy(src, dst, *args)
        with mock.patch.object(m.shutil, 'copyfileobj', side_effect=copy):
            with self.assertRaisesRegex(OSError, 'copy failed'): self.install()
        self.assertFalse(self.volume.rw); self.assertEqual(self.old, self.snapshot())
        self.assertFalse(list((self.target/'nixos').glob('.gemini-store-*')))
        self.assertTrue(self.install()['changed'])

    def test_failed_publication_restores_readonly_and_keeps_default(self):
        with mock.patch.object(m, 'publish', side_effect=subprocess.CalledProcessError(1, 'publisher')):
            with self.assertRaises(subprocess.CalledProcessError): self.install()
        self.assertFalse(self.volume.rw)
        self.assertEqual((self.target/m.CONFIG).read_bytes(), self.old[m.CONFIG])
        self.assertTrue(self.install()['changed'])

    def test_check_does_not_write_or_select_entry(self):
        with self.assertRaisesRegex(RuntimeError, 'not installed'): self.install(check=True)
        self.assertEqual(self.old, self.snapshot()); self.assertEqual(self.volume.writes, 0)


class MountRecovery(unittest.TestCase):
    def test_restores_readonly_after_each_failure_and_success(self):
        for failure in ('remount', 'verification', 'installation', None):
            with self.subTest(failure=failure):
                volume = m.BootVolume(Path('/gemian'))
                calls = []
                def run(command, **kw):
                    calls.append(command)
                    if failure == 'remount' and command[-2] == 'remount,rw':
                        raise subprocess.CalledProcessError(1, command)
                def require(writable=False):
                    if writable and failure == 'verification': raise RuntimeError('verification failed')
                with mock.patch.object(volume, 'require', side_effect=require), \
                        mock.patch.object(m.subprocess, 'run', side_effect=run), mock.patch.object(m.os, 'sync'):
                    def operation():
                        with volume.writable():
                            if failure == 'installation': raise RuntimeError('installation failed')
                    if failure:
                        with self.assertRaises((RuntimeError, subprocess.SubprocessError)): operation()
                    else: operation()
                self.assertEqual(calls[-1], ['mount', '-o', 'remount,ro', '/gemian'])

    def test_recovery_noload_mount_refuses_update(self):
        for option in ('noload', 'norecovery'):
            with mock.patch.object(Path, 'read_text', return_value=f'/dev/mmcblk0p29 /gemian ext4 ro,{option} 0 0\n'), \
                    mock.patch.object(Path, 'is_symlink', return_value=False):
                with self.assertRaisesRegex(RuntimeError, 'journal enabled'): m.BootVolume(Path('/gemian')).require()


class Generations(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.target = self.base/'boot'; self.target.mkdir()
        self.volume = Volume(self.target)
        self.roots = self.base/'gcroots'
        self.profiles = self.base/'profiles'; self.profiles.mkdir()
        original_temporary = tempfile.TemporaryDirectory
        patches = [
            mock.patch.object(m, 'GENERATION_ROOTS', self.roots),
            mock.patch.object(m, 'SYSTEM_PROFILES', self.profiles),
            mock.patch.object(m, 'SYSTEM_PATH', re.escape(str(self.base))+r'/[0-9a-z]{32}-system'),
            mock.patch.object(m.tempfile, 'TemporaryDirectory',
                              side_effect=lambda **kw: original_temporary(**dict(kw, dir=self.base))),
        ]
        real_run = subprocess.run
        self.validated = []
        def run(command, **kw):
            if command[:2] == ['nix-store', '--check-validity']:
                self.validated.append(command[2]); return None
            return real_run(command, **kw)
        patches.append(mock.patch.object(m.subprocess, 'run', side_effect=run))
        for patch in patches:
            patch.start(); self.addCleanup(patch.stop)
        pe = bytearray(256); pe[:2] = b'MZ'
        struct.pack_into('<I', pe, 0x3c, 64); pe[64:68] = b'PE\0\0'
        for offset, value in ((68, 0xaa64), (88, 0x20b), (156, 10)):
            struct.pack_into('<H', pe, offset, value)
        self.manager = self.base/'manager'; self.manager.write_bytes(pe)
        self.systems = []
        for index in (1, 2, 3):
            system = self.base/(str(index)*32+'-system'); system.mkdir()
            (system/'kernel').write_bytes(pe)
            (system/'initrd').write_bytes(b'shared generic initramfs')
            (system/'init').write_text('init')
            (system/'kernel-params').write_text('console=tty0 rdinit=/init\n')
            subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(system/'gemini.dtb')],
                           input='/dts-v1/; / { chosen {}; };', text=True, check=True)
            (self.profiles/f'system-{index}-link').symlink_to(system)
            self.systems.append(system)
        recovery = self.target/'loader/entries/recovery.conf'
        recovery.parent.mkdir(parents=True); recovery.write_text('title Recovery\n')

    def install(self, index=0, **kw):
        return m.install(self.systems[index], self.volume, system=True, manager=self.manager, **kw)

    def test_update_and_rollback_use_the_selected_system_without_a_store_image(self):
        old = self.install(); new = self.install(1)
        self.assertNotEqual(old['entry'], new['entry'])
        self.assertFalse((self.target/'nixos').exists())
        for result in (old, new):
            text = (self.target/'loader/entries'/result['entry']).read_text()
            self.assertIn('init='+result['system']+'/init\n', text)
            self.assertEqual(os.readlink(self.roots/result['entry']), result['system'])
        self.assertEqual(self.validated, list(map(str, self.systems[:2])))
        rollback = self.install()
        self.assertEqual(rollback['entry'], old['entry'])
        self.assertFalse(self.install(check=True)['changed'])
        self.assertFalse(self.volume.rw)

    def test_removed_profile_collects_only_its_owned_entry_and_payload(self):
        old = self.install(); new = self.install(1)
        (self.profiles/'system-1-link').unlink()
        self.install(1)
        self.assertFalse((self.target/'loader/entries'/old['entry']).exists())
        self.assertFalse((self.target/'EFI/Gemini'/old['payload_identity']).exists())
        self.assertFalse((self.roots/old['entry']).exists())
        self.assertTrue((self.roots/new['entry']).is_symlink())
        self.assertTrue((self.target/'loader/entries/recovery.conf').exists())

    def test_bad_image_or_conflicting_init_cannot_change_the_default(self):
        self.install()
        previous = (self.target/m.CONFIG).read_bytes()
        (self.systems[1]/'kernel-params').write_text('init=/wrong/init\n')
        with self.assertRaisesRegex(ValueError, 'override NixOS init'): self.install(1)
        (self.systems[1]/'kernel-params').write_text('console=tty0\n')
        (self.systems[1]/'kernel').write_bytes(b'not an EFI image')
        with self.assertRaisesRegex(ValueError, 'not PE'): self.install(1)
        self.assertEqual(previous, (self.target/m.CONFIG).read_bytes())
        self.assertFalse(self.volume.rw)

    def test_full_volume_reclaims_obsolete_payload_before_installation(self):
        old = self.install(); current = self.install(1)
        (self.profiles/'system-1-link').unlink()
        old_payload = self.target/'EFI/Gemini'/old['payload_identity']
        def available(_):
            return SimpleNamespace(free=1 if old_payload.exists() else 64 * 1024 * 1024)
        with mock.patch.object(m.shutil, 'disk_usage', side_effect=available):
            new = self.install(2)
        self.assertFalse(old_payload.exists())
        self.assertFalse((self.roots/old['entry']).is_symlink())
        self.assertTrue((self.target/'loader/entries'/current['entry']).is_file())
        self.assertIn(new['entry'], (self.target/m.CONFIG).read_text())
        self.assertFalse(self.volume.rw)

    def test_full_volume_keeps_current_default_without_its_profile(self):
        current = self.install()
        (self.profiles/'system-1-link').unlink()
        previous = (self.target/m.CONFIG).read_bytes()
        with mock.patch.object(m.shutil, 'disk_usage', return_value=SimpleNamespace(free=1)):
            with self.assertRaisesRegex(RuntimeError, 'space'): self.install(1)
        self.assertEqual(previous, (self.target/m.CONFIG).read_bytes())
        self.assertTrue((self.roots/current['entry']).is_symlink())
        self.assertTrue((self.target/'EFI/Gemini'/current['payload_identity']/'linux.efi').is_file())
        self.assertFalse(self.volume.rw)

    def test_failed_publication_after_cleanup_preserves_current_default(self):
        old = self.install(); current = self.install(1)
        (self.profiles/'system-1-link').unlink()
        (self.profiles/'system-2-link').unlink()
        old_payload = self.target/'EFI/Gemini'/old['payload_identity']
        previous = (self.target/m.CONFIG).read_bytes()
        def available(_):
            return SimpleNamespace(free=1 if old_payload.exists() else 64 * 1024 * 1024)
        with mock.patch.object(m.shutil, 'disk_usage', side_effect=available), \
                mock.patch.object(m, 'publish', side_effect=subprocess.CalledProcessError(1, 'publisher')):
            with self.assertRaises(subprocess.CalledProcessError): self.install(2)
        self.assertFalse(old_payload.exists())
        self.assertEqual(previous, (self.target/m.CONFIG).read_bytes())
        self.assertTrue((self.target/'loader/entries'/current['entry']).is_file())
        self.assertTrue((self.roots/current['entry']).is_symlink())
        self.assertTrue((self.target/'EFI/Gemini'/current['payload_identity']/'linux.efi').is_file())
        self.assertFalse(self.volume.rw)


if __name__ == '__main__':
    unittest.main()
