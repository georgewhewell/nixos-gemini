#!/usr/bin/env python3
"""Exercise actual GPT CRCs, preservation and filesystem extent failures."""
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest import mock
import uuid
import zlib

spec=importlib.util.spec_from_file_location('swap_plan',Path(__file__).with_name('plan-gemini-swap.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def fixture():
    table=bytearray(p.TABLE_SIZE)
    critical={22:('boot',362496,32768),29:('linux',6586368,82720768),
              30:('boot2',89307136,32768),31:('boot3',89339904,32768),
              32:('userdata',p.DATA_START,p.OLD_DATA_SIZE),33:('flashinfo',122109919,32768)}
    for number in range(1,34):
        off=(number-1)*128
        table[off:off+16]=uuid.UUID(int=100).bytes_le
        table[off+16:off+32]=uuid.UUID(int=number).bytes_le
        name,first,size=critical.get(number,(f'partition{number}',128+number*16,8))
        struct.pack_into('<QQQ',table,off+32,first,first+size-1,0x102 if number==32 else 0)
        encoded=name.encode('utf-16-le');table[off+56:off+56+len(encoded)]=encoded
    def image(backup):
        raw=bytearray(33*512 if backup else 32768)
        off=32*512 if backup else 512
        struct.pack_into('<8sIIIIQQQQ',raw,off,b'EFI PART',0x10000,92,0,0,
                         p.SECTORS-1 if backup else 1,1 if backup else p.SECTORS-1,34,p.SECTORS-34)
        raw[off+56:off+72]=uuid.UUID(int=200).bytes_le
        struct.pack_into('<QIII',raw,off+72,p.SECTORS-33 if backup else 2,128,128,0)
        # Nonzero surrounding bytes must survive too.
        if not backup:raw[:512]=b'M'*512;raw[34*512:]=b'P'*(32768-34*512)
        return p.rewrite(raw,table,backup)
    return image(False),image(True)


class FixedSwapPlan(unittest.TestCase):
    def setUp(self):
        self.primary,self.backup=fixture()
        self.extent=dict(uuid=p.DATA_UUID,block_count=2781184,block_size=4096)
        self.pin=mock.patch.object(p,'PRIMARY_SHA',p.sha(self.primary));self.pin.start();self.addCleanup(self.pin.stop)

    def plan(self, primary=None, backup=None, extent=None):
        return p.plan(self.primary if primary is None else primary,
                      self.backup if backup is None else backup,
                      self.extent if extent is None else extent)

    def test_exact_gpt_writes_preserve_all_other_entries_and_flashinfo_boundary(self):
        manifest,primary,backup=self.plan()
        self.assertEqual(len(primary),34*512)
        self.assertEqual(len(backup),33*512)
        self.assertEqual(manifest['writes'][1]['offset'],(122109919+32768)*512)
        complete=primary+self.primary[len(primary):]
        before=p.verify_pair(self.primary,self.backup)
        after=p.verify_pair(complete,backup)
        self.assertEqual(complete[:512],self.primary[:512])
        self.assertEqual(complete[34*512:],self.primary[34*512:])
        for n in range(128):
            if n not in (31,33):self.assertEqual(after[n*128:(n+1)*128],before[n*128:(n+1)*128])
        old=before[31*128:32*128];new=after[31*128:32*128]
        self.assertEqual(old[:40],new[:40]);self.assertEqual(old[48:],new[48:])
        self.assertEqual(p.geometry(new),('userdata',p.DATA_START,p.DATA_SIZE))
        swap=after[33*128:34*128]
        self.assertEqual(p.geometry(swap),('swap',p.SWAP_START,p.SWAP_SIZE))
        self.assertEqual(str(uuid.UUID(bytes_le=swap[16:32])),p.SWAP_GUID)
        self.assertEqual(manifest['rollback'][0]['sha256'],p.sha(self.primary[:34*512]))
        self.assertEqual(manifest['rollback'][1]['sha256'],p.sha(self.backup))
        self.assertFalse(manifest['device_writes_performed'])

    def test_oversize_filesystem_rejected_before_output(self):
        self.plan(extent=dict(self.extent,block_count=p.DATA_SIZE*512//4096))
        with self.assertRaisesRegex(ValueError,'filesystem would exceed'):
            self.plan(extent=dict(self.extent,block_count=p.DATA_SIZE*512//4096+1))
        for changed in ({'uuid':str(uuid.UUID(int=42))},{'block_count':True},
                        {'block_count':0},{'block_count':'2781184'},{'block_size':512}):
            with self.assertRaises(ValueError):self.plan(extent=dict(self.extent,**changed))

    def test_stale_or_damaged_captures_rejected(self):
        with self.assertRaises(ValueError):self.plan(primary=self.primary[:-1])
        with self.assertRaises(ValueError):self.plan(backup=self.backup[:-1])
        for off in (16,32*512+16):
            damaged=bytearray(self.backup);damaged[off]^=1
            with self.assertRaises(ValueError):self.plan(backup=bytes(damaged))
        table=bytearray(p.verify_pair(self.primary,self.backup));table[56]^=1
        stale=p.rewrite(self.backup,table,True)
        with self.assertRaisesRegex(ValueError,'disagree'):self.plan(backup=stale)
        foreign=bytearray(self.primary);foreign[0]^=1
        with self.assertRaisesRegex(ValueError,'factory baseline'):self.plan(primary=bytes(foreign))

    def test_changed_protected_geometry_and_foreign_p34_are_rejected(self):
        table=bytearray(p.verify_pair(self.primary,self.backup))
        for off in (32*128+32,33*128):
            changed=table.copy();changed[off]^=1
            primary=p.rewrite(self.primary,changed);backup=p.rewrite(self.backup,changed,True)
            with mock.patch.object(p,'PRIMARY_SHA',p.sha(primary)),self.assertRaises(ValueError):
                self.plan(primary,backup)

    def test_header_bounds_and_disk_identity_must_match(self):
        for offset in (32*512+32,32*512+56):
            changed=bytearray(self.backup);changed[offset]^=1
            struct.pack_into('<I',changed,32*512+16,0)
            struct.pack_into('<I',changed,32*512+16,zlib.crc32(changed[32*512:32*512+92]))
            with self.assertRaises(ValueError):self.plan(backup=bytes(changed))


if __name__=='__main__':unittest.main()
