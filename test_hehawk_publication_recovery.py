"""Fault injection at publication boundaries; no real media."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hehawk_publication as pub


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.target = self.root / 'audio/test.mka'
        self.journal = self.root / '.publication.json'
        self.manifest = self.root / 'manifest.json'

    def publish(self):
        return pub.publish(self.root, 'audio/test.mka', 'test',
                           lambda p: p.write_bytes(b'verified payload'),
                           lambda p: None, lambda: None)

    def check_journal(self):
        record = json.loads(self.journal.read_text())
        self.assertEqual(record['state'], 'verified')
        self.assertEqual(record['sha256'], pub.digest(self.target))
        self.assertEqual(record['size'], self.target.stat().st_size)
        self.assertEqual(record['target'], 'audio/test.mka')
        return record

    def test_before_manifest_commit(self):
        original = pub.atomic_json
        def fail(path, value, replace=False):
            if path == self.manifest:
                raise OSError('injected manifest failure')
            return original(path, value, replace)
        with patch.object(pub, 'atomic_json', side_effect=fail):
            with self.assertRaises(OSError):
                self.publish()
        record = self.check_journal()
        self.assertFalse(self.manifest.exists())
        self.assertEqual((self.root / record['temporary']).stat().st_ino,
                         self.target.stat().st_ino)
        with self.assertRaises(RuntimeError):
            self.publish()
        self.assertEqual(self.target.read_bytes(), b'verified payload')

    def test_after_manifest_commit(self):
        original = pub.atomic_json
        def fail(path, value, replace=False):
            original(path, value, replace)
            if path == self.manifest:
                raise OSError('injected post-commit failure')
        with patch.object(pub, 'atomic_json', side_effect=fail):
            with self.assertRaises(OSError):
                self.publish()
        record = self.check_journal()
        entry = json.loads(self.manifest.read_text())['resources']['test']
        self.assertEqual(entry['sha256'], record['sha256'])
        with self.assertRaises(RuntimeError):
            self.publish()

    def test_unexplained_destination(self):
        self.target.parent.mkdir()
        self.target.write_bytes(b'unrelated')
        with self.assertRaises(FileExistsError):
            self.publish()
        self.assertFalse(self.journal.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(self.target.read_bytes(), b'unrelated')


if __name__ == '__main__':
    unittest.main()
