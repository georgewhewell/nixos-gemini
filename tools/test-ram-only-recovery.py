#!/usr/bin/env python3
"""Check preservation and reject unsafe rescue archive/image mutations."""
import gzip
import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location('rescue', Path(__file__).with_name('build-ram-only-recovery.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

INIT = b'''#!/bin/sh
hibernate_resume() {
  echo 1 > /sys/power/resume
}

hibernate_resume
mount_persistent_storage
'''


def entry(name, data, mode=0o100755, links=1):
    values = [1, mode, 0, 0, links, 0, len(data), 0, 0, 0, 0, len(name)+1, 0]
    return name, b'070701'+b''.join(f'{v:08X}'.encode() for v in values), data


def archive(init=INIT, links=1):
    return r.serialize_archive([
        entry('.', b'', 0o40755, 2), entry('init', init, links=links),
        # An uppercase size field with hex letters caught unintended header
        # normalization during the first build of the real archived bundle.
        entry('bin/busybox', b'unchanged-binary-payload'*13, 0o100555),
        entry('bin/sh', b'/bin/busybox', 0o120777),
        entry('TRAILER!!!', b'', 0),
    ])


def header():
    b = bytearray(r.PAGE)
    struct.pack_into('<8s10I', b, 0, b'ANDROID!', 0, 0x40200000,
                     0, 0x45000000, 0, 0x40f00000, 0x44000000, r.PAGE, 0, 0)
    return b


class Rescue(unittest.TestCase):
    def test_only_init_changes_preserving_binary_symlink_and_metadata(self):
        old = archive()
        patched, changes, count = r.patch_initramfs(gzip.compress(old, mtime=0))
        before, after = r.parse_archive(old), r.parse_archive(gzip.decompress(patched))
        self.assertEqual(count, 5)
        self.assertEqual(len(changes), 1)
        for a, b in zip(before, after):
            if a[0] != 'init':
                self.assertEqual(a, b)
        init = next(data for name, _, data in after if name == 'init')
        self.assertNotIn(b'/sys/power/resume', init)
        self.assertIn(b'rescue-active-swap', init)
        self.assertIn(b'mount_persistent_storage', init)

    def test_resume_or_direct_swap_ambiguity_is_rejected(self):
        for bad in (INIT+b'hibernate_resume\n', INIT.replace(b'hibernate_resume\n', b''),
                    INIT+b'swapon /dev/mmcblk0p34\n', INIT+b'mkswap /dev/mmcblk1p2\n'):
            with self.subTest(init=bad), self.assertRaises(ValueError):
                r.patch_initramfs(gzip.compress(archive(bad), mtime=0))

    def test_init_cannot_be_a_symlink_or_hardlink(self):
        with self.assertRaises(ValueError):
            r.patch_initramfs(gzip.compress(archive(links=2), mtime=0))
        entries = r.parse_archive(archive())
        entries[1] = entry('init', INIT, 0o120777)
        with self.assertRaises(ValueError):
            r.patch_initramfs(gzip.compress(r.serialize_archive(entries), mtime=0))

    def test_truncated_archive_and_concatenated_gzip_are_rejected(self):
        raw = archive()
        with self.assertRaises(ValueError):
            r.parse_archive(raw[:120])
        with self.assertRaises(ValueError):
            r.patch_initramfs(gzip.compress(raw, mtime=0)+gzip.compress(raw, mtime=0))

    def test_duplicate_init_and_unsafe_paths_are_rejected(self):
        for name in ('./init', '/init', '../init'):
            entries = r.parse_archive(archive())
            entries.insert(-1, entry(name, INIT))
            with self.subTest(name=name), self.assertRaises(ValueError):
                r.parse_archive(r.serialize_archive(entries))

    def test_boot_repack_preserves_kernel_addresses_and_round_trips(self):
        kernel, ramdisk = b'kernel-payload'+bytes(257), b'ramdisk-payload'
        b = header()
        struct.pack_into('<I', b, 8, len(kernel))
        cmd = 'bootopt=64S3,32N2,64N2 '+' '.join(r.POLICY_ARGS)
        image = r.repack_image(b, kernel, ramdisk, cmd)
        _, k, rd, c = r.unpack_image(image)
        self.assertEqual((k, rd, c), (kernel, ramdisk, cmd))
        self.assertEqual(len(image), r.SIZE)
        self.assertEqual(struct.unpack_from('<I', image, 12)[0], 0x40200000)
        self.assertEqual(struct.unpack_from('<I', image, 20)[0], 0x45000000)

    def test_lk_command_line_overflow_is_rejected(self):
        with self.assertRaises(ValueError):
            r.repack_image(header(), b'kernel', b'ramdisk', 'x'*512)

    def test_bad_boot_id_and_trailing_payload_are_rejected(self):
        b = header()
        struct.pack_into('<I', b, 8, 6)
        image = r.repack_image(b, b'kernel', b'ramdisk', 'bootopt=64S3,32N2,64N2')
        for offset in (576, r.SIZE-1):
            bad = bytearray(image)
            bad[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                r.unpack_image(bad)


if __name__ == '__main__':
    unittest.main()
