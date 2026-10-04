#!/usr/bin/env python3
"""Reject incomplete, reordered or altered GPT qualification evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('qualification',Path(__file__).with_name('qualify-gpt-rewrite.py'))
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)


class Evidence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)
        primary=b'P'*32768;backup=b'B'*(33*512)
        for key,value in {'PRIMARY_SHA':q.g.sha(primary),'PRIMARY_WRITE_SHA':q.g.sha(primary[:34*512]),'BACKUP_SHA':q.g.sha(backup)}.items():
            patch=mock.patch.object(q.g,key,value);patch.start();self.addCleanup(patch.stop)
        for prefix,raw in (('primary',primary),('backup',backup)):
            for suffix in ('before','after'):(self.directory/(prefix+'-'+suffix+'.bin')).write_bytes(raw)
        self.before={'flashinfo_sha256':'a'*64}
        protected={name:sha for name,_,_,sha in q.g.PROTECTED};protected['flashinfo']='a'*64
        guards=[('primary-before',0,32768,q.g.PRIMARY_SHA),('backup-before',q.g.BACKUP_OFFSET,33*512,q.g.BACKUP_SHA)]
        protected_reads=[(name,offset,size,protected[name]) for name,offset,size,_ in q.g.PROTECTED]
        def reads(rows):
            return [dict(event='read-verified',name=name,offset=offset,size=size,sha256=digest) for name,offset,size,digest in rows]
        self.events=reads(guards+protected_reads)+[dict(event='admitted',primary_sha256=q.g.PRIMARY_SHA,backup_sha256=q.g.BACKUP_SHA)]
        for name,offset,size,sha in (('backup',q.g.BACKUP_OFFSET,33*512,q.g.BACKUP_SHA),('primary',0,34*512,q.g.PRIMARY_WRITE_SHA)):
            for event,suffix in (('write-intent',''),('write-acknowledged',''),('read-verified','-readback')):
                self.events.append(dict(event=event,name=name+suffix,offset=offset,size=size,sha256=sha))
        self.events+=reads([(name.replace('-before','-after'),offset,size,digest) for name,offset,size,digest in guards]+protected_reads)+[dict(event='reboot',acknowledged=True)]
        self.result=dict(schema='gemini-factory-gpt-rewrite-v1',operation_qualified=True,
                         original_layout_verified=True,reboot_acknowledged=True,
                         write_attempted=True,rollback_attempted=False,
                         protected_before=protected,protected_after=protected,events=self.events)

    def verify(self,result=None,events=None,rc=0,complete=True,ack=True):
        result=self.result if result is None else result
        events=result['events'] if events is None else events
        (self.directory/'gpt-result.json').write_text(json.dumps(result))
        (self.directory/'gpt-events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        return q.verify_evidence(self.directory,self.before,rc,SimpleNamespace(complete=complete,acknowledged=ack))

    def test_complete_ordered_proof_is_accepted(self):self.verify()

    def test_false_flags_incomplete_usb_and_nonzero_exit_are_rejected(self):
        for key in ('operation_qualified','original_layout_verified','reboot_acknowledged','write_attempted'):
            with self.subTest(key=key),self.assertRaises(RuntimeError):self.verify(dict(self.result,**{key:False}))
        for args in ({'rc':1},{'complete':False},{'ack':False},{'result':dict(self.result,rollback_attempted=True)}):
            with self.assertRaises(RuntimeError):self.verify(**args)

    def test_missing_acks_wrong_ranges_and_primary_before_backup_are_rejected(self):
        for field,value in (('offset',512),('size',32768),('sha256','b'*64)):
            result=copy.deepcopy(self.result);result['events'][8][field]=value
            with self.assertRaises(RuntimeError):self.verify(result)
        result=copy.deepcopy(self.result);result['events'].pop(8)
        with self.assertRaises(RuntimeError):self.verify(result)
        result=copy.deepcopy(self.result);result['events'][7:13]=result['events'][10:13]+result['events'][7:10]
        with self.assertRaises(RuntimeError):self.verify(result)
        result=copy.deepcopy(self.result);result['events'][9],result['events'][10]=result['events'][10],result['events'][9]
        with self.assertRaises(RuntimeError):self.verify(result)

    def test_mutated_binary_readbacks_cannot_be_hidden_by_success_json(self):
        path=self.directory/'backup-after.bin';path.write_bytes(b'X'*(33*512))
        with self.assertRaises(RuntimeError):self.verify()

    def test_changed_protected_partition_and_nonmatching_journal_are_rejected(self):
        result=copy.deepcopy(self.result);result['protected_after']['flashinfo']='b'*64
        with self.assertRaises(RuntimeError):self.verify(result)
        with self.assertRaises(RuntimeError):self.verify(events=[])


if __name__=='__main__':unittest.main()
