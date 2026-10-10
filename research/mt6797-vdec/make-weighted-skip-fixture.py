#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build an original Main/CAVLC weighted P-skip header from public H.264 syntax.

An existing original I_PCM fixture supplies the first picture. FFmpeg must
independently reproduce every derived weighted luma/chroma sample.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import importlib.util

spec = importlib.util.spec_from_file_location("original_pcm", Path(__file__).with_name("make-pcm-fixture.py"))
pcm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pcm)
Bits, nal = pcm.Bits, pcm.nal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ffmpeg', required=True)
    args = parser.parse_args()
    base = json.loads((args.base / 'pcm64.json').read_text())
    w, h = base['width'], base['height']
    reference = (args.base / 'pcm64.yuv').read_bytes()
    first = (args.base / 'pcm64.nal').read_bytes()
    assert len(reference) == w * h * 3 // 2
    assert hashlib.sha256(first).hexdigest() == base['hashes']['pcm64.nal']
    assert hashlib.sha256(reference).hexdigest() == base['hashes']['pcm64.yuv']
    sps = Bits()
    sps.put(77, 8); sps.put(0, 8); sps.put(10, 8)
    for value in (0, 0, 0, 0, 1): sps.ue(value)
    sps.put(0); sps.ue(w // 16 - 1); sps.ue(h // 16 - 1)
    for value in (1, 1, 0, 0): sps.put(value)
    sps.trailing()
    pps = Bits()
    pps.ue(0); pps.ue(0); pps.put(0); pps.put(0)
    for _ in range(3): pps.ue(0)
    pps.put(1); pps.put(0, 2)
    for _ in range(3): pps.se(0)
    for value in (1, 0, 0): pps.put(value)
    pps.trailing()
    predicted = Bits()
    for value in (0, 0, 0): predicted.ue(value)
    predicted.put(1, 4); predicted.put(2, 4)
    predicted.put(0); predicted.put(0)
    start = 8 + len(predicted.bits)
    predicted.ue(1); predicted.ue(2)  # luma/chroma denominators
    predicted.put(1); predicted.se(3); predicted.se(-12)
    predicted.put(1)
    for weight, offset in ((3, 17), (-3, 127)):
        predicted.se(weight); predicted.se(offset)
    end = 8 + len(predicted.bits)
    predicted.put(0); predicted.se(0); predicted.ue(1)
    header_bits = 8 + len(predicted.bits)
    predicted.ue(w * h // 256); predicted.trailing()
    p = nal(0x41, predicted.bytes())
    stream = b''.join(b'\x00\x00\x00\x01' + item for item in
                      (nal(0x67, sps.bytes()), nal(0x68, pps.bytes()), first, p))
    def weighted(samples, weight, offset, denom):
        return bytes(max(0, min(255, ((weight * sample + (1 << (denom - 1))) >> denom) + offset))
                     for sample in samples)
    luma, chroma = w * h, w * h // 4
    second = (weighted(reference[:luma], 3, -12, 1) +
              weighted(reference[luma:luma + chroma], 3, 17, 2) +
              weighted(reference[luma + chroma:], -3, 127, 2))
    command = [args.ffmpeg, '-v', 'error', '-nostdin', '-f', 'h264', '-i', 'pipe:0',
               '-frames:v', '2', '-pix_fmt', 'yuv420p', '-f', 'rawvideo', 'pipe:1']
    decoded = subprocess.run(command, input=stream, check=True, capture_output=True, timeout=30)
    assert not decoded.stderr and decoded.stdout == reference + second
    args.out.mkdir(parents=True, exist_ok=True)
    artifacts = {'stream.h264': stream, 'reference.yuv': decoded.stdout, 'weighted64-p.nal': p,
                 'weighted64-p.yuv': second, 'decode-stderr.txt': decoded.stderr}
    for name, data in artifacts.items(): (args.out / name).write_bytes(data)
    info = dict(schema=1, width=w, height=h, frames=2, profile='main', entropy_coding='cavlc',
                weighted_prediction=True, original_input='Original I_PCM + fully constructed weighted P-skip',
                software_decode_verified=True, hardware_tested=False, header_bit_size=header_bits,
                weight_start=start, weight_end=end, luma_denom=1, chroma_denom=2,
                luma_weight=3, luma_offset=-12, chroma_weight=[3, -3], chroma_offset=[17, 127],
                decode_command=command,
                hashes={name:hashlib.sha256(data).hexdigest() for name,data in artifacts.items()})
    (args.out / 'fixture.json').write_text(json.dumps(info, indent=2) + '\n')
    print(f'Verified2 weighted P-skip pictures {w}x{h}, header{header_bits}, table{start}..{end}')


if __name__ == '__main__': main()
