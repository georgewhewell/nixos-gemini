#!/usr/bin/env python3
"""Populate only the provenance leaf after the normal A72 DT composition."""
import json, subprocess, sys
from pathlib import Path
kernel,dtb,generator=map(Path,sys.argv[1:])
record=kernel/'a72-build-provenance.json';r=json.loads(record.read_text())
cmd=[sys.executable,str(generator),'--vmlinux',str(kernel/'vmlinux'),
     '--config',str(kernel/'kernel.config'),'--image',str(kernel/'Image'),
     '--dtb',str(dtb),'--record-json',str(dtb.parent/'a72-runtime-provenance.json'),
     '--profile-id','mt6797-a53-a72-a41-v7','--build-provenance',str(record)]
for key in ['source-sha256','patchset-sha256','config-inputs-sha256','resolved-config-sha256']:
    cmd += ['--'+key,r[key]]
def snapshot(node='/'):
    def get(*args):
        return subprocess.check_output(['fdtget', *args], text=True).strip()
    data={node:{p:get('-t','bx',str(dtb),node,p)
                for p in get('-p',str(dtb),node).split()}}
    for child in get('-l',str(dtb),node).split():
        data.update(snapshot(node.rstrip('/')+'/'+child))
    return data
before=snapshot()
subprocess.run(cmd,check=True)
after=snapshot()
leaf='/chosen/gemini-late-cpu-provenance'
assert set(after)-set(before)=={leaf}, 'unexpected provenance DT nodes'
del after[leaf]
assert before==after, 'provenance changed existing DT properties'
print('PASS runtime provenance: only the chosen provenance leaf added')
