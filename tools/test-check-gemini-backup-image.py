#!/usr/bin/env python3
"""Use native ext4 tools to prove host journal replay preserves raw evidence."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import uuid

spec = importlib.util.spec_from_file_location('check_image', Path(__file__).with_name('check-gemini-backup-image.py'))
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
BIN = Path(c.E2FSCK).parent
SIZE = 64 * 1024 * 1024
UUID = '5d978ad4-a987-4b3f-bef6-f73ad7c2d986'


def extent(raw):
    blocks = struct.unpack_from('<I', raw, 4)[0]
    state = struct.unpack_from('<H', raw, 58)[0]
    recovery = bool(struct.unpack_from('<I', raw, 96)[0] & 4)
    return dict(uuid=str(uuid.UUID(bytes=raw[104:120])), block_count=blocks,
                block_size=4096, size=blocks*4096, clean=state == 1 and not recovery,
                needs_recovery=recovery)


class ImageCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name); self.image = self.directory / 'data.ext4'
        with self.image.open('wb') as stream: stream.truncate(SIZE)
        self.run_tool('mke2fs', '-q', '-t', 'ext4', '-b', '4096', '-U', UUID, str(self.image))
        proof = self.directory / 'proof'; proof.write_bytes(b'Persistent backup content\n')
        self.run_tool('debugfs', '-w', '-R', 'write ' + str(proof) + ' /proof', str(self.image))
        self.run_tool('debugfs', '-w', '-R', 'feature needs_recovery', str(self.image))

    def run_tool(self, name, *args):
        return subprocess.run([str(BIN / name), *args], check=True, capture_output=True, timeout=20)

    def expected(self):
        with self.image.open('rb') as stream:
            stream.seek(1024); fs = extent(stream.read(1024)); stream.seek(0)
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        return dict(filesystem=fs, data_sha256=digest)

    def test_native_journal_only_replay_preserves_original_and_file_contents(self):
        expected = self.expected(); self.assertTrue(expected['filesystem']['needs_recovery'])
        result = c.check(self.directory, expected, extent)
        self.assertTrue(result['raw_preserved']); self.assertTrue(result['readonly_fsck_passed'])
        self.assertTrue(result['recovered_filesystem']['clean'])
        self.assertNotEqual(result['raw_sha256'], result['recovered_sha256'])
        data = self.run_tool('debugfs', '-R', 'cat /proof', str(self.directory / 'data-recovered.ext4')).stdout
        self.assertEqual(data, b'Persistent backup content\n')
        wanted = {'/proof': hashlib.sha256(data).hexdigest()}
        self.assertEqual(c.verify_files(self.directory, wanted), wanted)
        with self.assertRaises(RuntimeError): c.verify_files(self.directory, {'/proof': '0'*64})

    def test_journal_replay_does_not_mask_unrelated_bitmap_corruption(self):
        self.run_tool('debugfs', '-w', '-R', 'setb 12000', str(self.image))
        expected = self.expected()
        with self.assertRaisesRegex(RuntimeError, 'filesystem check failed'):
            c.check(self.directory, expected, extent)
        self.assertEqual(self.expected()['data_sha256'], expected['data_sha256'])
        self.assertFalse((self.directory / 'fsck-result.json').exists())

    def test_stale_digest_and_existing_destination_never_run_replay(self):
        expected = self.expected(); expected['data_sha256'] = '0'*64
        with self.assertRaisesRegex(RuntimeError, 'changed before host recovery'):
            c.check(self.directory, expected, extent)
        self.assertFalse((self.directory / 'fsck-commands.json').exists())
        with self.assertRaises(FileExistsError): c.check(self.directory, self.expected(), extent)

    def test_symlink_source_is_rejected(self):
        expected = self.expected(); old = self.directory / 'old'; self.image.rename(old); self.image.symlink_to(old)
        with self.assertRaises(OSError): c.check(self.directory, expected, extent)


if __name__ == '__main__': unittest.main()
