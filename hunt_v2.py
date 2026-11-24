#!/usr/bin/env python3
"""HUNT V2: bounded, shifted investigations from PERCH recommendations."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('perch', type=Path)
    p.add_argument('roost', type=Path)
    p.add_argument('--source-start', type=float, required=True)
    p.add_argument('--source-end', type=float, required=True)
    p.add_argument('--budget', type=int, default=6)
    p.add_argument('--total-budget', type=int, default=20,
                   help='Maximum total windows including initial observations')
    p.add_argument('-o', '--output', type=Path, required=True)
    p.add_argument('--json', type=Path, required=True)
    a = p.parse_args()
    paths = [a.perch, a.roost, a.output, a.json]
    if len({x.resolve() for x in paths}) != 4 or any(x.exists() for x in paths[2:]):
        p.error('Use distinct, new output paths')
    pb, rb = a.perch.read_bytes(), a.roost.read_bytes()
    pc, ro = json.loads(pb), json.loads(rb)
    digest = hashlib.sha256(rb).hexdigest()
    if (pc['schema'], pc['schema_version'], pc['timestamp_basis']) != ('hehawk.perch', 1, 'episode') or (ro['schema'], ro['schema_version'], ro['timestamp_basis']) != ('hehawk.roost', 1, 'episode') or pc['roost_sha256'] != digest:
        p.error('Expected matching PERCH V1 and ROOST V1')
    lo, hi = a.source_start, a.source_end
    if not all(map(math.isfinite, (lo, hi))) or not 0 <= lo < hi or min(a.budget, a.total_budget) < 1:
        p.error('Invalid bounds or budget')
    rg = {g['id']: g for g in ro['groups']}
    if sorted(g['group_id'] for g in pc['groups']) != sorted(rg):
        p.error('Group mismatch')
    existing = [(w['start_seconds'], w['end_seconds']) for w in ro['windows']]
    if any(not lo <= s < e <= hi for s,e in existing):
        p.error('Existing window outside source bounds')
    budget = max(0, min(a.budget, a.total_budget-len(existing)))
    regions = []
    for g in pc['groups']:
        if g['action'] != 'INVESTIGATE':
            continue
        s,e = g['start_seconds'],g['end_seconds']
        if not lo <= s <= e <= hi or (s,e) != (rg[g['group_id']]['start_seconds'],rg[g['group_id']]['end_seconds']):
            p.error('Invalid group bounds')
        regions.append(dict(id=len(regions),start_seconds=s,end_seconds=e,group_ids=[g['group_id']],reasons=[g['reason']],windows=[]))
    scheduled = []
    # Round robin: distribute experiments across unresolved groups.
    for length, shift in [(30,-5),(30,5),(15,-3),(15,3),(60,-8),(60,8)]:
        for r in regions:
            if len(scheduled) >= budget:
                break
            s,e = r['start_seconds'],r['end_seconds']
            x = round(max(lo,min((s+e-length)/2+shift,hi-length)), 3)
            y = x+length
            if x < lo or y > hi or s-x < 2 or y-e < 2:
                continue
            if any(abs(x-u)<2 and abs(y-v)<2 for u,v in existing+scheduled):
                continue
            scheduled.append((x,y))
            r['windows'].append(dict(start_seconds=x,end_seconds=y,duration_seconds=length,status='planned',reason=None))
    for r in regions:
        r['disposition'] = 'INVESTIGATE' if r['windows'] else 'REVIEW_OR_OTHER_ENGINE'
    result = dict(schema='hehawk.hunt',schema_version=1,timestamp_basis='episode',planner_version=2,perch_sha256=hashlib.sha256(pb).hexdigest(),beak_sha256=pc['beak_sha256'],roost_sha256=digest,settings=dict(source_start=lo,source_end=hi,budget=a.budget,total_budget=a.total_budget,existing_windows=len(existing),effective_budget=budget,minimum_window_difference_seconds=2),regions=regions)
    def fmt(t):
        return f'{int(t//60):02}:{t%60:06.3f}'
    lines = ['HEHAWK — HUNT V2','Shifted windows; no access to verified answers.','']
    for r in regions:
        lines.append(f"R{r['id']:03} {fmt(r['start_seconds'])}–{fmt(r['end_seconds'])} | {r['disposition']} | Groups {r['group_ids']}")
        for w in r['windows']:
            lines.append(f"  {fmt(w['start_seconds'])}–{fmt(w['end_seconds'])} ({w['duration_seconds']:g}s)")
    lines.append(f'{len(regions)} regions; {len(scheduled)} planned windows; {len(existing)} existing; total cap {a.total_budget}')
    with a.output.open('x',encoding='utf-8') as f:
        f.write('\n'.join(lines)+'\n')
    with a.json.open('x',encoding='utf-8') as f:
        json.dump(result,f,indent=2,allow_nan=False)
    print(lines[-1])

if __name__ == '__main__':
    main()
