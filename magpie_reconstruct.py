#!/usr/bin/env python3
"""MAGPIE 3A: local, provisional boundary reconstruction review inventory."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from magpie_merge import parse


def words(text):
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", re.sub(r'<[^>]*>', '', text).casefold().replace('’', "'"))


def subsequence(needle, haystack):
    it = iter(haystack)
    return all(any(x == n for x in it) for n in needle)


def proposals(ref, inv, srt):
    result = []
    for c in inv['candidates']:
        if (c['kind'], c['location']) != ('recognition_only', 'crosses_boundary'):
            continue
        affected = [q for q in ref['cues'] if q['id'] in c['overlapping_cue_ids']]
        if not affected:
            raise ValueError('Boundary candidate has no reference cues')
        start = min(round(c['start']*1000), *(q['start_ms'] for q in affected))
        end = max(round(c['end']*1000), *(q['end_ms'] for q in affected))
        selected = [dict(id=n,start_ms=s,end_ms=e,text=t) for s,e,t,n in srt if s<end and e>start]
        original = words(' '.join(q['comparison_text'] for q in affected))
        proposed = words(' '.join(q['text'] for q in selected))
        missing = [w['word'] for w in c['recognition']]
        conflicts = [q['id'] for q in ref['cues'] if q not in affected and any(q['start_ms']<r['end_ms'] and q['end_ms']>r['start_ms'] for r in selected)]
        result.append(dict(candidate_id=c['id'],status='unreviewed',start_ms=start,end_ms=end,original_cues=affected,recognition_words=c['recognition'],parakeet_cues=selected,original_words_retained=subsequence(original,proposed),candidate_words_retained=subsequence(words(' '.join(missing)),proposed),other_reference_conflicts=conflicts))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','inventory','recognition','parakeet_srt','output'):
        p.add_argument(name,type=Path)
    a=p.parse_args()
    paths=[a.reference,a.inventory,a.recognition,a.parakeet_srt]
    raw=[x.read_bytes() for x in paths]
    hashes=[hashlib.sha256(x).hexdigest() for x in raw]
    ref,inv=map(json.loads,raw[:2])
    if (inv.get('schema'),inv.get('schema_version'))!=('magpie_inventory',1): p.error('Unsupported inventory')
    for key,i in [('reference',0),('recognition',2)]:
        if inv['sources'][key]['sha256']!=hashes[i]: p.error(f'{key} hash mismatch')
    rows=proposals(ref,inv,parse(raw[3]))
    payload=dict(schema='magpie_reconstruction_review',schema_version=1,sources=[dict(path=str(x),sha256=h) for x,h in zip(paths,hashes)],proposals=rows)
    with a.output.open('x',encoding='utf-8') as f: json.dump(payload,f,ensure_ascii=False,indent=2); f.write('\n')
    print('Boundary candidates:',len(rows))
    print('ID   Original  Candidate  Other conflicts  ASR cues')
    for r in rows:
        print(f"{r['candidate_id']:3}  {str(r['original_words_retained']):8}  {str(r['candidate_words_retained']):9}  {str(r['other_reference_conflicts']):15}  {[q['id'] for q in r['parakeet_cues']]}")
    print('Created:',a.output)

if __name__=='__main__': main()
