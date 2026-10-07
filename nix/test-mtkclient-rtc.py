"""Exercise actual CLI/multi dispatch, protocol selection and RTC packet bit."""
import contextlib
import importlib.util
import io
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec=importlib.util.spec_from_file_location('reset_base',sys.argv.pop(1))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
from mtkclient.Library.DA.mtk_daloader import DAloader
from mtkclient.config.brom_config import DAmodes


class PreserveRtc(unittest.TestCase):
    def test_cli_option_and_multi_connection(self):
        with patch.object(base.cli,'Main') as main,patch.object(sys,'argv',['mtk','reset','--bootmode','reboot','--preserve-rtc']):
            base.cli.main()
        self.assertTrue(main.call_args.args[0].preserve_rtc)
        mtk=Mock();mtk.config.debugmode=False
        handler=Mock();handler.connect.return_value=mtk;handler.configure_da.return_value=mtk
        with patch.object(base.mtk_main,'Mtk',return_value=mtk),patch.object(base.mtk_main,'DaHandler',return_value=handler), \
                patch.object(sys,'argv',['mtk','multi','printgpt;reset --bootmode reboot --preserve-rtc']):
            base.cli.main()
        self.assertEqual(handler.connect.call_count,1)
        last=handler.handle_da_cmds.call_args_list[-1]
        self.assertEqual(last.args[1],'reset');self.assertTrue(last.args[2].preserve_rtc)

    def test_flag_reaches_loader_and_failure_keeps_session(self):
        for accepted in (True,False):
            with tempfile.TemporaryDirectory() as tmp:
                state=Path(tmp)/'.state';state.write_text('owned session')
                handler,mtk=base.ResetTests.handler(self,tmp,accepted)
                args=SimpleNamespace(bootmode='reboot',preserve_rtc=True)
                with contextlib.redirect_stdout(io.StringIO()):
                    if accepted:handler.handle_da_cmds(mtk,'reset',args)
                    else:
                        with self.assertRaises(SystemExit):handler.handle_da_cmds(mtk,'reset',args)
                mtk.daloader.shutdown.assert_called_once_with(bootmode=1,preserve_rtc=True)
                self.assertEqual(state.exists(),not accepted)

    def test_only_xflash_can_claim_preservation(self):
        for mode in (DAmodes.XFLASH,DAmodes.LEGACY,DAmodes.XML):
            da=DAloader.__new__(DAloader);da.flashmode=mode;da.error=Mock();da.da=SimpleNamespace(shutdown=Mock(return_value=True))
            result=da.shutdown(bootmode=1,preserve_rtc=True)
            self.assertEqual(result,mode==DAmodes.XFLASH)
            if result:da.da.shutdown.assert_called_once_with(async_mode=0,dl_bit=0,bootmode=1,preserve_rtc=True)
            else:da.da.shutdown.assert_not_called()
            da.da.shutdown.reset_mock();self.assertTrue(da.shutdown(bootmode=1))
            da.da.shutdown.assert_called_once_with(async_mode=0,dl_bit=0,bootmode=1)

    def test_only_rtc_word_changes_and_packet_size_stays_correct(self):
        for code,words in ((0x6797,7),(0x6765,8)):
            for mode in (0,1,2):
                for preserve in (False,True):
                    da=base.ResetTests.xflash(self,[0,0]);da.config.chipconfig.dacode=code
                    self.assertTrue(da.shutdown(bootmode=mode,preserve_rtc=preserve))
                    packet=struct.unpack('<'+'I'*words,da.xsend.call_args_list[1].args[0])
                    expected=(int(mode!=0 or preserve),0,0,mode,0,int(preserve),0)+((0,) if words==8 else ())
                    self.assertEqual(packet,expected)
                    da.mtk.port.close.assert_called_once_with(reset=False)

    def test_negative_ack_does_not_claim_preservation(self):
        for statuses in ([1],[0,1]):
            da=base.ResetTests.xflash(self,statuses)
            self.assertFalse(da.shutdown(bootmode=1,preserve_rtc=True))
            for call in da.mtk.port.close.call_args_list:
                self.assertEqual(call.kwargs,dict(reset=True))


if __name__=='__main__':unittest.main()
