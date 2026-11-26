#!/usr/bin/env python3
"""MAGPIE experiment 1: non-destructive evidence inventory."""
import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
import compare as c
from word_timing import word_groups


def load(path):
    raw = Path(path).read_bytes()
    return json.loads(raw), {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def reference_words(data):
    words = []
    cues = sorted(data['cues'], key=lambda x: x['start_ms'])
    for cue in cues:
        for i, word in enumerate(c.tokenize(cue['comparison_text'])):
            words.append(dict(word=word, normalized=c.normalize_word(word),
                              start=cue['start_ms']/1000, end=cue['end_ms']/1000,
                              cue=cue['id'], cue_word=i, global_index=len(words)))
    return words


def recognition_words(data):
    tokens, times, durations = (data[k] for k in ('tokens','timestamps','durations'))
    if not len(tokens) == len(times) == len(durations):
        raise ValueError('Mismatched token arrays')
    # Experiment 1 accepts full-episode evidence only; avoid ambiguous offset conventions.
    if data.get('source_offset_seconds', 0) != 0:
        raise ValueError('Nonzero source offset is not supported in experiment 1')
    if any(not math.isfinite(t) or not math.isfinite(d) or t < 0 or d < 0
           for t,d in zip(times,durations)):
        raise ValueError('Invalid token timing')
    words = []
    for raw,a,b,start,end in word_groups(tokens,times,durations,0,len(tokens)):
        for word in c.tokenize(raw):
            words.append(dict(word=word, normalized=c.normalize_word(word), start=start,
                              end=end, token_start=a, token_end=b))
    words.sort(key=lambda w:w['start'])
    for i,w in enumerate(words): w['global_index']=i
    return words


def classify(start,end,cues):
    hits=[q for q in cues if q['start_ms']/1000 < end and q['end_ms']/1000 > start]
    if not hits: return 'outside_captions', []
    if len(hits)==1 and hits[0]['start_ms']/1000 <= start and end <= hits[0]['end_ms']/1000:
        return 'inside_caption', [hits[0]['id']]
    return 'crosses_boundary', [q['id'] for q in hits]


def inventory(ops,ref,asr,cues):
    result=[]
    pending=[]
    def flush():
        if not pending: return
        r=[ref[i] for _,i,j in pending if i is not None]
        a=[asr[j] for _,i,j in pending if j is not None]
        kind='competing' if r and a else 'reference_only' if r else 'recognition_only'
        start=min(w['start'] for w in (a or r)); end=max(w['end'] for w in (a or r))
        location,ids=classify(start,end,cues)
        result.append(dict(id=len(result)+1,kind=kind,location=location,start=start,end=end,
                           overlapping_cue_ids=ids,reference=r,recognition=a,status='unreviewed'))
        pending.clear()
    for op in ops:
        if op[0]=='equal': flush()
        else: pending.append(op)
    flush()
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('gulp'); p.add_argument('recognition'); p.add_argument('--output-prefix',required=True)
    args=p.parse_args()
    paths=[Path(args.output_prefix+s) for s in ('.json','.txt')]
    if any(x.exists() for x in paths): p.error('Output already exists; choose a new prefix')
    g,gs=load(args.gulp); a,ats=load(args.recognition)
    ref=reference_words(g); asr=recognition_words(a)
    ops=c.align_words(ref,asr)
    candidates=inventory(ops,ref,asr,g['cues'])
    counts=Counter(x['kind'] for x in candidates)
    locations=Counter(x['location'] for x in candidates if x['kind']=='recognition_only')
    stats=dict(reference_words=len(ref),recognition_words=len(asr),matched_words=sum(o[0]=='equal' for o in ops),candidates=len(candidates),kinds=dict(counts),recognition_only_locations=dict(locations))
    report=['MAGPIE experiment 1',json.dumps(stats,indent=2),'', 'Candidate inventory (no dialogue):']
    for x in candidates:
        report.append(f"{x['id']:4} {x['start']:9.3f}-{x['end']:9.3f} {x['kind']:17} {x['location']:19} ref={len(x['reference'])} asr={len(x['recognition'])} cues={x['overlapping_cue_ids']}")
    payload=dict(schema='magpie_inventory',schema_version=1,sources={'reference':gs,'recognition':ats},parameters={'max_match_distance':c.MAX_MATCH_DISTANCE,'gap_cost':c.GAP_COST,'time_penalty_per_second':c.TIME_PENALTY_PER_SECOND,'max_time_penalty':c.MAX_TIME_PENALTY},stats=stats,candidates=candidates)
    created=[]
    try:
        for path,content in zip(paths,[json.dumps(payload,ensure_ascii=False,indent=2)+'\n','\n'.join(report)+'\n']):
            with path.open('x',encoding='utf-8') as f:
                created.append(path); f.write(content)
    except BaseException:
        for path in created: path.unlink()
        raise
    print(json.dumps(stats,indent=2))
    for path in paths: print('Created:',path)

if __name__=='__main__': main()
