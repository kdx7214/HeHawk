"""Synthetic regression tests for OWL Scan; no episode data required."""
import copy
import unittest
from owl_scan import scan


def entry(id, canonical, variant, relation, state='verified'):
    return dict(id=id, canonical=canonical, kind='character', variants=[variant],
                relationships=[dict(text=variant, type=relation)], state=state,
                source='Synthetic test fixture', notes='')


def segment(text, id=0, start=10.0, end=12.0):
    return dict(group_id=id, text=text, start_seconds=start, end_seconds=end,
                issues=[], selected=None, timing_basis='estimated_group_interval')


class OwlScanExam(unittest.TestCase):
    def setUp(self):
        self.k = dict(schema='hehawk.owl', schema_version=2, series='Synthetic',
                      entries=[entry('a','Dawn','Don','homophone'),
                               entry('b','Shepherd','Shepard','spelling')])

    def run_scan(self, *segments):
        h = dict(schema='hehawk.hatch', schema_version=1,
                 timestamp_basis='episode', segments=list(segments))
        before = copy.deepcopy((self.k,h))
        rows = scan(self.k,h)
        self.assertEqual((self.k,h),before)
        return rows

    def test_homophone_forward(self):
        r, = self.run_scan(segment('Don'))
        self.assertEqual(r['alternatives'][0]['alternative'],'Dawn')

    def test_homophone_reverse(self):
        r, = self.run_scan(segment('Dawn'))
        self.assertEqual(r['alternatives'][0]['alternative'],'Don')

    def test_both_spellings(self):
        rows = self.run_scan(segment('Don and Dawn'))
        self.assertEqual([r['recognized'] for r in rows],['Don','Dawn'])
        self.assertEqual(len({r['id'] for r in rows}),2)

    def test_repeated_occurrences(self):
        rows = self.run_scan(segment('Don met Don'))
        self.assertEqual(len(rows),2)
        self.assertEqual(len({r['id'] for r in rows}),2)
        self.assertEqual([r['parts'][0]['char_start'] for r in rows],[0,8])

    def test_whole_word(self):
        self.assertEqual(self.run_scan(segment('Donny')),[])

    def test_canonical_spelling(self):
        self.assertEqual(self.run_scan(segment('Shepherd')),[])

    def test_spelling_variant(self):
        r, = self.run_scan(segment('Shepard'))
        self.assertEqual(r['alternatives'][0]['alternative'],'Shepherd')

    def test_case_and_punctuation(self):
        rows = self.run_scan(segment('DON, dawn!'))
        self.assertEqual([r['recognized'] for r in rows],['DON','dawn'])

    def test_rejected_and_alias(self):
        self.k['entries'] += [entry('c','Aster','Asta','spelling','rejected'),
                              entry('d','Robert','Bob','alias')]
        self.assertEqual(self.run_scan(segment('Asta Bob')),[])

    def test_multiple_alternatives(self):
        self.k['entries'].append(entry('c','Dan','Don','homophone'))
        r, = self.run_scan(segment('Don'))
        self.assertEqual({a['alternative'] for a in r['alternatives']},{'Dawn','Dan'})

    def test_cross_segment(self):
        self.k['entries'].append(entry('c','Star Gate','Starr Gate','spelling'))
        r, = self.run_scan(segment('Starr',0,10,11),segment('Gate',1,11.1,12))
        self.assertEqual(r['recognized'],'Starr Gate')
        self.assertEqual([p['group_id'] for p in r['parts']],[0,1])

    def test_no_cross_pause(self):
        self.k['entries'].append(entry('c','Star Gate','Starr Gate','spelling'))
        self.assertEqual(self.run_scan(segment('Starr',0,10,11),segment('Gate',1,12,13)),[])

    def test_unresolved(self):
        s = segment('Don'); s['issues']=['synthetic issue']
        self.assertEqual(self.run_scan(s),[])

    def test_estimated_timing(self):
        r, = self.run_scan(segment('Don'))
        self.assertEqual(r['parts'][0]['timing_basis'],'estimated_group_interval')
        self.assertEqual((r['start_seconds'],r['end_seconds']),(10,12))

    def test_observed_timing(self):
        s = segment('Hi Don'); s['timing_basis']='observed'
        s['selected'] = dict(observation=dict(words=[dict(text='Hi',start_seconds=10,end_seconds=10.2),dict(text='Don',start_seconds=10.3,end_seconds=10.6)]))
        r, = self.run_scan(s)
        self.assertEqual(r['parts'][0]['timing_basis'],'observed_word_interval')
        self.assertEqual((r['start_seconds'],r['end_seconds']),(10.3,10.6))

if __name__ == '__main__':
    unittest.main(verbosity=2)
