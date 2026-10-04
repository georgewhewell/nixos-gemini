"""Test real mtkclient reset dispatch and DA packets without accessing USB."""
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path.cwd()))
from mtkclient.Library.DA.mtk_da_handler import DaHandler
from mtkclient.Library.DA.xflash.xflash_lib import DAXFlash
from mtkclient.Library.DA.xflash.xflash_param import Cmd
from mtkclient.Library.DA.legacy.dalegacy_lib import DALegacy
from mtkclient.Library.DA.legacy.dalegacy_param import Cmd as LegacyCmd, Rsp
from mtkclient.Library import mtk_main

spec = importlib.util.spec_from_file_location('mtk_cli_test', 'mtk.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class ResetTests(unittest.TestCase):
    def test_cli_modes_and_invalid_mode(self):
        for argv, expected in ((['reset'], 'shutdown'),
                               (['reset', '--bootmode', 'reboot'], 'reboot'),
                               (['reset', '--bootmode', 'fastboot'], 'fastboot')):
            with self.subTest(argv=argv), patch.object(cli, 'Main') as main, \
                 patch.object(sys, 'argv', ['mtk'] + argv), \
                 contextlib.redirect_stdout(io.StringIO()):
                cli.main()
                self.assertEqual(main.call_args.args[0].bootmode, expected)
        with patch.object(cli, 'Main') as main, \
             patch.object(sys, 'argv', ['mtk', 'reset', '--bootmode', 'typo']), \
             contextlib.redirect_stderr(io.StringIO()), \
             self.assertRaises(SystemExit) as error:
            cli.main()
        self.assertEqual(error.exception.code, 2)
        main.assert_not_called()

    def test_multi_parses_explicit_reboot_in_same_connection(self):
        mtk = Mock()
        mtk.config.debugmode = False
        handler = Mock()
        handler.connect.return_value = mtk
        handler.configure_da.return_value = mtk
        commands = 'printgpt;ro 0 0x8000 gpt-primary.bin;r boot boot-readback.img;reset --bootmode reboot'
        with patch.object(mtk_main, 'Mtk', return_value=mtk), \
             patch.object(mtk_main, 'DaHandler', return_value=handler), \
             patch.object(sys, 'argv', ['mtk', 'multi', commands]):
            cli.main()
        handler.connect.assert_called_once()
        handler.configure_da.assert_called_once()
        calls = handler.handle_da_cmds.call_args_list
        self.assertEqual([call.args[1] for call in calls], ['printgpt', 'ro', 'r', 'reset'])
        self.assertEqual(calls[-1].args[2].bootmode, 'reboot')

    def handler(self, directory, result):
        loader = SimpleNamespace(config=SimpleNamespace(generatekeys=False),
                                 shutdown=Mock(return_value=result))
        mtk = SimpleNamespace(daloader=loader,
                              config=SimpleNamespace(hwparam_path=directory))
        handler = DaHandler.__new__(DaHandler)
        handler.mtk, handler.error = mtk, Mock()
        return handler, mtk

    def test_modes_reach_da_and_clear_state_only_after_ack(self):
        for mode, wire in (('shutdown', 0), ('reboot', 1), ('fastboot', 2)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                state = Path(directory) / '.state'
                state.write_text('existing DA session')
                handler, mtk = self.handler(directory, True)
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    handler.handle_da_cmds(mtk, 'reset', SimpleNamespace(bootmode=mode))
                mtk.daloader.shutdown.assert_called_once_with(bootmode=wire)
                self.assertFalse(state.exists())
                self.assertIn(f'acknowledged {mode}', output.getvalue())

    def test_rejected_shutdown_is_failure_and_preserves_state(self):
        for result in (False, None):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as directory:
                state = Path(directory) / '.state'
                state.write_text('existing DA session')
                handler, mtk = self.handler(directory, result)
                with contextlib.redirect_stdout(io.StringIO()) as output, \
                     self.assertRaises(SystemExit) as error:
                    handler.handle_da_cmds(mtk, 'reset', SimpleNamespace(bootmode='reboot'))
                self.assertEqual(error.exception.code, 1)
                self.assertEqual(state.read_text(), 'existing DA session')
                self.assertNotIn('acknowledged', output.getvalue())
                handler.error.assert_called_once()

    def xflash(self, statuses):
        da = DAXFlash.__new__(DAXFlash)
        da.cmd = Cmd()
        da.xsend = Mock(return_value=True)
        da.status = Mock(side_effect=statuses)
        da.error = Mock()
        da.eh = SimpleNamespace(status=str)
        da.mtk = SimpleNamespace(port=SimpleNamespace(close=Mock()))
        da.config = SimpleNamespace(chipconfig=SimpleNamespace(dacode=0x6765))
        return da

    def test_xflash_wire_modes_and_no_usb_reset_after_ack(self):
        for mode in (0, 1, 2):
            da = self.xflash([0, 0])
            self.assertTrue(da.shutdown(bootmode=mode))
            self.assertEqual(da.xsend.call_args_list[0].args, (Cmd.SHUTDOWN,))
            packet = da.xsend.call_args_list[1].args[0]
            self.assertEqual(struct.unpack('<8I', packet),
                             (int(mode != 0), 0, 0, mode, 0, 0, 0, 0))
            da.mtk.port.close.assert_called_once_with(reset=False)

    def test_mt6797_packet_fits_real_da_receive_buffer_despite_success_status(self):
        # Read the contract from the actual pinned MT6797 download agent.
        # cmd_shutdown passes 28 bytes of capacity to the shared receiver,
        # whose oversize error it ignores before acknowledging success.
        loader = Path('mtkclient/Loader/MTK_DA_V5.bin').read_bytes()
        entries = struct.unpack_from('<I', loader, 0x68)[0]
        offset = next(0x6c + i * 0xdc for i in range(entries)
                      if struct.unpack_from('<H', loader, 0x6c + i * 0xdc + 2)[0] == 0x6797)
        start, length = struct.unpack_from('<II', loader, offset + 20 + 2 * 20)
        da2 = loader[start:start + length]
        self.assertEqual(hashlib.sha256(da2).hexdigest(),
                         'e7ad09de8ef025b9416ac4eca1c85938d3303c1aea462e5cfaa7c15721a1c45b')
        self.assertEqual(da2[0x66d0:0x66de], bytes.fromhex('70b500228cb01c23054603920493'))
        capacity = struct.unpack_from('<H', da2, 0x66d6)[0] & 0xff
        for mode in (1, 2):
            with self.subTest(mode=mode):
                received = bytearray(capacity)
                def send(data):
                    if isinstance(data, bytes) and len(data) <= capacity:
                        received[:len(data)] = data
                    return True  # Host USB writes also succeed for oversize packets.
                send(struct.pack('<8I', 1, 0, 0, mode, 0, 0, 0, 0))
                self.assertEqual(received, bytes(capacity))  # Old packet was discarded.
                da = self.xflash([0, 0])
                da.config.chipconfig.dacode = 0x6797
                da.xsend.side_effect = send
                self.assertTrue(da.shutdown(bootmode=mode))
                self.assertEqual(struct.unpack('<7I', received), (1, 0, 0, mode, 0, 0, 0))
                da.mtk.port.close.assert_called_once_with(reset=False)

    def test_xflash_failure_is_not_success(self):
        for statuses in ([1], [0, 1]):
            da = self.xflash(statuses)
            self.assertFalse(da.shutdown(bootmode=1))
        da = self.xflash([])
        da.xsend.return_value = False
        self.assertFalse(da.shutdown(bootmode=1))
        da.status.assert_not_called()
        da = self.xflash([0])
        da.xsend.side_effect = [True, False]
        self.assertFalse(da.shutdown(bootmode=1))
        self.assertEqual(da.status.call_count, 1)

    def test_legacy_real_ack_bytes_and_failure_propagation(self):
        for replies, accepted in (([b'\x5a', b'\x5a'], True),
                                  ([b'\xa5'], False), ([b''], False),
                                  ([b'\x5a', b'\xa5'], False)):
            da = DALegacy.__new__(DALegacy)
            da.Cmd, da.Rsp = LegacyCmd(), Rsp()
            da.usbwrite = Mock(return_value=True)
            da.usbread = Mock(side_effect=replies)
            da.mtk = SimpleNamespace(port=SimpleNamespace(close=Mock()))
            self.assertEqual(da.shutdown(bootmode=1), accepted)
            da.mtk.port.close.assert_called_once_with(reset=not accepted)
            if accepted:
                self.assertEqual(da.usbwrite.call_args_list[-1].args,
                                 (struct.pack('>I', 1),))
        for writes, replies in (([False], []), ([True, False], [b'\x5a'])):
            da.usbwrite = Mock(side_effect=writes)
            da.usbread = Mock(side_effect=replies)
            self.assertFalse(da.shutdown(bootmode=1))


if __name__ == '__main__':
    unittest.main()
