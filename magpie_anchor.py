#!/usr/bin/env python3
"""MAGPIE 3B: contextual anchors, no automatic replacement."""
import argparse
import hashlib
import json
from pathlib import Path
from collections import defaultdict
import magpie as m
from magpie_reconstruct import words, subsequence
from magpie_merge import parse


def proposals(ref, asr, ops, candidates, srt):
    # Require a lossless lexical mapping before using presentation boundaries.
    flat = []
    owners = []
    for s,e,t,n in srt:
        w = words(t)
        flat.extend(w)
        owners.extend([n]*len(w))
    expected = [w['normalized'] for w in asr]
    if flat != expected:
        first = next((i for i,(a,b) in enumerate(zip(flat,expected)) if a!=b), min(len(flat),len(expected)))
        raise ValueError(f'ASR SRT lexical mapping differs: SRT={len(flat)}, recognition={len(expected)}, first difference index={first}; no proposals written')
    anchors = defaultdict(list)
    for op,i,j in ops:
        if op == 'equal':
            anchors[ref[i]['cue']].append(j)
    return anchors, owners


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','inventory','recognition','parakeet_srt','output'):
        p.add_argument(name,type=Path)
    a=p.parse_args()
    paths=[a.reference,a.inventory,a.recognition,a.parakeet_srt]
    raw=[x.read_bytes() for x in paths]
    hashes=[hashlib.sha256(x).hexdigest() for x in raw]
    g,inv,r=map(json.loads,raw[:3])
    if (inv.get('schema'),inv.get('schema_version'))!=('magpie_inventory',1): p.error('Unsupported inventory')
    for key,i in [('reference',0),('recognition',2)]:
        if inv['sources'][key]['sha256']!=hashes[i]: p.error(f'{key} hash mismatch')
    ref,asr=m.reference_words(g),m.recognition_words(r)
    ops=m.c.align_words(ref,asr)
    if m.inventory(ops,ref,asr,g['cues'])!=inv['candidates']: p.error('Recomputed alignment differs from inventory')
    srt=parse(raw[3])
    try: anchors,owners=proposals(ref,asr,ops,inv['candidates'],srt)
    except ValueError as e: p.error(str(e))
    rows=[]
    for c in inv['candidates']:
        if (c['kind'],c['location'])!=('recognition_only','crosses_boundary'): continue
        affected=[q for q in g['cues'] if q['id'] in c['overlapping_cue_ids']]
        anchor_indices=sorted({j for q in affected for j in anchors[q['id']]})
        candidate_indices=[w['global_index'] for w in c['recognition']]
        indices=anchor_indices+candidate_indices
        # Include intervening captions, but never expand on timing overlap alone.
        selected_ids=set(owners[min(indices):max(indices)+1])
        selected=[dict(id=n,start_ms=s,end_ms=e,text=t) for s,e,t,n in srt if n in selected_ids]
        proposed=words(' '.join(q['text'] for q in selected))
        original=words(' '.join(q['comparison_text'] for q in affected))
        missing=words(' '.join(w['word'] for w in c['recognition']))
        conflicts=[q['id'] for q in g['cues'] if q not in affected and any(q['start_ms']<z['end_ms'] and q['end_ms']>z['start_ms'] for z in selected)]
        foreign=sorted({qid for qid,js in anchors.items() if qid not in c['overlapping_cue_ids'] and any(owners[j] in selected_ids for j in js)})
        rows.append(dict(candidate_id=c['id'],status='unreviewed',original_cues=affected,recognition_words=c['recognition'],anchor_indices=anchor_indices,unanchored_original_cues=[q['id'] for q in affected if not anchors[q['id']]],parakeet_cues=selected,original_words_retained=subsequence(original,proposed),candidate_words_retained=subsequence(missing,proposed),other_reference_conflicts=conflicts,foreign_anchor_cues=foreign))
    payload=dict(schema='magpie_contextual_review',schema_version=1,sources=[dict(path=str(x),sha256=h) for x,h in zip(paths,hashes)],proposals=rows)
    with a.output.open('x',encoding='utf-8') as f: json.dump(payload,f,ensure_ascii=False,indent=2); f.write('\n')
    print('Boundary candidates:',len(rows))
    print('ID   Anchors  Original  Candidate  Time conflicts  Foreign anchors  ASR cues')
    for q in rows:
        print(f"{q['candidate_id']:3}  {len(q['anchor_indices']):7}  {str(q['original_words_retained']):8}  {str(q['candidate_words_retained']):9}  {str(q['other_reference_conflicts']):14}  {str(q['foreign_anchor_cues']):15}  {[z['id'] for z in q['parakeet_cues']]}")
    print('Created:',a.output)

if __name__=='__main__': main()
