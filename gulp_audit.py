#!/usr/bin/env python3
"""Read-only, local SRT conversion audit; reports no dialogue."""
import argparse
import html
import re
from collections import Counter
from pathlib import Path

TIME = re.compile(r'(\d+:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{3})(.*)')
TOKEN = re.compile(r'<[^>\n]+>|\{\\[^}]*\}')


def ms(s):
    h,m,rest = s.replace(',', '.').split(':')
    sec, frac = rest.split('.')
    if int(m)>=60 or int(sec)>=60: raise ValueError('Invalid timestamp')
    return (int(h)*3600+int(m)*60+int(sec))*1000+int(frac)


def read_srt(path):
    raw = Path(path).read_bytes()
    text = raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')
    text = text.replace('\r\n','\n').replace('\r','\n').strip('\n')
    cues=[]
    for block in re.split(r'\n[ \t]*\n',text):
        lines=block.split('\n')
        if not block.strip(): continue
        if lines[0].strip().isdigit(): lines.pop(0)
        match=TIME.fullmatch(lines.pop(0).strip())
        if not match: raise ValueError(f'Invalid timing at cue {len(cues)+1}')
        a,b,extra=match.groups()
        cues.append((ms(a),ms(b),'\n'.join(lines),bool(extra.strip())))
    return cues


def inspect(text, reference=False):
    chars=[]; styles=[]; stack=[]; issues=set(); pos=0
    def emit(value):
        if reference:
            value = value.replace(r"\h", "\u00a0")
        for c in html.unescape(value):
            if c=='\n' and stack: issues.add('cross_line_tags')
            chars.append(c)
            styles.append((('b' in stack),('i' in stack)) if c!='\n' else None)
    for match in TOKEN.finditer(text):
        emit(text[pos:match.start()]); tag=match.group().lower(); pos=match.end()
        if tag in ('<b>','<i>'): stack.append(tag[1])
        elif tag in ('</b>','</i>'):
            if not stack or stack[-1]!=tag[2]:
                issues.add('unbalanced_tags')
                if tag[2] in stack: stack.remove(tag[2])
            else: stack.pop()
        elif re.fullmatch(r'</?(?:font|u|s|strike|span)(?:\s[^>]*)?>',tag) or tag.startswith('{\\'):
            issues.add('unwanted_formatting')
        else:
            issues.add('unknown_markup'); emit(match.group())
    emit(text[pos:])
    if stack: issues.add('unbalanced_tags')
    return ''.join(chars),styles,issues


def audit(reference, candidate):
    counts=Counter(); locations={}
    def mark(kind,i):
        counts[kind]+=1
        if len(locations.setdefault(kind,[]))<10: locations[kind].append(i)
    if len(reference)!=len(candidate): counts['cue_count_difference']=abs(len(reference)-len(candidate))
    for i,c in enumerate(candidate,1):
        _,_,issues=inspect(c[2])
        for issue in issues: mark('candidate_'+issue,i)
        if c[3]: mark('candidate_positioning',i)
    for i,(a,b) in enumerate(zip(reference,candidate),1):
        if a[:2]!=b[:2]: mark('timing_difference',i)
        ta,sa,ia=inspect(a[2], reference=True); tb,sb,ib=inspect(b[2])
        if ia & {'unknown_markup','unbalanced_tags'}: mark('reference_markup_uncertain',i)
        if ta!=tb: mark('text_or_line_break_difference',i)
        elif sa!=sb: mark('formatting_difference',i)
    return counts,locations


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('reference'); p.add_argument('candidate'); args=p.parse_args()
    try: a,b=read_srt(args.reference),read_srt(args.candidate); counts,locations=audit(a,b)
    except (OSError,ValueError,IndexError) as exc:
        print(f'AUDIT ERROR: {type(exc).__name__}'); return 2
    print(f'Reference cues: {len(a)}\nCandidate cues: {len(b)}')
    for key in sorted(counts): print(f'{key}: {counts[key]}'+(f' (first cue positions: {locations[key]})' if key in locations else ''))
    print('AUDIT DIFFERENCES FOUND' if counts else 'AUDIT PASSED')
    return int(bool(counts))

if __name__=='__main__': raise SystemExit(main())
