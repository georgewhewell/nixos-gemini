#!/usr/bin/env python3
"""Apply the cellular overlay to the symbolic integration DT and verify its delta."""
from pathlib import Path
import subprocess
import sys
import tempfile

source, overlay = map(Path, sys.argv[1:])
def get(tree, node, prop, kind='s'):
    return subprocess.check_output(['fdtget', '-t', kind, str(tree), node, prop], text=True).strip()
def listing(tree, node, flag):
    return subprocess.check_output(['fdtget', flag, str(tree), node], text=True).split()
def snapshot(tree, node='/'):
    data = {node: {p: get(tree, node, p, 'bx') for p in listing(tree, node, '-p')}}
    for child in listing(tree, node, '-l'):
        data.update(snapshot(tree, node.rstrip('/') + '/' + child))
    return data

def apply():
    before = snapshot(source)
    providers = {
        'infrasys': 'mediatek,mt6797-infracfg syscon',
        'scpsys': 'mediatek,mt6797-scpsys syscon',
        'watchdog': 'mediatek,mt6797-wdt mediatek,mt6589-wdt',
        'sysirq': 'mediatek,mt6797-sysirq mediatek,mt6577-sysirq',
        'pmic': 'mediatek,mt6351',
        'md1_shared_memory': 'mediatek,reserve-memory-ccci_share',
    }
    handles = {}
    for label, compatible in providers.items():
        node = get(source, '/__symbols__', label)
        assert get(source, node, 'compatible') == compatible, label
        handles[label] = get(source, node, 'phandle', 'x')
    nodes = ('/modem-lk-handoff-probe', '/modem-boot-status@10201300',
             '/modem-remap-observe@10001000', '/modem-emi-mpu',
             '/modem-cold-owner@10001000', '/modem@10014000')
    assert all(n not in before for n in nodes)
    assert get(source, '/pwrap@1000d000', 'resets', 'x') == handles['infrasys'] + ' 1'
    with tempfile.TemporaryDirectory() as directory:
        result = Path(directory) / 'result.dtb'
        subprocess.run(['fdtoverlay', '-i', str(source), '-o', str(result), str(overlay)], check=True)
        for node in nodes:
            assert get(result, node, 'status') == 'disabled'
            subprocess.run(['fdtput', '-t', 's', str(result), node, 'status', 'okay'], check=True)
        subprocess.run(['fdtput', '-t', 'x', str(result), '/pwrap@1000d000',
                        'mediatek,boot-watchdog', handles['watchdog']], check=True)
        for node, prop, expected in (
            ('/modem-cold-owner@10001000', 'resets', handles['infrasys'] + ' 3 ' + handles['infrasys'] + ' 2'),
            ('/modem-cold-owner@10001000', 'mediatek,pmic', handles['pmic']),
            ('/modem-cold-owner@10001000', 'mediatek,boot-watchdog', handles['watchdog']),
            ('/modem@10014000', 'memory-region', handles['md1_shared_memory']),
            ('/modem@10014000', 'interrupt-parent', handles['sysirq']),
        ):
            assert get(result, node, prop, 'x') == expected, (node, prop)
        after = snapshot(result)
        for node, props in before.items():
            assert node in after, node
            for prop, value in props.items():
                if (node, prop) != ('/pwrap@1000d000', 'mediatek,boot-watchdog'):
                    assert after[node].get(prop) == value, (node, prop)
            extra = set(after[node]) - set(props)
            if node == '/__symbols__':
                assert extra <= {'md1_lk_handoff_probe','md1_boot_status_observe','md1_remap_observe',
                                 'md1_emi_mpu','md1_cold_owner','md1_ccci'}, extra
            elif node == '/pwrap@1000d000':
                assert extra <= {'mediatek,boot-watchdog'}, extra
            else:
                assert not extra, (node, extra)
        assert set(after) - set(before) == set(nodes) | {
            '/modem@10014000/sim-eint-1', '/modem@10014000/sim-eint-2'}
        for index, selector in ((1, 1), (2, 0)):
            node = f'/modem@10014000/sim-eint-{index}'
            for prop, value in {'eint-number':index-1, 'debounce-us':100000, 'active-high':1,
                                'edge-triggered':0, 'socket-type':0, 'dedicated-enable':0,
                                'source-selector':selector}.items():
                assert int(get(result, node, 'mediatek,' + prop, 'u')) == value
        source.write_bytes(result.read_bytes())
    print('PASS integration cellular DT: resolved providers, six active nodes, SIM metadata; existing platform properties preserved')

apply()
