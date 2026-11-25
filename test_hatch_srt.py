"""Synthetic exporter regression tests; no episode data required."""
import copy
import unittest
from hatch_srt import convert

class ExportExam(unittest.TestCase):
    def setUp(self):
        w = dict(text='Don.', start_seconds=10.0, end_seconds=10.5, token_start=0, token_end_exclusive=2)
        self.h = dict(schema='hehawk.hatch', schema_version=1, timestamp_basis='episode', pending_groups=[], segments=[dict(group_id=0, text='Don.', start_seconds=10.0, end_seconds=10.5, timing_basis='observed', issues=[], selected=dict(observation=dict(text='Don.', words=[w])))])
        self.e = copy.deepcopy(self.h)
        self.e['schema']='hehawk.owl.edited'
        s=self.e['segments'][0]
        s.update(text='Dawn.', owl_original_text='Don.', owl_edits=[dict(id='test')], editorial_words=copy.deepcopy(s['selected']['observation']['words']))
        s['editorial_words'][0]['text']='Dawn.'
    def test_original(self):
        self.assertIn('Don.', convert(self.h)[0])
    def test_editorial(self):
        before=copy.deepcopy(self.e)
        self.assertEqual(convert(self.e)[0],convert(self.h)[0].replace('Don.','Dawn.'))
        self.assertEqual(self.e,before)
    def test_timing_tamper(self):
        self.e['segments'][0]['editorial_words'][0]['end_seconds']=11
        with self.assertRaises(ValueError): convert(self.e)
    def test_token_tamper(self):
        self.e['segments'][0]['editorial_words'][0]['token_start']=1
        with self.assertRaises(ValueError): convert(self.e)
    def test_text_mismatch(self):
        self.e['segments'][0]['text']='Other.'
        with self.assertRaises(ValueError): convert(self.e)
    def test_missing_provenance(self):
        del self.e['segments'][0]['owl_edits']
        with self.assertRaises(ValueError): convert(self.e)
    def test_pending(self):
        self.e['pending_groups']=[0]
        with self.assertRaises(ValueError): convert(self.e)
        self.assertIn('[REVIEW G000]',convert(self.e,True)[0])
    def test_estimated(self):
        s=self.e['segments'][0]
        s.update(selected=None,timing_basis='estimated_group_interval')
        del s['editorial_words']
        self.assertEqual(convert(self.e)[2],1)
        self.assertIn('Dawn.',convert(self.e)[0])

if __name__=='__main__': unittest.main()
