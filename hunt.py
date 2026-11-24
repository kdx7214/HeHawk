#!/usr/bin/env python3
"""HUNT V1: plan targeted retranscription; never modify observations."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def plan(beak, roost, lo, hi, lengths, gap, margin, budget, boundary=False):
    if (beak['schema'], beak['schema_version']) != ('hehawk.beak', 2):
        raise ValueError('Expected BEAK V2')
    if (roost['schema'], roost['schema_version'], roost['timestamp_basis']) != ('hehawk.roost', 1, 'episode'):
        raise ValueError('Expected ROOST V1, episode timestamps')
    if not all(math.isfinite(x) for x in [lo, hi, gap, margin, *lengths]) or lo < 0 or hi <= lo or gap < 0 or margin < 0 or min(lengths) <= 0 or budget < 1:
        raise ValueError('Invalid planning settings')
    wanted = {'LEXICAL CONFLICT', 'OMISSION CONFLICT'}
    if boundary:
        wanted.add('BOUNDARY CONFLICT')
    regions = []
    for g in sorted(beak['groups'], key=lambda g: g['start_seconds']):
        flags = wanted.intersection(g['flags'])
        if not flags:
            continue
        a, b = g['start_seconds'], g['end_seconds']
        if not lo <= a <= b <= hi:
            raise ValueError('Conflict outside source bounds')
        if not regions or a > regions[-1]['end_seconds'] + gap:
            regions.append(dict(start_seconds=a, end_seconds=b, group_ids=[], reasons=[]))
        r = regions[-1]
        r['end_seconds'] = max(r['end_seconds'], b)
        r['group_ids'].append(g['group_id'])
        r['reasons'] = sorted(set(r['reasons']) | flags)
    existing = [(w['start_seconds'], w['end_seconds']) for w in roost['windows']]
    scheduled = []
    for i, r in enumerate(regions):
        r['id'] = i
        r['windows'] = []
        a, b = r['start_seconds'], r['end_seconds']
        for length in sorted(set(lengths), reverse=True):
            s = max(lo, min((a+b-length)/2, hi-length))
            e = s+length
            reason = None
            if e > hi+1e-8 or a-s < margin-1e-8 or e-b < margin-1e-8:
                reason = 'insufficient context or source extent'
            elif any(abs(s-x)<0.001 and abs(e-y)<0.001 for x,y in existing):
                reason = 'already processed'
            elif any(abs(s-x)<0.001 and abs(e-y)<0.001 for x,y in scheduled):
                reason = 'already planned'
            elif len(scheduled) >= budget:
                reason = 'budget exhausted'
            if reason is None:
                scheduled.append((s,e))
            r['windows'].append(dict(start_seconds=s,end_seconds=e,duration_seconds=length,status='skipped' if reason else 'planned',reason=reason))
    return regions


def fmt(t):
    return f'{int(t//60):02}:{t%60:06.3f}'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('beak',type=Path); p.add_argument('roost',type=Path)
    p.add_argument('--source-start',type=float,required=True); p.add_argument('--source-end',type=float,required=True)
    p.add_argument('--lengths',type=float,nargs='+',default=[60,30,15]); p.add_argument('--gap',type=float,default=2)
    p.add_argument('--margin',type=float,default=2); p.add_argument('--budget',type=int,default=12)
    p.add_argument('--include-boundary',action='store_true'); p.add_argument('-o','--output',type=Path,required=True); p.add_argument('--json',type=Path,required=True)
    a=p.parse_args(); paths=[a.beak,a.roost,a.output,a.json]
    if len({x.resolve() for x in paths})!=4 or any(x.exists() for x in paths[2:]): p.error('Use distinct, new output paths')
    br=a.beak.read_bytes(); rr=a.roost.read_bytes(); b=json.loads(br); r=json.loads(rr)
    digest=hashlib.sha256(rr).hexdigest()
    if b['source_sha256']!=digest: p.error('BEAK does not match ROOST source hash')
    regions=plan(b,r,a.source_start,a.source_end,a.lengths,a.gap,a.margin,a.budget,a.include_boundary)
    result=dict(schema='hehawk.hunt',schema_version=1,timestamp_basis='episode',beak_sha256=hashlib.sha256(br).hexdigest(),roost_sha256=digest,settings=dict(source_start=a.source_start,source_end=a.source_end,lengths=a.lengths,gap=a.gap,margin=a.margin,budget=a.budget,include_boundary=a.include_boundary),regions=regions)
    lines=['HEHAWK — HUNT V1','Planning only; no transcription or decisions.','']
    for r in regions:
        lines.append(f"R{r['id']:03} {fmt(r['start_seconds'])} - {fmt(r['end_seconds'])} | {', '.join(r['reasons'])}")
        lines.append(f"  Groups: {r['group_ids']}")
        for w in r['windows']:
            lines.append(f"  {fmt(w['start_seconds'])} - {fmt(w['end_seconds'])} ({w['duration_seconds']:g}s): {w['status']}" + (f" — {w['reason']}" if w['reason'] else ''))
        lines.append('')
    n=sum(w['status']=='planned' for r in regions for w in r['windows'])
    lines.append(f'{len(regions)} regions; {n} planned windows')
    with a.output.open('x',encoding='utf-8') as f: f.write('\n'.join(lines)+'\n')
    with a.json.open('x',encoding='utf-8') as f: json.dump(result,f,indent=2,allow_nan=False)
    print(lines[-1])

if __name__=='__main__': main()
