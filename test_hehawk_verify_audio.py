"""Synthetic native audio verification regression tests."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from fractions import Fraction
from unittest.mock import patch
import hehawk_verify_audio as v

class AudioVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.source = cls.root / 'source.mka'
        cls.copy = cls.root / 'copy.mka'
        cls.other = cls.root / 'other.mka'
        cls.shifted = cls.root / 'shifted.mka'
        cls.short = cls.root / 'short.mka'
        cls.stereo = cls.root / 'stereo.mka'
        cls.corrupt = cls.root / 'corrupt.mka'
        cls.corrupt.write_bytes(b'not a media container')
        def ff(*args):
            subprocess.run(['ffmpeg','-nostdin','-v','error','-n',*map(str,args)],check=True,capture_output=True)
        for path, frequency, channels in [(cls.source,440,1),(cls.other,880,1),(cls.stereo,440,2)]:
            ff('-f','lavfi','-i',f'sine=frequency={frequency}:sample_rate=48000:duration=2','-ac',channels,'-c:a','aac',path)
        ff('-copyts','-i',cls.source,'-map','0:0','-c:a','copy','-avoid_negative_ts','disabled',cls.copy)
        ff('-itsoffset','1','-i',cls.source,'-map','0:0','-c:a','copy','-copyts',cls.shifted)
        ff('-i',cls.source,'-t','1','-c:a','copy',cls.short)

    def test_lossless(self):
        r=v.verify(self.source,self.copy,0,decode=True)
        self.assertTrue(r['passed']); self.assertTrue(r['decoded_match'])
    def test_different_audio(self):
        r=v.verify(self.source,self.other,0,decode=True)
        self.assertFalse(r['passed']); self.assertFalse(r['packet_match'])
    def test_shifted(self):
        self.assertFalse(v.verify(self.source,self.shifted,0)['packet_match'])
    def test_truncated(self):
        self.assertFalse(v.verify(self.source,self.short,0)['packet_match'])
    def test_channels(self):
        self.assertIn('channels',v.verify(self.source,self.stereo,0)['metadata_differences'])
    def test_rational(self):
        from xml.etree.ElementTree import fromstring
        def record(pts,tb,side=''):
            return v.packet_record(fromstring(f'<packet pts="{pts}" dts="{pts}" duration="{pts}" size="1" data_hash="SHA256:{"a"*64}">{side}</packet>'),tb)
        self.assertEqual(record(1,Fraction(1,1000)),record(48,Fraction(1,48000)))
    def test_side_data_difference(self):
        from xml.etree.ElementTree import fromstring
        def record(skip):
            return v.packet_record(fromstring(f'<packet pts="0" dts="0" duration="1" size="1" data_hash="SHA256:{"a"*64}"><side_data_list><side_data side_data_type="Skip Samples" skip_samples="{skip}"/></side_data_list></packet>'),Fraction(1,1000))
        self.assertNotEqual(record(0),record(1024))
    def test_invalid_index(self):
        with self.assertRaises((ValueError,subprocess.SubprocessError)):
            v.verify(self.source,self.copy,99)
    def test_missing(self):
        with self.assertRaises(FileNotFoundError):
            v.verify(self.source,self.root/'missing.mka',0)
    def test_corrupt(self):
        with self.assertRaises((ValueError,subprocess.SubprocessError)):
            v.verify(self.source,self.corrupt,0)
    def test_probe_failure(self):
        with patch.object(v.subprocess,'run',side_effect=subprocess.CalledProcessError(1,'ffprobe')):
            with self.assertRaises(subprocess.CalledProcessError): v.verify(self.source,self.copy,0)
    def test_decode_failure(self):
        original=v.subprocess.run
        def run(args,*a,**kw):
            if args[0]=='ffmpeg': raise subprocess.CalledProcessError(1,args)
            return original(args,*a,**kw)
        with patch.object(v.subprocess,'run',side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError): v.verify(self.source,self.copy,0,decode=True)
    def test_no_decode(self):
        r=v.verify(self.source,self.copy,0)
        self.assertTrue(r['passed']); self.assertIsNone(r['decoded_match'])
        self.assertEqual(r['timeline_mapping'],'unverified')

if __name__=='__main__': unittest.main()
