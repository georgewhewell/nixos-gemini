#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Original POC-type1/type2 motion streams with independent pixel expectations."""
import argparse,hashlib,importlib.util,json,subprocess
from pathlib import Path
R=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('pcm',R/'make-pcm-fixture.py');pcm=importlib.util.module_from_spec(spec);spec.loader.exec_module(pcm);Bits,nal=pcm.Bits,pcm.nal
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--ffmpeg',required=True);p.add_argument('--poc-type',type=int,choices=(1,2),default=1);p.add_argument('--offset',type=int,choices=(8,32760),default=8);p.add_argument('--direct',choices=('temporal','spatial'),default='temporal');p.add_argument('--coding',choices=('skip','direct'),default='skip');p.add_argument('--position',choices=('middle','early'),default='middle');p.add_argument('--implicit',action='store_true');a=p.parse_args()
if a.poc_type==2 and (a.offset!=8 or a.position!='middle'):p.error('POC type2 fixture uses its fixed0/2/1 counts and middle position')
if a.poc_type==1 and a.offset==32760 and a.direct=='spatial' and a.position=='middle' and a.implicit:
 p.error('This normative weighting case disagrees with the independent FFmpeg oracle; excluded from qualified fixtures')
future=a.offset if a.poc_type==1 else 2;current=future//(4 if a.position=='early' else 2)
planes=[bytes(16+(x+2*y)%220 for y in range(64) for x in range(64)),bytes(64+(x+y)%192 for y in range(32) for x in range(32)),bytes(128+(x+2*y)%128 for y in range(32) for x in range(32))]
def shift(plane,stride,delta):return bytes(plane[y*stride+max(0,min(stride-1,x+delta))] for y in range(len(plane)//stride) for x in range(stride))
original=b''.join(planes);shifted_planes=[shift(plane,stride,delta) for plane,stride,delta in zip(planes,(64,32,32),(8,4,4))];shifted=b''.join(shifted_planes)
s=Bits();s.put(77,8);s.put(0,8);s.put(10,8);s.ue(0);s.ue(0);s.ue(a.poc_type)
if a.poc_type==1:s.put(0);s.se(0);s.se(0);s.ue(1);s.se(a.offset)
s.ue(2);s.put(0);s.ue(3);s.ue(3)
for value in (1,1,0,0):s.put(value)
s.trailing();q=Bits();q.ue(0);q.ue(0);q.put(0);q.put(0)
for _ in range(3):q.ue(0)
q.put(0);q.put(2 if a.implicit else 0,2)
for _ in range(3):q.se(0)
for value in (1,0,0):q.put(value)
q.trailing();frames=[];headers=[]
def prefix(kind,frame,delta,idr=False):
 b=Bits()
 for value in (0,kind,0):b.ue(value)
 b.put(frame,4)
 if idr:b.ue(0)
 if a.poc_type==1:b.se(delta)
 return b
b=prefix(2,0,0,True);b.put(0);b.put(0);b.se(0);b.ue(1);headers.append(8+len(b.bits))
for mby in range(4):
 for mbx in range(4):
  b.ue(25);b.align()
  for plane,stride,block in zip(planes,(64,32,32),(16,8,8)):
   for row in range(block):
    for sample in plane[(mby*block+row)*stride+mbx*block:(mby*block+row)*stride+(mbx+1)*block]:b.put(sample,8)
b.trailing();frames.append(nal(0x65,b.bytes()))
b=prefix(0,1,0);b.put(0);b.put(0);b.put(0);b.se(0);b.ue(1);headers.append(8+len(b.bits))
for mb in range(16):b.ue(0);b.ue(0);b.se(32 if not mb else 0);b.se(0);b.ue(0)
b.trailing();frames.append(nal(0x41,b.bytes()))
b=prefix(1,1,current);b.put(int(a.direct=='spatial'));b.put(0);b.put(0);b.put(0);b.se(0);b.ue(1);headers.append(8+len(b.bits))
if a.coding=='skip':b.ue(16)
else:
 for _ in range(16):b.ue(0);b.ue(0);b.ue(0)
b.trailing();frames.append(nal(0x01,b.bytes()))
# H.2648.2.1 requires used differences to fit signed16bits;8.4.1.2.3 and
#8.4.3 derive temporal-direct and implicit weights from clipped differences.
td=max(-128,min(127,future));tb=max(-128,min(127,current));tx=(16384+abs(td//2))//td;scale=max(-1024,min(1023,(tb*tx+32)>>6));mv0=(scale*32+128)>>8;mv1=mv0-32
w1=scale>>2 if a.implicit and -64<=scale>>2<=128  else 32;w0=64-w1
assert mv0%8==mv1%8==0
result=[]
for original_plane,predicted_plane,stride in zip(planes,shifted_planes,(64,32,32)):
 factor=4 if stride==64 else 8
 left=shift(original_plane,stride,mv0//factor if a.direct=='temporal' else 0);right=shift(predicted_plane,stride,mv1//factor if a.direct=='temporal' else 0)
 result.append(bytes(max(0,min(255,(w0*x+w1*y+32)>>6)) if a.implicit else (x+y+1)>>1 for x,y in zip(left,right)))
final=b''.join(result);stream=b''.join(b'\x00\x00\x00\x01'+n for n in [nal(0x67,s.bytes()),nal(0x68,q.bytes()),*frames]);expected=original+final+shifted
command=[a.ffmpeg,'-v','error','-nostdin','-f','h264','-i','pipe:0','-frames:v','3','-fps_mode','passthrough','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'];run=subprocess.run(command,input=stream,check=True,capture_output=True,timeout=30)
if run.stderr or run.stdout!=expected:raise RuntimeError(f'Independent decoder differs: {run.stderr!r}; lengths={len(run.stdout)}/{len(expected)}; mismatch={sum(x!=y for x,y in zip(run.stdout,expected))}')
a.out.mkdir(parents=True,exist_ok=True);artifacts={'stream.h264':stream,'reference.yuv':expected,'final-b.nal':frames[-1],'final-b.yuv':final}
for name,data in artifacts.items():(a.out/name).write_bytes(data)
info=dict(schema=1,width=64,height=64,frames=3,poc_type=a.poc_type,offset=a.offset,direct=a.direct,coding=a.coding,position=a.position,implicit=a.implicit,pocs=[0,future,current],headers=headers,colocated_motion_quarter_luma=[32,0],temporal_direct_expected_motion={'l0':[mv0,0],'l1':[mv1,0]},implicit_weights=[w0,w1],software_decode_verified=True,hardware_tested=False,hashes={name:hashlib.sha256(data).hexdigest() for name,data in artifacts.items()});(a.out/'fixture.json').write_text(json.dumps(info,indent=2)+'\n');print(f'PASS original POCtype{a.poc_type}/offset{a.offset}/{a.direct}/{a.coding}/{a.position}/implicit={a.implicit}, POCs0/{future}/{current}')
