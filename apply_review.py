#!/usr/bin/env python3
"""Apply version 2 review decisions to a copy of Parakeet JSON."""
import argparse
import os
import shutil
import tempfile
import hashlib
import json
import math
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path


def field(text, name):
    matches = re.findall(r'^' + re.escape(name) + r':[ \t]*(.*)$', text, re.M)
    if len(matches) != 1:
        raise ValueError(f'Expected exactly one {name} field')
    return matches[0].strip()


def seconds(s):
    h, m, sec = s.split(':')
    return int(h)*3600 + int(m)*60 + float(sec)


def parse_review(text):
    v3 = text.startswith('SUBTITLE REVIEW - VERSION 3\n')
    if not v3 and not text.startswith('SUBTITLE REVIEW - VERSION 2\n'):
        raise ValueError('Expected version 2 or 3 review file')
    parts = re.split(r'^REVIEW (\d+) \| ([\d:.]+) - ([\d:.]+)$', text, flags=re.M)
    rows = []
    for i in range(1, len(parts), 4):
        number, start, end, block = parts[i:i+4]
        a, b = map(int, field(block, 'Token range').split(':'))
        status = field(block, 'Status').upper()
        correction = field(block, 'Correction')
        if v3 and status == 'ACCEPT':
            if correction: raise ValueError('ACCEPT requires blank Correction')
            correction = field(block, 'Suggestion')
            status = 'EDIT'
        if status not in {'TODO','KEEP','EDIT','DELETE','UNSURE'}:
            raise ValueError(f'Review {number}: invalid status {status}')
        if (status == 'EDIT') != bool(correction):
            raise ValueError(f'Review {number}: EDIT requires a nonempty Correction; other statuses require it blank')
        rows.append((int(number), seconds(start), seconds(end), a, b, status, correction))
    if len(rows) != int(field(parts[0], 'Review sections')) or [r[0] for r in rows] != list(range(1,len(rows)+1)):
        raise ValueError('Review section count or numbering mismatch')
    return parts[0], rows


from word_timing import word_groups


def normalized(s):
    return re.sub(r'[^\w]', '', s.casefold()) or s


def apply(data, rows):
    tokens, times, durations = (data[k] for k in ('tokens','timestamps','durations'))
    n = len(tokens)
    if not n == len(times) == len(durations):
        raise ValueError('Mismatched transcription arrays')
    if any(not math.isfinite(t) or not math.isfinite(d) or d < 0 for t,d in zip(times,durations)):
        raise ValueError('Invalid source timing')
    out = [[],[],[]]
    def copy(a,b):
        for dest, src in zip(out,(tokens,times,durations)):
            dest.extend(src[a:b])
    def emit(word,start,end):
        out[0].append(' '+word)
        out[1].append(start)
        out[2].append(max(0,end-start))
    bounds = {w[2]: w[4] for w in word_groups(tokens,times,durations,0,n)}
    cursor = 0
    previous_end = 0
    estimated = 0
    for number, start, end, a, b, status, correction in rows:
        if not cursor <= a <= b <= n or end < start:
            raise ValueError(f'Review {number}: invalid or overlapping range')
        previous_end = end
        for pos in (a,b):
            if 0 < pos < n and not tokens[pos].startswith(' '):
                raise ValueError(f'Review {number}: token range splits a word at {pos}')
        copy(cursor,a)
        if status not in {'EDIT','DELETE'}:
            copy(a,b)
        elif status == 'EDIT':
            old = word_groups(tokens,times,durations,a,b)
            new = correction.split()
            matcher = SequenceMatcher(None,[normalized(w[0]) for w in old],[normalized(w) for w in new],autojunk=False)
            lo = old[0][3] if old else start
            hi = old[-1][4] if old else end
            # Allow leading/trailing omitted speech inside the review interval,
            # but never extend estimates into adjacent original words.
            lo = min(lo,start)
            hi = max(hi,end)
            if a: lo = max(lo,bounds[a])
            if b<n: hi = min(hi,times[b])
            for tag,i,j,k,l in matcher.get_opcodes():
                if tag == 'equal':
                    for w, replacement in zip(old[i:j],new[k:l]):
                        if w[0] == replacement: copy(w[1],w[2])
                        else: emit(replacement,w[3],w[4])
                elif tag != 'delete':
                    if tag == 'replace' and j-i == l-k:
                        for w,replacement in zip(old[i:j],new[k:l]):
                            emit(replacement,w[3],w[4]); estimated += 1
                        continue
                    left = old[i-1][4] if i else lo
                    right = old[j][3] if j<len(old) else hi
                    if right <= left:
                        raise ValueError(f'Review {number}: no timing space for inserted words; adjust review interval or defer this edit')
                    step = (right-left)/(l-k)
                    for q,word in enumerate(new[k:l]):
                        emit(word,left+q*step,left+(q+1)*step); estimated += 1
        cursor = b
    copy(cursor,n)
    result = dict(data)
    result.update(zip(('tokens','timestamps','durations'),out))
    result['text'] = ''.join(out[0]).strip()
    return result,estimated


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('review',type=Path)
    p.add_argument('transcription',type=Path)
    p.add_argument('-o','--output',type=Path)
    args = p.parse_args()
    output = args.output or args.transcription.with_name(args.transcription.stem+'_corrected.json')
    try:
        header,rows = parse_review(args.review.read_text(encoding='utf-8-sig'))
        raw = args.transcription.read_bytes()
        if hashlib.sha256(raw).hexdigest() != field(header,'Transcription SHA256'):
            raise ValueError('Transcription checksum mismatch; no changes written')
        data = json.loads(raw)
        result,estimated = apply(data,rows)
        backup = output.with_name(output.name + '.old')
        for target in (output, backup):
            for source in (args.transcription, args.review):
                if target.resolve() == source.resolve() or (target.exists() and source.exists() and target.samefile(source)):
                    raise ValueError('Output or backup would overwrite an input file')
        temporary = None
        backup_temp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as f:
                temporary = Path(f.name)
                json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
                f.write('\n')
            if output.exists():
                with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as f:
                    backup_temp = Path(f.name)
                shutil.copy2(output, backup_temp)
                os.replace(backup_temp, backup)
                print(f'Previous output backed up to: {backup}')
            os.replace(temporary, output)
        finally:
            for path in (temporary, backup_temp):
                if path is not None:
                    path.unlink(missing_ok=True)
        counts = Counter(r[5] for r in rows)
        for status in ('KEEP','EDIT','DELETE','TODO','UNSURE'):
            print(f'{status}: {counts[status]}')
        print(f'Words with replacement/estimated timing: {estimated}')
        print(f'Written to: {output}')
    except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
        p.exit(1,f'Error: {exc}\n')


if __name__ == '__main__':
    main()
