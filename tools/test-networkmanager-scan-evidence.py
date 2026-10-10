#!/usr/bin/env python3
"""Execute the actual remote scan checker against fake bus/process/fs evidence."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

helper = Path(__file__).with_name('networkmanager-scan-evidence.py')
spec = importlib.util.spec_from_file_location('scan_helper', helper)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
WIFI = '/sys/bus/platform/devices/180f0000.wifi'
EXE = '/nix/store/fixture-wpa/bin/wpa_supplicant'
START = '/nix/store/fixture-unit/bin/wpa_supplicant-start'
PRIVATE = 'PRIVATE_NETWORK_NAME_PRIVATE_MAC_PRIVATE_PASSWORD'

def case(mode):
    now, requested, attempts, polls = [100.0], [False], [0], [0]
    class FakePath:
        def __init__(self, *parts):
            self.value = '/'.join(str(p).rstrip('/') for p in parts)
        def __str__(self): return self.value
        def __eq__(self, other): return str(self) == str(other)
        def __truediv__(self, other): return FakePath(self.value, str(other))
        def is_absolute(self): return self.value.startswith('/')
        def is_file(self):
            return self.value in (EXE, '/nix/store/shadow/bin/wpa_supplicant')
        def read_bytes(self):
            assert self.value == '/proc/2/environ'
            prefix = ('relative' if mode == 'unit-relative-path' else
                      '/nix/store/shadow/bin' if mode == 'unit-shadowed' else
                      '/nix/store/missing/bin' if mode == 'unit-missing' else
                      '/nix/store/fixture-wpa/bin')
            suffix = '' if mode == 'unit-missing' else ':/nix/store/fixture-wpa/bin'
            return ('PATH=' + prefix + suffix + '\0SECRET=' + PRIVATE + '\0').encode()
        @property
        def name(self): return self.value.rsplit('/',1)[-1]
        def joinpath(self, *parts): return FakePath(self.value, *parts)
        def resolve(self, strict=False):
            paths = {'/run/current-system':'/nix/store/fixture-system',
                     WIFI+'/driver':'/sys/bus/platform/drivers/mt6797-wifi',
                     '/proc/1/exe':'/nix/store/fixture-nm/bin/NetworkManager',
                     '/proc/2/exe': EXE, '/proc/3/exe':'/nix/store/fixture-other/bin/program'}
            return FakePath(paths.get(self.value, self.value))
        def is_dir(self): return True
        def iterdir(self):
            if self.value == '/proc': return iter([FakePath('/proc',str(n)) for n in (1,2,3)])
            assert self.value == WIFI+'/net'
            return iter([FakePath(self.value,'wlan0')])
        def read_text(self):
            if self.value == '/proc/sys/kernel/random/boot_id': return 'fixture-boot\n'
            assert self.value == START
            return '#!/bin/sh\nexec '+('wpa_supplicant' if mode.startswith('unit-') else EXE)+' -u -s\n'
    def run(argv, **kwargs):
        out, error, code = '', '', 0
        if argv[0] == 'systemctl':
            if argv[1] == 'is-active': out='active'
            elif argv[3:5] == ['-p','MainPID']:
                out = '1' if argv[2] == 'NetworkManager' else ('3' if mode=='restart' and requested[0] else '2')
            else:
                assert argv[3:5] == ['-p','ExecStart']
                out='{ path='+START+' ; argv[]='+START+' ; ignore_errors=no ; }'
        elif argv[0] == 'journalctl':
            if '-k' in argv:
                if mode=='hif' and requested[0]: out='mt6797-wifi 180f0000.wifi: runtime HIF fault -5'
                if mode=='shared' and requested[0]: out='mt6797-consys 18000000.consys: CONMCU reset failed; reboot required'
            elif mode=='scan-failed' and requested[0]:
                out=json.dumps({'__MONOTONIC_TIMESTAMP':str(int(now[0]*1e6)),
                                'MESSAGE':'CTRL-EVENT-SCAN-FAILED errno=-95 '+PRIVATE})
        else:
            assert argv[0:2] == ['busctl','--system']
            if argv[2] == 'call':
                if argv[6] == 'GetDeviceByIpIface': out='o "/nm/device/1"'
                elif argv[6] == 'GetInterface': out='o "/wpa/interface/1"'
                else:
                    assert argv[6:13] == ['RequestScan','a{sv}','1','ssids','aay','2','24']
                    assert bytes(map(int,argv[13:-1])) == b'gemini-driver-scan-check'
                    assert argv[-1] == '0'
                    attempts[0]+=1
                    if mode=='request-rejected': code,error=1,'InvalidArguments '+PRIVATE
                    elif mode=='retry' and attempts[0]<3: code,error=1,'NotAllowed '+PRIVATE
                    else: requested[0]=True
            else:
                name=argv[6]
                if name=='Managed': out='b true'
                elif name=='State': out='u '+('30' if mode=='disconnected' else '50' if mode=='retry' and not requested[0] else '100')
                elif name=='ActiveConnection': out='o "/nm/active/'+('2' if mode=='connection-change' and requested[0] else '1')+'"'
                elif name=='Scanning':
                    if requested[0]: polls[0]+=1
                    out='b '+('true' if requested[0] and polls[0] == 1 else 'false')
                elif name=='LastScan': out='x '+('20' if requested[0] and polls[0]>=2 and mode!='no-completion' else '10')
                else: raise AssertionError(name)
        return subprocess.CompletedProcess(argv,code,out,error)
    output=io.StringIO()
    with patch('pathlib.Path',FakePath), patch('subprocess.run',run), \
         patch('time.monotonic',lambda:now[0]), patch('time.monotonic_ns',lambda:int(now[0]*1e9)), \
         patch('time.sleep',lambda seconds:now.__setitem__(0,now[0]+seconds)), \
         patch.object(sys,'argv',['remote','fixture-boot','/nix/store/fixture-system']), \
         contextlib.redirect_stdout(output):
        try: exec(compile(module.REMOTE_CODE,'remote-checker','exec'),{})
        except SystemExit as result: status=result.code
    raw=output.getvalue()
    assert PRIVATE not in raw and '/nm/active/' not in raw and EXE not in raw
    record=json.loads(raw)
    expected=mode in ('connected','disconnected','retry','unit-bare')
    assert (status==0)==expected, (mode,record)
    assert (record['result']=='passed')==expected, (mode,record)
    assert record['manual_connection_actions']==0 and record['scan_requests']<=1
    assert attempts[0]==(0 if mode.startswith('unit-') and not expected else 3 if mode=='retry' else 1), (mode,record)
    return {'case':mode,'checker_exit':status,'expected_result_observed':True,
            'private_output_absent':True,'request_attempts':attempts[0]}

results=[case(mode) for mode in ('connected','disconnected','retry','request-rejected',
          'scan-failed','hif','shared','restart','connection-change','no-completion',
          'unit-bare','unit-shadowed','unit-relative-path','unit-missing')]
print(json.dumps({'result':'passed','cases':results},indent=2))
print('PASS: actual remote checker preserves connections, admits one synthetic scan, retries NM admission only, awaits asynchronous completion, rejects scan/HIF/shared-radio/owner/connection failures, and retains no private network output including the actual NixOS bare-command start script and PATH failures')
