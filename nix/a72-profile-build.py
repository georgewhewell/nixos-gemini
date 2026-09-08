#!/usr/bin/env python3
"""Bind the imported A72 profile to this build's source and configuration inputs."""
import argparse, hashlib, json, os, re, stat
from pathlib import Path

def digest(data): return hashlib.sha256(data).hexdigest()
def encoded(value): return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
def bind_array(source, name, value, last=False):
    pattern = re.compile(r'(static const u64 '+name+r'\[ARM64_LATE_CPU_ID_WORDS\] __initconst = \{).*?(\n\};)', re.S)
    matches=list(pattern.finditer(source)); assert matches
    m=matches[-1] if last else matches[0]
    words=[value[i:i+16] for i in range(0,64,16)]
    text=m[1]+'\n\t'+', '.join('0x'+w for w in words)+','+m[2]
    return source[:m.start()]+text+source[m.end():]

parser=argparse.ArgumentParser()
parser.add_argument('phase',choices=['inputs','bind'])
parser.add_argument('--source',type=Path,default=Path('.'))
parser.add_argument('--record',type=Path,default=Path('a72-build-provenance.json'))
parser.add_argument('--config',type=Path,default=Path('.config'))
parser.add_argument('--fragments',nargs='*',default=[])
a=parser.parse_args()
if a.phase=='inputs':
    assert not a.record.exists(), 'input record must precede generated build files'
    manifest=[]
    for p in sorted(a.source.rglob('*')):
        rel=p.relative_to(a.source)
        if '.git' in rel.parts: continue
        if p.is_symlink(): manifest.append([str(rel),'symlink',os.readlink(p)])
        elif p.is_file(): manifest.append([str(rel),stat.S_IMODE(p.stat().st_mode),digest(p.read_bytes())])
    fragments=[{'name':Path(f).name,'sha256':digest(Path(f).read_bytes())} for f in a.fragments]
    imported=a.source/'tools/gemini/a72-late-cpu-import.json'
    record={'schema':'gemini-a72-build-v1','sourceDigestFormat':'sha256-canonical-path-mode-content-manifest-v1',
            'source-sha256':digest(encoded(manifest)), 'patchset-sha256':digest(imported.read_bytes()),
            'fragments':fragments}
else:
    record=json.loads(a.record.read_text())
    config=a.config.read_text();cmdline=re.search(r'^CONFIG_CMDLINE=(.+)$',config,re.M)[1]
    assert 'CONFIG_ARM64_MT6797_A72_CAPABILITY_PROFILE=y' in config
    assert 'CONFIG_ARM64_MT6797_A72_FIXTURE_EVIDENCE=y' not in config
    record['config-inputs-sha256']=digest(encoded({'fragments':record['fragments'],'forcedCmdline':cmdline}))
    record['resolved-config-sha256']=digest(a.config.read_bytes())
    p=a.source/'arch/arm64/kernel/mt6797_psci.c';source=p.read_text()
    source=bind_array(source,'mt6797_a72_source_parent_identity',record['source-sha256'])
    source=bind_array(source,'mt6797_a72_config_input_identity',record['config-inputs-sha256'],last=True)
    p.write_text(source)
    record['configured-profile-sha256']=digest(p.read_bytes())
a.record.write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
print('A72 build binding:',a.phase)
