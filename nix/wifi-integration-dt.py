#!/usr/bin/env python3
"""Enable the canonical connectivity suppliers and WLAN endpoint only."""
from pathlib import Path
import subprocess,sys,tempfile
source,overlay,output=map(Path,sys.argv[1:])
def run(*args):return subprocess.check_output(list(map(str,args)),text=True).strip()
def get(tree,node,prop,kind='bx'):return run('fdtget','-t',kind,tree,node,prop)
def snapshot(tree,node='/'):
 data={node:{p:get(tree,node,p) for p in run('fdtget','-p',tree,node).split()}}
 for child in run('fdtget','-l',tree,node).split():data.update(snapshot(tree,node.rstrip('/')+'/'+child))
 return data
opt_in='mediatek,experimental-shared-emi-ownership'
before=snapshot(source)
labels={label:get(source,'/__symbols__',label,'s') for label in ['consys_emi_mpu','btif','consys','wifi']}
assert labels['consys']=='/consys@18070000'
assert labels['wifi']=='/consys@18070000/wifi@180f0000'
assert labels['consys_emi_mpu']=='/emi-mpu@10203000'
assert len(set(labels.values()))==4
for node in labels.values():assert get(source,node,'status','s')=='disabled',node
with tempfile.TemporaryDirectory() as d:
 result=Path(d)/'wifi.dtb';run('fdtoverlay','-i',source,'-o',result,overlay)
 run('fdtput',result,labels['consys_emi_mpu'],opt_in)
 after=snapshot(result);assert before.keys()==after.keys(),'unexpected nodes'
 for node,props in before.items():
  for prop in props.keys()|after[node].keys():
   if props.get(prop)!=after[node].get(prop):
    assert (node in labels.values() and prop=='status') or (node==labels['consys_emi_mpu'] and prop==opt_in and prop not in props and after[node][prop]==''),(node,prop)
 for node in labels.values():assert get(result,node,'status','s')=='okay'
 assert get(result,'/consys@18070000/bluetooth','status','s')=='disabled'
 with output.open('xb') as f:f.write(result.read_bytes())
print('PASS connectivity DT: four activation statuses and explicit shared-EMI opt-in; modem, GPU, A72, storage and all other properties preserved')
