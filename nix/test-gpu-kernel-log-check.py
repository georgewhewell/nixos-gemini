from pathlib import Path
import subprocess,tempfile
checker=Path(__file__).with_name('gpu-kernel-log-check.sh')
zero='[ 120.978347] panfrost 13040000.gpu: MT6797_GPU_DIAG event=submit as=0 status=00000000 fault=00000000 tt_flags=007 memattr=0000000000484d48 transcfg=0000000000000000'
warning='[ 120.00] panfrost 13040000.gpu: [drm:panfrost_devfreq_init [panfrost]] Failed to register cooling device'
cases=[('ordinary debug: startup\n',True),(zero,True),(warning,True),
 (zero.replace('fault=00000000','fault=00000001'),False),
 (zero.replace('status=00000000','status=00000001'),False),
 (zero.replace('event=submit','event=fault'),False),
 (zero+' trailing error',False),
 ('panfrost 13040000.gpu: GPU job timed out',False),
 ('GPULDO_FIRST_FAILURE stage=rail',False),
 ('rcu: INFO: rcu_preempt detected stalls on CPUs/tasks',False),
 ('BUG: sleeping function called from invalid context',False),
 ('Kernel panic - not syncing: fatal',False)]
with tempfile.TemporaryDirectory() as d:
 p=Path(d)
 for i,(line,ok) in enumerate(cases):
  (p/'log').write_text(line+'\n')
  result=subprocess.run(['sh',str(checker),str(p/'log'),str(p/'scoped')],capture_output=True,text=True)
  assert (result.returncode==0)==ok,(i,result.stdout,result.stderr)
print('PASS actual GPU log classifier: precise zero-fault/warning allowlist and nine real/malformed failure cases')
