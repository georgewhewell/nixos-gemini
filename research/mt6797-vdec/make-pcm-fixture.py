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
    parser.add_argument('--p-skip', action='store_true',
                        help='Also verify an original P picture referencing the I_PCM frame')
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
    rows = [', '.join(f'0x{byte:02x}' for byte in nals[2][i:i + 12])
            for i in range(0, len(nals[2]), 12)]
    (args.out / 'pcm64-fixture.h').write_text(
        '/* SPDX-License-Identifier: GPL-2.0-only */\n'
        '/* Generated by make-pcm-fixture.py; original test data, not firmware. */\n'
        'static const u8 pcm64_nal[] = {\n\t' + ',\n\t'.join(rows) + '\n};\n')
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
    flat = Bits()
    flat.bits = picture.bits[:header_bits - 8].copy()
    for _ in range(16):
        flat.ue(3)  # I_16x16, DC prediction, no coded AC or chroma residual
        flat.ue(0)  # DC chroma prediction
        flat.se(0)  # Unchanged QP
        flat.put(1)  # CAVLC coeff_token: zero luma DC coefficients, nC=0
    flat.trailing()
    flat_nal = nal(0x65, flat.bytes())
    flat_stream = b''.join(b'\0\0\0\1' + item for item in (*nals[:2], flat_nal))
    flat_expected = bytes([128]) * len(expected)
    decoded = subprocess.run(
        [args.ffmpeg, '-v', 'error', '-nostdin', '-f', 'h264', '-i', 'pipe:0',
         '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', 'pipe:1'],
        input=flat_stream, capture_output=True, check=True, timeout=30)
    if decoded.stdout != flat_expected or decoded.stderr:
        raise RuntimeError('Compressed intra reference did not match every sample: ' +
                           decoded.stderr.decode(errors='replace'))
    flat_artifacts = {'grey64.h264': flat_stream, 'grey64.nal': flat_nal,
                      'grey64.yuv': flat_expected}
    for name, data in flat_artifacts.items():
        (args.out / name).write_bytes(data)
    flat_info = dict(info, macroblock_type='I_16x16_DC',
                     hashes={name: hashlib.sha256(data).hexdigest()
                             for name, data in flat_artifacts.items()})
    (args.out / 'grey64.json').write_text(json.dumps(flat_info, indent=2) + '\n')
    flat_rows = [', '.join(f'0x{byte:02x}' for byte in flat_nal[i:i + 12])
                 for i in range(0, len(flat_nal), 12)]
    with (args.out / 'pcm64-fixture.h').open('a') as header:
        header.write('static const u8 grey64_nal[] = {\n\t' +
                     ',\n\t'.join(flat_rows) + '\n};\n')
    print('Verified original compressed I_16x16 DC frame:', len(flat_nal),
          'NAL bytes,', len(flat_expected), 'matching decoded bytes')
    pattern = Bits()
    # The fixed IDR header up to slice_qp_delta is sixteen RBSP bits.
    pattern.bits = picture.bits[:header_bits - 8 - 4].copy()
    pattern.se(20)  # QP 46 makes a single DC coefficient add +/-8 samples.
    pattern.ue(1)
    pattern_header_bits = 8 + len(pattern.bits)
    block_values = []
    for mb_y in range(4):
        for mb_x in range(4):
            negative = (mb_x * 3 + mb_y * 5) % 4 >= 2
            pattern.ue(3)
            pattern.ue(0)
            pattern.se(0)
            pattern.put(1, 2)  # coeff_token 01: TotalCoeff=TrailingOnes=1
            pattern.put(int(negative))
            pattern.put(1)  # total_zeros=0 at tzVlcIndex=1
            # ITU-T H.264 8.3.3.3 and 8.5.10: flat scaling 16, QP46,
            # DC level +/-1 -> scaled DC +/-512 -> sample residual +/-8.
            left = block_values[-1] if mb_x else None
            top = block_values[(mb_y - 1) * 4 + mb_x] if mb_y else None
            prediction = ((left + top + 1) // 2 if left is not None and top is not None
                          else left if left is not None else top if top is not None else 128)
            block_values.append(max(0, min(255, prediction + (-8 if negative else 8))))
    pattern.trailing()
    pattern_nal = nal(0x65, pattern.bytes())
    pattern_stream = b''.join(b'\0\0\0\1' + item for item in (*nals[:2], pattern_nal))
    pattern_expected = bytes(block_values[(row // 16) * 4 + x // 16]
                             for row in range(64) for x in range(64)) + bytes([128]) * 2048
    decoded = subprocess.run(
        [args.ffmpeg, '-v', 'error', '-nostdin', '-f', 'h264', '-i', 'pipe:0',
         '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', 'pipe:1'],
        input=pattern_stream, capture_output=True, check=True, timeout=30)
    if decoded.stdout != pattern_expected or decoded.stderr:
        raise RuntimeError('Patterned intra reference disagrees with derived samples: ' +
                           decoded.stderr.decode(errors='replace'))
    pattern_artifacts = {'pattern64.h264': pattern_stream, 'pattern64.nal': pattern_nal,
                         'pattern64.yuv': pattern_expected}
    for name, data in pattern_artifacts.items():
        (args.out / name).write_bytes(data)
    pattern_info = dict(info, macroblock_type='I_16x16_DC', slice_qp_delta=20,
                        header_bit_size=pattern_header_bits, block_luma=block_values,
                        hashes={name: hashlib.sha256(data).hexdigest()
                                for name, data in pattern_artifacts.items()})
    (args.out / 'pattern64.json').write_text(json.dumps(pattern_info, indent=2) + '\n')
    pattern_rows = [', '.join(f'0x{byte:02x}' for byte in pattern_nal[i:i + 12])
                    for i in range(0, len(pattern_nal), 12)]
    with (args.out / 'pcm64-fixture.h').open('a') as header:
        header.write('static const u8 pattern64_nal[] = {\n\t' +
                     ',\n\t'.join(pattern_rows) + '\n};\n')
    print('Verified patterned compressed intra frame:', len(pattern_nal),
          'NAL bytes,', pattern_header_bits, 'header bits,',
          len(pattern_expected), 'matching samples; luma blocks:', block_values)
    if args.p_skip:
        predicted = Bits()
        for value in (0, 0, 0):  # first_mb, P slice, PPS id
            predicted.ue(value)
        predicted.put(1, 4)  # frame_num
        predicted.put(2, 4)  # pic_order_cnt_lsb
        predicted.put(0)  # Default single active L0 reference
        predicted.put(0)  # No reference-list modification
        predicted.put(0)  # No adaptive reference marking
        predicted.se(0)
        predicted.ue(1)  # Deblocking disabled
        predicted_header_bits = 8 + len(predicted.bits)
        predicted.ue(16)  # All sixteen macroblocks skip with inferred zero MV
        predicted.trailing()
        predicted_nal = nal(0x41, predicted.bytes())
        sequence = stream + b'\0\0\0\1' + predicted_nal
        decoded = subprocess.run(
            [args.ffmpeg, '-v', 'error', '-nostdin', '-f', 'h264', '-i', 'pipe:0',
             '-frames:v', '2', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', 'pipe:1'],
            input=sequence, capture_output=True, check=True, timeout=30)
        if decoded.stdout != expected * 2 or decoded.stderr:
            raise RuntimeError('P-skip reference did not match both generated frames: ' +
                               decoded.stderr.decode(errors='replace'))
        sequence_artifacts = {'pcm64-p.h264': sequence, 'pcm64-p.nal': predicted_nal,
                              'pcm64-p.yuv': expected}
        for name, data in sequence_artifacts.items():
            (args.out / name).write_bytes(data)
        predicted_info = dict(info, header_bit_size=predicted_header_bits, slice_type=0,
                              nal_ref_idc=2, decode_flags=8, frame_num=1,
                              pic_order_cnt_lsb=2, top_field_order_cnt=2,
                              bottom_field_order_cnt=2, reference_frame_num=0,
                              frames_verified=2, sample_bytes_verified=len(expected) * 2,
                              hashes={name: hashlib.sha256(data).hexdigest()
                                      for name, data in sequence_artifacts.items()})
        (args.out / 'pcm64-p.json').write_text(json.dumps(predicted_info, indent=2) + '\n')
        with (args.out / 'pcm64-fixture.h').open('a') as header:
            header.write('static const u8 pskip64_nal[] = {\n\t' +
                         ', '.join(f'0x{byte:02x}' for byte in predicted_nal) + '\n};\n')
        print('Verified original P-skip reference:', len(predicted_nal), 'NAL bytes,',
              predicted_header_bits, 'header bits,', len(expected) * 2,
              'matching decoded bytes across two frames')


if __name__ == '__main__':
    main()
