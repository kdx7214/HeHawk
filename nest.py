#!/usr/bin/env python3
"""NEST V1: assemble provisional transcript without changing evidence."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from collections import Counter


def load(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def stamp(t):
    m, s = divmod(round(t * 1000), 60000)
    h, m = divmod(m, 60)
    return f'{h:02}:{m:02}:{s/1000:06.3f}'


def assemble(perch, roost, tolerance):
    sources = {w['id']: w for w in roost['windows']}
    groups = roost['groups']
    if [g['group_id'] for g in perch['groups']] != [g['id'] for g in groups]:
        raise ValueError('Group IDs do not match')
    segments, issues, used = [], [], {}
    previous = None
    for p, r in zip(perch['groups'], groups):
        gid = r['id']
        a, b = r['start_seconds'], r['end_seconds']
        if not math.isfinite(a) or not math.isfinite(b) or a > b:
            raise ValueError(f'Invalid group timing: {gid}')
        if (a,b) != (p['start_seconds'],p['end_seconds']):
            raise ValueError(f'Group timing mismatch: {gid}')
        s = dict(group_id=gid, action=p['action'], reason=p['reason'],
                 start_seconds=a, end_seconds=b, column_ids=r['column_ids'],
                 alternatives=p['alternatives'], flags=p['flags'],
                 omission_windows=p['omission_windows'],
                 partial_missing_windows=p['partial_missing_windows'],
                 selected=None, issues=[])
        choice = p['selected']
        if p['action'] in ('RETAIN','PREFER'):
            if not choice or not any(choice == w for alt in p['alternatives'] for w in alt['witnesses']):
                raise ValueError(f'Invalid selected candidate: {gid}')
            wid = choice['window_id']
            obs = next((w['observation'] for w in r['witnesses'] if w['window_id']==wid), None)
            if not obs or any(obs[k]!=choice[k] for k in ('text','start_seconds','end_seconds')):
                raise ValueError(f'Selected observation does not match ROOST: {gid}')
            s['selected'] = dict(window_id=wid, source=sources[wid], observation=obs)
            s['start_seconds'],s['end_seconds'] = obs['start_seconds'],obs['end_seconds']
            s['text'] = obs['text']
            for word in obs['words']:
                lo, hi = word['token_start'], word['token_end_exclusive']
                if lo < used.get(wid,0) or hi <= lo:
                    raise ValueError(f'Reused or reordered source tokens: {gid}/{wid}')
                used[wid] = hi
            if previous is not None:
                overlap = previous['end_seconds'] - s['start_seconds']
                if overlap > tolerance or s['start_seconds'] < previous['start_seconds']:
                    issue = dict(kind='TIMING CONFLICT', group_ids=[previous['group_id'],gid], overlap_seconds=overlap)
                    issues.append(issue)
                    s['issues'].append(issue)
                    previous['issues'].append(issue)
            previous = s
        elif p['action'] in ('REVIEW','INVESTIGATE'):
            if choice is not None:
                raise ValueError(f'Unexpected selection for unresolved group {gid}')
            s['text'] = None
        else:
            raise ValueError(f'Unknown action: {p["action"]}')
        segments.append(s)
    return segments, issues


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('perch', type=Path)
    ap.add_argument('roost', type=Path)
    ap.add_argument('-o', required=True, type=Path)
    ap.add_argument('--json', required=True, type=Path)
    ap.add_argument('--overlap-tolerance', type=float, default=0.12)
    args = ap.parse_args()
    if not math.isfinite(args.overlap_tolerance) or args.overlap_tolerance < 0:
        ap.error('Overlap tolerance must be finite and nonnegative')
    paths = [p.resolve() for p in (args.perch,args.roost,args.o,args.json)]
    if len(set(paths)) != 4 or args.o.exists() or args.json.exists():
        ap.error('Inputs and new outputs must be distinct; no overwriting')
    p, ph = load(args.perch)
    r, rh = load(args.roost)
    for d, schema in ((p,'hehawk.perch'),(r,'hehawk.roost')):
        if (d['schema'],d['schema_version'],d['timestamp_basis']) != (schema,1,'episode'):
            raise ValueError(f'Unsupported {schema} contract')
    if p['roost_sha256'] != rh:
        raise ValueError('PERCH/ROOST hash mismatch')
    segments, issues = assemble(p,r,args.overlap_tolerance)
    counts = dict(Counter(s['action'] for s in segments))
    def display(s):
        if s['text'] is None or s['issues']:
            return f'[REVIEW G{s["group_id"]:03}]'
        return s['text']
    transcript = ' '.join(map(display,segments))
    data = dict(schema='hehawk.nest',schema_version=1,timestamp_basis='episode',
                perch_sha256=ph,roost_sha256=rh,settings=dict(overlap_tolerance_seconds=args.overlap_tolerance),
                counts=counts,segments=segments,issues=issues,provisional_text=transcript)
    lines = ['NEST V1 — PROVISIONAL TRANSCRIPT',str(counts), '', transcript,'','REVIEW QUEUE']
    for s in segments:
        if s['text'] is not None and not s['issues']:
            continue
        lines += ['',f'G{s["group_id"]:03} {stamp(s["start_seconds"])} – {stamp(s["end_seconds"])}',s['reason']]
        for issue in s['issues']:
            lines.append(str(issue))
        for alt in s['alternatives']:
            lines.append(f'  {alt["support"]} observation(s): {alt["witnesses"][0]["text"]}')
        if s['omission_windows']:
            lines.append('  Omitted by: '+', '.join(s['omission_windows']))
    encoded = json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    with args.o.open('x',encoding='utf-8') as f:
        f.write('\n'.join(lines)+'\n')
    with args.json.open('x',encoding='utf-8') as f:
        f.write(encoded)
    print(f'{len(segments)} groups; {sum(s["text"] is None or bool(s["issues"]) for s in segments)} review groups; {len(issues)} timing conflicts')


if __name__ == '__main__':
    main()
