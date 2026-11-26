#!/usr/bin/env python3
"""Generate a non-destructive missing-dialogue preview from MAGPIE evidence."""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path


def stamp(ms):
    s, ms = divmod(ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def preview(inventory, tokens, pause=0.75, width=84):
    rows = []
    selected = 0
    for candidate in inventory['candidates']:
        if (candidate['kind'], candidate['location']) != ('recognition_only', 'outside_captions'):
            continue
        selected += 1
        group = []
        seen = set()
        def flush():
            if group:
                start = round(min(w[1] for w in group)*1000)
                end = round(max(w[2] for w in group)*1000)
                if end <= start:
                    raise ValueError(f"Candidate {candidate['id']}: nonpositive duration")
                rows.append((start, end, ' '.join(w[0] for w in group), candidate['id']))
                group.clear()
        for w in candidate['recognition']:
            a,b = w['token_start'],w['token_end']
            if not 0 <= a < b <= len(tokens):
                raise ValueError('Invalid token range')
            # A token group may contain multiple lexical words. Do not include
            # its raw text twice or accidentally recover matched lexical words.
            if (a,b) in seen:
                continue
            seen.add((a,b))
            raw = ''.join(tokens[a:b]).strip()
            lexical = re.findall(r"[^\W_]+(?:['’][^\W_]+)*",raw)
            selected_words = [x['word'] for x in candidate['recognition'] if (x['token_start'],x['token_end'])==(a,b)]
            text = raw if lexical == selected_words else ' '.join(selected_words)
            start,end = w['start'],w['end']
            if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end):
                raise ValueError('Invalid word timing')
            if group and (start-max(x[2] for x in group)>=pause or re.search(r'[.!?][\"\'”’)]*$',group[-1][0]) or len(' '.join(x[0] for x in group))+1+len(text)>width):
                flush()
            group.append((text,start,end))
        flush()
    rows.sort(key=lambda x:x[0])
    if any(a[1]>b[0] for a,b in zip(rows,rows[1:])):
        raise ValueError('Preview contains overlapping cues; inspect candidate timing')
    return selected, rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('inventory',type=Path)
    p.add_argument('recognition',type=Path)
    p.add_argument('output',type=Path)
    args=p.parse_args()
    inv=json.loads(args.inventory.read_bytes())
    if inv.get('schema')!='magpie_inventory' or inv.get('schema_version')!=1:
        p.error('Unsupported inventory schema')
    raw=args.recognition.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=inv['sources']['recognition']['sha256']:
        p.error('Recognition hash does not match inventory')
    selected,rows=preview(inv,json.loads(raw)['tokens'])
    content=''.join(f'{i}\n{stamp(s)} --> {stamp(e)}\n{t}\n\n' for i,(s,e,t,c) in enumerate(rows,1))
    with args.output.open('x',encoding='utf-8') as f:
        f.write(content)
    print(f'Candidates selected: {selected}\nPreview cues: {len(rows)}\nCreated: {args.output}')

if __name__=='__main__': main()
