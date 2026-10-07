#!/usr/bin/env python3
"""Reject false persistence evidence, including unrelated bind/overlay mounts."""
import copy
import importlib.util
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('persistence',Path(__file__).with_name('qualify-gemini-persistence.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
MOUNTS='''21 1 179:32 / /persist rw,nosuid,nodev - ext4 /dev/mmcblk0p32 rw
22 1 179:32 /home /home rw,nosuid,nodev - ext4 /dev/mmcblk0p32 rw
23 1 179:32 /nix/var /nix/var rw,nosuid,nodev - ext4 /dev/mmcblk0p32 rw
24 1 7:0 / /nix/.ro-store ro,nodev - squashfs /dev/loop0 ro
25 1 0:20 / /nix/store rw - overlay overlay rw,lowerdir=/mnt/nixos/nix/.ro-store,upperdir=/mnt/nixos/persist/nix/upper,workdir=/mnt/nixos/persist/nix/work
'''

class Persistence(unittest.TestCase):
    def test_standard_and_recovery_store_roots(self):
        system='/nix/store/'+'a'*32+'-nixos-system-gemini'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            store=root/'nix/store';store.mkdir(parents=True)
            state=root/'nix/var/nix';state.mkdir(parents=True)
            roots=state/'gcroots';roots.mkdir()
            persistent=root/'persist/nixos/nix/store'
            persistent.parent.mkdir(parents=True);persistent.symlink_to(store)
            standard=roots/'booted-system';standard.symlink_to('/run/booted-system')
            paths=('/persist/nixos/nix/store','/nix/var/nix','/nix/store')
            pattern='|'.join(re.escape(path) for path in paths)
            command=re.sub(pattern,lambda m: shlex.quote(str(root/m[0].lstrip('/'))),
                           p.store_state_check(system))
            def run(service_exit=1):
                return subprocess.run(['bash','-c',
                    f'set -eu; systemctl() {{ return {service_exit}; }}\n'+command],
                    capture_output=True,text=True).returncode
            self.assertEqual(run(),0) # Normal store needs no seed service.
            standard.unlink()
            self.assertNotEqual(run(),0)
            standard.symlink_to('/run/wrong-system')
            self.assertNotEqual(run(),0)
            standard.unlink();standard.symlink_to('/run/booted-system')
            persistent.unlink();persistent.mkdir()
            self.assertNotEqual(run(),0) # Unrelated store directory.

            (store/'.gemini-system').write_text(Path(system).name)
            (state/'gemini-seeded-system').write_text(Path(system).name)
            legacy=roots/'gemini-booted-system';legacy.symlink_to('/run/booted-system')
            standard.unlink()
            self.assertEqual(run(service_exit=0),0)
            self.assertNotEqual(run(service_exit=1),0)
            (state/'gemini-seeded-system').write_text('wrong-system')
            self.assertNotEqual(run(service_exit=0),0)
            (state/'gemini-seeded-system').write_text(Path(system).name)
            legacy.unlink()
            self.assertNotEqual(run(service_exit=0),0)

    def test_registered_store_binds_and_readonly_protection(self):
        raw='''21 1 179:32 / /persist rw,nosuid,nodev - ext4 /dev/mmcblk0p32 rw
22 1 179:32 /home /home rw,nosuid,nodev - ext4 /dev/mmcblk0p32 rw
23 1 179:32 /nixos/nix/var /nix/var rw,nosuid,nodev - ext4 /dev/mmcblk0p32 rw
25 1 179:32 /nixos/nix/store /nix/store rw,nosuid,nodev - ext4 /dev/mmcblk0p32 rw
26 25 179:32 /nixos/nix/store /nix/store ro,nosuid,nodev - ext4 /dev/mmcblk0p32 rw
'''
        self.assertEqual(len(p.verify_mounts(raw,'179:32')),4)
        for old,new in [('/nixos/nix/var','/nix/var'),('/nixos/nix/store','/nix/upper'),
                        ('/nix/store ro,','/nix/store rw,'),('26 25 179:32','26 25 179:33')]:
            with self.subTest(new=new),self.assertRaises(RuntimeError):
                p.verify_mounts(raw.replace(old,new),'179:32')

    def test_actual_stage1_layout(self):
        self.assertEqual(len(p.verify_mounts(MOUNTS,'179:32')),5)
        p.verify_mounts(MOUNTS.replace('/mnt/nixos',''),'179:32')
    def test_nixos_store_bind_and_unrelated_overmount(self):
        bind=MOUNTS.splitlines()[-1].replace('25 1','26 25').replace('/nix/store rw','/nix/store ro')+'\n'
        p.verify_mounts(MOUNTS+bind,'179:32')
        p.verify_mounts(MOUNTS+bind.replace('/nix/store ro','/nix/store rw'),'179:32')
        for bad in (bind.replace('26 25','26 1'),bind.replace('0:20','0:21'),
                    bind.replace('upperdir=/mnt/nixos/persist/nix/upper','upperdir=/tmp'),bind+bind):
            with self.subTest(bad=bad),self.assertRaises(RuntimeError):p.verify_mounts(MOUNTS+bad,'179:32')
    def test_wrong_device_bind_root_and_readonly_refused(self):
        for old,new in [('179:32','179:29'),('/home /home','/other /home'),
                        ('/nix/var /nix/var','/ /nix/var'),
                        ('/persist rw,','/persist ro,'),
                        ('/dev/mmcblk0p32','/dev/mmcblk0p29')]:
            with self.subTest(new=new),self.assertRaises(RuntimeError):
                p.verify_mounts(MOUNTS.replace(old,new),'179:32')
    def test_missing_stacked_or_wrong_overlay_refused(self):
        for raw in (MOUNTS.split('\n',1)[1],MOUNTS+MOUNTS.splitlines()[0],
                    MOUNTS.replace('upperdir=/mnt/nixos/persist/nix/upper','upperdir=/tmp'),
                    MOUNTS.replace('lowerdir=/mnt/nixos/nix/.ro-store','lowerdir=/tmp'),
                    MOUNTS.replace('/nix/.ro-store ro,','/nix/.ro-store rw,')):
            with self.subTest(raw=raw),self.assertRaises(RuntimeError):p.verify_mounts(raw,'179:32')
    def test_content_and_database_survive(self):
        token='a'*32
        expected=dict(content_sha256='b'*64,output='/nix/store/'+'c'*32+'-gemini-persistence-'+token,
                      nix_hash='sha256:'+'d'*52,
                      deriver='/nix/store/'+'e'*32+'-gemini-persistence-'+token+'.drv')
        observed=dict(home_sha256='b'*64,output_sha256='b'*64,
                      nix_hash=expected['nix_hash'],deriver=expected['deriver'])
        p.verify_content(expected,observed)
        for key in observed:
            bad=copy.deepcopy(observed);bad[key]='changed'
            with self.subTest(key=key),self.assertRaises(RuntimeError):p.verify_content(expected,bad)

if __name__=='__main__':unittest.main()
