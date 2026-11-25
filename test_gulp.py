import unittest
from gulp import clean_ass, clean_srt, parse_ass, parse_srt, timestamp

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

if __name__ == '__main__': unittest.main()
