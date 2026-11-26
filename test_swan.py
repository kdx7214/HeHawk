import unittest
from swan import analyze


def cues(*intervals):
    return [dict(id=i,start_ms=a,end_ms=b,display_text='Hello') for i,(a,b) in enumerate(intervals,1)]


class SwanTests(unittest.TestCase):
    def test_nested(self):
        r=analyze(cues((0,8000),(2000,4000),(3000,6000),(7000,10000)))
        self.assertEqual(r['pairs'],[(1,2,2000),(1,3,3000),(2,3,1000),(1,4,1000)])
        self.assertEqual((r['peak'],r['overlap_ms'],r['pairwise_ms'],r['longest_ms']),(3,5000,7000,3000))
        self.assertEqual(r['groups'],[[1,2,3,4]])
    def test_identical_and_touching(self):
        r=analyze(cues((0,1000),(0,1000),(1000,2000),(2024,3000)))
        self.assertEqual(r['pairs'],[(1,2,1000)])
        self.assertEqual(r['issues']['insufficient_gap'],[(1,3,0)])
    def test_order(self):
        r=analyze(cues((2000,3000),(0,1000)))
        self.assertEqual(r['issues']['out_of_order'],[(2,0,2000)])
    def test_presentation(self):
        c=cues((0,500)); c[0]['display_text']='<i>\u00a0\u00a0'+('a'*43)+'</i>\nB\nC'
        r=analyze(c)
        self.assertEqual(r['issues']['indentation'],[(1,1,2)])
        self.assertEqual(r['issues']['long_line'],[(1,1,45)])
        for k in ('short_duration','too_many_lines','reading_speed'): self.assertIn(k,r['issues'])
    def test_chain(self):
        r=analyze(cues((0,1000),(900,2000),(1900,3000),(4000,5000)))
        self.assertEqual(r['groups'],[[1,2,3]])
        self.assertEqual(r['overlap_ms'],200)

if __name__=='__main__': unittest.main()
