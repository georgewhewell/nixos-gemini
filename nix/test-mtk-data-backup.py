#!/usr/bin/env python3
"""Exercise offline capture, early rejection and recovery without flash writes."""
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
from mtkclient.Library import gemini_data_backup as b
if __name__ == '__main__':
    # mtkclient initializes its terminal streams while importing the handler;
    # do that before unittest owns those streams. Host byte-verifier tests can
    # reuse the fixture without importing USB/crypto dependencies.
    from mtkclient.Library.DA.mtk_da_handler import DaHandler


class Backup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        for name in b.OUTPUTS: (self.directory / name).touch()
        self.data = bytearray(b'X' * 65536)
        sb = bytearray(1024)
        struct.pack_into('<I', sb, 4, 16)
        struct.pack_into('<I', sb, 24, 2)
        struct.pack_into('<HH', sb, 56, 0xef53, 1)
        sb[104:120] = uuid.UUID(b.DATA_UUID).bytes
        self.data[1024:2048] = sb
        self.primary = b'P' * 32768; self.backup = b'B' * (33 * 512)
        self.memory = {0: self.primary, b.g.BACKUP_OFFSET: self.backup,
                       b.DATA_OFFSET: self.data, b.SWAP_OFFSET: b'S' * 4096}
        protected = []
        for i, (name, offset, size, digest) in enumerate(b.g.PROTECTED):
            raw = bytes([i + 42]) * 4096; self.memory[offset] = raw
            protected.append((name, offset, len(raw), b.g.sha(raw) if digest else None))
        for mod, values in ((b, dict(DATA_SIZE=len(self.data), CHUNK=16384)),
                            (b.g, dict(PRIMARY_SHA=b.g.sha(self.primary), BACKUP_SHA=b.g.sha(self.backup), PROTECTED=tuple(protected)))):
            for key, value in values.items():
                patch = mock.patch.object(mod, key, value); patch.start(); self.addCleanup(patch.stop)
        self.calls = []; self.short_at = None
        self.loader = SimpleNamespace(readflash=self.read,
            writeflash=mock.Mock(side_effect=AssertionError('No device writes allowed')),
            shutdown=mock.Mock(return_value=True),
            daconfig=SimpleNamespace(storage=SimpleNamespace(flashsize=b.g.FLASH_SIZE)))
        self.mtk = SimpleNamespace(config=SimpleNamespace(hwcode=0x279, pagesize=512), daloader=self.loader)

    def read(self, addr, length, filename, parttype, display):
        self.assertEqual((filename, parttype, display), ('', 'user', False))
        self.calls.append((addr, length))
        for start, raw in self.memory.items():
            if start <= addr and addr + length <= start + len(raw):
                data = bytes(raw[addr-start:addr-start+length])
                return data[:-1] if addr == self.short_at else data
        self.fail('Read outside fixture: ' + repr((addr, length)))

    def capture(self):
        with contextlib.redirect_stdout(io.StringIO()):
            ok = b.capture(self.mtk, self.directory)
        self.loader.writeflash.assert_not_called()
        return ok, json.loads((self.directory / 'backup-result.json').read_text())

    def test_complete_offline_data_exact_bytes_and_ordered_reads(self):
        ok, result = self.capture(); self.assertTrue(ok)
        self.assertEqual((self.directory / 'data.ext4').read_bytes(), bytes(self.data))
        self.assertEqual(result['data_sha256'], b.g.sha(self.data))
        self.assertEqual(result['protected_before'], result['protected_after'])
        chunks = [(e['offset'], e['size']) for e in result['events'] if e['event'] == 'chunk-captured']
        self.assertEqual(chunks, [(i, 16384) for i in range(0, 65536, 16384)])
        self.assertEqual((self.directory / 'swap-header-before.bin').read_bytes(), b'S' * 4096)
        self.loader.shutdown.assert_called_once_with(bootmode=1)

    def test_short_data_read_rejected_but_original_linux_rebooted(self):
        self.short_at = b.DATA_OFFSET + 16384
        ok, result = self.capture(); self.assertFalse(ok)
        self.assertFalse(result['capture_complete']); self.assertTrue(result['original_layout_verified'])
        self.assertTrue(result['reboot_acknowledged'])
        self.assertEqual((self.directory / 'data.ext4').stat().st_size, 16384)

    def test_unclean_filesystem_is_rejected_before_copy_and_rebooted(self):
        struct.pack_into('<H', self.data, 1024 + 58, 0)
        ok, result = self.capture(); self.assertFalse(ok)
        self.assertTrue(result['reboot_acknowledged'])
        self.assertEqual((self.directory / 'data.ext4').stat().st_size, 0)

    def test_wrong_gpt_or_boot_image_is_never_admitted(self):
        for address in (0, b.g.PROTECTED[0][1]):
            with self.subTest(address=address):
                old = self.memory[address]; self.memory[address] = b'Z' + old[1:]
                ok, result = self.capture(); self.assertFalse(ok)
                self.loader.shutdown.assert_not_called()
                self.assertEqual((self.directory / 'data.ext4').stat().st_size, 0)
                self.memory[address] = old
                for name in b.OUTPUTS: (self.directory / name).write_bytes(b'')

    def test_extent_rejects_foreign_geometry_but_records_pending_journal_replay(self):
        clean = bytes(self.data[1024:2048]); self.assertTrue(b.extent(clean)['clean'])
        for offset, fmt, value in ((4, '<I', 17), (24, '<I', 3), (56, '<H', 0),
                                    (58, '<H', 3), (104, '<I', 0)):
            bad = bytearray(clean); struct.pack_into(fmt, bad, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError): b.extent(bytes(bad))
        bad = bytearray(clean); struct.pack_into('<I', bad, 96, 0x80); struct.pack_into('<I', bad, 0x150, 1)
        with self.assertRaises(ValueError): b.extent(bytes(bad))
        with self.assertRaises(ValueError): b.extent(clean[:-1])
        pending = bytearray(clean); struct.pack_into('<I', pending, 96, 4)
        self.assertFalse(b.extent(bytes(pending))['clean'])
        self.assertTrue(b.extent(bytes(pending))['needs_recovery'])

    def test_capture_preserves_pending_journal_bytes_for_host_replay(self):
        struct.pack_into('<I', self.data, 1024 + 96, 4)
        ok, result = self.capture(); self.assertTrue(ok)
        self.assertTrue(result['filesystem']['needs_recovery'])
        self.assertFalse(result['filesystem']['clean'])
        self.assertEqual((self.directory / 'data.ext4').read_bytes(), bytes(self.data))

    def test_stale_or_symlink_output_and_wrong_device_stop_before_io(self):
        path = self.directory / 'data.ext4'; path.write_bytes(b'stale')
        with self.assertRaises(ValueError): self.capture()
        path.unlink(); path.symlink_to(self.directory / 'primary-before.bin')
        with self.assertRaises(OSError): self.capture()
        path.unlink(); path.touch(); self.mtk.config.hwcode = 0
        with self.assertRaises(ValueError): self.capture()
        self.assertEqual(self.calls, [])

    def test_reboot_failure_retains_capture_but_does_not_qualify(self):
        self.loader.shutdown.side_effect = OSError('USB disconnected')
        ok, result = self.capture(); self.assertFalse(ok)
        self.assertTrue(result['capture_complete']); self.assertFalse(result['reboot_acknowledged'])
        self.assertEqual(result['recovery_error'], 'USB disconnected')

    def test_real_cli_and_da_dispatch_propagate_failure(self):
        from mtkclient.Library.DA.mtk_da_handler import DaHandler
        spec = importlib.util.spec_from_file_location('cli', 'mtk.py')
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        with mock.patch.object(cli, 'Main') as main, mock.patch.object(sys, 'argv', ['mtk', 'gemini-data-backup', str(self.directory)]):
            cli.main()
        args = main.call_args.args[0]
        self.assertEqual(args.cmd, 'gemini-data-backup'); self.assertEqual(args.directory, str(self.directory))
        handler = object.__new__(DaHandler); handler.mtk = self.mtk
        self.loader.config = SimpleNamespace(generatekeys=False)
        with mock.patch.object(b, 'capture', return_value=False) as capture, self.assertRaises(SystemExit):
            handler.handle_da_cmds(self.mtk, args.cmd, args)
        capture.assert_called_once_with(self.mtk, args.directory)


if __name__ == '__main__': unittest.main()
