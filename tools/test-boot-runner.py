#!/usr/bin/env python3
"""Check bundle selection, durable worker routing and recovery on failed checks."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

# These fixtures model trials from the direct-boot M69 baseline.
os.environ['GEMINI_ACCEPTED_BASELINE'] = str(Path(__file__).resolve().parents[1]/'research/baselines/m69.json')
spec=importlib.util.spec_from_file_location('rtc_profile',Path(__file__).with_name('test-boot.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class Profile(unittest.TestCase):
    def test_gnome_health_requires_activation_without_boot_qualification(self):
        r = m.configure()
        original = r.qualify.SNAPSHOT
        selected = r.qualify.desktop_snapshot(original, 'gnome')
        self.assertIn('systemctl is-active display-manager gemini-jpeg gemini-gpu ', selected)
        self.assertNotIn('gemini-gnome-qualify', selected)
        self.assertNotIn('systemctl is-active gemini-desktop ', selected)
        self.assertIn('unattended_recovery=healthy', selected)
        self.assertIn('boot_sha256=', selected)
        self.assertEqual(r.qualify.desktop_snapshot(selected, 'gnome'), selected)
        self.assertEqual(r.CANDIDATE_DESKTOP, 'gnome')
        self.assertEqual(r.PAGING_POLICY, 'zram')
        with self.assertRaises(RuntimeError):
            r.qualify.desktop_snapshot(original.replace('systemctl is-active ', ':'), 'gnome')
        legacy = 'set -eu\nsystemctl is-active gemini-desktop gemini-jpeg gemini-gpu gemini-wifi gemini-audio >/dev/null\n'
        adapted = r.qualify.desktop_snapshot(legacy, 'gnome')
        self.assertIn('network_service=gemini-wifi', adapted)
        for status in (0, 3):
            checked = subprocess.run(['sh', '-c', f'systemctl() {{ return {status}; }}\n'+adapted], capture_output=True)
            self.assertEqual(checked.returncode, status)
        with self.assertRaises(RuntimeError):
            r.qualify.desktop_snapshot(legacy.replace('set -eu', 'set -e'), 'gnome')

    def test_failed_health_snapshot_retains_only_public_failure_details(self):
        r = m.configure()
        spec = importlib.util.spec_from_file_location('health_snapshot', Path(__file__).with_name('qualify-mtkclient.py'))
        q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root/'accepted'
            marker.write_text('unattended_recovery=healthy\n')
            network = root/'NetworkManager.service'
            script = q.desktop_snapshot(q.SNAPSHOT, 'gnome')
            script = script.replace('/run/unattended-recovery.accepted', str(marker))
            script = script.replace('/etc/systemd/system/NetworkManager.service', str(network))
            script = script.replace('/sys/class/block/mmcblk0p34', str(root/'absent'))
            systemctl = root/'systemctl'
            systemctl.write_text(r'''#!/bin/sh
case "$1" in
  is-active) exit "${HEALTH_ACTIVE_STATUS:-3}" ;;
  show)
    [ "${HEALTH_SHOW_STALL:-0}" = 0 ] || { trap '' TERM; sleep 10; }
    shift
    for unit; do
      [ "$unit" != -p ] || break
      if [ "$unit" = display-manager.service ]; then
        printf 'ActiveState=failed\nSubState=failed\nResult=exit-code\nExecMainStatus=1\n'
      else
        printf 'ActiveState=active\nSubState=exited\nResult=success\nExecMainStatus=0\n'
      fi
      printf 'Id=%s\n\n' "$unit"
    done ;;
  --failed) [ "${HEALTH_ACTIVE_STATUS:-3}" = 0 ] || echo 'display-manager.service loaded failed failed fixed' ;;
  *) exit 1 ;;
esac
''')
            systemctl.chmod(0o755)
            env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ['PATH'])
            stub = r'''
cat() {
  case "$1" in
    */boot_id) echo 11111111-1111-1111-1111-111111111111 ;;
    */mmcblk0/size) echo 122142720 ;;
    */mmcblk0p22/start) echo 362496 ;;
    */mmcblk0p22/size) echo 32768 ;;
    */mmcblk0p32/size) echo 32737247 ;;
    *) return 1 ;;
  esac
}
readlink() { echo /nix/store/11111111111111111111111111111111-nixos-system-test; }
sha256sum() { echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }
head() { :; }
'''
            for managed in (False, True):
                if managed:
                    network.touch()
                checked = subprocess.run(['sh', '-c', stub+script], text=True, capture_output=True, env=env, timeout=8)
                self.assertEqual(checked.returncode, 3, checked.stderr)
                error = subprocess.CalledProcessError(checked.returncode, ['private-command'],
                                                      checked.stdout, 'private-stderr')
                details = q.health_failure_details(error)
                self.assertEqual(details['step'], 'network' if managed else 'services')
                self.assertEqual(details['returncode'], 3)
                self.assertEqual(details['exit_status'], 3)
                self.assertEqual(details['failed_units'], ['display-manager.service'])
                self.assertEqual(details['units']['display-manager.service']['ExecMainStatus'], '1')
                self.assertEqual(details['boot_id'], '11111111-1111-1111-1111-111111111111')
                poisoned = checked.stdout+'\n\nId=private.service\nActiveState=failed\nSecret=private\n'
                error.stdout = poisoned
                self.assertNotIn('private', json.dumps(q.health_failure_details(error)))
            passed = subprocess.run(['sh', '-c', stub+script], text=True, capture_output=True,
                                    env=dict(env, HEALTH_ACTIVE_STATUS='0'), timeout=8)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            self.assertIn('healthy=yes\n', passed.stdout)
            self.assertNotIn('health_failure_step', passed.stdout)
            started = time.monotonic()
            stalled = subprocess.run(['sh', '-c', stub+script], text=True, capture_output=True,
                                     env=dict(env, HEALTH_SHOW_STALL='1'), timeout=9)
            self.assertEqual(stalled.returncode, 3, stalled.stderr)
            self.assertLess(time.monotonic()-started, 8)
            self.assertIn('health_failure_step=network\n', stalled.stdout)
            self.assertNotIn('Id=', stalled.stdout)
            # The actual retry path preserves failure status; diagnosis cannot promote it.
            transport = subprocess.CalledProcessError(255, ['private-ssh'], '', 'private-stderr')
            with mock.patch.object(r, 'candidate_snapshot', side_effect=[error, transport]), \
                    mock.patch.object(r, 'read_state', return_value='waiting'), \
                    mock.patch.object(r.time, 'monotonic', side_effect=[0, 0, 0, 361]), \
                    mock.patch.object(r.time, 'sleep'), \
                    mock.patch.object(r, 'handoff_tree') as handoff:
                with self.assertRaisesRegex(RuntimeError, 'Healthy candidate Linux did not return'):
                    r.candidate_return([], {}, root, m.p.PROFILE)
                handoff.assert_not_called()
                retained = json.loads((root/'candidate-linux-last-error.json').read_text())
                self.assertEqual(retained['returncode'], 255)
                self.assertNotIn('private', json.dumps(retained))
                health = json.loads((root/'candidate-linux-last-health-error.json').read_text())
                self.assertEqual(health['returncode'], 3)
                self.assertEqual(health['failed_units'], ['display-manager.service'])
                self.assertNotIn('private', json.dumps(health))
                self.assertFalse((root/'candidate-linux.json').exists())

    def test_native_startup_evidence_survives_parking_and_rejects_failed_boot(self):
        boot = '6b06926a-a9ab-4367-beec-c95a952bf376'
        proof = ('cpu8_start=requested\n'
                 '[64.1] CPU8 PSCI CPU_ON committed with CPU4 prerequisite\n'
                 'cpu9_start=requested\n'
                 '[64.2] CPU9 PSCI CPU_ON committed with CPU8 prerequisite\n'
                 '0-9\na72_startup=pass\n')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            boot_file = root/'boot'; boot_file.write_text(boot)
            result = root/'result'; result.write_text(proof)
            for cpu in (8, 9):
                (root/f'cpu{cpu}').mkdir()
                (root/f'cpu{cpu}'/'online').write_text('0')
            script = m.native_cpu_script(boot).replace('/proc/sys/kernel/random/boot_id', str(boot_file))
            script = script.replace('/run/gemini-a72-preflight/result', str(result))
            script = script.replace('/sys/devices/system/cpu', str(root))
            def execute(**overrides):
                props = dict(ActiveState='active', SubState='exited', Result='success', ExecMainStatus='0')
                props.update(overrides)
                stub = 'systemctl() { case "$4" in\n'
                stub += ''.join(f'{key}) echo {value};;\n' for key, value in props.items())
                stub += '*) return 1;; esac; }\n'
                return subprocess.run(['sh', '-c', stub+script], capture_output=True, text=True)
            for state in ((0,0), (1,0), (1,1)):
                for cpu, online in zip((8,9),state):
                    (root/f'cpu{cpu}'/'online').write_text(str(online))
                checked = execute()
                self.assertEqual(checked.returncode, 0, checked.stderr)
                self.assertIn(f'current_cpu8_online={state[0]}', checked.stdout)
                self.assertIn(f'current_cpu9_online={state[1]}', checked.stdout)
            for prop, value in [('ActiveState','failed'), ('SubState','running'),
                                ('Result','exit-code'), ('ExecMainStatus','1')]:
                with self.subTest(prop=prop):
                    self.assertNotEqual(execute(**{prop:value}).returncode, 0)
            for line in proof.splitlines(keepends=True):
                result.write_text(proof.replace(line, ''))
                self.assertNotEqual(execute().returncode, 0, line)
            result.write_text(proof+'late failure\n')
            self.assertNotEqual(execute().returncode, 0)
            result.write_text(proof)
            (root/'cpu8'/'online').write_text('invalid')
            self.assertNotEqual(execute().returncode, 0)
            (root/'cpu8'/'online').write_text('0')
            boot_file.write_text('another-boot')
            self.assertNotEqual(execute().returncode, 0)
        with self.assertRaises(ValueError):
            m.native_cpu_script('invalid; false')

    def test_observation_is_bounded_and_keeps_strict_qualification(self):
        r = m.configure()
        state = {'boot_id': 'candidate'}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'before-tree.json').write_text('{}')
            with mock.patch.object(r, 'OBSERVE_SECONDS', 5), \
                    mock.patch.object(r, 'candidate_snapshot', return_value=state), \
                    mock.patch.object(r, 'handoff_tree', return_value={}), \
                    mock.patch.object(r, 'verify_handoff_tree'), \
                    mock.patch.object(r, 'read_state', return_value='waiting'), \
                    mock.patch.object(r.time, 'monotonic', side_effect=[0, 0, 0, 0, 5, 5]), \
                    mock.patch.object(r.time, 'sleep') as sleep, \
                    mock.patch.object(r.power_kernel, 'evidence', side_effect=RuntimeError('strict check failed')) as strict:
                with self.assertRaisesRegex(RuntimeError, 'strict check failed'):
                    r.candidate_return([], {}, root, m.p.PROFILE)
                sleep.assert_called_once_with(5)
                strict.assert_called_once()
                record = json.loads((root/'candidate-observation.json').read_text())
                self.assertTrue(record['completed'])
                self.assertFalse(record['candidate_qualified'])

    def test_default_observation_does_not_delay_or_probe(self):
        r = m.configure()
        with mock.patch.object(r, 'candidate_snapshot') as snapshot, \
                mock.patch.object(r.time, 'sleep') as sleep:
            r.observe_candidate([], {}, Path('/unused'), m.p.PROFILE, {})
            snapshot.assert_not_called()
            sleep.assert_not_called()

    def test_observation_stops_on_changed_boot_or_recovery(self):
        r = m.configure()
        for recovered in (False, True):
            with self.subTest(recovered=recovered), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(r, 'OBSERVE_SECONDS', 90), \
                    mock.patch.object(r, 'candidate_snapshot', return_value={'boot_id': 'other'}), \
                    mock.patch.object(r, 'read_state', return_value=r.SUCCESS if recovered else 'waiting'), \
                    mock.patch.object(r.time, 'sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError, 'rescue|identity'):
                    r.observe_candidate([], {}, Path(tmp), m.p.PROFILE, {'boot_id': 'candidate'})
                sleep.assert_not_called()

    def test_observation_argument_rejects_unbounded_wait(self):
        for seconds in ('-1', '91'):
            with self.subTest(seconds=seconds), \
                    mock.patch.object(sys, 'argv', ['test-boot.py', '--out', '/unused', '--observe-seconds', seconds]), \
                    mock.patch.object(m.p, 'configure') as configure, \
                    mock.patch.object(sys, 'stderr'):
                with self.assertRaises(SystemExit): m.p.main()
                configure.assert_not_called()

    def test_typec_capture_keeps_controller_identity_and_missing_attributes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ports = root/'class'; ports.mkdir()
            controller = root/'11008000.i2c'/'1-0025'/'typec'/'port7'
            controller.mkdir(parents=True)
            (ports/'port7').symlink_to(controller)
            (controller/'power_role').write_text('[sink]\n')
            (controller/'data_role').write_text('[device]\n')
            (controller/'orientation').write_text('reverse\n')
            partner = controller/'port7-partner'; partner.mkdir()
            (ports/'port7-partner').symlink_to(partner)
            env = dict(os.environ, TYPEC_CLASS_ROOT=str(ports))
            raw = subprocess.check_output(['sh', '-c', m.TYPEC_STATUS_SCRIPT], env=env, text=True)
            self.assertEqual(raw.count('\nport='), 1)
            self.assertIn('port='+str(controller), raw)
            self.assertIn('orientation=reverse\n', raw)
            self.assertIn('power_operation_mode=unavailable\n', raw)
            self.assertIn('partner=present\n', raw)
            partner.rmdir()
            raw = subprocess.check_output(['sh', '-c', m.TYPEC_STATUS_SCRIPT], env=env, text=True)
            self.assertIn('partner=absent\n', raw)

    def test_usb_link_follows_device_across_bus_numbers_and_checks_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            net = root/'net'; net.mkdir()
            interface = net/'enp167s0u2'; interface.mkdir()
            (interface/'address').write_text('42:00:15:19:82:00\n')
            for bus, speed in (('3-2', '480'), ('4-2', '5000')):
                device = root/bus; device.mkdir()
                child = device/(bus+':1.0'); child.mkdir()
                for name, value in dict(idVendor='0525', idProduct='a4a2', speed=speed).items():
                    (device/name).write_text(value+'\n')
                link = interface/'device'
                link.unlink(missing_ok=True); link.symlink_to(child)
                result = m.host_usb_link(net)
                self.assertEqual(result['speed_mbps'], speed)
                self.assertEqual(result['usb_path'], str(device))
            (device/'idProduct').write_text('0000')
            with self.assertRaisesRegex(RuntimeError, 'exactly one'):
                m.host_usb_link(net)

    def test_usb3_requires_negotiated_speed_at_both_ends(self):
        for current, maximum, host_speed, expected in (
                ('high-speed', 'super-speed', '480', False),
                ('super-speed', 'super-speed', '480', False),
                ('super-speed', 'super-speed', '5000', True)):
            with self.subTest(current=current, host=host_speed):
                raw = (f'boot_id=boot\ncurrent_speed={current}\n'
                       f'maximum_speed={maximum}\nstate=configured\n')
                runner = SimpleNamespace(persistence=SimpleNamespace(run=mock.Mock(return_value=raw)),
                                         qualify=SimpleNamespace(save=mock.Mock()))
                with mock.patch.object(m, 'host_usb_link', return_value={'speed_mbps': host_speed}):
                    m.usb_link_evidence(runner, [], {'boot_id': 'boot'}, Path('/unused'))
                    self.assertEqual(runner.qualify.save.call_args.args[-1]['superspeed_observed'], expected)
                    with self.assertRaisesRegex(RuntimeError, 'identity'):
                        m.usb_link_evidence(runner, [], {'boot_id': 'different'}, Path('/unused'))

    def test_manifest_selects_bundle_and_rejects_changed_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); data=b'compressed store fixture'
            sha=hashlib.sha256(data).hexdigest(); name='mainline-nixos-'+sha+'.squashfs'
            (root/name).write_bytes(data)
            (root/'kernel').symlink_to(m.p.KERNEL)
            (root/'boot-padded-p22.img').write_bytes(b'boot fixture')
            manifest=(f'store-file={name}\nstore-sha256={sha}\nstore-size={len(data)}\n'
                      f'kernel={m.p.KERNEL.name}\nsystem=/nix/store/'+ 'a'*32+'-system\n')
            (root/'MANIFEST').write_text(manifest)
            names=('BUNDLE','KERNEL','SYSTEM','STORE_SHA','STORE_SIZE','BOOT_SHA','NOTES_SHA')
            original={key:getattr(m.p,key) for key in names}
            try:
                with mock.patch.object(m.p.f.q.r.power_kernel,'notes_sha',return_value='b'*64), \
                        mock.patch.object(m.zram, 'probe_identity') as paging_identity:
                    m.artifacts(root)
                    paging_identity.assert_called_once_with(m.p)
                    self.assertEqual(m.p.BUNDLE,root)
                    self.assertEqual(m.p.STORE_SHA,sha)
                    self.assertEqual(m.p.store_profile(m.p.f.q.r.efi_linux).bundle,root)
                    (root/name).write_bytes(b'X'*len(data))
                    with self.assertRaisesRegex(ValueError,'content'): m.artifacts(root)
                    (root/name).write_bytes(data)
                    (root/'MANIFEST').write_text(manifest+'store-size=1\n')
                    with self.assertRaisesRegex(ValueError,'Duplicate'): m.artifacts(root)
            finally:
                for key,value in original.items(): setattr(m.p,key,value)

    def test_durable_worker_receives_resolved_bundle_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bundle=root/'bundle'; bundle.mkdir()
            cache=root/'cache'; cache.touch(); alias=root/'result'; alias.symlink_to(bundle)
            argv=['test-boot.py','--execute','--out',tmp+'/trial','--bundle',str(alias),
                  '--reclaim-cache',str(cache),'--watchdog-expiry','--observe-seconds','90']
            setup=mock.Mock()
            with mock.patch.object(sys,'argv',argv),mock.patch.object(m.p.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                m.p.main(setup)
            setup.assert_called_once_with(bundle,cache,None,None,None)
            command=run.call_args.args[0]
            self.assertIn(str(m.p.ENTRYPOINT),command)
            self.assertIn('--worker',command)
            self.assertEqual(command[command.index('--bundle')+1],str(bundle))
            self.assertEqual(command[command.index('--reclaim-cache')+1],str(cache))
            self.assertIn('--watchdog-expiry',command)
            self.assertEqual(command[command.index('--observe-seconds')+1], '90')
            self.assertTrue(any(v.startswith('--unit=boot-test-') for v in command))

    def test_durable_worker_receives_efi_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle=root/'bundle';bundle.mkdir();efi=root/'efi';efi.mkdir()
            setup=mock.Mock()
            with mock.patch.object(sys,'argv',['test-boot.py','--execute','--out',tmp+'/trial',
                    '--bundle',str(bundle),'--install-efi',str(efi)]), \
                    mock.patch.object(m.p.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                m.p.main(setup)
            setup.assert_called_once_with(bundle,None,efi,None,None)
            command=run.call_args.args[0]
            self.assertEqual(command[command.index('--install-efi')+1],str(efi))

    def test_bootloader_worker_receives_both_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle=root/'bundle';bundle.mkdir();efi=root/'efi';efi.mkdir();loader=root/'loader';loader.mkdir()
            setup=mock.Mock()
            with mock.patch.object(sys,'argv',['test-boot.py','--execute','--out',tmp+'/trial',
                    '--bundle',str(bundle),'--bootloader',str(loader),'--efi-files',str(efi)]), \
                    mock.patch.object(m.p.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                m.p.main(setup)
            setup.assert_called_once_with(bundle,None,None,loader,efi)
            command=run.call_args.args[0]
            self.assertEqual(command[command.index('--bootloader')+1],str(loader))
            self.assertEqual(command[command.index('--efi-files')+1],str(efi))

    def test_bootloader_requires_installed_entry_without_publication_or_pruning(self):
        path=Path('/unused')
        for kw in (dict(bootloader=path),dict(efi_files=path),
                   dict(bootloader=path,efi_files=path,install_efi=path),
                   dict(bootloader=path,efi_files=path,reclaim_cache=path)):
            with self.subTest(kw=kw),self.assertRaisesRegex(ValueError,'already installed'):
                m.artifacts(path,**kw)

    def test_normal_efi_mode_checks_real_handoff_and_rejects_fallback(self):
        sha='c'*64
        with mock.patch.object(m,'BOOTLOADER',Path('/carrier')), \
                mock.patch.object(m,'EFI_MANIFEST',{'files':{m.installer.MANAGER:{'sha256':sha}}}):
            r=m.configure()
            self.assertEqual(r.PROFILES[m.p.PROFILE][0],Path('/carrier/boot-padded-p22.img'))
            self.assertNotIn(m.p.PROFILE,r.DIRECT_NIX_PROFILES)
            self.assertIn(m.p.PROFILE,r.NIX_EFI_PROFILES)
            self.assertTrue(r.store_profile_for(m.p.PROFILE).require_efi)
            self.assertTrue(r.power_kernel.evidence.keywords['require_efi'])
            before={'memory/reg':'same'}
            after=dict(before,**{r.HANDOFF_MARKER:b'efi\0'.hex(),
                r.efi_manager.PREFIX+'result':b'starting\0'.hex(),
                r.efi_manager.PREFIX+'stage':b'start-image\0'.hex(),r.efi_manager.PREFIX+'sha256':sha})
            r.verify_handoff_tree(before,after,m.p.PROFILE)
            for key,value in ((r.HANDOFF_MARKER,b'fit\0'.hex()),('memory/reg','different'),
                              (r.CONSOLE_MARKER,b'passed\0'.hex()),(r.efi_manager.PREFIX+'sha256','d'*64)):
                with self.subTest(key=key),self.assertRaises(RuntimeError):
                    r.verify_handoff_tree(before,dict(after,**{key:value}),m.p.PROFILE)

    def test_pm_and_usb_compose_but_not_with_watchdog_expiry(self):
        for args in (dict(pm_test='freezer'),dict(pm_test='s2idle'),dict(cycle=True)):
            with self.subTest(args=args):
                r=m.configure(**args)
                self.assertEqual((r.pm_test_last_stage,r.usb_cycle_requested),(args.get('pm_test'),args.get('cycle',False)))
        for args in (dict(watchdog=True,pm_test='s2idle'),dict(watchdog=True,cycle=True)):
            with self.subTest(args=args),self.assertRaises(ValueError):m.configure(**args)

    def test_missing_rtc_proof_still_runs_existing_recovery_and_retention_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);r=SimpleNamespace(watchdog_expiry_requested=False,qualify=SimpleNamespace(save=mock.Mock()))
            with mock.patch.object(m,'base_finish',side_effect=RuntimeError('failed profile')) as finish:
                with self.assertRaisesRegex(RuntimeError,'failed profile'):m.alarm_finish(r,root,'before')
            self.assertIsInstance(finish.call_args.args[-1],FileNotFoundError)
            saved=r.qualify.save.call_args.args[-1]
            self.assertFalse(saved['rtc_alarm_diagnostics_qualified'])


class MMCHighSpeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('desktop_profile',
            Path(__file__).with_name('test-network-audio-desktop.py'))
        cls.desktop = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.desktop)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.boot_id = '11111111-1111-1111-1111-111111111111'
        self.system = str(self.root/'nix/store' / ('a'*32+'-candidate'))
        Path(self.system).mkdir(parents=True)
        self.write('/proc/sys/kernel/random/boot_id', self.boot_id+'\n')
        self.write('/proc/sys/kernel/tainted', '0\n')
        self.path('/run').mkdir()
        self.path('/run/current-system').symlink_to(self.system)
        self.native = self.path('/sys/devices/platform/soc/11230000.mmc')
        self.native.mkdir(parents=True)
        self.driver = self.path('/sys/bus/platform/drivers/mtk-msdc')
        self.driver.mkdir(parents=True)
        (self.native/'driver').symlink_to(self.driver)
        self.write('/sys/devices/platform/soc/11230000.mmc/of_node/compatible',
                   'mediatek,mt6797-mmc\0')
        devices = self.path('/sys/bus/platform/devices'); devices.mkdir()
        (devices/'11230000.mmc').symlink_to(self.native)
        self.host = self.native/'mmc_host/mmc0'; self.host.mkdir(parents=True)
        hosts = self.path('/sys/class/mmc_host'); hosts.mkdir(parents=True)
        (hosts/'mmc0').symlink_to(self.host)
        self.debug = self.path('/sys/kernel/debug/mmc0'); self.debug.mkdir(parents=True)
        self.scope = {'__name__': 'mmc_fixture'}
        exec(compile(self.desktop.MMC_REMOTE_CODE, '<actual-mmc-reader>', 'exec'), self.scope)
        self.scope['Path'] = self.path
        self.ios_text = ('clock:\t\t52000000 Hz\nactual clock:\t47999984 Hz\n'
            'vdd:\t\t21 (3.3 ~ 3.4 V)\nbus mode:\t2 (push-pull)\n'
            "chip select:\t0 (don't care)\npower mode:\t2 (on)\n"
            'bus width:\t3 (8 bits)\ntiming spec:\t1 (mmc high-speed)\n'
            'signal voltage:\t1 (1.80 V)\ndriver type:\t0 (type B)\n')
        self.error_text = ('# Command Timeout Occurred:\t 0\n# Command CRC Errors Occurred:\t 0\n'
            '# Data Timeout Occurred:\t 0\n# Data CRC Errors Occurred:\t 0\n'
            '# Auto-Cmd Error Occurred:\t 0\n# ADMA Error Occurred:\t 0\n'
            '# Tuning Error Occurred:\t 0\n# CMDQ RED Errors:\t 0\n# CMDQ GCE Errors:\t 0\n'
            '# CMDQ ICCE Errors:\t 0\n# Request Timedout:\t 0\n# CMDQ Request Timedout:\t 0\n'
            '# ICE Config Errors:\t 0\n# Controller Timedout errors:\t 0\n# Unexpected IRQ errors:\t 0\n')
        self.restore()

    def path(self, value):
        return self.root / str(value).lstrip('/')

    def test_explicit_gnome_session_checks_identity_and_propagates_failure(self):
        trace = self.root/'gnome-calls'
        for status, boot_id in ((0, self.boot_id), (1, self.boot_id), (0, 'other')):
            trace.write_text('')
            def run(ssh, script, directory, name, timeout):
                script = script.replace('/proc/sys/kernel/random/boot_id', str(self.path('/proc/sys/kernel/random/boot_id')))
                script = script.replace('/run/current-system', str(self.path('/run/current-system')))
                stub = f'systemctl() {{ echo "$1" >> {trace}; return {status}; }}\n'
                checked = subprocess.run(['sh', '-c', stub+script], text=True, capture_output=True, timeout=5)
                if checked.returncode:
                    raise subprocess.CalledProcessError(checked.returncode, ['fixture'], checked.stdout, checked.stderr)
                return checked.stdout
            runner = SimpleNamespace(persistence=SimpleNamespace(run=run))
            with mock.patch.object(self.desktop.p, 'SYSTEM', self.system):
                if status or boot_id != self.boot_id:
                    with self.assertRaises(subprocess.CalledProcessError):
                        self.desktop.gnome_evidence(runner, [], {'boot_id': boot_id}, self.root)
                    self.assertEqual(trace.read_text(), 'start\n' if status else '')
                else:
                    result = self.desktop.gnome_evidence(runner, [], {'boot_id': boot_id}, self.root)
                    self.assertEqual(result['result'], 'passed')
                    self.assertEqual(trace.read_text(), 'start\nis-active\n')

    def write(self, path, value):
        target = self.path(path); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)

    def restore(self):
        (self.debug/'ios').write_text(self.ios_text)
        (self.debug/'err_stats').write_text(self.error_text)
        self.write('/sys/kernel/debug/clk/infra_msdc0/clk_rate', '383999878\n')

    def read_snapshot(self):
        return self.scope['snapshot'](self.boot_id, self.system)

    def test_actual_reader_handles_native_sdr_clock_branches(self):
        for source, actual in ((383999878, 47999984), (192000000, 48000000),
                               (208000000, 52000000), (104000000, 52000000),
                               (52000000, 52000000)):
            with self.subTest(source=source):
                self.write('/sys/kernel/debug/clk/infra_msdc0/clk_rate', str(source)+'\n')
                (self.debug/'ios').write_text(self.ios_text.replace('47999984', str(actual)))
                record = self.read_snapshot()
                self.assertEqual(record['ios']['actual clock'], actual)
                self.assertEqual(self.desktop.verify_mmc_report(json.dumps(record)), record)
                self.assertFalse(record['ios_alone_qualifies_raw_clock'])

    def test_actual_reader_rejects_legacy_wrong_ios_and_clock_projection(self):
        for old, new in (('52000000', '25000000'), ('1 (mmc high-speed)', '0 (legacy)'),
                         ('1 (mmc high-speed)', '2 (sd high-speed)'),
                         ('3 (8 bits)', '2 (4 bits)'), ('1 (1.80 V)', '0 (3.30 V)'),
                         ('2 (on)', '1 (up)'), ('47999984', '52000000')):
            with self.subTest(new=new):
                (self.debug/'ios').write_text(self.ios_text.replace(old, new))
                with self.assertRaises(self.scope['CheckError']): self.read_snapshot()
        self.restore()
        for value in ('0', '-1', 'bad', str(2**32), '192000000'):
            with self.subTest(source=value):
                self.write('/sys/kernel/debug/clk/infra_msdc0/clk_rate', value+'\n')
                with self.assertRaises(self.scope['CheckError']): self.read_snapshot()

    def test_actual_reader_rejects_missing_duplicate_and_malformed_fields(self):
        bad_ios = (self.ios_text.replace('actual clock:\t47999984 Hz\n', ''),
                   self.ios_text+'clock:\t52000000 Hz\n',
                   self.ios_text+'foreign:\t0\n', self.ios_text.replace('47999984', '-1'),
                   self.ios_text.replace('47999984', str(2**32)), 'x'*4097)
        bad_errors = (self.error_text.split('\n', 1)[1],
                      self.error_text+self.error_text.splitlines()[0]+'\n',
                      self.error_text.replace(':\t 0', ':\t -1', 1),
                      self.error_text.replace(':\t 0', ':\t '+str(2**32), 1),
                      self.error_text+'# unknown:\t 0\n')
        for name, values in (('ios', bad_ios), ('err_stats', bad_errors)):
            for value in values:
                with self.subTest(name=name, value=value[:40]):
                    self.restore(); (self.debug/name).write_text(value)
                    with self.assertRaises(self.scope['CheckError']): self.read_snapshot()

    def test_actual_reader_attributes_each_nonzero_error_and_closes_reads(self):
        before_fds = len(list(Path('/proc/self/fd').iterdir()))
        for row in self.error_text.splitlines():
            name = row.split(':')[0].removeprefix('# ')
            with self.subTest(counter=name):
                (self.debug/'err_stats').write_text(self.error_text.replace('# '+name+':\t 0', '# '+name+':\t 1'))
                with self.assertRaisesRegex(self.scope['CheckError'], 'native_error_counter_nonzero'):
                    self.read_snapshot()
        self.assertEqual(len(list(Path('/proc/self/fd').iterdir())), before_fds)

    def test_actual_reader_rejects_identity_binding_and_host_changes(self):
        for path, value in (('/proc/sys/kernel/random/boot_id', 'different'),
                            ('/proc/sys/kernel/tainted', '1'),
                            ('/sys/devices/platform/soc/11230000.mmc/of_node/compatible', 'foreign\0')):
            target = self.path(path); original = target.read_text()
            with self.subTest(path=path), self.assertRaises(self.scope['CheckError']):
                target.write_text(value); self.read_snapshot()
            target.write_text(original)
        with self.assertRaisesRegex(self.scope['CheckError'], 'system_identity_changed'):
            self.scope['snapshot'](self.boot_id, self.system+'-foreign')
        (self.native/'driver').unlink(); (self.native/'driver').symlink_to(self.native/'of_node')
        with self.assertRaisesRegex(self.scope['CheckError'], 'native_driver_missing'): self.read_snapshot()
        (self.native/'driver').unlink(); (self.native/'driver').symlink_to(self.driver)
        extra = self.native/'mmc_host/mmc1'; extra.mkdir()
        self.path('/sys/class/mmc_host/mmc1').symlink_to(extra)
        with self.assertRaisesRegex(self.scope['CheckError'], 'native_host_not_unique'): self.read_snapshot()

    def test_actual_reader_detects_rebind_during_snapshot(self):
        read = self.scope['read']
        def rebound(path, limit=256):
            value = read(path, limit)
            if path == self.debug/'ios':
                (self.native/'driver').rename(self.native/'retired-driver')
                (self.native/'driver').symlink_to(self.driver)
            return value
        self.scope['read'] = rebound
        with self.assertRaisesRegex(self.scope['CheckError'], 'owner_changed_during_snapshot'):
            self.read_snapshot()

    def test_actual_reader_rejects_missing_attributes(self):
        for path in (self.debug/'ios', self.debug/'err_stats', self.native/'driver',
                     self.path('/sys/kernel/debug/clk/infra_msdc0/clk_rate')):
            retired = path.with_name(path.name+'.missing')
            with self.subTest(attribute=path.name):
                path.rename(retired)
                try:
                    with self.assertRaises(OSError): self.read_snapshot()
                finally:
                    retired.rename(path)

    def test_report_parser_rejects_incomplete_duplicate_or_false_success(self):
        record = self.read_snapshot()
        for value in ({}, dict(record, errors=[0]*14), dict(record, errors=[False]*15),
                      dict(record, identity_preserved=False), dict(record, owner_fingerprint=[])):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.desktop.verify_mmc_report(json.dumps(value))
        with self.assertRaises(ValueError):
            self.desktop.verify_mmc_report('{"schema":1,"schema":1}')

    def test_gate_brackets_existing_storage_once_and_does_not_mutate_shared_owner(self):
        events = []
        output = object()
        def storage(*args, **kwargs): events.append('existing-storage'); return output
        owner = SimpleNamespace(evidence=storage, retained_attribute=object())
        def save(directory, name, value): (directory/name).write_text(json.dumps(value))
        runner = SimpleNamespace(persistent_nix=owner, qualify=SimpleNamespace(save=save))
        def snapshot(r, ssh, boot, system, directory, phase):
            events.append(phase); return self.read_snapshot()
        with mock.patch.object(self.desktop, 'mmc_snapshot', side_effect=snapshot):
            self.desktop.install_mmc_gate(runner)
            self.desktop.install_mmc_gate(runner)
            result = runner.persistent_nix.evidence([], self.boot_id, self.root, runner.qualify,
                                                    object(), system=self.system, kernel='/kernel')
        self.assertIs(result, output)
        self.assertEqual(events, ['before', 'existing-storage', 'after'])
        self.assertIs(owner.evidence, storage)
        self.assertIs(runner.persistent_nix.retained_attribute, owner.retained_attribute)
        self.assertEqual(json.loads((self.root/'mmc-high-speed/result.json').read_text())['result'], 'passed')
        second = SimpleNamespace(persistent_nix=owner)
        self.desktop.install_mmc_gate(second)
        self.assertIs(second.persistent_nix.evidence._mmc_original, storage)

    def test_gate_failures_abort_before_candidate_can_return(self):
        for failure in ('before', 'storage', 'after', 'rebind', 'source'):
            with self.subTest(failure=failure):
                events = []
                def save(directory, name, value): (directory/name).write_text(json.dumps(value))
                def storage(*args, **kwargs):
                    events.append('existing-storage')
                    if failure == 'storage': raise RuntimeError('storage failed')
                owner = SimpleNamespace(evidence=storage)
                runner = SimpleNamespace(persistent_nix=owner, qualify=SimpleNamespace(save=save))
                def snapshot(r, ssh, boot, system, directory, phase):
                    events.append(phase)
                    if phase == failure: raise RuntimeError('MMC failed')
                    record = self.read_snapshot()
                    if phase == 'after' and failure == 'rebind': record['owner_fingerprint'][0][1] += 1
                    if phase == 'after' and failure == 'source': record['source_hz'] += 1
                    return record
                self.desktop.install_mmc_gate(runner)
                with mock.patch.object(self.desktop, 'mmc_snapshot', side_effect=snapshot), self.assertRaises(RuntimeError):
                    runner.persistent_nix.evidence([], self.boot_id, self.root, runner.qualify,
                                                   object(), system=self.system)
                    events.append('candidate-returned')
                self.assertNotIn('candidate-returned', events)
                if failure == 'before': self.assertEqual(events, ['before'])
                if failure == 'storage': self.assertEqual(events, ['before', 'existing-storage'])
                self.assertEqual(json.loads((self.root/'mmc-high-speed/result.json').read_text())['result'], 'failed')

    def test_configured_candidate_rejects_mmc_before_desktop_checks(self):
        for failure in ('before', 'after'):
            with self.subTest(failure=failure):
                trial = self.root/failure; trial.mkdir()
                (trial/'before-tree.json').write_text('{}')
                runner = self.desktop.base_configure()
                owner = runner.persistent_nix
                storage = mock.Mock(spec=lambda: None)
                runner.persistent_nix = SimpleNamespace(**vars(owner))
                runner.persistent_nix.evidence = storage
                state = {'boot_id': self.boot_id}
                phases = []
                def snapshot(r, ssh, boot, system, directory, phase):
                    phases.append(phase)
                    if phase == failure: raise RuntimeError('MMC admission failed')
                    return self.read_snapshot()
                with mock.patch.object(self.desktop, 'base_configure', return_value=runner), \
                        mock.patch.object(self.desktop, 'mmc_snapshot', side_effect=snapshot), \
                        mock.patch.object(self.desktop, 'usb_evidence') as usb, \
                        mock.patch.object(runner, 'candidate_snapshot', return_value=state), \
                        mock.patch.object(runner, 'handoff_tree', return_value={}), \
                        mock.patch.object(runner, 'verify_handoff_tree'), \
                        mock.patch.object(runner, 'observe_candidate'), \
                        mock.patch.object(runner, 'read_state', return_value='waiting'), \
                        mock.patch.object(runner.efi_files, 'evidence'), \
                        mock.patch.object(runner.qualify, 'run', side_effect=AssertionError('unexpected remote command')), \
                        mock.patch.object(runner.power_kernel, 'evidence'):
                    configured = self.desktop.configure()
                    with self.assertRaisesRegex(RuntimeError, 'MMC admission failed'):
                        configured.candidate_return([], {}, trial, self.desktop.p.PROFILE)
                self.assertEqual(phases, ['before'] if failure == 'before' else ['before', 'after'])
                self.assertEqual(storage.call_count, int(failure == 'after'))
                usb.assert_not_called()
                self.assertIs(runner.persistent_nix.evidence._mmc_original, storage)
                self.assertIsNot(owner.evidence, storage)
        self.assertEqual(self.desktop.p.EXTRA_EXECUTED_SOURCES.count('tools/test-network-audio-desktop.py'), 1)


class MediaAdmission(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('media_profile', Path(__file__).with_name('test-media-boot.py'))
        self.media = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.media)
        self.boot = self.media.boot
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.before = {'boot_id': '11111111-1111-1111-1111-111111111111'}
        self.boot_file = self.root/'boot'; self.boot_file.write_text(self.before['boot_id'])
        self.system = '/nix/store/'+'a'*32+'-candidate-system'
        self.init = self.root/'store'/self.system.lstrip('/')/'init'
        self.init.parent.mkdir(parents=True)
        self.valid = True

        def remote(ssh, script, directory, name):
            self.assertEqual(name, 'persistent-store-installed')
            script = script.replace('/proc/sys/kernel/random/boot_id', str(self.boot_file))
            script = script.replace('/persist/nixos', str(self.root/'store'))
            stub = f'nix-store() {{ return {0 if self.valid else 1}; }}\ndf() {{ :; }}\n'
            return subprocess.run(['sh', '-c', stub+script], check=True, capture_output=True, text=True).stdout

        def save(directory, name, value):
            (directory/name).write_text(json.dumps(value))

        self.runner = SimpleNamespace(LOCKS=self.root,
            persistence=SimpleNamespace(run=mock.Mock(side_effect=remote)),
            qualify=SimpleNamespace(check_host_idle=mock.Mock(), save=save),
            candidate_needs_rescue_reboot=mock.Mock(return_value=False), reboot=mock.Mock(), trial=mock.Mock())
        self.enterContext(mock.patch.object(self.boot, 'STORE_ROOT', '/persist/nixos'))
        self.enterContext(mock.patch.object(self.boot.p, 'SYSTEM', self.system))
        self.base = self.enterContext(mock.patch.object(self.boot, 'base_preflight', return_value=self.before))
        self.enterContext(mock.patch.object(self.boot.p.f, 'snapshot', return_value=dict(self.before, layout='swap')))
        self.stage1 = self.enterContext(mock.patch.object(self.boot.stage1, 'install', wraps=self.boot.stage1.install))

    def install_init(self):
        self.init.write_text('#!/bin/sh\n'); self.init.chmod(0o700)

    def test_missing_or_invalid_candidate_blocks_actual_worker_before_trial(self):
        for valid, present, executable in ((False, True, True), (True, False, False), (True, True, False)):
            with self.subTest(valid=valid, present=present, executable=executable):
                self.valid = valid
                self.init.unlink(missing_ok=True)
                if present:
                    self.install_init()
                    if not executable: self.init.chmod(0o600)
                with mock.patch.object(sys, 'argv', ['test-media-boot.py', '--worker', '--out', str(self.root)]), \
                        mock.patch.dict(os.environ, GEMINI_POWER_SWAP_UNIT='boot-test-1-2', INVOCATION_ID='host-fixture'), \
                        mock.patch.object(self.media.p.f.q.r.qualify, 'run', return_value=str(os.getpid())), \
                        mock.patch.object(self.media.p, 'configure', return_value=self.runner), \
                        mock.patch.object(self.media.p, 'finish') as finish:
                    with self.assertRaises(subprocess.CalledProcessError): self.media.p.main()
                self.runner.trial.assert_not_called()
                self.stage1.assert_not_called()
                finish.assert_not_called()

    def test_media_admits_store_and_installs_stage1_once_without_rtc(self):
        self.install_init()
        original = self.runner.candidate_needs_rescue_reboot
        with mock.patch.object(self.boot.calendar, 'install') as calendar, \
                mock.patch.object(self.boot.rtc, 'install') as alarm, \
                mock.patch.object(self.boot.startup, 'install_probe') as startup:
            self.media.configure()
            self.assertEqual(self.media.p.preflight(self.runner, self.root, True), self.before)
        self.base.assert_called_once_with(self.runner, self.root, True)
        self.runner.persistence.run.assert_called_once()
        self.stage1.assert_called_once_with(self.boot.p, self.runner, self.root)
        self.assertIsNot(self.runner.candidate_needs_rescue_reboot, original)
        for rtc in (calendar, alarm, startup): rtc.assert_not_called()

    def test_changed_boot_blocks_store_admission(self):
        self.install_init(); self.boot_file.write_text('another-boot')
        with self.assertRaises(subprocess.CalledProcessError):
            self.media.p.preflight(self.runner, self.root, True)
        self.stage1.assert_not_called()

    def test_squashfs_admission_prepares_and_installs_before_stage1(self):
        events = []
        with mock.patch.object(self.boot, 'STORE_ROOT', None), \
                mock.patch.object(self.boot.cache, 'prepare', side_effect=lambda *a: events.append('prepare')), \
                mock.patch.object(self.boot.cache, 'install', side_effect=lambda *a: events.append('install')), \
                mock.patch.object(self.boot.stage1, 'install', side_effect=lambda *a: events.append('stage1')):
            self.assertEqual(self.media.p.preflight(self.runner, self.root, True), self.before)
        self.assertEqual(events, ['prepare', 'install', 'stage1'])
        self.runner.persistence.run.assert_not_called()

    def test_generic_finish_recovers_then_checks_cache_and_records_failure(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                events = []
                def recover(*args):
                    events.append('recovery')
                    self.runner.qualify.save(self.root, 'result.json', dict(result='passed', profile_qualified=True))
                def verify(*args):
                    events.append('cache')
                    if failed: raise RuntimeError('cache proof failed')
                    return {'unused_cache_pruned': False}
                with mock.patch.object(self.boot, 'STORE_ROOT', None), \
                        mock.patch.object(self.boot, 'base_finish', side_effect=recover), \
                        mock.patch.object(self.boot.cache, 'verify_final', side_effect=verify):
                    if failed:
                        with self.assertRaisesRegex(RuntimeError, 'cache proof failed'):
                            self.media.p.finish(self.runner, self.root, self.before)
                    else:
                        self.media.p.finish(self.runner, self.root, self.before)
                self.assertEqual(events, ['recovery', 'cache'])
                result = json.loads((self.root/'result.json').read_text())
                self.assertEqual(result['profile_qualified'], not failed)
                self.assertEqual(result['result'], 'failed' if failed else 'passed')
                if failed: self.assertEqual(result['error'], 'cache proof failed')
                else: self.assertFalse(result['unused_cache_pruned'])

    def test_persistent_finish_skips_cache_and_failed_recovery_cannot_pass(self):
        error = RuntimeError('recovery failed')
        self.runner.qualify.save(self.root, 'result.json', dict(result='passed', profile_qualified=True))
        with mock.patch.object(self.boot, 'base_finish') as recover, \
                mock.patch.object(self.boot.cache, 'verify_final') as cache:
            self.media.p.finish(self.runner, self.root, self.before)
            cache.assert_not_called()
            recover.side_effect = error
            with self.assertRaisesRegex(RuntimeError, 'recovery failed'):
                self.media.p.finish(self.runner, self.root, self.before)
            cache.assert_not_called()
        self.assertFalse(json.loads((self.root/'result.json').read_text())['profile_qualified'])


if __name__=='__main__':unittest.main()
