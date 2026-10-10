#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Original long-term replacement and frame-number-wrap H.264 fixture."""
import argparse,hashlib,importlib.util,json,subprocess
from pathlib import Path
R=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('pcm',R/'make-pcm-fixture.py');pcm=importlib.util.module_from_spec(spec);spec.loader.exec_module(pcm)
Bits,nal=pcm.Bits,pcm.nal
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--ffmpeg',required=True);p.add_argument('--mode',choices=('keep','replace','release-replace'),default='replace');a=p.parse_args()
s=Bits();s.put(77,8);s.put(0,8);s.put(10,8)
for value in (0,0,0,2,2):s.ue(value)
s.put(0);s.ue(3);s.ue(3)
for value in (1,1,0,0):s.put(value)
s.trailing()
q=Bits();q.ue(0);q.ue(0);q.put(0);q.put(0);q.ue(0);q.ue(1);q.ue(0);q.put(0);q.put(0,2)
for _ in range(3):q.se(0)
for value in (1,0,0):q.put(value)
q.trailing();frames=[];pictures=[];headers=[]
for frame in range(24):
 colors=(16+8*frame,48+5*frame,200-4*frame);picture=b''.join(bytes([color])*size for color,size in zip(colors,(4096,1024,1024)));pictures.append(picture)
 b=Bits()
 for value in (0,2,0):b.ue(value)
 b.put(frame%16,4)
 if not frame:b.ue(0)
 b.put(frame*2,6)
 if not frame:b.put(0);b.put(0)
 elif frame==1:
  b.put(1);b.ue(4);b.ue(2);b.ue(3);b.ue(0);b.ue(1);b.ue(0)
 elif frame==12 and a.mode!='keep':
  b.put(1)
  if a.mode=='release-replace':b.ue(2);b.ue(1)
  b.ue(6);b.ue(1);b.ue(0)
 else:b.put(0)
 b.se(0);b.ue(1);headers.append(8+len(b.bits))
 for _ in range(16):
  b.ue(25);b.align()
  for color,size in zip(colors,(256,64,64)):
   for _ in range(size):b.put(color,8)
 b.trailing();frames.append(nal(0x65 if not frame else 0x41,b.bytes()))
long_frame=0 if a.mode=='keep' else 12;order=[23,long_frame]
b=Bits()
for value in (0,0,0):b.ue(value)
b.put(8,4);b.put(48,6);b.put(0);b.put(0);b.put(0);b.se(0);b.ue(1);headers.append(8+len(b.bits));final=bytearray(6144)
for mb in range(16):
 ref=mb%2;b.ue(0);b.ue(0);b.put(1-ref);b.se(0);b.se(0);b.ue(0)
 source=pictures[order[ref]]
 for stride,block,offset in [(64,16,0),(32,8,4096),(32,8,5120)]:
  x,y=(mb%4)*block,(mb//4)*block
  for row in range(y,y+block):final[offset+row*stride+x:offset+row*stride+x+block]=source[offset+row*stride+x:offset+row*stride+x+block]
b.trailing();frames.append(nal(0x41,b.bytes()));stream=b''.join(b'\x00\x00\x00\x01'+n for n in [nal(0x67,s.bytes()),nal(0x68,q.bytes()),*frames]);expected=b''.join(pictures)+final
command=[a.ffmpeg,'-v','error','-nostdin','-f','h264','-i','pipe:0','-frames:v','25','-fps_mode','passthrough','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'];run=subprocess.run(command,input=stream,check=True,capture_output=True,timeout=30)
if run.stderr or run.stdout!=expected:raise RuntimeError(f'Independent decoder differs: {run.stderr!r}; lengths={len(run.stdout)}/{len(expected)}, mismatch={sum(x!=y for x,y in zip(run.stdout,expected))}')
a.out.mkdir(parents=True,exist_ok=True);artifacts={'stream.h264':stream,'reference.yuv':expected,'final-p.nal':frames[-1],'final-p.yuv':bytes(final)}
for name,data in artifacts.items():(a.out/name).write_bytes(data)
info=dict(schema=1,width=64,height=64,frames=25,mode=a.mode,long_term_frame_idx=1,long_term_source_frame=long_frame,reference_order=order,headers=headers,frame_number_wrap_at=16,software_decode_verified=True,hardware_tested=False,hashes={name:hashlib.sha256(data).hexdigest() for name,data in artifacts.items()});(a.out/'fixture.json').write_text(json.dumps(info,indent=2)+'\n');print(f'PASS original25-picture {a.mode} chain with long-term index1 and frame-number wrap')
