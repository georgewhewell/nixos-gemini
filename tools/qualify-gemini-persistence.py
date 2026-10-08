#!/usr/bin/env python3
"""Evidence for p32 home and Nix persistence across supervised M69 boots.

M69 lacks NET_NS, so ordinary sandboxed derivations cannot start. A local
fixed-output derivation tests store writes with the existing sandbox policy;
it inherits networking by Nix's normal fixed-output rules but uses no network.
This does not qualify ordinary builds or the missing M69 daemon units.
"""
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import uuid

BUSYBOX='/nix/store/x81n0zd9g0hln8s4vnli06qskzim48xs-busybox-aarch64-unknown-linux-gnu-1.36.1'
NIX='/nix/store/901bv963zyappp014njspvbif0k3yzyq-nix-aarch64-unknown-linux-gnu-2.13.6/bin'
FS_UUID='5d978ad4-a987-4b3f-bef6-f73ad7c2d986'
MOUNTS=('/persist','/home','/nix/var','/nix/store','/nix/.ro-store')


def verify_mounts(raw, devno):
    mounts={}
    for line in raw.splitlines():
        left,right=line.split(' - ',1)
        fields=left.split();fs=right.split()
        target=fields[4]
        if target not in MOUNTS:continue
        m=dict(id=fields[0],parent=fields[1],device=fields[2],root=fields[3],
               options=fields[5].split(','),type=fs[0],source=fs[1],super=fs[2].split(','))
        if target in mounts:
            # NixOS stage 2 protects the store with a read-only bind over
            # the writable overlay. Nix remounts that bind for its writes.
            base=mounts[target]
            if (target!='/nix/store' or 'bind' in base or m['parent']!=base['id'] or
                    any(m[k]!=base[k] for k in ('device','root','type','source','super'))):
                raise RuntimeError('Unexpected stacked persistence mount: '+target)
            base['bind']=m
        else:mounts[target]=m
    persistent = mounts.get('/nix/store', {}).get('type') == 'ext4'
    expected = set(MOUNTS) - ({'/nix/.ro-store'} if persistent else set())
    if set(mounts)!=expected:raise RuntimeError('Missing persistence mount')
    data_mounts = [('/persist','/'),('/home','/home'),
                   ('/nix/var','/nixos/nix/var' if persistent else '/nix/var')]
    if persistent: data_mounts.append(('/nix/store','/nixos/nix/store'))
    for target,root in data_mounts:
        m=mounts[target]
        if (m['device']!=devno or m['root']!=root or m['type']!='ext4' or
                m['source']!='/dev/mmcblk0p32' or 'rw' not in m['options']):
            raise RuntimeError('Persistence mount identity differs: '+target)
    if persistent:
        if 'ro' not in mounts['/nix/store'].get('bind', {}).get('options', []):
            raise RuntimeError('NixOS did not protect the persistent store')
        return mounts
    lower=mounts['/nix/.ro-store'];store=mounts['/nix/store']
    if lower['type']!='squashfs' or 'ro' not in lower['options']:
        raise RuntimeError('Store lower layer is not read-only squashfs')
    if store['type']!='overlay' or 'rw' not in store['options']:
        raise RuntimeError('Store is not a writable overlay')
    opts=dict(x.split('=',1) for x in store['super'] if '=' in x)
    for key,path in (('lowerdir','/nix/.ro-store'),('upperdir','/persist/nix/upper'),
                     ('workdir','/persist/nix/work')):
        if opts.get(key) not in (path,'/mnt/nixos'+path):
            raise RuntimeError('Unexpected overlay '+key)
    return mounts


def run(ssh, command, directory, name, timeout=60):
    (directory/(name+'.sh')).write_text(command)
    result=subprocess.run(ssh+[command],capture_output=True,text=True,timeout=timeout)
    (directory/(name+'.stdout')).write_text(result.stdout)
    (directory/(name+'.stderr')).write_text(result.stderr)
    result.check_returncode()
    return result.stdout


def store_state_check(system):
    return f'''if test -f /nix/store/.gemini-system; then
 systemctl is-active gemini-nix-db-seed >/dev/null
 test "$(cat /nix/var/nix/gemini-seeded-system)" = {shlex.quote(Path(system).name)}
 test "$(readlink /nix/var/nix/gcroots/gemini-booted-system)" = /run/booted-system
else
 test /nix/store -ef /persist/nixos/nix/store
 test "$(readlink /nix/var/nix/gcroots/booted-system)" = /run/booted-system
fi'''


def store_checks(previous):
    """Shell that verifies a token output from either installed store layout.

    M69 runs an overlay store whose upper layer and state are /nix/upper and
    /nix/var on p32. The normal generation mounts /persist/nixos/nix. Each
    can see the other's files on p32 but not its store at /nix/store, so a
    foreign token is checked by bytes and root link; its own system checks
    the database identity.
    """
    built=previous.get('store','m69-overlay')
    if built not in ('m69-overlay','normal'): raise ValueError('Unknown token store')
    name=Path(previous['output']).name
    root=Path(previous['gcroot']).name
    native=f''' test "$(readlink {previous['gcroot']})" = {previous['output']}
 {NIX}/nix-store --check-validity {previous['output']}
 printf 'output_sha256='; sha256sum {previous['output']} | cut -d' ' -f1
 printf 'nix_hash='; {NIX}/nix-store --query --hash {previous['output']}
 printf 'deriver='; {NIX}/nix-store --query --deriver {previous['output']}'''
    if built=='m69-overlay':
        foreign=f''' test "$(readlink /persist/nix/var/nix/gcroots/{root})" = {previous['output']}
 printf 'output_sha256='; sha256sum /persist/nix/upper/{name} | cut -d' ' -f1
 printf 'store=foreign\\n'
'''
        same='test -f /nix/store/.gemini-system'
    else:
        foreign=f''' test "$(readlink /persist/nixos/nix/var/nix/gcroots/{root})" = {previous['output']}
 printf 'output_sha256='; sha256sum /persist/nixos/nix/store/{name} | cut -d' ' -f1
 printf 'store=foreign\\n'
'''
        same='test ! -f /nix/store/.gemini-system'
    return f'if {same}; then\n{native}\nelse\n{foreign}\nfi'


def evidence(ssh, boot_id, directory, qualify, previous=None, system=None):
    phase='persistence-after' if previous else 'persistence-before'
    system=system or qualify.ACCEPTED_SYSTEM
    raw=run(ssh,f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(boot_id)}
test "$(readlink /run/current-system)" = {system}
test "$(dumpe2fs -h /dev/mmcblk0p32 2>/dev/null | sed -n 's/^Filesystem UUID: *//p')" = {FS_UUID}
{store_state_check(system)}
{NIX}/nix-store --check-validity {system} {BUSYBOX}
printf 'device='; cat /sys/class/block/mmcblk0p32/dev
cat /proc/self/mountinfo
''',directory,phase+'-mounts')
    devno,raw=raw.split('\n',1)
    if not re.fullmatch(r'device=\d+:\d+',devno):raise RuntimeError('Missing p32 device number')
    mounts=verify_mounts(raw,devno.removeprefix('device='))
    if previous is None:
        token=uuid.uuid4().hex
        content='Gemini persistent home and Nix build '+token+'\n'
        content_sha=hashlib.sha256(content.encode()).hexdigest()
        home='/home/gemini/.gemini-persistence-'+token
        gcroot='/nix/var/nix/gcroots/gemini-persistence-'+token
        expr=('builtins.derivation { name = "gemini-persistence-'+token+'"; '
              'system = "aarch64-linux"; builder = (builtins.storePath '+json.dumps(BUSYBOX)+') + "/bin/sh"; '
              'args = [ "-c" '+json.dumps("printf '%s\\n' "+shlex.quote(content.rstrip('\n'))+' > "$out"')+' ]; '
              'outputHashMode = "flat"; outputHashAlgo = "sha256"; outputHash = '+json.dumps(content_sha)+'; }')
        output=run(ssh,f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(boot_id)}
test ! -e {home} && test ! -L {home}
test ! -e {gcroot} && test ! -L {gcroot}
(set -C; printf '%s' {shlex.quote(content)} > {home})
chown gemini:users {home}
chmod 0600 {home}
{NIX}/nix-build --store local --no-out-link --option substituters '' --option builders '' --expr {shlex.quote(expr)}
''',directory,phase+'-build').strip()
        if not re.fullmatch(r'/nix/store/[0-9a-z]{32}-gemini-persistence-'+token,output):
            raise RuntimeError('Unexpected Nix build output')
        built_in=run(ssh,'test -f /nix/store/.gemini-system && echo m69-overlay || echo normal',
                     directory,phase+'-store').strip()
        previous=dict(boot_id=boot_id,home=home,output=output,gcroot=gcroot,build_store='local',store=built_in,
                      build_type='fixed-output',sandbox_setting=True,ordinary_builds_qualified=False,
                      content_sha256=content_sha)
        run(ssh,f'''set -eu
{NIX}/nix-store --realise {output} --add-root {gcroot}
sync
''',directory,phase+'-root')
    elif previous['boot_id']==boot_id:
        raise RuntimeError('Persistence was checked in the original boot')
    command=f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(boot_id)}
test "$(stat -c %U:%G:%a {previous['home']})" = gemini:users:600
printf 'home_sha256='; sha256sum {previous['home']} | cut -d' ' -f1
{store_checks(previous)}
'''
    observed=dict(line.split('=',1) for line in run(ssh,command,directory,phase+'-verify').splitlines())
    verify_content(previous,observed)
    result=dict(previous,observed_boot_id=boot_id,mounts=mounts,**observed,
                survived_reboot=(phase=='persistence-after'))
    qualify.save(directory,phase+'.json',result)
    return result


def verify_content(expected,observed):
    if any(observed.get(k)!=expected['content_sha256'] for k in ('home_sha256','output_sha256')):
        raise RuntimeError('Persistent home or Nix output bytes changed')
    if observed.get('store')=='foreign':
        return
    if not observed.get('nix_hash','').startswith('sha256:'):
        raise RuntimeError('Nix database lacks the output hash')
    name=expected['output'].split('-',1)[1]
    if not re.fullmatch(r'/nix/store/[0-9a-z]{32}-'+re.escape(name)+r'\.drv',observed.get('deriver','')):
        raise RuntimeError('Nix output lacks its registered derivation')
    for key in ('nix_hash','deriver'):
        if key in expected and observed[key]!=expected[key]:
            raise RuntimeError('Persistent Nix database identity changed: '+key)
