#!/usr/bin/env python3
"""Check LK early-DTB window and Android-v0 carrier boundary failures."""
from pathlib import Path
import os
import runpy
import struct
import unittest

api = runpy.run_path(os.environ.get('GEMINI_CARRIER_BUILDER',
                        str(Path(__file__).with_name('build-android-uboot-carrier-v0.py'))))


def dtb(size=64):
    return api['FDT_MAGIC'] + struct.pack('>I', size) + bytes(size-8)


class Carrier(unittest.TestCase):
    def test_generation_command_line_fits_lks_first_android_field(self):
        command = api['CMDLINE']+' init=/nix/store/generation/init '+('x'*400)
        image, _ = api['build'](b'uboot', b'ramdisk', dtb(), command)
        actual = (image[64:576]+image[608:1632]).split(b'\0', 1)[0].decode()
        self.assertEqual(command, actual)
        for command in ('missing-bootopt', api['CMDLINE']+'\0', api['CMDLINE'].ljust(512)):
            with self.assertRaises(ValueError): api['build'](b'u', b'r', dtb(), command)

    def test_small_payload_has_aligned_early_loader_window(self):
        image, compressed = api['build'](b'uboot', b'ramdisk', dtb())
        size, load = struct.unpack_from('<2I', image, 8)
        self.assertEqual((size, load), (512*1024, 0x40200000))
        self.assertEqual(image[2048:2048+len(compressed)], compressed)
        self.assertEqual(image[2048+size-64:2048+size], dtb())
        self.assertEqual(image[2048+size:2048+size+7], b'ramdisk')
        kernel = image[2048:2048+size]
        expected_id = api['canonical_v0_id'](kernel, b'ramdisk')
        self.assertEqual(image[576:596], expected_id)

    def test_exact_window_boundary(self):
        image, _ = api['build'](b'uboot', b'', dtb(512*1024))
        size = struct.unpack_from('<I', image, 8)[0]
        self.assertEqual(size % 2048, 0)
        self.assertEqual(image[2048+size-512*1024:2048+size], dtb(512*1024))

    def test_rejects_window_overflow_and_later_false_magic(self):
        for data in (dtb(512*1024+1), dtb(512*1024+2048),
                     dtb()[:-4]+api['FDT_MAGIC']):
            with self.assertRaises(ValueError):
                api['build'](b'uboot', b'', data)

    def test_rejects_invalid_inputs_and_partition_overflow(self):
        for uboot, ramdisk, tree in ((b'', b'', dtb()), (b'u', b'', b'bad'),
                                     (b'u', b'', dtb()[:-1]),
                                     (b'u', bytes(16*1024*1024), dtb()),
                                     (bytes(28*1024*1024+1), b'', dtb())):
            with self.assertRaises(ValueError):
                api['build'](uboot, ramdisk, tree)


if __name__ == '__main__':
    unittest.main()
