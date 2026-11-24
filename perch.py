#!/usr/bin/env python3
"""PERCH V1: conservative, auditable phrase recommendations; no edits."""
import argparse
import hashlib
import json
from pathlib import Path
from collections import Counter


def recommend(g, edge):
    flags = set(g['flags'])
    candidates = g['alternatives']
    ranked = sorted(candidates, key=lambda a: (-sum(w['edge_distance_seconds'] >= edge for w in a['witnesses']), -a['support'], a['normalized']))
    a = ranked[0] if ranked else None
    interior = [w for w in a['witnesses'] if w['edge_distance_seconds'] >= edge] if a else []
    omissions = g['omission_windows']
    action, reason = 'REVIEW', 'Insufficient corroboration'
    if 'LEXICAL CONFLICT' in flags or 'PARTIAL COVERAGE UNCERTAIN' in flags:
        action, reason = 'INVESTIGATE', 'Unresolved lexical or partial coverage conflict'
    elif a and len(interior) >= 2:
        ids = {w['window_id'] for w in a['witnesses']}
        relations = {frozenset(r['window_ids']): r['kind'] for r in g['relations']}
        rivals = [w for b in ranked[1:] for w in b['witnesses']]
        compatible = all(all(relations.get(frozenset((w['window_id'], k))) == 'COMPATIBLE TRUNCATION' for k in ids) and len(w['text']) < len(interior[0]['text']) for w in rivals)
        edge_only = all(w['edge_distance_seconds'] < edge and all(relations.get(frozenset((w['window_id'], k))) == 'BOUNDARY-ASSOCIATED SUBSTITUTION' for k in ids) for w in rivals)
        if rivals and not (compatible or edge_only):
            action, reason = 'INVESTIGATE', 'Competing observations not explained by boundary evidence'
        elif omissions and len(interior) <= len(omissions):
            action, reason = 'INVESTIGATE', 'Interior support does not exceed omission count'
        elif rivals or omissions:
            action, reason = 'PREFER', 'Corroborated interior evidence; opposition is omission, truncation or edge-associated'
        else:
            action, reason = 'RETAIN', 'Corroborated interior evidence without substantive opposition'
    selected = max(interior, key=lambda w: w['edge_distance_seconds']) if action in ('RETAIN','PREFER') else None
    return dict(group_id=g['group_id'], start_seconds=g['start_seconds'], end_seconds=g['end_seconds'], action=action, reason=reason, selected=selected, flags=g['flags'], alternatives=candidates, relations=g['relations'], omission_windows=omissions, partial_missing_windows=g['partial_missing_windows'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('beak',type=Path); p.add_argument('roost',type=Path); p.add_argument('-o','--output',required=True,type=Path); p.add_argument('--json',required=True,type=Path)
    a=p.parse_args(); paths=[a.beak,a.roost,a.output,a.json]
    if len({x.resolve() for x in paths})!=4 or any(x.exists() for x in paths[2:]): p.error('Use distinct new output paths')
    raw=a.beak.read_bytes(); b=json.loads(raw); rr=a.roost.read_bytes(); r=json.loads(rr)
    if (b['schema'],b['schema_version'])!=('hehawk.beak',3) or (r['schema'],r['schema_version'],r['timestamp_basis'])!=('hehawk.roost',1,'episode') or b['source_sha256']!=hashlib.sha256(rr).hexdigest(): p.error('Expected matching BEAK V3 and ROOST V1')
    if [g['group_id'] for g in b['groups']] != [g['id'] for g in r['groups']]: p.error('Group IDs differ')
    edge=r['settings']['edge_seconds']; groups=[recommend(g,edge) for g in b['groups']]
    counts=Counter(g['action'] for g in groups)
    lines=['HEHAWK — PERCH V1','Phrase recommendations only; no edits or confidence probabilities.','Support is correlated, not independent.','']
    for g in groups:
        lines.append(f"G{g['group_id']:03} {g['start_seconds']:.3f}–{g['end_seconds']:.3f} | {g['action']} | {g['reason']}")
        if g['selected']: lines.append(f"  Proposed: {g['selected']['text']} [{g['selected']['window_id']}]")
        for c in g['alternatives']: lines.append(f"  Candidate: {c['witnesses'][0]['text']} | support={c['support']}")
    lines.append(str(dict(counts)))
    with a.output.open('x',encoding='utf-8') as f: f.write('\n'.join(lines)+'\n')
    with a.json.open('x',encoding='utf-8') as f: json.dump(dict(schema='hehawk.perch',schema_version=1,timestamp_basis='episode',beak_sha256=hashlib.sha256(raw).hexdigest(),roost_sha256=b['source_sha256'],settings=dict(edge_seconds=edge,min_interior_support=2),groups=groups),f,indent=2,ensure_ascii=False,allow_nan=False)
    print(dict(counts))

if __name__=='__main__': main()
