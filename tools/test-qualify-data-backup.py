#!/usr/bin/env python3
"""Reject incomplete or altered offline backup evidence and byte streams."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qualification', ROOT / 'tools/qualify-data-backup.py')
q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)
fixture = q.q.module('backup_fixture', ROOT / 'nix/test-mtk-data-backup.py')


class Verify(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.Backup('test_complete_offline_data_exact_bytes_and_ordered_reads')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        patch = mock.patch.object(q, 'b', fixture.b); patch.start(); self.addCleanup(patch.stop)
        self.directory = self.fixture.directory
        ok, self.result = self.fixture.capture(); self.assertTrue(ok)
        self.before = dict(flashinfo_sha256=self.result['protected_before']['flashinfo'])

    def save(self):
        (self.directory / 'backup-result.json').write_text(json.dumps(self.result))
        (self.directory / 'backup-events.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in self.result['events']))

    def verify(self, rc=0, complete=True, acknowledged=True):
        return q.verify_capture(self.directory, self.before, rc, SimpleNamespace(complete=complete, acknowledged=acknowledged))

    def test_real_capture_passes_independent_host_chunk_and_complete_hashes(self):
        proof = self.verify()
        self.assertEqual(proof['data_sha256'], q.b.g.sha(self.fixture.data))
        self.assertEqual(proof['captured_chunks'], 4)

    def test_no_success_on_failed_read_reboot_or_device_write_claim(self):
        for args in ({'rc':1}, {'complete':False}, {'acknowledged':False}):
            with self.assertRaises(RuntimeError): self.verify(**args)
        for key, bad in (('qualified',False), ('capture_complete',False),
                          ('original_layout_verified',False), ('reboot_acknowledged',False),
                          ('device_writes_performed',True)):
            original = self.result[key]; self.result[key] = bad; self.save()
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.verify()
            self.result[key] = original; self.save()

    def test_missing_reordered_or_wrong_chunk_evidence_is_rejected(self):
        original = json.loads(json.dumps(self.result))
        for mutation in ('missing', 'reordered', 'offset', 'size', 'sha256'):
            self.result = json.loads(json.dumps(original)); events = self.result['events']
            if mutation == 'missing': events.pop(7)
            elif mutation == 'reordered': events[7], events[8] = events[8], events[7]
            else: events[7][mutation] = '0'*64 if mutation == 'sha256' else 42
            self.save()
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError): self.verify()

    def test_changed_image_or_tail_is_not_hidden_by_success_result(self):
        for name in ('data.ext4', 'swap-header-before.bin', 'backup-after.bin'):
            path = self.directory / name; old = path.read_bytes(); path.write_bytes(b'Z' + old[1:])
            with self.subTest(name=name), self.assertRaises(RuntimeError): self.verify()
            path.write_bytes(old)
        path = self.directory / 'data.ext4'; path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(RuntimeError): self.verify()

    def test_changed_protected_data_and_admission_fields_are_rejected(self):
        original = json.loads(json.dumps(self.result))
        for mutation in ('protected', 'extent', 'guard_phase', 'guard_offset'):
            self.result = json.loads(json.dumps(original))
            if mutation == 'protected': self.result['protected_after']['flashinfo'] = 'f'*64
            if mutation == 'extent': self.result['events'][6]['block_count'] = 42
            if mutation == 'guard_phase': self.result['events'][0]['phase'] = 'after'
            if mutation == 'guard_offset': self.result['events'][0]['offset'] = 512
            self.save()
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError): self.verify()

    def test_complete_digest_and_duplicate_journal_must_agree(self):
        self.result['data_sha256'] = 'f'*64; self.save()
        with self.assertRaises(RuntimeError): self.verify()
        (self.directory / 'backup-events.jsonl').write_text('')
        with self.assertRaises(RuntimeError): self.verify()


if __name__ == '__main__': unittest.main()
