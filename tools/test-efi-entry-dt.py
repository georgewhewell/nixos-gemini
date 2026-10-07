#!/usr/bin/env python3
"""Reject stale entry markers and any mismatched selected-kernel provenance."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'))
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
d=module('qualify-efi-entry-dt');f=module('qualify-efi-files')
FDT=Path(d.FDTGET).with_name('fdtput')
class EntryDT(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.runtime=Path(self.temp.name)/'runtime.dtb'
        self.archive,self.manifest=f.payload(d.files_profile(f))
        self.source=d.BUNDLE/'tree'/self.manifest['entry_device_tree']
    def write(self,node,name,value):
        subprocess.run([str(FDT),'-t','s',str(self.runtime),node,name,value],check=True)
    def complete(self):
        shutil.copyfile(d.WORKSPACE/'handoff/efi-nix-manager-01/candidate-fdt.dtb',self.runtime)
        self.write('/chosen','gemini,efi-entry-id',d.IDENTITY)
        self.write('/chosen','gemini,uefi-dt-fixup','lk-delta-v1')
    def test_archive_binds_six_files_bls_reference_and_entry_marker(self):
        self.assertEqual(len(self.manifest['files']),6)
        entry=(d.BUNDLE/'tree/loader/entries'/d.ENTRY).read_text()
        self.assertIn('devicetree /'+self.manifest['entry_device_tree']+'\n',entry)
        with self.assertRaises(RuntimeError):f.payload(d.files_profile(f)._replace(count=5))
    def test_matching_runtime_requires_both_markers(self):
        self.complete();d.verify(self.source,self.runtime)
        for prop in ('gemini,efi-entry-id','gemini,uefi-dt-fixup'):
            self.complete();self.write('/chosen',prop,'stale')
            with self.assertRaises(RuntimeError):d.verify(self.source,self.runtime)
    def test_every_provenance_field_is_checked(self):
        for prop in d.properties(self.source,d.LEAF):
            self.complete();self.write(d.LEAF,prop,'wrong selected kernel')
            with self.assertRaises(RuntimeError):d.verify(self.source,self.runtime)
    def test_other_kernel_cannot_pass_with_matching_markers(self):
        shutil.copyfile(d.WORKSPACE/'handoff/uboot-efi-linux-04/candidate-fdt.dtb',self.runtime)
        self.write('/chosen','gemini,efi-entry-id',d.IDENTITY)
        self.write('/chosen','gemini,uefi-dt-fixup','lk-delta-v1')
        with self.assertRaises(RuntimeError):d.verify(self.source,self.runtime)
    def test_cross_carrier_has_older_payload_and_distinct_selected_identity(self):
        carrier=d.WORKSPACE/'handoff/efi-cross-entry-dt-manager/boot-padded-p22.img'
        sha='d399b431e2683039848550bd64e2c43be343522b0d14cf1551a06511d02615d4'
        evidence=d.cross_carrier(carrier,sha,self.source)
        self.assertIn('expected-ikconfig-identity',evidence['changed_provenance_fields'])
        with self.assertRaises(RuntimeError):d.cross_carrier(carrier,'0'*64,self.source)
        with self.assertRaises(RuntimeError):
            d.cross_carrier(carrier,sha,d.OLD_BUNDLE/'gemini-usb11-host.dtb')
        same=d.WORKSPACE/'handoff/nix-efi-entry-dt-manager-pad/boot-padded-p22.img'
        with self.assertRaises(RuntimeError):
            d.cross_carrier(same,'ef5c215b95da370e993710785d23c84c57dda47e40dab600b2ee302ef1d4ec19',self.source)
    def test_cross_result_requires_selected_provenance_before_saving(self):
        shutil.copyfile(d.WORKSPACE/'handoff/uboot-efi-linux-04/candidate-fdt.dtb',self.runtime)
        self.write('/chosen','gemini,efi-entry-id',d.IDENTITY)
        self.write('/chosen','gemini,uefi-dt-fixup','lk-delta-v1')
        shutil.copyfile(self.runtime,self.runtime.parent/'candidate-fdt.dtb')
        with patch.object(d,'cross_carrier') as check, self.assertRaises(RuntimeError):
            d.cross_evidence(self.runtime.parent,'boot',f,None,None,None)
        check.assert_not_called()
    def test_native_entry_preserves_cpu_properties_and_has_no_legacy_record(self):
        source=self.runtime.with_name('native.dtb');dts=self.runtime.with_suffix('.dts');identity='a'*64
        dts.write_text('/dts-v1/; / { chosen { gemini,efi-entry-id = "'+identity+'"; }; '
                       'cpus { #address-cells = <1>; #size-cells = <0>; '
                       'cpu@8 { device_type = "cpu"; compatible = "arm,cortex-a72"; reg = <8>; }; }; };')
        subprocess.run([str(FDT.with_name('dtc')),'-I','dts','-O','dtb','-o',str(source),str(dts)],check=True)
        shutil.copyfile(source,self.runtime)
        self.write('/chosen','gemini,uefi-dt-fixup','lk-delta-v1')
        d.verify_native(source,self.runtime,identity)
        with self.assertRaises(RuntimeError):d.verify_native(source,self.runtime,'b'*64)
        self.write('/cpus/cpu@8','compatible','arm,cortex-a53')
        with self.assertRaises(RuntimeError):d.verify_native(source,self.runtime,identity)
        self.write('/cpus/cpu@8','compatible','arm,cortex-a72')
        subprocess.run([str(FDT),'-c',str(self.runtime),d.LEAF],check=True)
        with self.assertRaises(RuntimeError):d.verify_native(source,self.runtime,identity)
if __name__=='__main__':unittest.main()
