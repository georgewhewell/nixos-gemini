#!/usr/bin/env python3
"""A physical jack event must not hide a changed route or gain control."""
import os
from pathlib import Path
import subprocess

script = Path(__file__).with_name('audio-controls.awk')
route = "numid=3,iface=MIXER,name='HPL Mux'\n  ; type=ENUMERATED,access=rw------,values=1,items=3\n  : values=0\n"
gain = "numid=40,iface=MIXER,name='Headphone Volume'\n  ; type=INTEGER,access=rw---R--,values=2,min=0,max=18,step=0\n  : values=0,0\n  | dBscale-min=-10.00dB,step=1.00dB,mute=0\n"
readonly = "numid=52,iface=MIXER,name='Other Status'\n  ; type=BOOLEAN,access=r-----,values=1\n  : values=off\n"
hp = "numid=58,iface=CARD,name='Headphone Jack'\n  ; type=BOOLEAN,access=r-----,values=1\n  : values=off\n"
mic = "numid=59,iface=CARD,name='Headset Mic Jack'\n  ; type=BOOLEAN,access=r-----,values=1\n  : values=off\n"
def run(text):
    return subprocess.run([os.environ.get('AWK', 'awk'), '-f', str(script)], input=text,
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
for plugs in ((hp, mic), (hp.replace('off','on'), mic.replace('off','on'))):
    result = run(route + plugs[0] + gain + plugs[1] + readonly)
    assert result.returncode == 0 and result.stdout == route + gain + readonly, result
changed = run(route.replace('values=0\n', 'values=2\n') + hp + gain + mic)
assert changed.returncode == 0 and changed.stdout != route + gain
for invalid in (route + gain, hp + route + gain, hp + mic + hp,
                hp.replace('r-----','rw----') + mic,
                hp.replace('iface=CARD','iface=MIXER') + mic,
                hp + mic.replace('  ; type=BOOLEAN,access=r-----,values=1\n', '')):
    assert run(invalid).returncode != 0
print('PASS physical jack changes excluded; route/gain/unrelated status retained; missing, duplicate, writable and malformed jack controls rejected')
