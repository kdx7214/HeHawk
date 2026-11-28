import json
import tempfile
import unittest
from pathlib import Path
from hehawk_publication import publish, project_lock


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / 'audio/test.mka'

    def run_publish(self, producer=None, verifier=None, preflight=lambda: None, relative='audio/test.mka'):
        return publish(self.root, relative, 'test', producer or (lambda p: p.write_bytes(b'test')), verifier or (lambda p: None), preflight)

    def test_success(self):
        result = self.run_publish()
        self.assertEqual(self.target.read_bytes(), b'test')
        self.assertEqual(json.loads((self.root / 'manifest.json').read_text())['resources']['test'], result)
        self.assertFalse((self.root / '.publication.json').exists())

    def test_conflict(self):
        self.run_publish()
        with self.assertRaises(FileExistsError):
            self.run_publish()
        self.assertEqual(self.target.read_bytes(), b'test')

    def test_failed_verification(self):
        def fail(p):
            raise ValueError('invalid')
        with self.assertRaises(ValueError):
            self.run_publish(verifier=fail)
        self.assertFalse(self.target.exists())
        self.assertTrue((self.root / '.publication.json').exists())
        with self.assertRaises(RuntimeError):
            self.run_publish()

    def test_preflight(self):
        def fail():
            raise ValueError('storage unavailable')
        with self.assertRaises(ValueError):
            self.run_publish(preflight=fail)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_escape(self):
        with self.assertRaises(ValueError):
            self.run_publish(relative='../outside.mka')

    def test_lock(self):
        with project_lock(self.root):
            with self.assertRaises(BlockingIOError):
                self.run_publish()

    def test_interrupted_producer(self):
        def fail(p):
            p.write_bytes(b'partial')
            raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError):
            self.run_publish(producer=fail)
        self.assertFalse(self.target.exists())
        self.assertTrue((self.root / '.publication.json').exists())


if __name__ == '__main__':
    unittest.main()
