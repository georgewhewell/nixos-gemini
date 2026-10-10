#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Original POC-boundary motion fixture, checked by mathematics and FFmpeg."""
import argparse,hashlib,importlib.util,json,subprocess
from pathlib import Path
R=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('pcm',R/'make-pcm-fixture.py');pcm=importlib.util.module_from_spec(spec);spec.loader.exec_module(pcm);Bits,nal=pcm.Bits,pcm.nal
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--ffmpeg',required=True);p.add_argument('--boundary',type=int,choices=(-131072,131072,262144),default=131072);p.add_argument('--direct',choices=('temporal','spatial'),default='temporal');p.add_argument('--coding',choices=('skip','direct'),default='skip');p.add_argument('--position',choices=('middle','early'),default='middle');p.add_argument('--implicit',action='store_true');a=p.parse_args()
pocs=[0,*range(-30000,a.boundary-4,-30000),a.boundary-4] if a.boundary<0 else [0,*range(30000,a.boundary-4,30000),a.boundary-4];future_poc=a.boundary+4;current_poc=a.boundary if a.position=='middle' else a.boundary-2
planes=[bytes(16+(x+2*y)%220 for y in range(64) for x in range(64)),bytes(64+(x+y)%192 for y in range(32) for x in range(32)),bytes(128+(x+2*y)%128 for y in range(32) for x in range(32))]
def shift(plane,stride,delta):return bytes(plane[y*stride+max(0,min(stride-1,x+delta))] for y in range(len(plane)//stride) for x in range(stride))
original=b''.join(planes);shifted_planes=[shift(plane,stride,delta) for plane,stride,delta in zip(planes,(64,32,32),(8,4,4))];shifted=b''.join(shifted_planes)
s=Bits();s.put(77,8);s.put(0,8);s.put(10,8)
for value in (0,0,0,12,2):s.ue(value)
s.put(0);s.ue(3);s.ue(3)
for value in (1,1,0,0):s.put(value)
s.trailing();q=Bits();q.ue(0);q.ue(0);q.put(0);q.put(0)
for _ in range(3):q.ue(0)
q.put(0);q.put(2 if a.implicit else 0,2)
for _ in range(3):q.se(0)
for value in (1,0,0):q.put(value)
q.trailing();frames=[];headers=[];pictures=[]
for frame,poc in enumerate(pocs):
 picture=original if frame==len(pocs)-1 else bytes([80+frame])*4096+bytes([100+frame])*1024+bytes([140-frame])*1024;pictures.append(picture)
 frame_planes=[picture[:4096],picture[4096:5120],picture[5120:]];b=Bits()
 for value in (0,2,0):b.ue(value)
 b.put(frame,4)
 if not frame:b.ue(0)
 b.put(poc%65536,16);b.put(0)
 if not frame:b.put(0)
 b.se(0);b.ue(1);headers.append(8+len(b.bits))
 for mby in range(4):
  for mbx in range(4):
   b.ue(25);b.align()
   for plane,stride,block in zip(frame_planes,(64,32,32),(16,8,8)):
    for row in range(block):
     for sample in plane[(mby*block+row)*stride+mbx*block:(mby*block+row)*stride+(mbx+1)*block]:b.put(sample,8)
 b.trailing();frames.append(nal(0x65 if not frame else 0x41,b.bytes()))
b=Bits()
for value in (0,0,0):b.ue(value)
b.put(len(pocs),4);b.put(future_poc%65536,16);b.put(0);b.put(0);b.put(0);b.se(0);b.ue(1);headers.append(8+len(b.bits))
for mb in range(16):b.ue(0);b.ue(0);b.se(32 if not mb else 0);b.se(0);b.ue(0)
b.trailing();frames.append(nal(0x41,b.bytes()));b=Bits()
for value in (0,1,0):b.ue(value)
b.put(len(pocs)+1,4);b.put(current_poc%65536,16);b.put(int(a.direct=='spatial'));b.put(0);b.put(0);b.put(0);b.se(0);b.ue(1);headers.append(8+len(b.bits))
if a.coding=='skip':b.ue(16)
else:
 for _ in range(16):b.ue(0);b.ue(0);b.ue(0)
b.trailing();frames.append(nal(0x01,b.bytes()))
fraction=current_poc-pocs[-1];w1=16 if a.position=='early' else 32
result=[]
for original_plane,predicted_plane,stride in zip(planes,shifted_planes,(64,32,32)):
 delta=fraction if stride==64 else fraction//2
 left=shift(original_plane,stride,delta if a.direct=='temporal' else 0)
 right=shift(predicted_plane,stride,(delta-(8 if stride==64 else 4)) if a.direct=='temporal' else 0)
 result.append(bytes(((64-w1)*x+w1*y+32)>>6 if a.implicit else (x+y+1)>>1 for x,y in zip(left,right)))
final=b''.join(result);stream=b''.join(b'\x00\x00\x00\x01'+n for n in [nal(0x67,s.bytes()),nal(0x68,q.bytes()),*frames]);expected=b''.join(picture for _,picture in sorted([*zip(pocs,pictures),(current_poc,final),(future_poc,shifted)]))
command=[a.ffmpeg,'-v','error','-nostdin','-f','h264','-i','pipe:0','-frames:v',str(len(frames)),'-fps_mode','passthrough','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'];run=subprocess.run(command,input=stream,check=True,capture_output=True,timeout=30)
if run.stderr or run.stdout!=expected:raise RuntimeError(f'Independent decoder differs: {run.stderr!r}; lengths={len(run.stdout)}/{len(expected)}; mismatch={sum(x!=y for x,y in zip(run.stdout,expected))}')
a.out.mkdir(parents=True,exist_ok=True);artifacts={'stream.h264':stream,'reference.yuv':expected,'final-b.nal':frames[-1],'final-b.yuv':final}
for name,data in artifacts.items():(a.out/name).write_bytes(data)
info=dict(schema=1,width=64,height=64,frames=len(frames),boundary=a.boundary,direct=a.direct,coding=a.coding,position=a.position,implicit=a.implicit,pocs=pocs+[future_poc,current_poc],headers=headers,colocated_motion_quarter_luma=[32,0],implicit_weights=[64-w1,w1],software_decode_verified=True,hardware_tested=False,hashes={name:hashlib.sha256(data).hexdigest() for name,data in artifacts.items()});(a.out/'fixture.json').write_text(json.dumps(info,indent=2)+'\n');print(f'PASS {len(frames)} original {a.boundary}/{a.direct}/{a.coding}/{a.position}/implicit={a.implicit} POC-boundary pictures')
