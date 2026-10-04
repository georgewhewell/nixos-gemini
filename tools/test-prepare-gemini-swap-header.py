#!/usr/bin/env python3
"""Validate the native swap header oracle and reject unsafe header changes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('header', Path(__file__).with_name('prepare-gemini-swap-header.py'))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)


class Header(unittest.TestCase):
    def test_native_mkswap_and_blkid_agree_with_kernel_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'prepared'; result = h.prepare(directory)
            self.assertEqual(result['write_offset'], 111622144 * 512)
            self.assertEqual(result['write_size'], 4096)
            self.assertEqual(result['usable_bytes'], 5368709120 - 4096)
            self.assertFalse(result['device_writes_performed'])
            self.assertFalse((directory / 'swap-template.img').exists())
            original = (directory / 'swap-header.bin').read_bytes()
            for offset in (0, 1024, 1028, 1032, 1036, 1052, 1068, 4086):
                changed = bytearray(original); changed[offset] ^= 1
                with self.subTest(offset=offset), self.assertRaises(ValueError): h.validate(bytes(changed))
            with self.assertRaises(ValueError): h.validate(original[:-1])
            with self.assertRaises(FileExistsError): h.prepare(directory)


if __name__ == '__main__': unittest.main()
