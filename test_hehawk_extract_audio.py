"""Synthetic extraction/publication integration; mount checks mocked only."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hehawk_extract_audio as e

class ExtractionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.media = root / 'media'; self.media.mkdir()
        self.workspace = root / 'workspace'; self.workspace.mkdir()
        self.source = self.media / 'Movies' / 'Synthetic (2020).mkv'
        self.source.parent.mkdir()
        subprocess.run(['ffmpeg','-nostdin','-v','error','-n','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2','-c:a','aac',str(self.source)],check=True)
        self.resources = self.workspace / 'projects/Movies/Synthetic (2020)/resources'
        self.resources.mkdir(parents=True)
        (self.resources.parent/'project.json').write_text(json.dumps({'schema_version':1,'project_id':'synthetic','media_relative_path':'Movies/Synthetic (2020).mkv','source_size':self.source.stat().st_size}))
        self.config = {'minimum_free_gib':0}
        for target in ('hehawk_extract_audio.preflight','hehawk_resources.preflight'):
            p=patch(target,return_value=(self.media,self.workspace,root)); p.start(); self.addCleanup(p.stop)
        p=patch.object(Path,'is_mount',return_value=True); p.start(); self.addCleanup(p.stop)
        # Real safe_path checks require an actual mount; isolate this boundary.
        for target in ('hehawk_extract_audio.safe_path','hehawk_resources.safe_path'):
            p=patch(target,side_effect=lambda root,rel,mount: root/rel); p.start(); self.addCleanup(p.stop)
    def test_codec_allowlist(self):
        self.assertEqual(e.SUPPORTED_NATIVE_CODECS, {'aac','ac3','eac3','mp3','truehd'})
    def test_unsupported_codec(self):
        inventory = e.inspect(self.source)
        inventory['streams'][0]['codec_name'] = 'flac'
        with patch.object(e, 'inspect', return_value=inventory):
            with self.assertRaisesRegex(ValueError, 'Unsupported native audio codec'):
                e.extract(self.source,self.config,0)
        self.assertFalse((self.resources/'manifest.json').exists())
    def test_decoder_diagnostics_reject_clean_request(self):
        with patch.object(e,'verify_audio',return_value={
            'passed':False,'native_preservation_passed':True,
            'decoded_match':True,'clean_decoded_equivalence':False}):
            with self.assertRaises(ValueError):
                e.extract(self.source,self.config,0,decode=True)
        self.assertFalse((self.resources/'manifest.json').exists())
    def test_success(self):
        r=e.extract(self.source,self.config,0,decode=True)
        self.assertTrue(r['verification']['decoded_match'])
        self.assertEqual(r['timeline_mapping'],'unverified')
        self.assertEqual((self.resources/r['path']).stat().st_mode & 0o777,0o600)
        self.assertEqual(json.loads((self.resources/'manifest.json').read_text())['resources']['native_audio-000'],r)
    def test_no_decode(self):
        r=e.extract(self.source,self.config,0)
        self.assertIsNone(r['verification']['decoded_match'])
    def test_rejected(self):
        with patch.object(e,'verify_audio',return_value={'passed':False}):
            with self.assertRaises(ValueError): e.extract(self.source,self.config,0)
        self.assertFalse((self.resources/'audio/stream-000.mka').exists())
        self.assertFalse((self.resources/'manifest.json').exists())
        self.assertEqual(json.loads((self.resources/'.publication.json').read_text())['state'],'pending')
    def test_no_overwrite(self):
        r=e.extract(self.source,self.config,0)
        with self.assertRaises(FileExistsError): e.extract(self.source,self.config,0)
        self.assertEqual(json.loads((self.resources/'manifest.json').read_text())['resources']['native_audio-000'],r)

if __name__=='__main__': unittest.main()
