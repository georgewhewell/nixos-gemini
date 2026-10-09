#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Make an original baseline H.264 I_PCM frame and verify its decoded pixels.

Syntax follows ITU-T H.264 sections 7.3.2, 7.3.3 and 7.3.5, also referenced by
https://docs.kernel.org/userspace-api/media/v4l/ext-ctrls-codec-stateless.html
No encoder library or vendor implementation is used to construct the frame.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


class Bits:
    def __init__(self):
        self.bits = []

    def put(self, value, width=1):
        if value < 0 or value >= 1 << width:
            raise ValueError((value, width))
        self.bits.extend((value >> i) & 1 for i in range(width - 1, -1, -1))

    def ue(self, value):
        if value < 0:
            raise ValueError(value)
        width = (value + 1).bit_length()
        self.put(0, width - 1)
        self.put(value + 1, width)

    def se(self, value):
        self.ue(-2 * value if value <= 0 else 2 * value - 1)

    def align(self):
        while len(self.bits) % 8:
            self.put(0)

    def trailing(self):
        self.put(1)
        self.align()

    def bytes(self):
        if len(self.bits) % 8:
            raise ValueError('Unaligned bitstream')
        return bytes(sum(self.bits[i + j] << (7 - j) for j in range(8))
                     for i in range(0, len(self.bits), 8))


def nal(header, rbsp):
    data = bytearray([header])
    zeros = 0
    for byte in rbsp:
        if zeros == 2 and byte <= 3:
            data.append(3)
            zeros = 0
        data.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ffmpeg', required=True,
                        help='Independent software decoder used to check every pixel')
    args = parser.parse_args()
    width = height = 64
    sps = Bits()
    sps.put(66, 8)  # Baseline
    sps.put(0xc0, 8)  # Constraint sets 0 and 1
    sps.put(10, 8)
    for value in (0, 0, 0, 0, 1):  # SPS id, frame/POC sizes, one reference
        sps.ue(value)
    sps.put(0)  # No gaps
    sps.ue(width // 16 - 1)
    sps.ue(height // 16 - 1)
    for value in (1, 1, 0, 0):  # Frame-only, direct8x8, no crop or VUI
        sps.put(value)
    sps.trailing()
    pps = Bits()
    pps.ue(0)
    pps.ue(0)
    pps.put(0)  # CAVLC
    pps.put(0)  # No bottom-field POC
    for _ in range(3):  # No slice groups, one L0/L1 reference
        pps.ue(0)
    pps.put(0)  # No weighted prediction
    pps.put(0, 2)
    for _ in range(3):
        pps.se(0)  # QP/QS deltas and chroma offset
    pps.put(1)  # Deblocking control present
    pps.put(0)  # Unconstrained intra prediction
    pps.put(0)  # No redundant pictures
    pps.trailing()
    picture = Bits()
    for value in (0, 2, 0):  # first_mb, I slice, PPS id
        picture.ue(value)
    picture.put(0, 4)  # frame_num
    picture.ue(0)  # idr_pic_id
    picture.put(0, 4)  # pic_order_cnt_lsb
    picture.put(0)  # no_output_of_prior_pics_flag
    picture.put(0)  # long_term_reference_flag
    picture.se(0)  # slice_qp_delta
    picture.ue(1)  # Deblocking disabled
    header_bits = 8 + len(picture.bits)  # From NAL header, excluding start code
    y = bytes(16 + (x + 2 * row) % 220 for row in range(height) for x in range(width))
    u = bytes(64 + x + row for row in range(height // 2) for x in range(width // 2))
    v = bytes(128 + x + 2 * row for row in range(height // 2) for x in range(width // 2))
    for mb_y in range(height // 16):
        for mb_x in range(width // 16):
            picture.ue(25)  # I_PCM in an I slice
            picture.align()
            for plane, stride, block in ((y, width, 16), (u, width // 2, 8),
                                         (v, width // 2, 8)):
                for row in range(block):
                    start = (mb_y * block + row) * stride + mb_x * block
                    for sample in plane[start:start + block]:
                        picture.put(sample, 8)
    picture.trailing()
    nals = (nal(0x67, sps.bytes()), nal(0x68, pps.bytes()), nal(0x65, picture.bytes()))
    stream = b''.join(b'\0\0\0\1' + item for item in nals)
    expected = y + u + v
    decoded = subprocess.run([args.ffmpeg, '-v', 'error', '-nostdin', '-f', 'h264',
                              '-i', 'pipe:0', '-frames:v', '1', '-f', 'rawvideo',
                              '-pix_fmt', 'yuv420p', 'pipe:1'], input=stream,
                             capture_output=True, check=True, timeout=30)
    if decoded.stdout != expected or decoded.stderr:
        raise RuntimeError('Software decoder did not match every generated pixel: ' +
                           decoded.stderr.decode(errors='replace'))
    args.out.mkdir(parents=True, exist_ok=True)
    artifacts = {'pcm64.h264': stream, 'pcm64.nal': nals[2], 'pcm64.yuv': expected}
    for name, data in artifacts.items():
        (args.out / name).write_bytes(data)
    info = dict(schema=1, width=width, height=height, header_bit_size=header_bits,
                profile_idc=66, level_idc=10, constraint_set_flags=3,
                max_num_ref_frames=1, log2_max_frame_num_minus4=0,
                pic_order_cnt_type=0, log2_max_pic_order_cnt_lsb_minus4=0,
                pic_width_in_mbs_minus1=3, pic_height_in_map_units_minus1=3,
                sps_flags=0x50, pps_flags=8, first_mb_in_slice=0, slice_type=2,
                slice_qp_delta=0, disable_deblocking_filter_idc=1, nal_ref_idc=3,
                decode_flags=1, software_decode_verified=True,
                hashes={name: hashlib.sha256(data).hexdigest()
                        for name, data in artifacts.items()})
    (args.out / 'pcm64.json').write_text(json.dumps(info, indent=2) + '\n')
    print('Verified 64x64 baseline I_PCM frame:', len(nals[2]), 'NAL bytes,',
          header_bits, 'header bits,', len(expected), 'matching decoded bytes')


if __name__ == '__main__':
    main()
