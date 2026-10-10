#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Encode original changing YUV pixels with open-source x264 for decode tests.

This is a userspace fixture generator, not a hardware encoder implementation.
The comparison reference is FFmpeg's decoded lossy stream, not the input pixels.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ffmpeg', required=True)
    parser.add_argument('--width', type=int, default=128)
    parser.add_argument('--height', type=int, default=96)
    parser.add_argument('--frames', type=int, default=8)
    parser.add_argument('--refs', type=int, default=1, choices=range(1, 17),
                        help='Number of short-term references for separate hardware qualification')
    parser.add_argument('--entropy', choices=('cavlc', 'cabac'), default='cavlc',
                        help='CABAC generates Main profile for separate hardware qualification')
    parser.add_argument('--deblocking', action='store_true',
                        help='Generate a deblocked stream for separate hardware qualification')
    parser.add_argument('--transform-8x8', action='store_true',
                        help='Generate High profile with actual adaptive 8x8 transform use')
    parser.add_argument('--scaling', choices=('flat', 'jvt', 'custom'), default='flat',
                        help='High-profile quantization matrices for separate qualification')
    parser.add_argument('--weighted-pred', action='store_true',
                        help='Enable x264 weighted P prediction in Main/High profile')
    parser.add_argument('--fade', action='store_true',
                        help='Change brightness/chroma offsets to exercise nondefault weights')
    args = parser.parse_args()
    w, h, count = args.width, args.height, args.frames
    cabac = args.entropy == 'cabac'
    high = args.transform_8x8 or args.scaling != 'flat'
    profile = 'high' if high else 'main' if cabac or args.weighted_pred else 'baseline'
    if not (64 <= w <= 1920 and 64 <= h <= 1088 and not w % 16 and not h % 2
            and 2 <= count <= 32):
        parser.error('Use width64..1920 in steps16, even height64..1088 and2..32frames')
    args.out.mkdir(parents=True, exist_ok=True)
    original = bytearray()
    for frame in range(count):
        original.extend((16 + (x * 3 + row * 2) % 128 + frame * 3) if args.fade else
                        16 + (x * 3 + row * 2 + frame * 7) % 220
                        for row in range(h) for x in range(w))
        original.extend((64 + (x + row) % 96 + frame) if args.fade else
                        64 + (x + row + frame * 3) % 128
                        for row in range(h // 2) for x in range(w // 2))
        original.extend((96 + (x * 2 + row) % 96 + frame * 2) if args.fade else
                        128 + (x * 2 + row + frame * 2) % 112
                        for row in range(h // 2) for x in range(w // 2))
    source, stream, reference = [args.out / name for name in
                                 ('original.yuv', 'stream.h264', 'reference.yuv')]
    source.write_bytes(original)
    matrix_params = ''
    if args.scaling == 'jvt':
        matrix_params = ':cqm=jvt'
    elif args.scaling == 'custom':
        # Distinct, nonuniform raster-order lists expose list selection,
        # coefficient byte order and scan-order errors in a hardware port.
        lists = {name: [8 + (i * 3 + row * 5 + seed) % 24
                        for row in range(size) for i in range(size)]
                 for name, size, seed in [('cqm4iy', 4, 1), ('cqm4ic', 4, 4),
                                         ('cqm4py', 4, 7), ('cqm4pc', 4, 10),
                                         ('cqm8i', 8, 13), ('cqm8p', 8, 16)]}
        matrix_params = ''.join(':' + name + '=' + ','.join(map(str, values))
                                for name, values in lists.items())
        (args.out / 'custom-matrices.json').write_text(json.dumps(lists, indent=2) + '\n')
    command = [args.ffmpeg, '-v', 'info', '-nostdin', '-y', '-f', 'rawvideo',
               '-pix_fmt', 'yuv420p', '-s', f'{w}x{h}', '-r', '25', '-i', str(source),
               '-frames:v', str(count), '-c:v', 'libx264', '-profile:v', profile,
               '-preset', 'fast', '-qp', '24', '-bf', '0', '-refs', str(args.refs),
               '-x264-params', ('cabac=1:' if cabac else 'cabac=0:' if high or args.weighted_pred else '') +
               f'no-deblock={0 if args.deblocking else 1}:'
               f'8x8dct={int(args.transform_8x8)}:weightp={2 if args.weighted_pred else 0}:repeat-headers=1:'
               f'threads=1:scenecut=0:keyint={count}:min-keyint={count}' + matrix_params,
               str(stream)]
    encode = subprocess.run(command, check=True, capture_output=True)
    (args.out / 'encode-stderr.txt').write_bytes(encode.stderr)
    if b'Error parsing option' in encode.stderr:
        raise RuntimeError('Fixture encoder rejected an option')
    decode_command = [args.ffmpeg, '-v', 'error', '-nostdin', '-y', '-f', 'h264',
                      '-i', str(stream), '-pix_fmt', 'yuv420p', '-f', 'rawvideo',
                      str(reference)]
    decode = subprocess.run(decode_command, check=True, capture_output=True)
    (args.out / 'decode-stderr.txt').write_bytes(decode.stderr)
    if decode.stderr:
        raise RuntimeError('Software reference decoder reported errors')
    if reference.stat().st_size != count * w * h * 3 // 2:
        raise RuntimeError('Software decode returned the wrong picture count/size')
    trace_command = [args.ffmpeg, '-nostdin', '-i', str(stream), '-c', 'copy',
                     '-bsf:v', 'trace_headers', '-f', 'null', '-']
    trace = subprocess.run(trace_command, check=True, capture_output=True)
    (args.out / 'public-syntax-trace.txt').write_bytes(trace.stderr)
    syntax = trace.stderr.decode()
    for field, expected in [('profile_idc', 100 if high else 77 if cabac or args.weighted_pred else 66),
                            ('entropy_coding_mode_flag', int(cabac)),
                            ('weighted_pred_flag', int(args.weighted_pred)), ('weighted_bipred_idc', 0),
                            ('num_ref_idx_l0_default_active_minus1', args.refs - 1),
                            ('max_num_ref_frames', args.refs),
                            ('frame_mbs_only_flag', 1),
                            ('pic_width_in_mbs_minus1', w // 16 - 1),
                            ('pic_height_in_map_units_minus1', (h + 15) // 16 - 1),
                            ('frame_cropping_flag', int(bool(h % 16))),
                            ('disable_deblocking_filter_idc', 0 if args.deblocking else 1)]:
        values = re.findall(r'\b' + field + r'\s+\S+\s+=\s+(\d+)', syntax)
        if not values or any(int(v) != expected for v in values):
            raise RuntimeError(f'Unexpected public syntax {field}: {values}')
    if high:
        transforms = re.findall(r'\btransform_8x8_mode_flag\s+\S+\s+=\s+(\d+)', syntax)
        if not transforms or any(int(v) != int(args.transform_8x8) for v in transforms):
            raise RuntimeError(f'Unexpected 8x8 transform syntax: {transforms}')
        present = re.findall(r'\b(?:seq|pic)_scaling_matrix_present_flag\s+\S+\s+=\s+(\d+)', syntax)
        if not present or (any(int(v) for v in present) != (args.scaling != 'flat')):
            raise RuntimeError(f'Unexpected scaling matrix syntax: {present}')
    transform_usage = re.findall(r'8x8 transform intra:([\d.]+)% inter:([\d.]+)%',
                                encode.stderr.decode())
    weight_flags = re.findall(r'\bluma_weight_l0_flag\[0\]\s+\S+\s+=\s+(\d+)', syntax)
    if args.weighted_pred and args.fade and not any(int(v) for v in weight_flags):
        raise RuntimeError('Fade fixture did not encode actual nondefault luma weights')
    if args.transform_8x8 and (not transform_usage or
                              not any(float(v) > 0 for pair in transform_usage for v in pair)):
        raise RuntimeError('Encoder did not report actual 8x8 transform use')
    if h % 16:
        crop = re.findall(r'\bframe_crop_bottom_offset\s+\S+\s+=\s+(\d+)', syntax)
        if not crop or any(int(v) != (16 - h % 16) // 2 for v in crop):
            raise RuntimeError(f'Unexpected progressive4:2:0 crop bottom: {crop}')
    starts = re.findall(r'\bfirst_mb_in_slice\s+\S+\s+=\s+(\d+)', syntax)
    if len(starts) != count or any(int(v) for v in starts):
        raise RuntimeError('Expected exactly one complete slice per frame')
    names = ('original.yuv', 'stream.h264', 'reference.yuv', 'encode-stderr.txt',
             'decode-stderr.txt', 'public-syntax-trace.txt')
    metadata = dict(schema=1, width=w, height=h, frames=count,
                    original_input='Changing arithmetic Y/U/V gradients; generated here',
                    fixture_encoder='Open-source FFmpeg libx264; no hardware encoder claim',
                    reference='Independent FFmpeg software decode of the lossy stream',
                    software_decode_verified=True, hardware_tested=False,
                    coded_height=(h+15)//16*16, storage_height=(h+31)//32*32,
                    deblocking=args.deblocking, entropy_coding=args.entropy, profile=profile,
                    transform_8x8=args.transform_8x8, scaling=args.scaling,
                    weighted_prediction=args.weighted_pred, fade=args.fade, references=args.refs,
                    encoded_luma_weight_flags=weight_flags,
                    encoder_transform_usage=transform_usage,
                    encode_command=command, decode_command=decode_command,
                    public_syntax_checked=True,
                    hashes={n: hashlib.sha256((args.out / n).read_bytes()).hexdigest()
                            for n in names})
    (args.out / 'fixture.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Verified {count} {profile} frames, {w}x{h}: '
          f'{stream.stat().st_size} input bytes, {reference.stat().st_size} reference bytes')


if __name__ == '__main__':
    main()
