#!/usr/bin/env python3
"""MAGPIE experiment 2: provisional, provenance-tracked contextual preview."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from magpie_preview import preview, stamp

HEADER = re.compile(r'(\d+)\n(\d{2,}:\d{2}:\d{2},\d{3}) --> (\d{2,}:\d{2}:\d{2},\d{3})\n([\s\S]+)')

def ms(s):
    h,m,tail=s.split(':'); sec,milli=tail.split(',')
    return ((int(h)*60+int(m))*60+int(sec))*1000+int(milli)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def parse(raw):
    text=raw.decode('utf-8-sig').replace('\r\n','\n')
    rows=[]
    for block in re.split(r'\n\n+',text.rstrip('\n')):
        match=HEADER.fullmatch(block)
        if not match: raise ValueError('Unsupported SRT block')
        n,s,e,t=match.groups()
        if ms(e)<=ms(s): raise ValueError('Invalid original interval')
        rows.append((ms(s),ms(e),t,int(n)))
    if len({r[3] for r in rows})!=len(rows): raise ValueError('Duplicate original cue IDs')
    return rows

def canonical_rows(rows):
    # Comparison only: closing italics on either side of a newline.
    return [(s,e,t.replace("\n</i>", "</i>\n"),n) for s,e,t,n in rows]

def merge(original, additions):
    rows=[(s,e,t,'original',n) for s,e,t,n in original]
    rejected=[]
    for s,e,t,n in additions:
        hits=[{'source':k,'id':i} for a,b,_,k,i in rows if a<e and b>s]
        if hits:
            rejected.append(dict(candidate=n,start_ms=s,end_ms=e,conflicts=hits))
        else:
            rows.append((s,e,t,'magpie',n))
    rows.sort(key=lambda r:r[0])
    return rows,rejected

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('original_srt','reference_json','inventory','recognition','output_srt','manifest'):
        p.add_argument(name,type=Path)
    a=p.parse_args()
    paths=[a.original_srt,a.reference_json,a.inventory,a.recognition]
    raw=[x.read_bytes() for x in paths]
    ref,inv,rec=map(json.loads,raw[1:])
    if (inv.get('schema'),inv.get('schema_version'))!=('magpie_inventory',1): p.error('Unsupported inventory')
    for key,i in [('reference',1),('recognition',3)]:
        if inv['sources'][key]['sha256']!=digest(raw[i]): p.error(f'{key} hash mismatch')
    original=parse(raw[0])
    expected=[(q['start_ms'],q['end_ms'],q['display_text'],q['id']) for q in ref['cues']]
    if canonical_rows(original)!=canonical_rows(expected): p.error('Original SRT differs from reference JSON; refusing merge')
    selected, additions=preview(inv,rec['tokens'])
    rows,rejected=merge(original,additions)
    content=''.join(f'{i}\n{stamp(s)} --> {stamp(e)}\n{t}\n\n' for i,(s,e,t,k,n) in enumerate(rows,1)).encode('utf-8')
    manifest=dict(schema='magpie_merge',schema_version=1,status='provisional',sources=[dict(path=str(p),sha256=digest(r)) for p,r in zip(paths,raw)],output=dict(path=str(a.output_srt),sha256=digest(content)),parameters=dict(pause_seconds=0.75,width=84),cues=[dict(output_id=i,source=k,source_id=n,start_ms=s,end_ms=e,status='unreviewed' if k=='magpie' else 'original') for i,(s,e,t,k,n) in enumerate(rows,1)],rejected=rejected)
    created=[]
    try:
        for path,data in [(a.output_srt,content),(a.manifest,(json.dumps(manifest,indent=2)+'\n').encode())]:
            with path.open('xb') as f:
                created.append(path); f.write(data)
    except BaseException:
        for path in created: path.unlink()
        raise
    print(f'Original cues: {len(original)}\nCandidates selected: {selected}\nProposed additions: {len(additions)}\nInserted: {len(rows)-len(original)}\nRejected: {len(rejected)}\nTotal cues: {len(rows)}\nCreated: {a.output_srt}\nCreated: {a.manifest}')

if __name__=='__main__': main()
