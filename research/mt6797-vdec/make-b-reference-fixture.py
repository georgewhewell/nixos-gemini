#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Construct original I_PCM references and a reordered B prediction mosaic.

Public H.264 syntax only. Mathematical YUV mosaics must match an independent
FFmpeg decode, including forward/backward prediction and explicit/implicit weights.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from h264_reference_marking import MODES, long_term_indices, write_reference_marking

spec = importlib.util.spec_from_file_location('original_pcm', Path(__file__).with_name('make-pcm-fixture.py'))
pcm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pcm)
Bits, nal = pcm.Bits, pcm.nal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ffmpeg', required=True)
    parser.add_argument('--refs', type=int, default=16, choices=range(2, 17))
    parser.add_argument('--prediction', choices=('l0', 'l1', 'bi'), default='bi')
    parser.add_argument('--weighting', choices=('none', 'explicit', 'implicit'), default='none')
    parser.add_argument('--long-term', choices=MODES, default='none')
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
    pps.ue(0); pps.ue(refs - 1); pps.ue(refs - 1)
    pps.put(0); pps.put({'none': 0, 'explicit': 1, 'implicit': 2}[a.weighting], 2)
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
        b.put(frame * 4, 6)
        write_reference_marking(b, frame, refs, a.long_term)
        b.se(0); b.ue(1)
        headers.append(8 + len(b.bits))
        for _ in range(16):
            b.ue(25); b.align()
            for color, count in zip(colors, (256, 64, 64)):
                for _ in range(count): b.put(color, 8)
        b.trailing()
        encoded.append(nal(0x65 if not frame else 0x41, b.bytes()))
    current_poc = 4 * (refs - 1) - 3
    long_term = long_term_indices(refs, a.long_term)
    past = [frame for frame in range(refs) if frame not in long_term and frame * 4 < current_poc]
    future = [frame for frame in range(refs) if frame not in long_term and frame * 4 > current_poc]
    long_order = sorted(long_term, key=long_term.get)
    orders = [list(reversed(past)) + future + long_order, future + list(reversed(past)) + long_order]
    if orders[0] == orders[1] and refs > 1:
        orders[1][0], orders[1][1] = orders[1][1], orders[1][0]
    assert all(sorted(order) == list(range(refs)) for order in orders)
    b = Bits()
    for value in (0, 1, 0): b.ue(value)
    b.put(refs, 6); b.put(current_poc, 6)
    b.put(1)  # direct_spatial_mv_pred_flag; explicit MBs below
    b.put(0)  # PPS active-list counts
    b.put(0); b.put(0)  # no list modifications
    start = 8 + len(b.bits)
    weights = [[], []]
    if a.weighting == 'explicit':
        b.ue(1); b.ue(2)
        for which in range(2):
            for index in range(refs):
                factors = [(2 + (index + which) % 3, index - 8 + which * 4, 1),
                           (3 + (index + which) % 2, index - 4 + which, 2),
                           ((index + which) % 3 - 1, 100 - index - which * 5, 2)]
                weights[which].append(factors)
                b.put(1); b.se(factors[0][0]); b.se(factors[0][1])
                b.put(1)
                for weight, offset, denom in factors[1:]: b.se(weight); b.se(offset)
    end = 8 + len(b.bits)
    b.se(0); b.ue(1)  # nonreference B has no reference marking
    final_header = 8 + len(b.bits)
    final = bytearray(ysize + 2 * csize)
    clip = lambda v,lo,hi: max(lo,min(hi,v))
    for mb in range(16):
        indices = [mb % refs, (mb * 5 + 3) % refs]
        selected_lists = [0] if a.prediction == 'l0' else [1] if a.prediction == 'l1' else [0,1]
        b.ue(0); b.ue({'l0':1,'l1':2,'bi':3}[a.prediction])
        for which in selected_lists:
            if refs == 2: b.put(1 - indices[which])
            else: b.ue(indices[which])
        for _ in selected_lists: b.se(0); b.se(0)
        b.ue(0)
        sources = [pictures[orders[which][indices[which]]] for which in range(2)]
        for plane, stride, block, offset in [(0,width,16,0),(1,width//2,8,ysize),(2,width//2,8,ysize+csize)]:
            x,y = (mb%4)*block,(mb//4)*block
            for row in range(y,y+block):
                for col in range(x,x+block):
                    position=offset+row*stride+col
                    samples=[source[position] for source in sources]
                    if a.weighting == 'explicit':
                        factors=[weights[which][indices[which]][plane] for which in range(2)]
                        if len(selected_lists)==1:
                            which=selected_lists[0];weight,bias,denom=factors[which]
                            sample=((weight*samples[which]+(1<<(denom-1)))>>denom)+bias
                        else:
                            denom=factors[0][2]
                            sample=((factors[0][0]*samples[0]+factors[1][0]*samples[1]+(1<<denom))>>(denom+1))+((factors[0][1]+factors[1][1]+1)>>1)
                    elif len(selected_lists)==1:
                        sample=samples[selected_lists[0]]
                    elif a.weighting == 'implicit':
                        poc0,poc1=[orders[which][indices[which]]*4 for which in range(2)]
                        td=clip(poc1-poc0,-128,127);tb=clip(current_poc-poc0,-128,127)
                        w1=32
                        if td and not any(orders[which][indices[which]] in long_term for which in range(2)):
                            # H264 integer division truncates toward zero.
                            tx=int((16384+abs(int(td/2)))/td)
                            scale=clip((tb*tx+32)>>6,-1024,1023)
                            if -64 <= scale>>2 <= 128: w1=scale>>2
                        sample=((64-w1)*samples[0]+w1*samples[1]+32)>>6
                    else:
                        sample=(samples[0]+samples[1]+1)>>1
                    final[position]=clip(sample,0,255)
    b.trailing()
    last = nal(0x01, b.bytes())
    encoded.append(last)
    stream = b''.join(b'\x00\x00\x00\x01' + n for n in [nal(0x67, sps.bytes()), nal(0x68, pps.bytes()), *encoded])
    ordered = [(i*4,picture) for i,picture in enumerate(pictures)]+[(current_poc,bytes(final))]
    expected = b''.join(picture for _,picture in sorted(ordered))
    command = [a.ffmpeg, '-v', 'error', '-nostdin', '-f', 'h264', '-i', 'pipe:0',
               '-frames:v', str(refs + 1), '-fps_mode', 'passthrough', '-pix_fmt', 'yuv420p', '-f', 'rawvideo', 'pipe:1']
    decoded = subprocess.run(command, input=stream, check=True, capture_output=True, timeout=30)
    if decoded.stderr or decoded.stdout != expected:
        raise RuntimeError(f'Independent decoder mismatch: {decoded.stderr!r}; {len(decoded.stdout)} vs{len(expected)}bytes')
    a.out.mkdir(parents=True, exist_ok=True)
    artifacts = {'stream.h264': stream, 'reference.yuv': decoded.stdout, 'final-b.nal': last,
                 'final-b.yuv': final, 'decode-stderr.txt': decoded.stderr}
    for name, data in artifacts.items(): (a.out / name).write_bytes(data)
    info = dict(schema=1, width=width, height=height, frames=refs + 1, references=refs,
                profile='main', entropy_coding='cavlc', weighted_prediction=a.weighting, prediction=a.prediction,
                reference_orders=orders, current_poc=current_poc, long_term=a.long_term,
                long_term_indices=long_term, display_pocs=sorted(poc for poc,_ in ordered), original_input='Original distinct I_PCM pictures and a B16x16 mosaic with independent list0/list1 selections',
                software_decode_verified=True, hardware_tested=False, header_bit_size=final_header,
                intra_header_bits=headers, weight_start=start if a.weighting == "explicit" else 0,
                weight_end=end if a.weighting == "explicit" else 0, weights=weights, decode_command=command,
                hashes={name:hashlib.sha256(data).hexdigest() for name,data in artifacts.items()})
    (a.out / 'fixture.json').write_text(json.dumps(info, indent=2) + '\n')
    print(f'Verified{refs + 1} original pictures, {refs} references in both B lists, prediction={a.prediction}, weights={a.weighting}, header{final_header}')


if __name__ == '__main__': main()
