#!/usr/bin/env python3
"""Execute the production shell with filesystem and command adapters; no device IO."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

source = Path(__file__).with_name('cellular-stage2.sh').read_text()
realcat = shutil.which('cat')
python = shutil.which('python3')
realcp = shutil.which('cp')
adapter = r'''
import os,sys,subprocess
from pathlib import Path
root=Path(os.environ['FIXTURE'])
name=Path(sys.argv[0]).name;a=sys.argv[1:];case=os.environ['CASE']
with (root/'commands').open('a') as f:f.write(name+' '+' '.join(a)+'\n')
if name=='systemctl':
 if 'is-active' in a:print('inactive' if case=='watchdog-off' else 'active')
 else:print(os.environ['OWNER'])
elif name=='dmesg':
 print('MD1 accepted CCCI HS1 v2; runtime reply queued\nMD1 completed CCCI HS2' if (root/'ready').exists() else '')
 if (root/'fatal').exists():print('MT6797_CCCI_TERMINAL_FAILURE')
elif name=='mount':
 if a[1]=='ext4':
  assert a[3]=='ro,noload,nosuid,nodev,noexec'
  p=Path(a[-1])/'md';p.mkdir();(p/'seed').write_text(Path(a[-1]).name)
 else:
  assert a[1]=='tmpfs' and a[3]=='size=64m,nr_inodes=4096,mode=0700,nosuid,nodev,noexec'
 if case=='mount-fail' or case=='mount-fail-'+Path(a[-1]).name:sys.exit(1)
elif name=='restore':
 assert a==['--profile','gemini-stock-ecci-md3-v1','--sha256','1b7fb822e90492b4d14eee735c4b16bf0d34638b14407c1ee108ba8e459240c9']
 assert not (root/'ready').exists()
 for ram in ('ram','ramX','ramY'):assert (root/'run/gemini-cellular'/ram/'md/seed').exists()
 if case=='archive-fail':sys.exit(1)
 (root/'archive').touch()
 if case=='archive-drift':(root/'dev/mmcblk0p19').write_text('changed')
elif name=='helper':
 if case=='check-fail' and a[0]=='--check-roots-device':sys.exit(1)
 if a[0]=='--check-root-mount':
  assert len(a)==3 and {'Z':'nvdata','X':'protect1','Y':'protect2'}[a[1]]==Path(a[2]).name
  if case=='check-fail-'+a[1]:sys.exit(1)
 if a[0]=='--ram-roots':
  assert (root/'archive').exists()
  assert len(a)==7
  assert [Path(a[i]).name for i in range(1,7)]==['nvdata','ram','protect1','ramX','protect2','ramY']
  for i,label in [(2,'nvdata'),(4,'protect1'),(6,'protect2')]:
   assert (Path(a[i])/'md/seed').read_text()==label
  if case=='register-fail':sys.exit(1)
  (root/'ready').touch()
  if case=='fatal':(root/'fatal').touch()
  if case=='drift':(root/'dev/mmcblk0p6').write_text('changed')
  for part in ('8','9','19'):
   if case=='drift-'+part:(root/('dev/mmcblk0p'+part)).write_text('changed')
elif name=='cp':
 label=Path(a[-2]).parent.name
 if case=='copy-fail-'+label:sys.exit(1)
 ret=subprocess.call([os.environ['REALCP'],*a])
 if case=='seed-drift' and label=='protect2':(root/'dev/mmcblk0p8').write_text('changed')
 sys.exit(ret)
elif name=='cat':
 if not a:print('ERROR' if case=='bad-at' else '\r\nOK\r\n')
 else:sys.exit(subprocess.call([os.environ['REALCAT'],*a]))
elif name=='timeout':
 assert a[:2]==['-k','1'];sys.exit(subprocess.call(a[3:]))
elif name=='sleep':pass
else:raise AssertionError(name)
'''

def fixture(directory, case):
 root=Path(directory)
 for path,value in {
  'proc/sys/kernel/random/boot_id':'fixture-boot\n', 'proc/cmdline':'GEMINI_A72_CI9_M9\n',
  'run/unattended-recovery.lease-deadline':'format=gemini-unattended-recovery-lease-v1\nclock=monotonic-uptime-seconds\nstarted=10\ndeadline=730\nlease_seconds=720\n',
  'proc/uptime':'100.0 10\n', 'proc/self/mountinfo':'fixture\n',
  'sys/module/mt6797_md1_fs_provider/parameters/enable':'Y\n',
  'sys/module/mt6797_md1_fs_provider/parameters/enable_volatile':'Y\n',
  'sys/class/watchdog/watchdog0/identity':'mtk-wdt\n',
  'sys/class/watchdog/watchdog0/state':'active\n',
  'sys/class/watchdog/watchdog0/nowayout':'1\n',
  'sys/class/watchdog/watchdog0/timeout':'31\n',
  'run/unattended-recovery.watchdog-owner':str(os.getpid())+'\n',
  f'proc/{os.getpid()}/cmdline':f'fixture-busybox\0watchdog\0-F\0-t\010\0-T\031\0{root}/dev/watchdog\0',
  'dev/mmcblk0p19':'persistent backup fixture\n',
  'dev/mmcblk0p6':'persistent fixture Z\n',
  'dev/mmcblk0p8':'persistent fixture X\n',
  'dev/mmcblk0p9':'persistent fixture Y\n',
 }.items():
  # Avoid Python octal escapes in the synthetic argv.
  if path.endswith('/cmdline') and str(os.getpid()) in path:
   value='\0'.join(['fixture-busybox','watchdog','-F','-t','10','-T','31',str(root/'dev/watchdog'),''])
  p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
 fd=root/f'proc/{os.getpid()}/fd/3';fd.parent.mkdir();fd.symlink_to(root/'dev/watchdog')
 (root/'dev/wwan0at0').symlink_to('/dev/null')
 bin=root/'bin';bin.mkdir()
 for name in ('systemctl','dmesg','mount','helper','restore','cat','timeout','sleep','cp'):
  p=bin/name;p.write_text('#!'+python+'\n'+adapter);p.chmod(0o755)
 script=re.sub(r'(?<![\w/])/(?:run|proc|sys|dev)(?=[/\"\s])',lambda m:str(root)+m.group(),source)
 p=root/'script';p.write_text(script)
 env=dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],FIXTURE=str(root),CASE=case,
          OWNER=str(os.getpid()),REALCP=realcp,REALCAT=realcat,GEMINI_CELLULAR_HELPER=str(bin/'helper'),
          GEMINI_CELLULAR_RESTORE=str(bin/'restore'),GEMINI_CELLULAR_BUSYBOX='fixture-busybox')
 return root,p,env

cases=['pass','watchdog-off','check-fail','mount-fail','register-fail','fatal','bad-at','drift','drift-8','drift-9','seed-drift','late','archive-fail','archive-drift','drift-19']
cases += ['mount-fail-'+n for n in ('nvdata','protect1','protect2','ram','ramX','ramY')]
cases += ['check-fail-'+d for d in 'ZXY']
cases += ['copy-fail-'+n for n in ('nvdata','protect1','protect2')]
for case in cases:
 with tempfile.TemporaryDirectory() as directory:
  root,script,env=fixture(directory,case)
  if case=='late': (root/'proc/uptime').write_text('600.0 10\n')
  result=subprocess.run(['sh',str(script)],env=env,capture_output=True,text=True)
  success=root/'run/gemini-cellular/success'
  assert (result.returncode==0)==(case=='pass'),(case,result.stderr,(root/'run/gemini-cellular/result.log').read_text())
  assert success.exists()==(case=='pass'),case
  before=(root/'commands').read_text()
  registrations=[line for line in before.splitlines() if line.startswith('helper --ram-roots ')]
  assert len(registrations)==(1 if case in ('pass','register-fail','fatal','bad-at','drift','drift-8','drift-9','drift-19') else 0),case
  second=subprocess.run(['sh',str(script)],env=env,capture_output=True)
  assert second.returncode!=0 and (root/'commands').read_text()==before
  if case=='pass':
   assert subprocess.run(['sh',str(script),'--verify'],env=env,capture_output=True).returncode==0
   for path,value in [('proc/sys/kernel/random/boot_id','other-boot'),('dev/mmcblk0p6','changed'),('dev/mmcblk0p8','changed'),('dev/mmcblk0p9','changed'),('dev/mmcblk0p19','changed'),('proc/uptime','800.0 10')]:
    p=root/path;old=p.read_text();p.write_text(value)
    v=subprocess.run(['sh',str(script),'--verify'],env=env,capture_output=True)
    assert v.returncode!=0,(path,v.stdout,v.stderr,(root/'run/gemini-cellular/nvdata-live.sha256').read_text())
    p.write_text(old)
   (root/'fatal').touch()
   assert subprocess.run(['sh',str(script),'--verify'],env=env,capture_output=True).returncode!=0
  print('PASS actual stage2 shell:',case)
print('PASS one-shot refusal, same-boot/live-fatal/backing-drift acceptance rejection')
