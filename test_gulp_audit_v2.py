import unittest
from gulp_audit_v2 import audit

def cue(text,start=0,end=1000,extra=False): return (start,end,text,extra)
class AuditTests(unittest.TestCase):
    def check(self,a,b): return audit([cue(a)],[cue(b)])[0]
    def test_multiline(self): self.assertFalse(self.check('<font face="x">{\\an7}<i>A\nB</i></font>','<i>A</i>\n<i>B</i>'))
    def test_partial(self): self.assertFalse(self.check('X <i>A\nB</i> Y','X <i>A</i>\n<i>B</i> Y'))
    def test_nested(self): self.assertFalse(self.check('<i><b>A</b></i>','<b><i>A</i></b>'))
    def test_style(self): self.assertIn('formatting_difference',self.check('<i>A</i>','A'))
    def test_text(self): self.assertIn('text_or_line_break_difference',self.check('A','B'))
    def test_crossline(self): self.assertIn('candidate_cross_line_tags',self.check('<i>A\nB</i>','<i>A\nB</i>'))
    def test_unbalanced(self): self.assertIn('candidate_unbalanced_tags',self.check('A','<i>A'))
    def test_font(self): self.assertIn('candidate_unwanted_formatting',self.check('A','<font size="2">A</font>'))
    def test_time(self): self.assertIn('timing_difference',audit([cue('A')],[cue('A',1)])[0])
    def test_count(self): self.assertIn('cue_count_difference',audit([cue('A')],[])[0])
    def test_entity(self): self.assertFalse(self.check('A &amp; B','A & B'))
    def test_hard_space(self): self.assertFalse(self.check(r"\h\h<i>\hA</i>", "\u00a0\u00a0<i>\u00a0A</i>"))
    def test_missing_hard_space(self): self.assertIn('text_or_line_break_difference', self.check(r"\hA", "A"))
    def test_candidate_literal_escape(self): self.assertIn('text_or_line_break_difference', self.check(r"\hA", r"\hA"))
    def test_regular_space_distinct(self): self.assertIn('text_or_line_break_difference', self.check(r"\hA", " A"))
    def test_hard_space_style(self): self.assertIn('formatting_difference', self.check(r"<i>\h</i>A", "\u00a0A"))
if __name__=='__main__': unittest.main()
