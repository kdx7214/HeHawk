import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hehawk_publication as pub
import hehawk_recovery as rec


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.manifest = self.root / 'manifest.json'
        self.journal = self.root / '.publication.json'
        self.provenance = dict(project_id='synthetic', source_relative_path='Movies/Test.mkv',
                               source_size=123, source_mtime_ns=456, source_stream=1,
                               source_codec='aac', extraction_parameters=['-c:a', 'copy'],
                               ffmpeg_version='synthetic')

    def publish(self):
        return pub.publish(self.root, 'audio/test.mka', 'test',
                           lambda p: p.write_bytes(b'payload'), lambda p: None,
                           lambda: None, provenance=self.provenance)

    def check_entry(self):
        entry = json.loads(self.manifest.read_text())['resources']['test']
        self.assertEqual(entry['provenance'], self.provenance)
        self.assertEqual(entry['timeline_mapping'], 'unverified')
        self.assertFalse(self.journal.exists())

    def test_normal(self):
        self.assertEqual(self.publish()['provenance'], self.provenance)
        self.check_entry()

    def test_recovery_before_commit(self):
        original = pub.atomic_json
        def fail(path, value, replace=False):
            if path == self.manifest:
                raise OSError('injected')
            return original(path, value, replace)
        with patch.object(pub, 'atomic_json', side_effect=fail), self.assertRaises(OSError):
            self.publish()
        self.assertEqual(json.loads(self.journal.read_text())['provenance'], self.provenance)
        self.assertEqual(rec.reconcile(self.root, lambda: None), 'reconciled')
        self.check_entry()

    def test_recovery_after_commit(self):
        original = pub.atomic_json
        def fail(path, value, replace=False):
            original(path, value, replace)
            if path == self.manifest:
                raise OSError('injected')
        with patch.object(pub, 'atomic_json', side_effect=fail), self.assertRaises(OSError):
            self.publish()
        self.assertEqual(rec.reconcile(self.root, lambda: None), 'reconciled')
        self.check_entry()

    def test_invalid_provenance(self):
        self.provenance['source_size'] = float('nan')
        with self.assertRaises(ValueError):
            self.publish()
        self.assertFalse(self.journal.exists())
        self.assertFalse(self.manifest.exists())

if __name__ == '__main__':
    unittest.main()
