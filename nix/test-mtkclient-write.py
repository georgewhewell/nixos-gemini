"""Exercise partition-write results through the real handler and XFlash code."""
import contextlib
import builtins
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path.cwd()))
from mtkclient.Library.DA.mtk_da_handler import DaHandler
from mtkclient.Library.DA.xflash.xflash_lib import DAXFlash
from mtkclient.Library.DA.xflash.xflash_param import Cmd
from mtkclient.Library import mtk_main

spec = importlib.util.spec_from_file_location('mtk_cli_write_test', 'mtk.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.filename = str(Path(self.tmp.name) / 'boot.img')
        Path(self.filename).write_bytes(b'B' * 512)
        self.partition = SimpleNamespace(sector=362496, sectors=32768, name='boot')
        self.loader = SimpleNamespace(
            config=SimpleNamespace(generatekeys=False),
            writeflash=Mock(return_value=True),
            detect_partition=Mock(return_value=(True, self.partition)),
            shutdown=Mock(return_value=True), peek=Mock())
        self.mtk = SimpleNamespace(daloader=self.loader,
                                   config=SimpleNamespace(debugmode=False))
        self.handler = DaHandler.__new__(DaHandler)
        self.handler.mtk = self.mtk
        self.handler.config = SimpleNamespace(pagesize=512)
        self.handler.error, self.handler.info = Mock(), Mock()
        self.output = io.StringIO()

    def write(self, **overrides):
        kwargs = dict(parttype=None, filenames=[self.filename], partitions=['boot'])
        kwargs.update(overrides)
        with contextlib.redirect_stdout(self.output):
            return self.handler.da_write(**kwargs)

    def test_success_keeps_exact_partition_address_and_length(self):
        self.assertIs(self.write(), True)
        self.loader.writeflash.assert_called_once_with(
            addr=0xb100000, length=16 * 1024 * 1024, filename=self.filename, parttype=None)

    def test_failure_is_false_and_stops_subsequent_writes(self):
        self.loader.writeflash.return_value = False
        self.assertIs(self.write(filenames=[self.filename, self.filename], partitions=['boot', 'boot2']), False)
        self.loader.writeflash.assert_called_once()
        self.assertNotIn('Wrote ', self.output.getvalue())

    def test_input_errors_cannot_write(self):
        for kwargs in (dict(filenames=[], partitions=[]), dict(filenames=[]),
                       dict(filenames=[self.filename + '.missing']), dict(filenames=[self.tmp.name])):
            with self.subTest(kwargs=kwargs):
                self.assertIs(self.write(**kwargs), False)
        Path(self.filename).write_bytes(b'')
        self.assertIs(self.write(), False)
        self.loader.writeflash.assert_not_called()

    def test_missing_partition_and_oversize_input_cannot_write(self):
        self.loader.detect_partition.return_value = (False, [])
        self.assertIs(self.write(), False)
        self.loader.detect_partition.return_value = (True, self.partition)
        self.partition.sectors = 0
        self.assertIs(self.write(), False)
        self.loader.writeflash.assert_not_called()

    def test_other_storage_paths_also_report_backend_failure(self):
        self.loader.writeflash.return_value = False
        self.assertIs(self.write(partitions=['gpt']), False)
        self.assertIs(self.write(parttype='boot1'), False)

    def test_real_xflash_failure_and_ack_reach_cli_exit_status(self):
        original_open = builtins.open
        opened = []
        def open_image(*args, **kwargs):
            file = original_open(*args, **kwargs)
            opened.append(file)
            return file
        for command_ok, packet_ok, status in ((False, True, 0), (True, False, 0),
                                              (True, True, 0x1234), (True, True, 0)):
            with self.subTest(command=command_ok, packet=packet_ok, status=status):
                da = DAXFlash.__new__(DAXFlash)
                da.mtk = SimpleNamespace(config=SimpleNamespace(guiprogress=None))
                da.daconfig = SimpleNamespace(storage=SimpleNamespace(
                    get_storage=lambda parttype, length: (1, 8, length)))
                da.get_packet_length = lambda: SimpleNamespace(write_packet_length=512)
                da.cmd_write_data = Mock(return_value=command_ok)
                da.send_param = Mock(return_value=packet_ok)
                da.status = Mock(return_value=status)
                da.send_devctrl = Mock(return_value=True)
                da.cmd, da.eh, da.error = Cmd(), SimpleNamespace(status=str), Mock()
                self.loader.writeflash = lambda **kw: da.writeflash(display=False, **kw)
                args = SimpleNamespace(partitionname='boot', filename=self.filename, parttype=None)
                with contextlib.redirect_stdout(io.StringIO()), \
                     patch.object(builtins, 'open', side_effect=open_image):
                    if command_ok and packet_ok and status == 0:
                        self.handler.handle_da_cmds(self.mtk, 'w', args)
                    else:
                        with self.assertRaises(SystemExit) as error:
                            self.handler.handle_da_cmds(self.mtk, 'w', args)
                        self.assertEqual(error.exception.code, 1)
                da.cmd_write_data.assert_called_once_with(0xb100000, 512, 1, 8)
                self.assertTrue(all(file.closed for file in opened))

    def test_failed_write_stops_real_multi_command_dispatch(self):
        self.loader.writeflash.return_value = False
        self.handler.connect = Mock(return_value=self.mtk)
        self.handler.configure_da = Mock(return_value=self.mtk)
        commands = f'w boot {self.filename};reset --bootmode reboot'
        with patch.object(mtk_main, 'Mtk', return_value=self.mtk), \
             patch.object(mtk_main, 'DaHandler', return_value=self.handler), \
             patch.object(sys, 'argv', ['mtk', 'multi', commands]), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            cli.main()
        self.assertEqual(error.exception.code, 1)
        self.loader.shutdown.assert_not_called()


if __name__ == '__main__':
    unittest.main()
