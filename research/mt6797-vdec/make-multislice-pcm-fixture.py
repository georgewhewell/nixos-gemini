#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Original 64x64 multislice I_PCM/P_Skip pictures, no hardware qualification."""
import argparse,hashlib,importlib.util,json,subprocess
from pathlib import Path
R=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('pcm',R/'make-pcm-fixture.py');pcm=importlib.util.module_from_spec(spec);spec.loader.exec_module(pcm);Bits,nal=pcm.Bits,pcm.nal
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--ffmpeg',required=True);p.add_argument('--partition',choices=('one','two','four','sixteen','uneven'),default='two');a=p.parse_args()
counts={'one':[16],'two':[8,8],'four':[4]*4,'sixteen':[1]*16,'uneven':[1,5,3,7]}[a.partition];starts=[];total=0
for count in counts:starts.append(total);total+=count
assert total==16
planes=[bytes(16+(x+2*y)%220 for y in range(64) for x in range(64)),bytes(64+(x+y)%192 for y in range(32) for x in range(32)),bytes(128+(x+2*y)%128 for y in range(32) for x in range(32))];picture=b''.join(planes)
s=Bits();s.put(66,8);s.put(0xc0,8);s.put(10,8)
for value in (0,0,0,0,1):s.ue(value)
s.put(0);s.ue(3);s.ue(3)
for value in (1,1,0,0):s.put(value)
s.trailing();q=Bits();q.ue(0);q.ue(0);q.put(0);q.put(0)
for _ in range(3):q.ue(0)
q.put(0);q.put(0,2)
for _ in range(3):q.se(0)
for value in (1,0,0):q.put(value)
q.trailing();frames=[];metadata=[]
for frame in range(2):
 for first,count in zip(starts,counts):
  b=Bits()
  for value in (first,2 if frame==0 else 0,0):b.ue(value)
  b.put(frame,4)
  if not frame:b.ue(0)
  b.put(2*frame,4)
  if not frame:b.put(0);b.put(0)
  else:b.put(0);b.put(0);b.put(0)
  b.se(0);b.ue(1);header=8+len(b.bits)
  if frame:b.ue(count)
  else:
   for mb in range(first,first+count):
    mby,mbx=divmod(mb,4);b.ue(25);b.align()
    for plane,stride,block in zip(planes,(64,32,32),(16,8,8)):
     for row in range(block):
      for sample in plane[(mby*block+row)*stride+mbx*block:(mby*block+row)*stride+(mbx+1)*block]:b.put(sample,8)
  b.trailing();payload=nal(0x65 if not frame else 0x41,b.bytes());name=f'frame-{frame}-slice-{first}.nal';frames.append(payload);metadata.append(dict(frame=frame,first_mb=first,last_mb=first+count-1,count=count,header_bits=header,nal=name))
stream=b''.join(b'\x00\x00\x00\x01'+n for n in [nal(0x67,s.bytes()),nal(0x68,q.bytes()),*frames]);expected=picture*2
run=subprocess.run([a.ffmpeg,'-v','error','-nostdin','-f','h264','-i','pipe:0','-frames:v','2','-fps_mode','passthrough','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],input=stream,check=True,capture_output=True,timeout=30)
assert not run.stderr and run.stdout==expected,(run.stderr,len(run.stdout),sum(x!=y for x,y in zip(run.stdout,expected)))
a.out.mkdir(parents=True,exist_ok=True);artifacts={'stream.h264':stream,'reference.yuv':expected,**{m['nal']:data for m,data in zip(metadata,frames)}}
for name,data in artifacts.items():(a.out/name).write_bytes(data)
info=dict(schema=1,width=64,height=64,frames=2,partition=a.partition,slices=metadata,software_decode_verified=True,hardware_tested=False,hashes={name:hashlib.sha256(data).hexdigest() for name,data in artifacts.items()});(a.out/'fixture.json').write_text(json.dumps(info,indent=2)+'\n');print('PASS',a.partition,len(frames),'original I_PCM/P_Skip slices and12288 independently calculated sample bytes')
