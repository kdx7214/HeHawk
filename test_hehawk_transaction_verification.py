import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hehawk_publication as pub
import hehawk_recovery as rec

class VerificationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.target = self.root / 'audio/test.mka'
        self.journal = self.root / '.publication.json'
        self.manifest = self.root / 'manifest.json'
        self.report = {'passed': True, 'schema_version': 2, 'packet_match': True}

    def publish(self, report):
        return pub.publish(self.root, 'audio/test.mka', 'test',
                           lambda p: p.write_bytes(b'payload'), lambda p: report,
                           lambda: None, require_verification=True)

    def test_success(self):
        self.assertEqual(self.publish(self.report)['verification'], self.report)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)

    def test_rejected(self):
        with self.assertRaises(ValueError):
            self.publish({'passed': False})
        self.assertFalse(self.target.exists())
        self.assertEqual(rec.reconcile(self.root, lambda: None), 'incomplete_preserved')

    def test_missing(self):
        with self.assertRaises(ValueError):
            self.publish(None)
        self.assertFalse(self.target.exists())

    def test_invalid_json(self):
        with self.assertRaises(ValueError):
            self.publish({'passed': True, 'value': float('nan')})
        self.assertFalse(self.target.exists())

    def interrupt(self, after):
        original = pub.atomic_json
        def fail(path, value, replace=False):
            if path == self.manifest and not after:
                raise OSError('injected')
            original(path, value, replace)
            if path == self.manifest:
                raise OSError('injected')
        with patch.object(pub, 'atomic_json', side_effect=fail), self.assertRaises(OSError):
            self.publish(self.report)

    def check_recovery(self, after):
        self.interrupt(after)
        self.assertEqual(json.loads(self.journal.read_text())['verification'], self.report)
        self.assertEqual(rec.reconcile(self.root, lambda: None), 'reconciled')
        self.assertEqual(json.loads(self.manifest.read_text())['resources']['test']['verification'], self.report)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)

    def test_before_commit(self):
        self.check_recovery(False)

    def test_after_commit(self):
        self.check_recovery(True)

    def test_missing_recovery_evidence(self):
        self.interrupt(False)
        record = json.loads(self.journal.read_text())
        del record['verification']
        self.journal.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            rec.reconcile(self.root, lambda: None)
        self.assertFalse(self.manifest.exists())

if __name__ == '__main__':
    unittest.main()
