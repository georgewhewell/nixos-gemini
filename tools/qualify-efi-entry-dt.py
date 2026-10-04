#!/usr/bin/env python3
"""Pinned per-entry DT files and independent Linux handoff evidence."""
import hashlib
from pathlib import Path
import subprocess
import struct
import tempfile

WORKSPACE=Path(__file__).resolve().parents[2]
BUNDLE=WORKSPACE/'handoff/nix-efi-entry-dt-candidates'
IDENTITY='49d449df65df5f412d738d56cde096e212d61d437bb7faca7afccf86f6729da3'
ENTRY='gemini-'+IDENTITY+'.conf'
PREVIOUS_SHA='de14c808c332e2a9df4461364bca149519f9087bbe13b90d3e1e411545c578a2'
FDTGET='/nix/store/74jhgsdcy9h48bx7jb5rs347bs1y0w9l-dtc-1.7.2/bin/fdtget'
LEAF='/chosen/gemini-late-cpu-provenance'
DUMPIMAGE='/nix/store/4yg7l9vj65q65kv3a7bbxr72vysp35qq-uboot-tools-only_defconfig-2026.07/bin/dumpimage'
OLD_BUNDLE=Path('/nix/store/dh5pb6bs3niz76n47h30bqjin843j5kk-gemini-mainline-nixos-bundle')

def files_profile(files):
    return files.FilesProfile(BUNDLE,'3dfa2790fabf3a7875adc0b75c27e54f8607931a923a5db15958b26f2232a76b',20510720,6)

def properties(path,node):
    def get(*args):
        return subprocess.check_output([FDTGET,*args,str(path),node],text=True).split()
    names=get('-p')
    if not names or get('-l'):
        raise RuntimeError('CPU provenance must be a populated leaf')
    return {name:bytes(int(x,16) for x in subprocess.check_output(
        [FDTGET,'-t','bx',str(path),node,name],text=True).split()) for name in names}

def verify(source,runtime,identity=IDENTITY):
    expected=properties(source,LEAF)
    if properties(runtime,LEAF)!=expected:
        raise RuntimeError('Selected entry CPU provenance differs from runtime')
    for name,value in (('gemini,efi-entry-id',identity),('gemini,uefi-dt-fixup','lk-delta-v1')):
        actual=subprocess.check_output([FDTGET,'-t','s',str(runtime),'/chosen',name],text=True).strip()
        if actual!=value:
            raise RuntimeError('Missing or incorrect entry DT handoff: '+name)
    return {name:data.hex() for name,data in expected.items()}

def evidence(directory,boot_id,files,qualify):
    _,manifest=files.payload(files_profile(files))
    source=BUNDLE/'tree'/manifest['entry_device_tree']
    provenance=verify(source,directory/'candidate-fdt.dtb')
    qualify.save(directory,'entry-dt-evidence.json',dict(boot_id=boot_id,
        entry=ENTRY,identity=IDENTITY,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        fixup='lk-delta-v1',provenance=provenance))

def cross_carrier(carrier,sha,source):
    """Bind the older fallback kernel and both carrier DT copies to p22 bytes."""
    raw=carrier.read_bytes()
    if len(raw)!=16*1024*1024 or hashlib.sha256(raw).hexdigest()!=sha or raw[:8]!=b'ANDROID!':
        raise RuntimeError('Cross-kernel carrier differs from its pinned image')
    kernel_size,kernel_addr,fit_size,fit_addr=struct.unpack_from('<4I',raw,8)
    page=struct.unpack_from('<I',raw,36)[0]
    if page!=2048 or kernel_addr!=0x40200000 or fit_addr!=0x45000000 or kernel_size%page:
        raise RuntimeError('Unexpected cross-kernel carrier layout')
    start=page+kernel_size
    if not 0x80000<=kernel_size<len(raw) or not 40<=fit_size<=len(raw)-start:
        raise RuntimeError('Cross-kernel FIT is outside the image')
    old=OLD_BUNDLE/'gemini-usb11-host.dtb'
    old_raw=old.read_bytes()
    if raw[start-len(old_raw):start]!=old_raw:
        raise RuntimeError('LK carrier DT differs from the older kernel DT')
    with tempfile.TemporaryDirectory(prefix='gemini-cross-carrier-') as tmp:
        tmp=Path(tmp);fit=tmp/'carrier.itb';fit.write_bytes(raw[start:start+fit_size])
        for index,name in enumerate(('kernel/Image.gz','gemini-usb11-host.dtb','initramfs.cpio.gz')):
            output=tmp/str(index)
            subprocess.run([DUMPIMAGE,'-T','flat_dt','-p',str(index),'-o',str(output),str(fit)],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            if output.read_bytes()!=(OLD_BUNDLE/name).read_bytes():
                raise RuntimeError('Embedded fallback payload differs from the older kernel: '+name)
    baseline=properties(old,LEAF);selected=properties(source,LEAF)
    changed=sorted(name for name in baseline.keys()|selected.keys() if baseline.get(name)!=selected.get(name))
    if not {'expected-ikconfig-identity','expected-gnu-build-id-identity'}<=set(changed):
        raise RuntimeError('Cross-kernel proof needs different kernel config and build identities')
    return dict(carrier_sha256=sha,carrier_device_tree_sha256=hashlib.sha256(old_raw).hexdigest(),
                selected_device_tree_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                changed_provenance_fields=changed,
                carrier_provenance={name:value.hex() for name,value in baseline.items()})

def cross_evidence(directory,boot_id,files,qualify,carrier,sha):
    _,manifest=files.payload(files_profile(files))
    source=BUNDLE/'tree'/manifest['entry_device_tree']
    verify(source,directory/'candidate-fdt.dtb')
    qualify.save(directory,'cross-kernel-evidence.json',dict(boot_id=boot_id,
        entry=ENTRY,**cross_carrier(carrier,sha,source)))

def previous_files(ssh,boot_id,directory,qualify,persistence,persistent_nix,files,name):
    _,manifest=files.payload(persistent_nix.files_profile(files))
    persistent_nix.activation_evidence(ssh,boot_id,directory,qualify,persistence,name=name,
        previous_files=manifest['files'],previous_sha=PREVIOUS_SHA)
