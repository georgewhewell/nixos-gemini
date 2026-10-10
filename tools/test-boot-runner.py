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
from types import SimpleNamespace
import unittest
from unittest import mock

# These fixtures model trials from the direct-boot M69 baseline.
os.environ['GEMINI_ACCEPTED_BASELINE'] = str(Path(__file__).resolve().parents[1]/'research/baselines/m69.json')
spec=importlib.util.spec_from_file_location('rtc_profile',Path(__file__).with_name('test-boot.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class Profile(unittest.TestCase):
    def test_gnome_health_requires_gdm_and_a_verified_session(self):
        r = m.configure()
        original = r.qualify.SNAPSHOT
        selected = r.qualify.desktop_snapshot(original, 'gnome')
        self.assertIn('systemctl is-active display-manager gemini-gnome-qualify ', selected)
        self.assertNotIn('systemctl is-active gemini-desktop ', selected)
        self.assertIn('unattended_recovery=healthy', selected)
        self.assertIn('boot_sha256=', selected)
        self.assertEqual(r.qualify.desktop_snapshot(selected, 'gnome'), selected)
        self.assertEqual(r.CANDIDATE_DESKTOP, 'gnome')
        self.assertEqual(r.PAGING_POLICY, 'zram')
        with self.assertRaises(RuntimeError):
            r.qualify.desktop_snapshot(original.replace('systemctl is-active ', ':'), 'gnome')

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


if __name__=='__main__':unittest.main()
