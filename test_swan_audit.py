import unittest
from swan_audit import audit

BASE = b'1\r\n00:00:01,000 --> 00:00:02,000\r\n<i>Hello</i>\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nWorld\r\n'

class AuditTests(unittest.TestCase):
    def check(self, output, valid=True, original=BASE):
        errors, stats = audit(original, output)
        self.assertEqual(not errors, valid, errors)
        return stats
    def test_unchanged(self): self.assertEqual(self.check(BASE)['untouched'],2)
    def test_extension(self): self.assertEqual(self.check(BASE.replace(b'02,000',b'02,976'))['extended'],1)
    def test_text(self): self.check(BASE.replace(b'Hello',b'Hallo'),False)
    def test_start(self): self.check(BASE.replace(b'01,000',b'01,001'),False)
    def test_format(self): self.check(BASE.replace(b'<i>',b'<b>'),False)
    def test_line_endings(self): self.check(BASE.replace(b'\r\n',b'\n'),False)
    def test_number(self): self.check(BASE.replace(b'2\r\n00:',b'3\r\n00:'),False)
    def test_shortening(self): self.check(BASE.replace(b'02,000',b'01,950'))
    def test_excess_shortening(self): self.check(BASE.replace(b'02,000',b'01,949'),False)
    def test_gap(self): self.check(BASE.replace(b'02,000',b'02,977'),False)
    def test_final_extension(self): self.check(BASE.replace(b'04,000',b'04,001'),False)
    def test_overlap(self): self.check(BASE.replace(b'02,000',b'03,100'),False)
    def test_existing_overlap(self):
        raw=BASE.replace(b'02,000',b'03,100')
        self.check(raw,original=raw)
    def test_invalid_duration(self):
        with self.assertRaises(ValueError): audit(BASE,BASE.replace(b'02,000',b'01,000'))
    def test_missing_cue(self): self.check(BASE.split(b'\r\n\r\n')[0],False)
    def test_bom(self): self.check(b'\xef\xbb\xbf'+BASE,original=b'\xef\xbb\xbf'+BASE)

if __name__=='__main__': unittest.main()
