#!/usr/bin/env python3
"""Check archive admission, upload ownership and published-file evidence."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
spec=importlib.util.spec_from_file_location('files',Path(__file__).with_name('qualify-efi-files.py'))
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
class Files(unittest.TestCase):
    def setUp(self):
        self.before={'boot_id':'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','gpt_sha256':'b'*64}
    def test_pinned_archive_and_member_hashes(self):
        archive,manifest=f.payload();self.assertEqual(archive.stat().st_size,f.ARCHIVE_SIZE)
        self.assertEqual(len(manifest['files']),5)
        with patch.object(f,'ARCHIVE_SHA','0'*64),self.assertRaises(RuntimeError):f.payload()
    def test_upload_is_exclusive_ram_only_and_checks_identities(self):
        cmd=f.upload_command(self.before,'c'*64)
        self.assertIn('(set -C; cat > /run/efi-boot-files.upload)',cmd)
        self.assertIn('*,ro,*)',cmd);self.assertIn('gemini,uefi-storage-result',cmd)
        self.assertNotIn('mount -',cmd);self.assertNotIn('> /mnt/gemian',cmd)
        for key in self.before:
            with self.assertRaises(ValueError):f.upload_command(dict(self.before,**{key:'$(false)'}),'c'*64)
        with self.assertRaises(ValueError):f.upload_command(self.before,'d'*63)
    def test_wrong_request_and_rescue_prevent_upload(self):
        q=SimpleNamespace(run=Mock(return_value='efi-files=required wrong'))
        with tempfile.TemporaryDirectory() as d,patch.object(f.subprocess,'run') as upload:
            with self.assertRaises(RuntimeError):f.provision([],self.before,'c'*64,Path(d),q,lambda:False)
            upload.assert_not_called()
            with self.assertRaises(RuntimeError):f.provision([],self.before,'c'*64,Path(d),q,lambda:True)
            upload.assert_not_called()
    def test_verified_publication_skips_upload(self):
        q=SimpleNamespace(run=Mock(return_value=f.marker('verified')))
        with tempfile.TemporaryDirectory() as d,patch.object(f.subprocess,'run') as upload:
            f.provision([],self.before,'c'*64,Path(d),q,lambda:False);upload.assert_not_called()
    def test_readback_rejects_other_boot_missing_or_wrong_file(self):
        _,manifest=f.payload();boot='dddddddd-dddd-dddd-dddd-dddddddddddd'
        rows=['boot_id='+boot]+[v['sha256']+'  /gemian/'+k for k,v in manifest['files'].items()]
        q=SimpleNamespace(run=Mock(return_value='\n'.join(rows)),save=Mock())
        f.evidence([],boot,Path('/unused'),q);q.save.assert_called_once()
        for changed in (['boot_id='+self.before['boot_id']]+rows[1:],rows[:-1],rows[:-1]+['0'*64+rows[-1][64:]]):
            q.run.return_value='\n'.join(changed)
            with self.assertRaises(RuntimeError):f.evidence([],boot,Path('/unused'),q)
if __name__=='__main__':unittest.main()
