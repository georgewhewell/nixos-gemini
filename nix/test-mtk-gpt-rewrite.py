#!/usr/bin/env python3
"""Test the GPT transaction and real XFlash writes without touching hardware."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path.cwd()))
from mtkclient.Library import gemini_gpt_rewrite as g
from mtkclient.Library.DA.mtk_da_handler import DaHandler
from mtkclient.Library.DA.xflash.xflash_lib import DAXFlash
from mtkclient.Library.DA.xflash.xflash_param import Cmd

spec = importlib.util.spec_from_file_location('cli', 'mtk.py')
cli = importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


class Rewrite(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)
        self.primary=b'P'*32768;self.backup=b'B'*(33*512)
        self.inputs={'primary-gpt-before.bin':self.primary[:34*512], 'backup-gpt-before.bin':self.backup}
        for name,raw in self.inputs.items():(self.directory/name).write_bytes(raw)
        for name in g.OUTPUTS:(self.directory/name).touch()
        self.memory={0:bytearray(self.primary),g.BACKUP_OFFSET:bytearray(self.backup)}
        self.protected=[]
        for i,(name,offset,size,digest) in enumerate(g.PROTECTED):
            raw=bytes([i+42])*size;self.memory[offset]=bytearray(raw)
            self.protected.append((name,offset,size,g.sha(raw) if digest else None))
        for name,value in dict(PRIMARY_SHA=g.sha(self.primary),PRIMARY_WRITE_SHA=g.sha(self.inputs['primary-gpt-before.bin']),BACKUP_SHA=g.sha(self.backup),PROTECTED=tuple(self.protected)).items():
            patch=mock.patch.object(g,name,value);patch.start();self.addCleanup(patch.stop)
        self.calls=[];self.write_count=0;self.fail_write=None;self.corrupt_all=False;self.corrupt_first_readback=False
        self.loader=SimpleNamespace(readflash=self.read,writeflash=self.write,shutdown=mock.Mock(return_value=True),daconfig=SimpleNamespace(storage=SimpleNamespace(flashsize=g.FLASH_SIZE)))
        self.mtk=SimpleNamespace(config=SimpleNamespace(hwcode=0x279,pagesize=512),daloader=self.loader)

    def read(self,addr,length,filename,parttype,display):
        self.calls.append(('read',addr,length))
        self.assertEqual((filename,parttype,display),('','user',False))
        raw=bytes(self.memory[addr][:length])
        if self.corrupt_first_readback and self.write_count==1:
            self.corrupt_first_readback=False
            return b'X'+raw[1:]
        return raw

    def write(self,addr,length,wdata,filename,parttype,display):
        self.calls.append(('write',addr,length));self.write_count+=1
        self.assertEqual((filename,parttype,display),('','user',False))
        self.assertIn(addr,(0,g.BACKUP_OFFSET))
        self.assertEqual(length,len(wdata))
        self.memory[addr][:length]=wdata
        if self.corrupt_all or self.fail_write==self.write_count:
            self.memory[addr][0]^=1
            return False
        return True

    def run_rewrite(self):
        with contextlib.redirect_stdout(io.StringIO()):
            ok=g.rewrite_factory(self.mtk,self.directory)
        return ok,json.loads((self.directory/'gpt-result.json').read_text())

    def test_success_reads_all_guards_before_backup_then_primary_and_reboots(self):
        ok,result=self.run_rewrite();self.assertTrue(ok)
        self.assertTrue(result['operation_qualified']);self.assertFalse(result['rollback_attempted'])
        writes=[c for c in self.calls if c[0]=='write']
        self.assertEqual(writes,[('write',g.BACKUP_OFFSET,33*512),('write',0,34*512)])
        self.assertTrue(all(c[0]=='read' for c in self.calls[:6]))
        self.assertEqual(result['protected_before'],result['protected_after'])
        self.assertEqual(bytes(self.memory[0]),self.primary)
        self.assertEqual(bytes(self.memory[g.BACKUP_OFFSET]),self.backup)
        self.loader.shutdown.assert_called_once_with(bootmode=1)

    def test_foreign_gpt_read_does_not_write_or_reset(self):
        self.memory[0][0]^=1
        ok,result=self.run_rewrite();self.assertFalse(ok)
        self.assertFalse(result['write_attempted']);self.loader.shutdown.assert_not_called()
        self.assertNotIn('write',[c[0] for c in self.calls])

    def test_changed_boot_guard_does_not_write(self):
        self.memory[g.PROTECTED[0][1]][0]^=1
        ok,result=self.run_rewrite();self.assertFalse(ok)
        self.assertFalse(result['write_attempted']);self.loader.shutdown.assert_not_called()

    def check_partial_write_failure(self, failure):
        self.fail_write=failure
        ok,result=self.run_rewrite();self.assertFalse(ok)
        self.assertTrue(result['rollback_attempted']);self.assertTrue(result['original_layout_verified'])
        self.assertEqual(bytes(self.memory[0]),self.primary)
        self.assertEqual(bytes(self.memory[g.BACKUP_OFFSET]),self.backup)
        self.loader.shutdown.assert_called_once_with(bootmode=1)

    def test_partial_backup_write_failure_restores_both_copies_but_never_qualifies(self):
        self.check_partial_write_failure(1)

    def test_partial_primary_write_failure_restores_both_copies_but_never_qualifies(self):
        self.check_partial_write_failure(2)

    def test_unacknowledged_or_bad_readback_cannot_pass(self):
        self.corrupt_first_readback=True
        ok,result=self.run_rewrite();self.assertFalse(ok)
        self.assertTrue(result['rollback_attempted']);self.assertTrue(result['original_layout_verified'])

    def test_failed_restoration_never_reboots_corrupt_table(self):
        self.corrupt_all=True
        ok,result=self.run_rewrite();self.assertFalse(ok)
        self.assertTrue(result['rollback_attempted']);self.assertFalse(result['original_layout_verified'])
        self.loader.shutdown.assert_not_called()

    def test_reboot_failure_cannot_pass(self):
        self.loader.shutdown.return_value=False
        ok,result=self.run_rewrite();self.assertFalse(ok)
        self.assertTrue(result['original_layout_verified']);self.assertFalse(result['reboot_acknowledged'])

    def test_reboot_exception_preserves_verified_layout_evidence(self):
        self.loader.shutdown.side_effect=OSError('USB failure')
        ok,result=self.run_rewrite();self.assertFalse(ok)
        self.assertTrue(result['original_layout_verified']);self.assertEqual(result['reboot_error'],'USB failure')

    def test_inputs_and_stale_evidence_rejected_without_any_device_io(self):
        for file in ('primary-gpt-before.bin','gpt-result.json'):
            original=(self.directory/file).read_bytes();(self.directory/file).write_bytes(b'bad')
            with self.assertRaises(ValueError):self.run_rewrite()
            (self.directory/file).write_bytes(original)
        target=self.directory/'backup-gpt-before.bin';target.unlink();target.symlink_to(self.directory/'primary-gpt-before.bin')
        with self.assertRaises(OSError):self.run_rewrite()
        self.assertEqual(self.calls,[])

    def test_wrong_soc_or_flash_size_cannot_write(self):
        self.mtk.config.hwcode=0x1234
        with self.assertRaises(ValueError):self.run_rewrite()
        self.assertEqual(self.calls,[])

    def test_real_cli_parser_and_da_dispatch_propagate_failure(self):
        with mock.patch.object(cli,'Main') as main, mock.patch.object(sys,'argv',['mtk','gemini-gpt-rewrite',str(self.directory)]), contextlib.redirect_stdout(io.StringIO()):
            cli.main()
        args=main.call_args.args[0]
        handler=DaHandler.__new__(DaHandler)
        handler.error=mock.Mock()
        self.loader.config=SimpleNamespace(generatekeys=False)
        with mock.patch.object(g,'rewrite_factory',return_value=False) as rewrite,self.assertRaises(SystemExit) as caught:
            handler.handle_da_cmds(self.mtk,args.cmd,args)
        self.assertEqual(caught.exception.code,1);rewrite.assert_called_once_with(self.mtk,str(self.directory))

    def test_real_xflash_sends_exact_byte_address_length_and_memory_payload(self):
        for offset,raw in ((0,self.inputs['primary-gpt-before.bin']),(g.BACKUP_OFFSET,self.backup)):
            for status in (0,0x1234):
                with self.subTest(offset=offset,status=status):
                    da=DAXFlash.__new__(DAXFlash)
                    da.mtk=SimpleNamespace(config=SimpleNamespace(guiprogress=None))
                    da.daconfig=SimpleNamespace(storage=SimpleNamespace(get_storage=lambda parttype,length:(1,8,length)))
                    da.get_packet_length=lambda:SimpleNamespace(write_packet_length=4096)
                    da.cmd_write_data=mock.Mock(return_value=True)
                    da.send_param=mock.Mock(return_value=True);da.status=mock.Mock(return_value=status)
                    da.send_devctrl=mock.Mock(return_value=True);da.cmd=Cmd()
                    da.eh=SimpleNamespace(status=str);da.error=mock.Mock()
                    self.assertEqual(da.writeflash(offset,len(raw),wdata=raw,parttype='user',display=False),status==0)
                    da.cmd_write_data.assert_called_once_with(offset,len(raw),1,8)
                    self.assertEqual(b''.join(call.args[0][2] for call in da.send_param.call_args_list),raw)


if __name__=='__main__':unittest.main()
