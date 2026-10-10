#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Original motion-reference H.264 stream, checked by math and FFmpeg.

ITU-T H.264 8.4.1.2.3: a long-term list0 reference gives temporal-direct
mvL0=mvCol and mvL1=0. Promotion after the co-located picture was decoded
also exercises stable identity across a changed reference marking role.
"""
import argparse,hashlib,importlib.util,json,subprocess
from pathlib import Path
R=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('pcm',R/'make-pcm-fixture.py');pcm=importlib.util.module_from_spec(spec);spec.loader.exec_module(pcm)
Bits,nal=pcm.Bits,pcm.nal
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--ffmpeg',required=True);p.add_argument('--marking',choices=('short','long','promote'),default='long');p.add_argument('--direct',choices=('temporal','spatial'),default='temporal');p.add_argument('--coding',choices=('skip','direct'),default='skip');a=p.parse_args()
w=h=64;planes=[bytes(16+(x+2*y)%220 for y in range(h) for x in range(w)),bytes(64+(x+y)%192 for y in range(h//2) for x in range(w//2)),bytes(128+(x+2*y)%128 for y in range(h//2) for x in range(w//2))]
def shift(plane,stride,delta):return bytes(plane[y*stride+max(0,min(stride-1,x+delta))] for y in range(len(plane)//stride) for x in range(stride))
original=b''.join(planes);shifted_planes=[shift(plane,stride,delta) for plane,stride,delta in zip(planes,(64,32,32),(4,2,2))];shifted=b''.join(shifted_planes)
s=Bits();s.put(77,8);s.put(0,8);s.put(10,8)
for value in (0,0,0,0,2):s.ue(value)
s.put(0);s.ue(3);s.ue(3)
for value in (1,1,0,0):s.put(value)
s.trailing()
q=Bits();q.ue(0);q.ue(0);q.put(0);q.put(0)
for _ in range(3):q.ue(0)
q.put(0);q.put(0,2)
for _ in range(3):q.se(0)
for value in (1,0,0):q.put(value)
q.trailing()
frames=[];headers=[]
b=Bits()
for value in (0,2,0):b.ue(value)
b.put(0,4);b.ue(0);b.put(0,4);b.put(0);b.put(int(a.marking=='long'));b.se(0);b.ue(1);headers.append(8+len(b.bits))
for mby in range(4):
 for mbx in range(4):
  b.ue(25);b.align()
  for plane,stride,block in zip(planes,(64,32,32),(16,8,8)):
   for row in range(block):
    for sample in plane[(mby*block+row)*stride+mbx*block:(mby*block+row)*stride+(mbx+1)*block]:b.put(sample,8)
b.trailing();frames.append(nal(0x65,b.bytes()))
b=Bits()
for value in (0,0,0):b.ue(value)
b.put(1,4);b.put(4,4);b.put(0);b.put(0)
if a.marking=='promote':
 b.put(1);b.ue(4);b.ue(2);b.ue(3);b.ue(0);b.ue(1);b.ue(0)
else:b.put(0)
b.se(0);b.ue(1);headers.append(8+len(b.bits))
for mb in range(16):b.ue(0);b.ue(0);b.se(16 if not mb else 0);b.se(0);b.ue(0)
b.trailing();frames.append(nal(0x41,b.bytes()))
b=Bits()
for value in (0,1,0):b.ue(value)
b.put(2,4);b.put(2,4);b.put(int(a.direct=='spatial'));b.put(0)
b.put(1)
if a.marking=='short':b.ue(0);b.ue(1)
else:b.ue(2);b.ue(0 if a.marking=='long' else 1)
b.ue(3)
b.put(1);b.ue(0);b.ue(0);b.ue(3)
b.se(0);b.ue(1);headers.append(8+len(b.bits))
if a.coding=='skip':b.ue(16)
else:
 for _ in range(16):b.ue(0);b.ue(0);b.ue(0)
b.trailing();frames.append(nal(0x01,b.bytes()))
if a.direct=='temporal' and a.marking!='short':final=shifted
else:
 final_planes=[]
 for original_plane,predicted_plane,stride,delta in zip(planes,shifted_planes,(64,32,32),(2,1,1)):
  left=shift(original_plane,stride,delta if a.direct=='temporal' else 0)
  right=shift(predicted_plane,stride,-delta if a.direct=='temporal' else 0)
  final_planes.append(bytes((x+y+1)>>1 for x,y in zip(left,right)))
 final=b''.join(final_planes)
stream=b''.join(b'\x00\x00\x00\x01'+n for n in [nal(0x67,s.bytes()),nal(0x68,q.bytes()),*frames]);expected=original+final+shifted
command=[a.ffmpeg,'-v','error','-nostdin','-f','h264','-i','pipe:0','-frames:v','3','-fps_mode','passthrough','-pix_fmt','yuv420p','-f','rawvideo','pipe:1']
run=subprocess.run(command,input=stream,check=True,capture_output=True,timeout=30)
if run.stderr or run.stdout!=expected:raise RuntimeError(f'Independent decoder disagrees: {run.stderr!r}; differing samples={sum(x!=y for x,y in zip(run.stdout,expected))}, lengths={len(run.stdout)}/{len(expected)}')
a.out.mkdir(parents=True,exist_ok=True)
artifacts={'stream.h264':stream,'reference.yuv':expected,'final-b.nal':frames[-1],'final-b.yuv':final}
for name,data in artifacts.items():(a.out/name).write_bytes(data)
info=dict(schema=1,width=64,height=64,frames=3,marking=a.marking,direct=a.direct,coding=a.coding,headers=headers,software_decode_verified=True,hardware_tested=False,colocated_motion_quarter_luma=[16,0],temporal_direct_expected_motion={'l0':[8,0] if a.marking=='short' else [16,0],'l1':[-8,0] if a.marking=='short' else [0,0]},hashes={name:hashlib.sha256(data).hexdigest() for name,data in artifacts.items()})
(a.out/'fixture.json').write_text(json.dumps(info,indent=2)+'\n');print(f'PASS original three-picture {a.marking}/{a.direct}/{a.coding} motion fixture: all18432 samples match')
