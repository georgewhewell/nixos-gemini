#!/usr/bin/env python3
"""Host-only rejection tests for EFI proof and candidate/rescue identities."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('runner', Path(__file__).resolve().parents[1]/'tools/qualify-uboot-recovery.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
e = r.efi_linux

class EfiProof(unittest.TestCase):
    def test_manager_exception_is_diagnostic_and_never_a_boot_pass(self):
        for pc in (0x40200000,0x40212344,0x403ffffc):
            record=0x80000000|(0x25<<25)|(0x21<<19)|((pc-0x40200000)>>2)
            raw=f'{record:#010x}'
            result=r.phase_evidence('0x00000000',raw,'efi-manager')
            self.assertEqual(result['exception_pc'],hex(pc))
            self.assertEqual(result['exception_class'],'0x25')
            self.assertEqual(result['exception_iss_low6'],'0x21')
            self.assertTrue(result['uboot_execution_proven'])
            self.assertFalse(result['intended_test_branch_reached'])
            self.assertFalse(r.profile_qualified('efi-manager',result,26,False))
            self.assertFalse(r.phase_evidence(raw,raw,'efi-manager')['uboot_execution_proven'])
            self.assertFalse(r.phase_evidence('0x00000000',raw,'efi-storage')['uboot_execution_proven'])
    def test_console_requires_its_own_successful_efi_application(self):
        after={r.HANDOFF_MARKER:b'efi\0'.hex(),r.CONSOLE_MARKER:b'passed\0'.hex()}
        r.verify_handoff_tree({},after,'efi-console')
        for tree in ({r.HANDOFF_MARKER:b'efi\0'.hex()},
                     dict(after,**{r.CONSOLE_MARKER:b'failed\0'.hex()})):
            with self.assertRaises(RuntimeError): r.verify_handoff_tree({},tree,'efi-console')
        with self.assertRaises(RuntimeError): r.verify_handoff_tree({},after,'efi-linux')
        with self.assertRaises(RuntimeError): r.verify_handoff_tree(after,after,'efi-console')
    def test_keyboard_requires_real_scans_without_claiming_key_presses(self):
        after={r.HANDOFF_MARKER:b'efi\0'.hex(),r.CONSOLE_MARKER:b'passed\0'.hex(),
               r.KEYBOARD_MARKER:b'scanned\0'.hex(),r.KEYBOARD_SCANS:(200).to_bytes(4,'big').hex(),
               r.KEYBOARD_ERROR:'00000000'}
        r.verify_handoff_tree({},after,'efi-keyboard')
        for key,value in ((r.KEYBOARD_MARKER,b'failed\0'.hex()),(r.KEYBOARD_ERROR,'fffffffb'),
                          (r.KEYBOARD_SCANS,'00000013'),(r.KEYBOARD_SCANS,'')):
            with self.assertRaises(RuntimeError):
                r.verify_handoff_tree({},dict(after,**{key:value}),'efi-keyboard')
        with self.assertRaises(RuntimeError): r.verify_handoff_tree({},after,'efi-console')
        with self.assertRaises(RuntimeError): r.verify_handoff_tree(after,after,'efi-keyboard')
    def test_mmc_requires_exact_full_reads_and_native_bus_evidence(self):
        tree={r.HANDOFF_MARKER:b'efi\0'.hex(),r.CONSOLE_MARKER:b'passed\0'.hex(),
              r.KEYBOARD_MARKER:b'scanned\0'.hex(),r.KEYBOARD_SCANS:'00000100',r.KEYBOARD_ERROR:'00000000'}
        values={'result':b'passed\0'.hex(),'stage':b'filesystem\0'.hex(),'error':'00000000',
                'width':'00000008','clock':(25000000).to_bytes(4,'big').hex(),'elapsed-ms':'00001388',
                'gpt-sha256':r.MMC_GPT_SHA,'boot-sha256':r.PROFILES['efi-mmc'][1],
                'boot2-sha256':r.P30_SHA,'boot3-sha256':r.P31_SHA,'file-sha256':r.MMC_FILE_SHA}
        tree.update({'chosen/gemini,uefi-mmc-'+key:value for key,value in values.items()})
        r.verify_handoff_tree({},tree,'efi-mmc')
        for key in r.MMC_MARKERS:
            for bad in (None, '', '0' * 64, 'ffffffff', '00000000'):
                if bad == tree[key]: continue
                with self.subTest(key=key,value=bad), self.assertRaises(RuntimeError):
                    r.verify_handoff_tree({},dict(tree,**{key:bad}),'efi-mmc')
            missing=dict(tree);del missing[key]
            with self.assertRaises(RuntimeError): r.verify_handoff_tree({},missing,'efi-mmc')
        for profile in ('efi-keyboard','efi-console','efi-linux'):
            with self.assertRaises(RuntimeError): r.verify_handoff_tree({},tree,profile)
        with self.assertRaises(RuntimeError): r.verify_handoff_tree(tree,tree,'efi-mmc')
        self.assertEqual(r.phase_evidence('0x00000000','0x474d3016','efi-mmc')['uboot_phase'],
                         'mmc_resource_failure_errno_22')

    def test_storage_requires_efi_application_and_native_mmc_success(self):
        tree={r.HANDOFF_MARKER:b'efi\0'.hex(),r.CONSOLE_MARKER:b'passed\0'.hex(),
              r.KEYBOARD_MARKER:b'scanned\0'.hex(),r.KEYBOARD_SCANS:'00000100',r.KEYBOARD_ERROR:'00000000',
              r.STORAGE_MARKER:b'passed\0'.hex(),r.STORAGE_STATUS:'0000000000000000'}
        values={'result':b'passed\0'.hex(),'stage':b'filesystem\0'.hex(),'error':'00000000',
                'width':'00000008','clock':(25000000).to_bytes(4,'big').hex(),'elapsed-ms':'00001388',
                'gpt-sha256':r.MMC_GPT_SHA,'boot-sha256':r.PROFILES['efi-storage'][1],
                'boot2-sha256':r.P30_SHA,'boot3-sha256':r.P31_SHA,'file-sha256':r.MMC_FILE_SHA}
        tree.update({'chosen/gemini,uefi-mmc-'+key:value for key,value in values.items()})
        r.verify_handoff_tree({},tree,'efi-storage')
        provision=dict(tree,**{'chosen/gemini,uefi-mmc-boot-sha256':r.PROFILES['efi-provision'][1]})
        r.verify_handoff_tree({},provision,'efi-provision')
        with self.assertRaises(RuntimeError): r.verify_handoff_tree({},tree,'efi-provision')
        manager=dict(tree,**{'chosen/gemini,uefi-mmc-boot-sha256':r.PROFILES['efi-manager'][1],
                            r.efi_manager.PREFIX+'result':b'starting\0'.hex(),
                            r.efi_manager.PREFIX+'stage':b'start-image\0'.hex(),
                            r.efi_manager.PREFIX+'sha256':r.efi_manager.SHA})
        r.verify_handoff_tree({},manager,'efi-manager')
        with self.assertRaises(RuntimeError): r.verify_handoff_tree({},tree,'efi-manager')
        with self.assertRaises(RuntimeError): r.verify_handoff_tree({},manager,'efi-storage')
        for key in r.efi_manager.MARKERS:
            wrong=dict(manager,**{key:'0000000000000000'})
            with self.assertRaises(RuntimeError): r.verify_handoff_tree({},wrong,'efi-manager')
        for key,wrong in ((r.STORAGE_MARKER,b'failed\0'.hex()),(r.STORAGE_STATUS,'800000000000000e'),
                          (r.STORAGE_STATUS,'00000000'),('chosen/gemini,uefi-mmc-boot-sha256',r.PROFILES['efi-mmc'][1])):
            with self.assertRaises(RuntimeError): r.verify_handoff_tree({},dict(tree,**{key:wrong}),'efi-storage')
        for key in r.MARKERS:
            if key not in tree: continue
            missing=dict(tree);del missing[key]
            with self.assertRaises(RuntimeError): r.verify_handoff_tree({},missing,'efi-storage')
        with self.assertRaises(RuntimeError): r.verify_handoff_tree({},tree,'efi-mmc')
        with self.assertRaises(RuntimeError): r.verify_handoff_tree(tree,tree,'efi-storage')

    def setUp(self):
        self.entries = [(0x40000000,0x40001000,'Reserved'),
                        (0x40001000,0x43fff000,'Conventional'),
                        (0x43fff000,0x88000000,'Boot Data'),
                        (0x88000000,0x88600000,'Reserved'),
                        (0x88600000,0x140000000,'Boot Data')]
        self.props = {k:v.to_bytes(w,'big').hex() for k,v,w in (
            ('linux,uefi-system-table',0x43a00000,8), ('linux,uefi-mmap-start',0x42c00000,8),
            ('linux,uefi-mmap-size',200,4),('linux,uefi-mmap-desc-size',40,4),
            ('linux,uefi-mmap-desc-ver',1,4))}
        self.tree = {'reserved-memory/mblock-5-ccci/reg': '00000000880000000000000000600000',
                     'reserved-memory/mblock-5-ccci/no-map': ''}
    def log(self, entries=None):
        return ('[0.100000] arm64-late-cpu-profile: verified the pre-finalization runtime identity binding\n'
                '[0.110000] arm64-late-cpu-profile: mt6797-a53-a72-a41-v7 ready\n'
                '[0.000000] efi: EFI v2.110 by Das U-Boot\n[0.000000] efi: INITRD=0x43c00000\n') + '\n'.join(
            f'[0.000000] efi:   0x{lo:012x}-0x{hi-1:012x} [{kind:12}|WB]'
            for lo,hi,kind in (entries or self.entries))
    def test_full_map_is_required(self):
        self.assertTrue(e.verify_evidence(self.log(),self.props,'64',self.tree)['exit_boot_services_proven'])
        for entries in (self.entries[:-1],self.entries[1:], self.entries+self.entries[:1],
                        [*self.entries[:2],(0x43fff000,0x88000000,'Conventional'),*self.entries[3:]],
                        [*self.entries[:3],(0x88000000,0x88600000,'Boot Data'),self.entries[4]]):
            with self.subTest(entries=entries), self.assertRaises(RuntimeError):
                e.verify_evidence(self.log(entries),self.props,'64',self.tree)
    def test_real_efi_and_bounded_tables_are_required(self):
        for log,platform in (('', '64'), (self.log(),'32'), (self.log().replace('Das U-Boot','other'),'64')):
            with self.assertRaises(RuntimeError): e.verify_evidence(log,self.props,platform,self.tree)
        with self.assertRaises(RuntimeError):
            e.verify_evidence(self.log().replace('INITRD=', 'INVALID='),self.props,'64',self.tree)
        for message in ('verified the pre-finalization runtime identity binding',
                        'mt6797-a53-a72-a41-v7 ready'):
            with self.assertRaises(RuntimeError):
                e.verify_evidence(self.log().replace(message, 'identity mismatch'),self.props,'64',self.tree)
        for key,value in ((k,'') for k in self.props):
            with self.assertRaises(RuntimeError): e.verify_evidence(self.log(),dict(self.props,**{key:value}),'64',self.tree)
        for key,value in (('linux,uefi-system-table',(0x88000000).to_bytes(8,'big').hex()),
                          ('linux,uefi-mmap-desc-size',(41).to_bytes(4,'big').hex()),
                          ('linux,uefi-mmap-desc-ver',(2).to_bytes(4,'big').hex()),
                          ('linux,uefi-mmap-size',(240).to_bytes(4,'big').hex())):
            with self.assertRaises(RuntimeError): e.verify_evidence(self.log(),dict(self.props,**{key:value}),'64',self.tree)
    def test_efi_candidate_changes_only_its_expected_system_and_boot(self):
        before=dict(boot_id='a'*8+'-'+'a'*4+'-'+'a'*4+'-'+'a'*4+'-'+'a'*12,
                    system=r.qualify.ACCEPTED_SYSTEM,boot_sha256=r.qualify.ACCEPTED_BOOT,
                    gpt_sha256='b'*64,healthy='yes')
        middle=dict(before,boot_id='cccccccc-cccc-cccc-cccc-cccccccccccc',system=e.SYSTEM,
                    boot_sha256=r.PROFILES['efi-linux'][1])
        hashes=r.P30_SHA+' p30\n'+r.P31_SHA+' p31'
        for change in ({},{'system':before['system']},{'gpt_sha256':'c'*64}, {'boot_sha256':before['boot_sha256']}):
            rows='\n'.join(f'{k}={v}' for k,v in dict(middle,**change).items())
            with patch.object(r.qualify,'run',side_effect=[rows,hashes]):
                if change:
                    with self.assertRaises(RuntimeError): r.candidate_snapshot([],before,'efi-linux')
                else: self.assertEqual(r.candidate_snapshot([],before,'efi-linux')['system'],e.SYSTEM)
        self.assertEqual(r.rescue_identity(before,middle),dict(before,boot_id=middle['boot_id']))
        # Baseline and rescue retain their independent accepted-image guards.
        with patch.object(r.qualify,'run',return_value='\n'.join(f'{k}={v}' for k,v in middle.items())):
            with self.assertRaises(RuntimeError): r.qualify.snapshot([])
    def test_upload_rejects_unpinned_names_and_shell_values(self):
        before={'boot_id':'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','gpt_sha256':'b'*64}
        name=f'mainline-nixos-{e.STORE_SHA}.squashfs'
        script=e.upload_command(name,before,'c'*64)
        self.assertIn('(set -C; cat >',script)
        self.assertIn('*,noload,*|*,norecovery,*) exit 1',script)
        self.assertIn(e.ACCEPTED_STORE_SHA,script)
        for bad in ('x',e.ACCEPTED_STORE,name+"'; false"):
            with self.assertRaises(ValueError): e.upload_command(bad,before,'c'*64)
        with self.assertRaises(ValueError): e.upload_command(name,before,'$(false)')

if __name__ == '__main__': unittest.main()
