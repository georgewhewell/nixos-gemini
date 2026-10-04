"""Host-only checks for the read/reboot qualification runner."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('qualify', Path(__file__).with_name('qualify-mtkclient.py'))
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)


class QualificationTests(unittest.TestCase):
    def before(self):
        return dict(boot_id='11111111-1111-1111-1111-111111111111',
                    boot_sha256=q.ACCEPTED_BOOT, system=q.ACCEPTED_SYSTEM,
                    gpt_sha256='a' * 64, healthy='yes')

    def test_host_guard_ignores_own_command_and_rejects_other_clients(self):
        own = '10 1 python3 qualify-mtkclient.py --mtk /bin/mtk\n1 0 init\n'
        with patch.object(q.os, 'getpid', return_value=10), \
             patch.object(q.Path, 'glob', return_value=[]), \
             patch.object(q, 'run', return_value=own) as processes:
            q.check_host_idle()
            for command in ('/bin/mtk multi printgpt', 'python3 /bin/.mtk-wrapped printgpt',
                            'python3 /src/mtk.py printgpt', '/bin/flash_tool -x trial.xml'):
                processes.return_value = own + '20 1 ' + command + '\n'
                with self.subTest(command=command), self.assertRaises(RuntimeError):
                    q.check_host_idle()

    def test_require_fresh_boot_and_unchanged_state(self):
        before = self.before()
        after = dict(before, boot_id='22222222-2222-2222-2222-222222222222')
        q.verify_return(before, after)
        with self.assertRaises(RuntimeError):
            q.verify_return(before, before)
        for key in ('boot_sha256', 'gpt_sha256', 'system', 'healthy'):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                q.verify_return(before, dict(after, **{key: 'changed'}))

    def test_reject_unhealthy_or_wrong_linux(self):
        for field in ('boot_sha256', 'system', 'healthy', 'boot_id', 'gpt_sha256'):
            data = dict(self.before(), **{field: 'wrong'})
            with patch.object(q, 'run', return_value='\n'.join(f'{k}={v}' for k, v in data.items())), \
                 self.subTest(field=field), self.assertRaises(RuntimeError):
                q.snapshot(['ssh'])

    def test_readback_requires_complete_matching_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            boot, gpt = b'b' * (16 * 1024 * 1024), b'g' * 32768
            before = dict(boot_sha256=hashlib.sha256(boot).hexdigest(),
                          gpt_sha256=hashlib.sha256(gpt).hexdigest())
            (directory / 'boot-readback.img').write_bytes(boot)
            (directory / 'gpt-primary.bin').write_bytes(gpt)
            q.verify_reads(directory, before)
            for wrong in (gpt[:-1], b'x' + gpt[1:]):
                (directory / 'gpt-primary.bin').write_bytes(wrong)
                with self.assertRaises(RuntimeError):
                    q.verify_reads(directory, before)
            (directory / 'gpt-primary.bin').unlink()
            with self.assertRaises(FileNotFoundError):
                q.verify_reads(directory, before)

    def test_phase_capture_is_fixed_address_read_only(self):
        commands = q.commands_for(False, True).split(';')
        self.assertEqual(commands[0], 'da peek 0x10007024 4 --filename boot-phase.bin')
        self.assertFalse(any(command.startswith(('w ', 'da poke', 'e ')) for command in commands))
        self.assertEqual(q.commands_for(False, False), q.COMMANDS)
        self.assertEqual(q.commands_for(True, False), q.WRITE_COMMANDS)

    def test_ramoops_capture_precedes_flash_access_without_adding_writes(self):
        for writing in (False, True):
            for phase in (False, True):
                commands = q.commands_for(writing, phase, True).split(';')
                self.assertEqual(commands.count(q.RAMOOPS_READ), 1)
                self.assertLess(commands.index(q.RAMOOPS_READ), commands.index('printgpt'))
                self.assertEqual(any(c.startswith('w ') for c in commands), writing)
                self.assertFalse(any(c.startswith('da poke') for c in commands))

    def test_phase_capture_requires_complete_little_endian_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            path = directory / 'boot-phase.bin'
            path.write_bytes(bytes.fromhex('ec104d47'))
            result = q.phase_readback(directory)
            self.assertEqual(result['value_hex'], '0x474d10ec')
            self.assertFalse(result['retention_across_vendor_boot_stages_qualified'])
            for bad in (b'', b'abc', b'abcde'):
                path.write_bytes(bad)
                with self.assertRaises(RuntimeError):
                    q.phase_readback(directory)

    def test_default_preflight_cannot_start_trial(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            mtk = directory / 'mtk'
            mtk.touch()
            argv = ['qualify', '--mtk', str(mtk), '--out', str(directory / 'result'),
                    '--lock-dir', str(directory)]
            with patch.object(q.sys, 'argv', argv), patch.object(q, 'check_host_idle'), \
                 patch.object(q, 'run', return_value='--bootmode {shutdown,reboot,fastboot}'), \
                 patch.object(q, 'snapshot', return_value=self.before()), \
                 patch.object(q, 'trial') as trial, contextlib.redirect_stdout(io.StringIO()):
                q.main()
            trial.assert_not_called()

    def test_write_image_requires_exact_size_and_accepted_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'image'
            data = b'a' * (16 * 1024 * 1024)
            with patch.object(q, 'ACCEPTED_BOOT', hashlib.sha256(data).hexdigest()):
                source.write_bytes(data)
                self.assertEqual(q.accepted_boot_bytes(source), data)
                for bad in (data[:-1], data + b'x', b'x' + data[1:]):
                    source.write_bytes(bad)
                    with self.assertRaises(RuntimeError):
                        q.accepted_boot_bytes(source)

    def test_invalid_staged_write_cannot_start_client_or_reboot(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'accepted-boot.img').write_bytes(b'wrong image')
            with patch.object(q.subprocess, 'Popen') as client, \
                 patch.object(q.subprocess, 'run') as reboot, self.assertRaises(RuntimeError):
                q.trial(SimpleNamespace(mtk='/fake/mtk', rewrite_accepted_boot='requested'),
                        directory, self.before(), ['ssh'])
            client.assert_not_called()
            reboot.assert_not_called()

    def test_identical_image_write_requires_both_write_and_reboot_ack(self):
        q.verify_da_result(0, q.ACK, False)
        q.verify_da_result(0, q.WRITE_ACK + '\n' + q.ACK, True)
        for code, log in ((0, q.ACK), (0, q.WRITE_ACK),
                          (1, q.WRITE_ACK + '\n' + q.ACK),
                          (0, q.WRITE_ACK.replace('362496', '1') + '\n' + q.ACK)):
            with self.subTest(code=code, log=log), self.assertRaises(RuntimeError):
                q.verify_da_result(code, log, True)

    def test_write_preflight_only_stages_verified_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source, mtk = directory / 'source.img', directory / 'mtk'
            data = b'a' * (16 * 1024 * 1024)
            source.write_bytes(data)
            mtk.touch()
            out = directory / 'result'
            argv = ['qualify', '--mtk', str(mtk), '--out', str(out),
                    '--lock-dir', str(directory), '--rewrite-accepted-boot', str(source)]
            with patch.object(q, 'ACCEPTED_BOOT', hashlib.sha256(data).hexdigest()), \
                 patch.object(q.sys, 'argv', argv), patch.object(q, 'check_host_idle'), \
                 patch.object(q, 'run', return_value='--bootmode {shutdown,reboot,fastboot}'), \
                 patch.object(q, 'snapshot', return_value=self.before()), \
                 patch.object(q, 'trial') as trial, contextlib.redirect_stdout(io.StringIO()):
                q.main()
            trial.assert_not_called()
            self.assertEqual((out / 'accepted-boot.img').read_bytes(), data)
            plan = json.loads((out / 'plan.json').read_text())
            self.assertFalse(plan['execute'])
            self.assertTrue(plan['write_requested'])
            self.assertEqual([c for c in plan['commands'].split(';') if c.startswith('w ')],
                             ['w boot accepted-boot.img'])

    def test_early_mtk_exit_never_reboots_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            child = Mock()
            child.poll.return_value = 1
            with patch.object(q.subprocess, 'Popen', return_value=child), \
                 patch.object(q.subprocess, 'run') as reboot, self.assertRaises(RuntimeError):
                q.trial(SimpleNamespace(mtk='/fake/mtk'), Path(tmp), self.before(), ['ssh'])
            reboot.assert_not_called()

    def test_usb_ssh_target_keeps_known_host_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            mtk = directory / 'mtk'
            mtk.touch()
            argv = ['qualify', '--mtk', str(mtk), '--out', str(directory / 'result'),
                    '--lock-dir', str(directory), '--ssh-host', '10.15.19.82',
                    '--ssh-host-key-alias', '192.168.23.70']
            with patch.object(q.sys, 'argv', argv), patch.object(q, 'check_host_idle'), \
                 patch.object(q, 'run', return_value='--bootmode {shutdown,reboot,fastboot}'), \
                 patch.object(q, 'snapshot', return_value=self.before()) as snapshot, \
                 contextlib.redirect_stdout(io.StringIO()):
                q.main()
            ssh = snapshot.call_args.args[0]
            self.assertEqual(ssh[-1], 'root@10.15.19.82')
            self.assertIn('HostKeyAlias=192.168.23.70', ssh)
            self.assertIn('StrictHostKeyChecking=yes', ssh)
            self.assertIn('ControlPath=none', ssh)

    def test_readbacks_exist_before_privileged_client_and_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            child = Mock()
            child.poll.return_value = 1
            def start(*args, **kwargs):
                for name in ('gpt-primary.bin', 'boot-readback.img'):
                    path = directory / name
                    self.assertEqual(path.stat().st_uid, q.os.getuid())
                    self.assertEqual(path.read_bytes(), b'')
                    # The real DA writer truncates the existing file.
                    path.write_bytes(b'da output')
                return child
            with patch.object(q.subprocess, 'Popen', side_effect=start) as spawn:
                with self.assertRaises(RuntimeError):
                    q.trial(SimpleNamespace(mtk='/fake/mtk'), directory, self.before(), ['ssh'])
                for name in ('gpt-primary.bin', 'boot-readback.img'):
                    self.assertEqual((directory / name).read_bytes(), b'da output')
                with self.assertRaises(FileExistsError):
                    q.trial(SimpleNamespace(mtk='/fake/mtk'), directory, self.before(), ['ssh'])
                spawn.assert_called_once()

    def test_failed_mtk_still_observes_linux_and_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            child = Mock()
            child.poll.return_value = None
            def start(*args, **kwargs):
                kwargs['stdout'].write('Waiting for PreLoader\n')
                kwargs['stdout'].flush()
                return child
            def finish(**kwargs):
                child.poll.return_value = 1
                return 1
            child.wait.side_effect = finish
            after = dict(self.before(), boot_id='22222222-2222-2222-2222-222222222222')
            with patch.object(q.subprocess, 'Popen', side_effect=start), \
                 patch.object(q.subprocess, 'run', return_value=SimpleNamespace(returncode=255, stderr='disconnected')), \
                 patch.object(q, 'snapshot', return_value=after) as snapshot, \
                 contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                q.trial(SimpleNamespace(mtk='/fake/mtk'), Path(tmp), self.before(), ['ssh'])
            snapshot.assert_called_once()
            self.assertTrue((Path(tmp) / 'after.json').exists())
            self.assertFalse((Path(tmp) / 'result.json').exists())


if __name__ == '__main__':
    unittest.main()
