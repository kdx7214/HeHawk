import unittest
from copy import deepcopy
from swan_timing import plan, write_srt
from pathlib import Path
from tempfile import TemporaryDirectory

def cue(i,a,b,text='Hello'):
    return dict(id=i,start_ms=a,end_ms=b,display_text=text)

class TimingTests(unittest.TestCase):
    def test_overlap(self):
        r=plan([cue(1,0,1010),cue(2,1000,2000)])
        self.assertEqual(r['proposed'][0]['end_ms'],976)
        self.assertEqual(r['after']['pairs'],[])
    def test_gap(self):
        r=plan([cue(1,0,1000),cue(2,1000,2000)])
        self.assertEqual(r['proposed'][0]['end_ms'],976)
    def test_extension(self):
        r=plan([cue(1,0,500,'x'*40),cue(2,3000,4000)])
        self.assertEqual(r['proposed'][0]['end_ms'],2000)
    def test_uncapped_extension(self):
        r=plan([cue(1,0,500,'x'*100),cue(2,10000,11000)])
        self.assertEqual(r['proposed'][0]['end_ms'],5000)
    def test_long_gap_demand_only(self):
        r=plan([cue(1,0,370,'x'*27),cue(2,23000,24000)])
        self.assertEqual(r['proposed'][0]['end_ms'],1350)
    def test_long_extension_neighbor_limit(self):
        r=plan([cue(1,0,500,'x'*100),cue(2,4000,5000)])
        self.assertEqual(r['proposed'][0]['end_ms'],3976)
        self.assertEqual(r['after']['pairs'],[])
    def test_nested(self):
        cues=[cue(1,0,5000),cue(2,1000,2000),cue(3,3000,4000)]
        self.assertEqual(plan(cues)['proposed'],cues)
    def test_unsafe_reduction(self):
        cues=[cue(1,0,600),cue(2,590,2000)]
        self.assertEqual(plan(cues)['proposed'],cues)
    def test_last_and_immutability(self):
        cues=[cue(2,1000,1100),cue(1,0,500)]
        original=deepcopy(cues)
        r=plan(cues)
        self.assertEqual(cues,original)
        self.assertEqual([c['start_ms'] for c in r['proposed']],[1000,0])
        self.assertEqual(r['proposed'][0]['end_ms'],1100)
    def test_no_new_overlap(self):
        r=plan([cue(1,0,500,'x'*40),cue(2,700,1700)])
        self.assertEqual(r['proposed'][0]['end_ms'],676)
        self.assertEqual(r['after']['pairs'],[])

    def test_fast_overlap(self):
        r=plan([cue(1,0,1010,'x'*25),cue(2,1000,2000)])
        self.assertEqual(r['proposed'][0]['end_ms'],976)
    def test_fast_gap_protected(self):
        r=plan([cue(1,0,1000,'x'*25),cue(2,1000,2000)])
        self.assertEqual(r['proposed'][0]['end_ms'],1000)
    def test_write_preserves_bytes(self):
        with TemporaryDirectory() as d:
            a,b=Path(d)/'a.srt',Path(d)/'b.srt'
            raw=b'1\r\n00:00:00,000 --> 00:00:01,010\r\n<i>Hello</i>\r\n\r\n2\r\n00:00:01,000 --> 00:00:02,000\r\nHello\r\n'
            a.write_bytes(raw)
            cues=[cue(1,0,1010),cue(2,1000,2000)]
            proposed=plan(cues)['proposed']
            write_srt(a,b,cues,proposed)
            self.assertEqual(b.read_bytes(),raw.replace(b'01,010',b'00,976'))
            self.assertEqual(a.read_bytes(),raw)
            with self.assertRaises(FileExistsError):
                write_srt(a,b,cues,proposed)

if __name__=='__main__': unittest.main()
