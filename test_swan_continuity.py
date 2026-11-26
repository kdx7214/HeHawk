import unittest
from swan_continuity import classify, analyze


def cue(i, a, b, text):
    return dict(id=i, start_ms=a, end_ms=b, display_text=text)


class ContinuityTests(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(classify(['Hello'], ['Hello']), ['identical'])

    def test_progressive(self):
        self.assertIn('progressive_addition', classify(['Hello'], ['Hello world']))
        self.assertIn('progressive_removal', classify(['Hello world'], ['Hello']))
        self.assertNotIn('progressive_addition', classify(['He'], ['Hello']))

    def test_rollup(self):
        self.assertIn('rollup_candidate', classify(['A', 'B'], ['B', 'C']))
        self.assertNotIn('rollup_candidate', classify(['A', 'B'], ['A', 'C']))

    def test_gap_filter(self):
        self.assertNotIn('identical', analyze([cue(1,0,1000,'A'), cue(2,1200,2200,'A')]))

    def test_nested_slack(self):
        r = analyze([cue(1,0,3000,'A'), cue(2,1000,1100,'B'), cue(3,1500,1600,'C')])
        self.assertEqual(r['timing_slack'][1][4], -1500)
        self.assertEqual(r['timing_slack'][1][6], 0)

    def test_slack(self):
        r = analyze([cue(1,0,1000,'A'), cue(2,1200,1300,'<i>Hello</i>'), cue(3,1800,2800,'B')])
        self.assertEqual(r['timing_slack'][0], (2,100,5,600,200,500,176,476,0))


if __name__ == '__main__':
    unittest.main()
