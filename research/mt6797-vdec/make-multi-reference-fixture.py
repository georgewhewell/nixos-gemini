#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Construct original I_PCM references and a P mosaic selecting every reference.

Public H.264 syntax only. Mathematical YUV mosaics must match an independent
FFmpeg decode, including reordering and signed per-reference prediction weights.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

spec = importlib.util.spec_from_file_location('original_pcm', Path(__file__).with_name('make-pcm-fixture.py'))
pcm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pcm)
Bits, nal = pcm.Bits, pcm.nal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ffmpeg', required=True)
    parser.add_argument('--refs', type=int, default=16, choices=range(2, 17))
    parser.add_argument('--reorder', action='store_true')
    parser.add_argument('--weighted', action='store_true')
    a = parser.parse_args()
    refs, width, height = a.refs, 64, 64
    ysize, csize = width * height, width * height // 4
    sps = Bits()
    sps.put(77, 8); sps.put(0, 8); sps.put(10, 8)
    for value in (0, 2, 0, 2, refs): sps.ue(value)
    sps.put(0); sps.ue(3); sps.ue(3)
    for value in (1, 1, 0, 0): sps.put(value)
    sps.trailing()
    pps = Bits()
    pps.ue(0); pps.ue(0); pps.put(0); pps.put(0)
    pps.ue(0); pps.ue(refs - 1); pps.ue(0)
    pps.put(int(a.weighted)); pps.put(0, 2)
    for _ in range(3): pps.se(0)
    for value in (1, 0, 0): pps.put(value)
    pps.trailing()
    pictures, encoded, headers = [], [], []
    for frame in range(refs):
        colors = [16 + frame * 12, 48 + frame * 6, 200 - frame * 7]
        picture = bytes([colors[0]]) * ysize + bytes([colors[1]]) * csize + bytes([colors[2]]) * csize
        pictures.append(picture)
        b = Bits()
        for value in (0, 2, 0): b.ue(value)
        b.put(frame, 6)
        if not frame: b.ue(0)
        b.put(frame * 2, 6)
        b.put(0)
        if not frame: b.put(0)
        b.se(0); b.ue(1)
        headers.append(8 + len(b.bits))
        for _ in range(16):
            b.ue(25); b.align()
            for color, count in zip(colors, (256, 64, 64)):
                for _ in range(count): b.put(color, 8)
        b.trailing()
        encoded.append(nal(0x65 if not frame else 0x41, b.bytes()))
    default = list(reversed(range(refs)))
    selected = [refs // 3, 2 * refs // 3, refs - 1, 0] if a.reorder else []
    selected = list(dict.fromkeys(selected))
    order = selected + [frame for frame in default if frame not in selected]
    assert sorted(order) == list(range(refs))
    b = Bits()
    for value in (0, 0, 0): b.ue(value)
    b.put(refs, 6); b.put(refs * 2, 6)
    b.put(0)  # use the PPS active-list count
    b.put(int(a.reorder))
    if a.reorder:
        predicted = refs
        for frame in selected:
            difference = frame - predicted
            assert difference
            b.ue(1 if difference > 0 else 0); b.ue(abs(difference) - 1)
            predicted = frame
        b.ue(3)
    start = 8 + len(b.bits)
    weights = []
    if a.weighted:
        b.ue(1); b.ue(2)
        for index in range(refs):
            factors = [(2 + index % 3, index - 8, 1),
                       (3 + index % 2, index - 4, 2),
                       (index % 3 - 1, 100 - index, 2)]
            weights.append(factors)
            b.put(1); b.se(factors[0][0]); b.se(factors[0][1])
            b.put(1)
            for weight, offset, denom in factors[1:]: b.se(weight); b.se(offset)
    end = 8 + len(b.bits)
    b.put(0); b.se(0); b.ue(1)
    final_header = 8 + len(b.bits)
    final = bytearray(ysize + 2 * csize)
    for mb in range(16):
        reference = mb % refs
        b.ue(0); b.ue(0)  # no skip, P_L0_16x16
        if refs == 2: b.put(1 - reference)  # te(v) with maximum1
        else: b.ue(reference)
        b.se(0); b.se(0); b.ue(0)  # zero motion/residual
        source = pictures[order[reference]]
        for plane, stride, block, offset in [(0, width, 16, 0), (1, width // 2, 8, ysize), (2, width // 2, 8, ysize + csize)]:
            x, y = (mb % 4) * block, (mb // 4) * block
            for row in range(y, y + block):
                for col in range(x, x + block):
                    position = offset + row * stride + col
                    sample = source[position]
                    if a.weighted:
                        weight, bias, denom = weights[reference][plane]
                        sample = max(0, min(255, ((weight * sample + (1 << (denom - 1))) >> denom) + bias))
                    final[position] = sample
    b.trailing()
    last = nal(0x41, b.bytes())
    encoded.append(last)
    stream = b''.join(b'\x00\x00\x00\x01' + n for n in [nal(0x67, sps.bytes()), nal(0x68, pps.bytes()), *encoded])
    expected = b''.join(pictures) + final
    command = [a.ffmpeg, '-v', 'error', '-nostdin', '-f', 'h264', '-i', 'pipe:0',
               '-frames:v', str(refs + 1), '-pix_fmt', 'yuv420p', '-f', 'rawvideo', 'pipe:1']
    decoded = subprocess.run(command, input=stream, check=True, capture_output=True, timeout=30)
    if decoded.stderr or decoded.stdout != expected:
        raise RuntimeError(f'Independent decoder mismatch: {decoded.stderr!r}; {len(decoded.stdout)} vs{len(expected)}bytes')
    a.out.mkdir(parents=True, exist_ok=True)
    artifacts = {'stream.h264': stream, 'reference.yuv': decoded.stdout, 'final-p.nal': last,
                 'final-p.yuv': final, 'decode-stderr.txt': decoded.stderr}
    for name, data in artifacts.items(): (a.out / name).write_bytes(data)
    info = dict(schema=1, width=width, height=height, frames=refs + 1, references=refs,
                profile='main', entropy_coding='cavlc', weighted_prediction=a.weighted,
                reordered=a.reorder, reference_order=order, original_input='Original distinct I_PCM pictures and a P_L0_16x16 mosaic using every reference',
                software_decode_verified=True, hardware_tested=False, header_bit_size=final_header,
                intra_header_bits=headers, weight_start=start if a.weighted else 0,
                weight_end=end if a.weighted else 0, weights=weights, decode_command=command,
                hashes={name:hashlib.sha256(data).hexdigest() for name,data in artifacts.items()})
    (a.out / 'fixture.json').write_text(json.dumps(info, indent=2) + '\n')
    print(f'Verified{refs + 1} original pictures, all{refs} P references, reorder={a.reorder}, weights={a.weighted}, header{final_header}')


if __name__ == '__main__': main()
