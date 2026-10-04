#!/usr/bin/env python3
"""Exercise exact transition bounds, torn writes and same-session restoration."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

sys.path.insert(0, str(Path.cwd()))
from mtkclient.Library import gemini_fixed_swap as s
if __name__ == '__main__':
    from mtkclient.Library.DA.mtk_da_handler import DaHandler


class Transition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.factory = {'primary': b'P'*32768, 'backup': b'B'*(33*512), 'header': b'H'*4096}
        self.swap = {name: bytearray(raw) for name, raw in self.factory.items()}
        self.swap['primary'][5032:5040] = b'NEWBOUND'
        self.swap['backup'][4008:4016] = b'NEWBOUND'
        self.swap['header'][1036:1052] = b'NEW-SWAP-UUID!!!'
        self.swap = {name: bytes(raw) for name, raw in self.swap.items()}
        self.memory = {0: bytearray(self.factory['primary']), s.g.BACKUP_OFFSET: bytearray(self.factory['backup']),
                       s.b.SWAP_OFFSET: bytearray(self.factory['header'])}
        sb = bytearray(1024); struct.pack_into('<I', sb, 4, s.b.DATA_SIZE//4096)
        struct.pack_into('<I', sb, 24, 2); struct.pack_into('<HH', sb, 56, 0xef53, 1)
        sb[104:120] = uuid.UUID(s.b.DATA_UUID).bytes; self.memory[s.b.DATA_OFFSET+1024] = sb
        protected = []
        for i, (name, offset, _, digest) in enumerate(s.g.PROTECTED):
            raw = bytes([42+i])*4096; self.memory[offset] = bytearray(raw)
            protected.append((name, offset, len(raw), s.g.sha(raw) if digest else None))
        specs = []
        for layout, values in (('factory', self.factory), ('swap', self.swap)):
            for name, raw in values.items():
                if layout == 'swap' and name == 'primary': raw = raw[:34*512]
                filename = name+'-'+layout+'.bin'; (self.directory/filename).write_bytes(raw)
                specs.append((filename, len(raw), s.g.sha(raw)))
        for name in s.OUTPUTS: (self.directory/name).touch()
        for module, changes in ((s, {'INPUTS':tuple(specs), 'SWAP_PRIMARY_SHA':s.g.sha(self.swap['primary'])}),
                                 (s.g, {'PROTECTED':tuple(protected)})):
            for key, value in changes.items():
                patch=mock.patch.object(module,key,value);patch.start();self.addCleanup(patch.stop)
        self.calls=[];self.count=0;self.fail_at=None;self.fail_all=False;self.bad_readback=False
        self.loader=SimpleNamespace(readflash=self.read,writeflash=self.write,shutdown=mock.Mock(return_value=True),
            daconfig=SimpleNamespace(storage=SimpleNamespace(flashsize=s.g.FLASH_SIZE)))
        self.mtk=SimpleNamespace(config=SimpleNamespace(hwcode=0x279,pagesize=512),daloader=self.loader)

    def read(self, addr, length, filename, parttype, display):
        self.assertEqual((filename,parttype,display),('','user',False));self.calls.append(('read',addr,length))
        raw=bytes(self.memory[addr][:length])
        if self.bad_readback and self.count==1:
            self.bad_readback=False;return b'!'+raw[1:]
        return raw

    def write(self, addr, length, filename, parttype, wdata, display):
        self.assertEqual((filename,parttype,display),('','user',False))
        self.count+=1;self.calls.append(('write',addr,length))
        self.assertIn((addr,length),((0,34*512),(s.g.BACKUP_OFFSET,33*512),(s.b.SWAP_OFFSET,4096)))
        self.assertFalse(s.b.DATA_OFFSET <= addr < s.b.DATA_OFFSET+s.b.DATA_SIZE)
        self.memory[addr][:length]=wdata
        if self.fail_all or self.count==self.fail_at:
            self.memory[addr][0]^=1;return False
        return True

    def run_transition(self, restore=False):
        with contextlib.redirect_stdout(io.StringIO()):ok=s.transition(self.mtk,self.directory,restore)
        return ok,json.loads((self.directory/'swap-result.json').read_text())

    def assert_factory(self):
        for name,addr in (('primary',0),('backup',s.g.BACKUP_OFFSET),('header',s.b.SWAP_OFFSET)):
            self.assertEqual(bytes(self.memory[addr]),self.factory[name])

    def test_install_header_before_publishing_gpt_and_preserve_data_superblock(self):
        sb=bytes(self.memory[s.b.DATA_OFFSET+1024]);ok,result=self.run_transition();self.assertTrue(ok)
        self.assertEqual(result['final_layout'],'swap');self.assertFalse(result['rollback_attempted'])
        self.assertEqual([c[1:] for c in self.calls if c[0]=='write'],[(s.b.SWAP_OFFSET,4096),(s.g.BACKUP_OFFSET,33*512),(0,34*512)])
        self.assertEqual(bytes(self.memory[s.b.DATA_OFFSET+1024]),sb)
        self.loader.shutdown.assert_called_once_with(bootmode=1)

    def test_restore_accepts_installed_layout_and_restores_all_three_ranges(self):
        for name,addr in (('primary',0),('backup',s.g.BACKUP_OFFSET),('header',s.b.SWAP_OFFSET)):
            self.memory[addr][:]=self.swap[name]
        ok,result=self.run_transition(True);self.assertTrue(ok);self.assert_factory()
        self.assertEqual(result['final_layout'],'factory')
        self.assertEqual([c[1:] for c in self.calls if c[0]=='write'],[(s.g.BACKUP_OFFSET,33*512),(0,34*512),(s.b.SWAP_OFFSET,4096)])

    def test_each_failed_write_restores_original_bytes_before_reboot(self):
        for number in (1,2,3):
            with self.subTest(number=number):
                self.fail_at=number;self.count=0
                ok,result=self.run_transition();self.assertFalse(ok);self.assert_factory()
                self.assertTrue(result['rollback_attempted']);self.assertEqual(result['final_layout'],'factory')
                self.assertTrue(result['reboot_acknowledged'])
                for name in s.OUTPUTS:(self.directory/name).write_bytes(b'')

    def test_bad_readback_rolls_back_and_cannot_qualify(self):
        self.bad_readback=True;ok,result=self.run_transition();self.assertFalse(ok);self.assert_factory()
        self.assertTrue(result['rollback_attempted'])

    def test_failed_restoration_does_not_reboot_unverified_layout(self):
        self.fail_all=True;ok,result=self.run_transition();self.assertFalse(ok)
        self.assertIsNone(result['final_layout']);self.loader.shutdown.assert_not_called()

    def test_restore_repairs_torn_transition_but_install_refuses_it(self):
        self.memory[0][5032:5036]=b'????'
        ok,_=self.run_transition();self.assertFalse(ok);self.assertEqual(self.count,0)
        for name in s.OUTPUTS:(self.directory/name).write_bytes(b'')
        ok,result=self.run_transition(True);self.assertTrue(ok);self.assert_factory()
        self.assertEqual(result['initial_state']['primary'],'partial')

    def test_foreign_changes_are_never_overwritten_even_by_restore(self):
        self.memory[0][100]^=1
        ok,_=self.run_transition(True);self.assertFalse(ok);self.assertEqual(self.count,0)
        self.loader.shutdown.assert_not_called()

    def test_extent_mismatch_prevents_all_writes(self):
        struct.pack_into('<I',self.memory[s.b.DATA_OFFSET+1024],4,s.b.DATA_SIZE//4096+1)
        ok,_=self.run_transition();self.assertFalse(ok);self.assertEqual(self.count,0)

    def test_reboot_failure_does_not_qualify(self):
        self.loader.shutdown.return_value=False
        ok,result=self.run_transition();self.assertFalse(ok);self.assertEqual(result['final_layout'],'swap')

    def test_bad_inputs_and_stale_output_stop_before_device_access(self):
        path=self.directory/'header-swap.bin';raw=path.read_bytes();path.write_bytes(b'bad')
        with self.assertRaises(ValueError):self.run_transition()
        path.write_bytes(raw);(self.directory/'swap-events.jsonl').write_text('stale')
        with self.assertRaises(ValueError):self.run_transition()
        self.assertEqual(self.calls,[])

    def test_wrong_soc_stops_before_device_access(self):
        self.mtk.config.hwcode=0
        with self.assertRaises(ValueError):self.run_transition()
        self.assertEqual(self.calls,[])

    def test_real_cli_restore_dispatch_propagates_failure(self):
        from mtkclient.Library.DA.mtk_da_handler import DaHandler
        spec=importlib.util.spec_from_file_location('cli','mtk.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        with mock.patch.object(cli,'Main') as main,mock.patch.object(sys,'argv',['mtk','gemini-fixed-swap',str(self.directory),'--restore']):cli.main()
        args=main.call_args.args[0];self.assertTrue(args.restore)
        self.loader.config=SimpleNamespace(generatekeys=False);handler=DaHandler.__new__(DaHandler)
        with mock.patch.object(s,'transition',return_value=False) as transition,self.assertRaises(SystemExit):
            handler.handle_da_cmds(self.mtk,args.cmd,args)
        transition.assert_called_once_with(self.mtk,str(self.directory),restore=True)


if __name__ == '__main__':unittest.main()
