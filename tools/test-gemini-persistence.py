#!/usr/bin/env python3
"""Reject false persistence evidence, including unrelated bind/overlay mounts."""
import copy
import importlib.util
from pathlib import Path
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
