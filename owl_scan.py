#!/usr/bin/env python3
"""Read-only OWL V2 terminology advisories for HATCH V1."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from owl import validate, norm


def read(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def scan(k, h):
    validate(k)
    if k['schema_version'] != 2 or (h['schema'], h['schema_version'], h['timestamp_basis']) != ('hehawk.hatch', 1, 'episode'):
        raise ValueError('Requires OWL V2 and HATCH V1 episode timestamps')
    rules = {}
    for e in k['entries']:
        if e['state'] == 'rejected':
            continue
        for r in e['relationships']:
            if r['type'] == 'alias':
                continue
            for surface, alternative in [(r['text'], e['canonical'])] + ([(e['canonical'], r['text'])] if r['type'] == 'homophone' else []):
                key = norm(surface)
                if key == norm(alternative):
                    continue
                rules.setdefault(key, []).append(dict(alternative=alternative, relationship=r['type'], entry_id=e['id'], state=e['state'], source=e['source']))
    # Build contiguous text runs; never match across unresolved passages or long pauses.
    runs = []
    run = []
    for s in h['segments']:
        if s['text'] is None or s['issues']:
            if run: runs.append(run)
            run = []
            continue
        if not s['text']: continue
        if run and s['start_seconds'] - run[-1]['end_seconds'] >= .65:
            runs.append(run); run = []
        run.append(s)
    if run: runs.append(run)
    out = []
    for run in runs:
        text = ''; spans = []
        for s in run:
            if text: text += ' '
            a = len(text); text += s['text']; spans.append((a,len(text),s))
        # Normalize non-whitespace chunks while retaining original character spans.
        normalized = ''; mapping = []
        for m in re.finditer(r'\S+', text):
            if normalized: normalized += ' '; mapping.append((m.start()-1,m.start()))
            for i,c in enumerate(m.group()):
                n = norm(c)
                normalized += n; mapping.extend([(m.start()+i,m.start()+i+1)]*len(n))
        matches = {}
        for key, options in rules.items():
            for m in re.finditer(r'(?<!\w)'+re.escape(key)+r'(?!\w)', normalized):
                # Internal apostrophes join lexical words; quotation marks do not.
                if re.search(r"\w['’]$", normalized[:m.start()]):
                    continue
                if re.match(r"['’]\w", normalized[m.end():]):
                    continue
                a,b = mapping[m.start()][0],mapping[m.end()-1][1]
                matches.setdefault((a,b), []).extend(options)
        for (a,b), options in sorted(matches.items()):
            parts = []
            for x,y,s in spans:
                if a>=y or b<=x: continue
                lo,hi=max(a,x)-x,min(b,y)-x
                start,end=s['start_seconds'],s['end_seconds']; basis=s['timing_basis']
                obs=(s.get('selected') or {}).get('observation')
                if obs:
                    words=obs['words']; joined=' '.join(w['text'] for w in words)
                    if joined==s['text']:
                        pos=0; hit=[]
                        for w in words:
                            stop=pos+len(w['text'])
                            if lo<stop and hi>pos: hit.append(w)
                            pos=stop+1
                        if hit: start,end=hit[0]['start_seconds'],hit[-1]['end_seconds']; basis='observed_word_interval'
                    if basis!='observed_word_interval': basis='observed_group_interval'
                parts.append(dict(group_id=s['group_id'],char_start=lo,char_end_exclusive=hi,start_seconds=start,end_seconds=end,timing_basis=basis))
            out.append(dict(id=len(out)+1,recognized=text[a:b],start_seconds=parts[0]['start_seconds'],end_seconds=parts[-1]['end_seconds'],parts=parts,context=text[max(0,a-100):min(len(text),b+100)],alternatives=options,decision='TODO'))
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('knowledge',type=Path); p.add_argument('hatch',type=Path)
    p.add_argument('-o',type=Path,required=True); p.add_argument('--json',type=Path,required=True)
    a=p.parse_args()
    try:
        if len({x.resolve() for x in (a.knowledge,a.hatch,a.o,a.json)})!=4 or a.o.exists() or a.json.exists(): raise ValueError('Distinct inputs and new outputs required')
        k,kh=read(a.knowledge); h,hh=read(a.hatch); rows=scan(k,h)
        data=dict(schema='hehawk.owl.scan',schema_version=1,timestamp_basis='episode',series=k['series'],knowledge_sha256=kh,hatch_sha256=hh,occurrences=rows)
        payload=json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
        with a.json.open('x',encoding='utf-8') as f: f.write(payload)
        with a.o.open('x',encoding='utf-8') as f:
            for r in rows:
                f.write(f"[{r['id']}] {r['start_seconds']:.3f}–{r['end_seconds']:.3f}  {r['recognized']}\n  Context: {r['context']}\n")
                for v in r['alternatives']: f.write(f"  Alternative: {v['alternative']} ({v['relationship']}, {v['state']}) — {v['source']}\n")
                f.write('  Retain original or review alternative; no automatic replacement.\n\n')
            f.write(f'{len(rows)} occurrences\n')
        print(f'{len(rows)} occurrences; no automatic replacements')
    except (ValueError,OSError,KeyError,TypeError) as e: p.exit(1,f'OWL Scan: {e}\n')

if __name__=='__main__': main()
