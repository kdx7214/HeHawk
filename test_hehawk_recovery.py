"""Synthetic reconciliation tests using real publication fault boundaries."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hehawk_publication as pub
import hehawk_recovery as rec


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.target = self.root / 'audio/test.mka'
        self.journal = self.root / '.publication.json'
        self.manifest = self.root / 'manifest.json'

    def publish(self, producer=None):
        return pub.publish(self.root, 'audio/test.mka', 'test',
                           producer or (lambda p: p.write_bytes(b'payload')),
                           lambda p: None, lambda: None)

    def recover(self):
        return rec.reconcile(self.root, lambda: None)

    def interrupt(self, stage):
        original = pub.atomic_json
        def fail(path, value, replace=False):
            if path == self.manifest and stage == 'before_commit':
                raise OSError('injected')
            original(path, value, replace)
            if path == self.manifest and stage == 'after_commit':
                raise OSError('injected')
        if stage == 'before_link':
            original_link = pub.os.link
            def link(src, dst, *args, **kwargs):
                if Path(dst) == self.target:
                    raise OSError('injected')
                return original_link(src, dst, *args, **kwargs)
            context = patch.object(pub.os, 'link', side_effect=link)
        else:
            context = patch.object(pub, 'atomic_json', side_effect=fail)
        with context, self.assertRaises(OSError):
            self.publish()
        return self.root / json.loads(self.journal.read_text())['temporary']

    def check_complete(self, temporary):
        self.assertEqual(self.target.read_bytes(), b'payload')
        entry = json.loads(self.manifest.read_text())['resources']['test']
        self.assertEqual(entry['sha256'], pub.digest(self.target))
        self.assertEqual(entry['size'], 7)
        self.assertFalse(temporary.exists())
        self.assertFalse(self.journal.exists())

    def test_verified_unpublished(self):
        temporary = self.interrupt('before_link')
        self.assertFalse(self.target.exists())
        self.assertEqual(self.recover(), 'reconciled')
        self.check_complete(temporary)

    def test_published_uncommitted(self):
        temporary = self.interrupt('before_commit')
        self.assertEqual(self.recover(), 'reconciled')
        self.check_complete(temporary)

    def test_committed(self):
        temporary = self.interrupt('after_commit')
        self.assertEqual(self.recover(), 'reconciled')
        self.check_complete(temporary)

    def test_corruption(self):
        temporary = self.interrupt('before_commit')
        temporary.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.recover()
        self.assertTrue(self.journal.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(self.target.read_bytes(), b'corrupt')

    def test_unrelated_identical_destination(self):
        temporary = self.interrupt('before_link')
        self.target.write_bytes(b'payload')
        with self.assertRaisesRegex(ValueError, 'Unexplained'):
            self.recover()
        self.assertTrue(temporary.exists())
        self.assertTrue(self.journal.exists())
        self.assertFalse(self.manifest.exists())

    def test_incomplete(self):
        def producer(p):
            p.write_bytes(b'partial')
            raise OSError('injected')
        with self.assertRaises(OSError):
            self.publish(producer)
        temporary = self.root / json.loads(self.journal.read_text())['temporary']
        self.assertEqual(self.recover(), 'incomplete_preserved')
        self.assertEqual(temporary.read_bytes(), b'partial')
        self.assertFalse(self.target.exists())
        self.assertTrue(self.journal.exists())

    def test_idempotence(self):
        temporary = self.interrupt('before_commit')
        self.recover()
        before = self.manifest.read_bytes()
        self.assertEqual(self.recover(), 'no_pending_transaction')
        self.assertEqual(self.manifest.read_bytes(), before)
        self.check_complete(temporary)

    def test_interrupted_recovery(self):
        temporary = self.interrupt('before_link')
        with patch.object(rec, 'atomic_json', side_effect=OSError('injected')):
            with self.assertRaises(OSError):
                self.recover()
        self.assertTrue(self.target.samefile(temporary))
        self.assertTrue(self.journal.exists())
        self.assertEqual(self.recover(), 'reconciled')
        self.check_complete(temporary)


if __name__ == '__main__':
    unittest.main()
