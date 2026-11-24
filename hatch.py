#!/usr/bin/env python3
"""HATCH V1: human review of NEST transcripts, without modifying evidence."""
import argparse
import json
from pathlib import Path
from nest import load, stamp


def write(path, data):
    with path.open('x', encoding='utf-8') as f:
        f.write(data)


def encode(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def queue(n):
    return [s for s in n['segments'] if s['text'] is None or s['issues']]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['prepare','apply'])
    p.add_argument('nest', type=Path)
    p.add_argument('review', type=Path)
    p.add_argument('--roost', type=Path)
    p.add_argument('-o', type=Path)
    p.add_argument('--json', type=Path)
    a = p.parse_args()
    n, nh = load(a.nest)
    if (n['schema'], n['schema_version'], n['timestamp_basis']) != ('hehawk.nest',1,'episode'):
        p.error('Unsupported NEST contract')
    q = queue(n)
    if a.mode == 'prepare':
        entries = []
        for s in q:
            entries.append(dict(group_id=s['group_id'], time=stamp(s['start_seconds']),
                reason=s['reason'], alternatives=[dict(text=w['text'],window_id=w['window_id'])
                    for alt in s['alternatives'] for w in alt['witnesses']],
                decision='TODO', window_id=None, text=None))
        write(a.review, encode(dict(schema='hehawk.hatch.review',schema_version=1,nest_sha256=nh,entries=entries)))
        print(f'{len(entries)} review entries prepared')
        return
    if not all((a.roost,a.o,a.json)):
        p.error('apply requires --roost, -o and --json')
    paths=[x.resolve() for x in (a.nest,a.review,a.roost,a.o,a.json)]
    if len(set(paths))!=5 or a.o.exists() or a.json.exists():
        p.error('Inputs and new outputs must be distinct; no overwriting')
    r,rh=load(a.roost)
    v,vh=load(a.review)
    if (r['schema'],r['schema_version'],r['timestamp_basis'])!=('hehawk.roost',1,'episode') or rh!=n['roost_sha256']:
        p.error('ROOST contract or hash mismatch')
    if (v['schema'],v['schema_version'],v['nest_sha256'])!=('hehawk.hatch.review',1,nh):
        p.error('Review contract or NEST hash mismatch')
    entries=v['entries']
    if sorted(e['group_id'] for e in entries)!=sorted(s['group_id'] for s in q):
        p.error('Review group IDs mismatch')
    decisions={e['group_id']:e for e in entries}
    groups={g['id']:g for g in r['groups']}
    sources={w['id']:w for w in r['windows']}
    out=[]
    for s in n['segments']:
        t=dict(s, original_segment=s, human_decision=None, timing_basis='observed' if s['selected'] else None)
        e=decisions.get(s['group_id'])
        if e:
            d=e['decision'].upper()
            t['human_decision']=e
            if d=='SELECT':
                wid=e['window_id']
                obs=next((w['observation'] for w in groups[s['group_id']]['witnesses'] if w['window_id']==wid),None)
                if not obs or not any(w['window_id']==wid and w['text']==obs['text'] for alt in s['alternatives'] for w in alt['witnesses']):
                    p.error(f'Invalid selection G{s["group_id"]:03}')
                t.update(text=obs['text'],selected=dict(window_id=wid,source=sources[wid],observation=obs),start_seconds=obs['start_seconds'],end_seconds=obs['end_seconds'],timing_basis='observed')
            elif d=='EDIT':
                if not isinstance(e['text'],str) or not e['text'].strip():
                    p.error('EDIT requires nonempty text')
                t.update(text=e['text'].strip(),selected=None,timing_basis='estimated_group_interval')
            elif d=='DELETE':
                t.update(text='',selected=None,timing_basis=None)
            elif d in ('TODO','DEFER'):
                t.update(text=None,selected=None,timing_basis=None)
            else:
                p.error(f'Unknown decision {d}')
        t['issues']=[]
        out.append(t)
    previous=None
    used={}
    for t in out:
        if not t['text']: continue
        if t['selected']:
            wid=t['selected']['window_id']
            for w in t['selected']['observation']['words']:
                if w['token_start']<used.get(wid,0) or w['token_end_exclusive']<=w['token_start']:
                    p.error('Reused or reordered source tokens')
                used[wid]=w['token_end_exclusive']
        if previous and (previous['end_seconds']-t['start_seconds']>n['settings']['overlap_tolerance_seconds'] or t['start_seconds']<previous['start_seconds']):
            issue=dict(kind='TIMING CONFLICT',group_ids=[previous['group_id'],t['group_id']])
            previous['issues'].append(issue); t['issues'].append(issue)
        previous=t
    transcript=' '.join(f'[REVIEW G{t["group_id"]:03}]' if t['text'] is None or t['issues'] else t['text'] for t in out if t['text']!='')
    pending=[t['group_id'] for t in out if t['text'] is None or t['issues']]
    data=dict(schema='hehawk.hatch',schema_version=1,timestamp_basis='episode',nest_sha256=nh,roost_sha256=rh,review_sha256=vh,segments=out,pending_groups=pending,transcript=transcript)
    encoded=encode(data)
    write(a.o,transcript+'\n\nPending groups: '+str(pending)+'\n')
    write(a.json,encoded)
    print(f'{len(out)} groups; {len(pending)} pending review')

if __name__=='__main__':
    main()
