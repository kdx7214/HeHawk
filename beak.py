#!/usr/bin/env python3
"""BEAK V2: descriptive evidence assessment of ROOST V1; no decisions."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median


def evidence_flags(alternatives, coverage, edge):
    """Describe evidence without selecting or scoring a candidate."""
    flags = []
    if any(a['support'] > 1 for a in alternatives):
        flags.append('CORROBORATED')
    missing = any(c['missing'] for c in coverage.values())
    boundary = any(c['edge'] for c in coverage.values())
    lexical = len(alternatives) > 1
    if len(alternatives) == 1 and alternatives[0]['support'] == 1 and not missing:
        flags.append('UNOPPOSED')
    if missing:
        flags.append('OMISSION CONFLICT')
    if boundary or ((missing or lexical) and any(a['min_edge_seconds'] < edge for a in alternatives)):
        flags.append('BOUNDARY CONFLICT')
    if lexical:
        flags.append('LEXICAL CONFLICT')
    return flags


def assess(d):
    if (d['schema'], d['schema_version'], d['timestamp_basis']) != ('hehawk.roost', 1, 'episode'):
        raise ValueError('Expected ROOST V1 with episode timestamps')
    ids = [w['id'] for w in d['windows']]
    cols = {c['id']: c for c in d['columns']}
    if len(cols) != len(d['columns']) or len(set(ids)) != len(ids):
        raise ValueError('Duplicate column or window ID')
    if [i for g in d['groups'] for i in g['column_ids']] != list(cols):
        raise ValueError('Groups must partition columns in order')
    out = []
    for g in d['groups']:
        witnesses = g['witnesses']
        if [w['window_id'] for w in witnesses] != ids:
            raise ValueError('Unexpected group witnesses')
        candidates = defaultdict(list)
        coverage = {}
        for w in witnesses:
            k = w['window_id']
            underlying = [next(x for x in cols[i]['witnesses'] if x['window_id']==k) for i in g['column_ids']]
            states = [x['state'] for x in underlying]
            if states != w['states'] or set(states)-{'heard','missing','edge','outside'}:
                raise ValueError('Invalid coverage states')
            words = [word for x in underlying if x['observation'] for word in x['observation']['words']]
            o = w['observation']
            if words != (o['words'] if o else []):
                raise ValueError('Group observation differs from columns')
            coverage[k] = {s: states.count(s) for s in ('heard','missing','edge','outside')}
            if o:
                candidates[o['normalized']].append((k,o))
        alternatives=[]
        for key, obs in candidates.items():
            starts=[o['start_seconds'] for _,o in obs]; ends=[o['end_seconds'] for _,o in obs]
            distances=[o['edge_distance_seconds'] for _,o in obs]
            alternatives.append(dict(normalized=key, support=len(obs),
                witnesses=[dict(window_id=k,text=o['text'],edge_distance_seconds=o['edge_distance_seconds'],start_seconds=o['start_seconds'],end_seconds=o['end_seconds'],coverage=coverage[k]) for k,o in obs],
                median_edge_seconds=median(distances), min_edge_seconds=min(distances),
                start_spread_seconds=max(starts)-min(starts) if len(obs)>1 else None,
                end_spread_seconds=max(ends)-min(ends) if len(obs)>1 else None))
        out.append(dict(group_id=g['id'],label=g['label'],start_seconds=g['start_seconds'],end_seconds=g['end_seconds'],coverage=coverage,alternatives=alternatives,flags=evidence_flags(alternatives, coverage, d['settings']['edge_seconds'])))
    return out


def fmt(t):
    m,s=divmod(t,60); h,m=divmod(int(m),60)
    return f'{h:02}:{m:02}:{s:05.2f}'


def report(groups):
    lines=['HEHAWK — BEAK V2','Descriptive evidence only; no confidence scores or selections.','Support counts are correlated observations, not independent votes.','Coverage counts refer to alignment columns, not words or duration.','']
    for g in groups:
        lines.append(f"G{g['group_id']:03} {fmt(g['start_seconds'])} - {fmt(g['end_seconds'])} | {g['label']}")
        lines.append('  Flags: '+(', '.join(g['flags']) or 'none'))
        for k,c in g['coverage'].items():
            lines.append('  '+k+' coverage: '+', '.join(f'{s}={n}' for s,n in c.items() if n))
        for a in g['alternatives']:
            lines.append(f"  Candidate: {a['witnesses'][0]['text']} | support={a['support']}")
            for w in a['witnesses']:
                lines.append(f"    {w['window_id']}: {w['text']} | edge={w['edge_distance_seconds']:.2f}s")
            lines.append(f"    Edge median={a['median_edge_seconds']:.2f}s; minimum={a['min_edge_seconds']:.2f}s")
            if a['start_spread_seconds'] is None: lines.append('    Timing spread: unavailable (one witness)')
            else: lines.append(f"    Timing spread: start={a['start_spread_seconds']:.3f}s; end={a['end_spread_seconds']:.3f}s")
        lines.append('')
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path); p.add_argument('-o','--output',required=True,type=Path); p.add_argument('--json',type=Path)
    a=p.parse_args()
    paths=[a.input,a.output]+([a.json] if a.json else [])
    if len({x.resolve() for x in paths})!=len(paths) or any(x.exists() for x in paths[1:]): p.error('Use distinct, new output paths')
    raw=a.input.read_bytes(); groups=assess(json.loads(raw))
    with a.output.open('x',encoding='utf-8') as f: f.write(report(groups))
    if a.json:
        with a.json.open('x',encoding='utf-8') as f: json.dump(dict(schema='hehawk.beak',schema_version=2,source_sha256=hashlib.sha256(raw).hexdigest(),groups=groups),f,indent=2,ensure_ascii=False,allow_nan=False)
    print(f'{len(groups)} phrase groups assessed; report: {a.output}')

if __name__=='__main__': main()
