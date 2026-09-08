#!/usr/bin/env python3
"""Execute the actual host provisioning function across ownership transfer."""
from pathlib import Path
import subprocess,tempfile
s=Path(__file__).with_name('p22-recovery-harness.sh').read_text()
f=s[s.index('provision_stage2_store() {'):s.index('\nprepare_local_capture_dir()',s.index('provision_stage2_store() {'))]
setup=r'''
set -eu
STAGE2_POLICY=watchdog-takeover-required
STAGE2_STORE_TARGET_LIVE=/gemian/nixos/candidate
STAGE1_STORE_TARGET=/gemian/nixos/previous
STAGE2_STORE_SHA=abc
STAGE2_STORE_SIZE=123
STAGE1_STORE_SHA=def
STAGE1_STORE_SIZE=456
published=no
calls=0
device_ssh_gadget() {
 calls=$((calls+1))
 if [ "$published" = yes ]; then
  # Simulate Stage1 already unmounting p29: only RAM marker reads are valid.
  case "$1" in *sha256sum*|*/mnt/gemian*|*stat*) return 42;; esac
  case "$1" in *'/run/store-provision.ready'*) return 0;; *) return 43;; esac
 fi
 case "$calls" in 1|2) return 1;; 3) return 0;; *) return 44;; esac
}
stream_stage2_store() { published=yes; return 0; }
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'test.sh';p.write_text(setup+'\n'+f+'\nprovision_stage2_store\ntest "$STAGE2_STORE_PROVISIONED" = yes\ntest "$calls" -eq 4\n')
 subprocess.run(['sh',str(p)],check=True)
 # The old post-publication checksum must fail this same simulated handoff.
 old=f.replace('    STAGE2_STORE_TEMP=\n    STAGE2_STORE_PROVISIONED=yes\n}', '    device_ssh_gadget "sha256sum /mnt/gemian/nixos/candidate" || return 1\n    STAGE2_STORE_TEMP=\n    STAGE2_STORE_PROVISIONED=yes\n}')
 assert old!=f
 p.write_text(setup+'\n'+old+'\nprovision_stage2_store\n')
 assert subprocess.run(['sh',str(p)]).returncode!=0
print('PASS actual provisioning function: no p29 reopen after ready; old checksum race rejected')
