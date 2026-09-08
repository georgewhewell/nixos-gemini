#!/usr/bin/env python3
"""Compose the T9 GPU ownership/OPP profile without changing other devices.

Run before late-CPU provenance binding. This only creates a host artifact;
it does not enable the required kernel parameter or perform device I/O.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

source, overlay, output = map(Path, sys.argv[1:])

def run(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()

def get(tree, node, prop, kind='bx'):
    return run('fdtget', '-t', kind, tree, node, prop)

def snapshot(tree, node='/'):
    data = {node: {p: get(tree, node, p)
                  for p in run('fdtget', '-p', tree, node).split()}}
    for child in run('fdtget', '-l', tree, node).split():
        data.update(snapshot(tree, node.rstrip('/') + '/' + child))
    return data

GPU='/gpu@13040000'
SCP='/power-controller@10006000'
RAIL='/i2c@11010000/regulator@1c'
OPP='/gpu-g3-opp-table'
FLAG='mediatek,gemini-gpuldo-owner'
before=snapshot(source)
assert get(source, '/', 'compatible', 's') == 'planet,gemini-pda mediatek,mt6797'
for node in [GPU, RAIL, '/i2c@11010000', '/syscon@13000000']:
    assert get(source, node, 'status', 's') == 'disabled', node
assert OPP not in before
assert FLAG not in before[SCP] and 'mfg_async-supply' not in before[SCP]
assert not {'regulator-boot-on','regulator-always-on'} & before[RAIL].keys()
allowed={
 GPU: {'status','mali-supply','nvmem-cells','nvmem-cell-names','operating-points-v2',FLAG},
 SCP: {'mfg-supply','mfg_async-supply',FLAG},
 RAIL: {'status','regulator-ramp-delay'},
 '/i2c@11010000': {'status'}, '/syscon@13000000': {'status'},
}
with tempfile.TemporaryDirectory() as tmp:
    result=Path(tmp)/'gpu.dtb'
    run('fdtoverlay','-i',source,'-o',result,overlay)
    rail=get(result,RAIL,'phandle','x')
    assert get(result,GPU,'mali-supply','x') == rail
    assert get(result,SCP,'mfg-supply','x') == rail
    for node,prop in [(GPU,'mali-supply'),(SCP,'mfg-supply')]:
        run('fdtput','-d',result,node,prop)
    run('fdtput','-t','x',result,SCP,'mfg_async-supply',rail)
    for node in [GPU,SCP]: run('fdtput',result,node,FLAG)
    after=snapshot(result)
    assert set(after)-set(before) == {OPP,OPP+'/opp-238000000'}
    assert not set(before)-set(after)
    for node,props in before.items():
        for prop in set(props)|set(after[node]):
            if props.get(prop)!=after[node].get(prop):
                assert prop in allowed.get(node,set()), (node,prop)
    assert get(result,OPP+'/opp-238000000','opp-hz','u') == '0 238000000'
    assert get(result,OPP+'/opp-238000000','opp-microvolt','u') == '846700 846700 850000'
    assert get(result,OPP+'/opp-238000000','opp-supported-hw','x') == '1000'
    assert 'mali-supply' not in after[GPU] and 'mfg-supply' not in after[SCP]
    assert get(result,SCP,'mfg_async-supply','x') == rail
    assert get(result,RAIL,'regulator-ramp-delay','u') == '32000'
    with output.open('xb') as dest: dest.write(result.read_bytes())
print('PASS GPU DT composition: single T9 OPP and exclusive async rail owner; all unrelated properties unchanged')
