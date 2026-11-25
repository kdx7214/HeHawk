import unittest
from gulp_v4 import clean_ass, clean_srt, parse_ass, parse_srt, timestamp

class GulpTests(unittest.TestCase):
    def test_time(self): self.assertEqual(timestamp('1:02:03.45'),3723450)
    def test_ass_inline(self): self.assertEqual(clean_ass(r'Hel{\fnArial}lo {\i1}world{\i0}', '', {}), ('Hello world','Hello <i>world</i>'))
    def test_style(self): self.assertEqual(clean_ass(r'A{\b0}B', 'Default', {'default':(True,False)}), ('AB','<b>A</b>B'))
    def test_srt(self): self.assertEqual(clean_srt('<font color="red"><i>Hello</i></font>'), ('Hello','<i>Hello</i>'))
    def test_drawing(self): self.assertEqual(clean_ass(r'{\p1}m 0 0 l 2 2{\p0}Hello', '', {}), ('Hello','Hello'))
    def test_transform(self): self.assertEqual(clean_ass(r'{\t(0,100,\b1)}Hello', '', {}), ('Hello','Hello'))
    def test_ass_event(self):
        c = parse_ass('[Events]\nFormat: Start, End, Style, Name, Text\nDialogue: 0:00:01.00,0:00:02.00,Default,Sam,Hello, world')[0]
        self.assertEqual((c['speaker'],c['comparison_text']),('Sam','Hello, world'))
    def test_srt_event(self): self.assertEqual(parse_srt('1\n00:00:01,000 --> 00:00:02,000\nHello\nworld')[0]['comparison_text'],'Hello world')

    def test_partial_multiline(self):
        self.assertEqual(clean_ass(r'A {\i1}B\NC{\i0} D', '', {}), ('A B\nC D', 'A <i>B</i>\n<i>C</i> D'))
    def test_inherited_multiline(self):
        self.assertEqual(clean_ass(r'A\NB', 'Default', {'default':(False,True)}), ('A\nB','<i>A</i>\n<i>B</i>'))
    def test_overlap(self):
        self.assertEqual(clean_ass(r'{\i1}A{\b1}B\NC{\i0}D', '', {}), ('AB\nCD','<i>A</i><b><i>B</i></b>\n<b><i>C</i>D</b>'))
    def test_srt_multiline(self):
        self.assertEqual(clean_srt('<i>A\nB</i> C'), ('A\nB C','<i>A</i>\n<i>B</i> C'))
    def test_redundant_tags(self):
        self.assertEqual(clean_srt('<i>A</i><i>B</i>'), ('AB','<i>AB</i>'))

class RegistryTests(unittest.TestCase):
    def test_dispatch(self):
        from gulp_v4 import default_registry
        from pathlib import Path
        r = default_registry()
        self.assertEqual(r.select(Path('wrong.ass'), b'1\n00:00:01,000 --> 00:00:02,000\nHello').name, 'srt')
        self.assertEqual(r.select(Path('test.ssa'), b'[Events]\n').name, 'ass')
        self.assertEqual(r.select(Path('test.sup'), b'PG'+bytes(8)+b'\x80\x00\x00').name, 'pgs')
        self.assertEqual(r.select(Path('test.idx'), b'# VobSub index file').name, 'vobsub')
    def test_unsupported(self):
        from gulp_v4 import ingest, UnknownFormat
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as d:
            for name in ('test.sup', 'test.xyz', 'test.sub'):
                p = Path(d)/name
                p.write_bytes(b'unknown')
                with self.assertRaises(UnknownFormat): ingest(p)
    def test_extension_registration(self):
        from gulp_v4 import Converter, default_registry, ingest
        from tempfile import TemporaryDirectory
        from pathlib import Path
        r = default_registry()
        c = Converter('synthetic', ('.example',), 'text', lambda p,r: False,
                      lambda p,r: parse_srt(r.decode()))
        r.register(c)
        with self.assertRaises(ValueError): r.register(c)
        with TemporaryDirectory() as d:
            p = Path(d)/'test.example'
            p.write_text('1\n00:00:01,000 --> 00:00:02,000\nHello')
            # Content detection takes precedence over suffix fallback.
            self.assertEqual(ingest(p,r)['format'], 'srt')
            p.write_text('custom')
            r.converters['synthetic'] = Converter('synthetic', ('.example',), 'text', lambda p,r: False, lambda p,r: [{'id':1}])
            self.assertEqual(ingest(p,r)['format'], 'synthetic')

class DetectionTests(unittest.TestCase):
    def test_pgs_extensions(self):
        from gulp_v4 import default_registry
        from pathlib import Path
        packet = b'PG'+bytes(8)+b'\x80\x00\x00'
        for name in ('a.pgs','a.sup','a.bin'):
            self.assertEqual(default_registry().select(Path(name), packet).name, 'pgs')
    def test_unknown_signatures(self):
        from gulp_v4 import default_registry, UnknownFormat
        from pathlib import Path
        for name, raw in [('a.sup',b'SP'),('a.pgs',b'PG'),('a.sub',b'\x00\x00\x01\xba'),('a.srt',b'junk')]:
            with self.assertRaises(UnknownFormat): default_registry().select(Path(name),raw)
    def test_microdvd(self):
        from gulp_v4 import default_registry
        from pathlib import Path
        self.assertEqual(default_registry().select(Path('a.sub'),b'{1}{20}Hello').name,'microdvd')
    def test_cli_status(self):
        import subprocess, sys
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            p=Path(d)/'a.sup'
            for raw, status, code in [(b'junk',3,'UNKNOWN_FORMAT'),(b'PG'+bytes(8)+b'\x80\x00\x00',4,'UNSUPPORTED_FORMAT')]:
                p.write_bytes(raw)
                r=subprocess.run([sys.executable,'gulp_v4.py','ingest',str(p)],capture_output=True,text=True)
                self.assertEqual(r.returncode,status)
                self.assertIn(code,r.stderr)

if __name__ == '__main__': unittest.main()
