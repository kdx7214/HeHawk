#!/usr/bin/env python3
"""Apply explicitly reviewed MAGPIE proposals to a verified provisional merge."""
import argparse
import hashlib
import json
from pathlib import Path
from magpie_merge import parse, stamp, canonical_rows
from magpie_review import ready


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def verify(source):
    raw = Path(source['path']).read_bytes()
    if digest(raw) != source['sha256']:
        raise ValueError('Hash mismatch: ' + source['path'])
    return raw


def apply(rows, provenance, proposals, decisions):
    if len(rows) != len(provenance):
        raise ValueError('Manifest length mismatch')
    base = []
    for (s,e,t,n), p in zip(rows, provenance):
        if (n,s,e) != (p['output_id'],p['start_ms'],p['end_ms']):
            raise ValueError('Manifest cue mismatch')
        base.append((s,e,t,dict(p)))
    by_id = {q['candidate_id']:q for q in proposals}
    removed = set()
    additions = []
    for key, decision in decisions.items():
        q = by_id[int(key)]
        if decision == 'reject':
            continue
        if decision != 'accept' or not ready(q):
            raise ValueError('Invalid or ineligible approval: ' + key)
        for c in q['original_cues']:
            n = c['id']
            hits = [r for r in base if r[3]['source']=='original' and r[3]['source_id']==n]
            expected = [(c['start_ms'],c['end_ms'],c['display_text'],n)]
            if n in removed or len(hits)!=1 or canonical_rows([(hits[0][0],hits[0][1],hits[0][2],n)]) != canonical_rows(expected):
                raise ValueError('Original replacement conflict: ' + str(n))
            removed.add(n)
        for c in q['parakeet_cues']:
            s,e,t = c['start_ms'],c['end_ms'],c['text']
            if s<0 or e<=s or not t.strip():
                raise ValueError('Invalid proposed cue')
            additions.append((s,e,t,dict(source='reviewed_reconstruction',source_id=c['id'],candidate_id=int(key),replaces=[x['id'] for x in q['original_cues']],status='reviewed')))
    retained = [r for r in base if not (r[3]['source']=='original' and r[3]['source_id'] in removed)]
    internal = []
    for i,(s,e,t,p) in enumerate(additions):
        for a,b,_,other in retained + additions[:i]:
            if a<e and b>s:
                if other.get('source')=='reviewed_reconstruction' and other['candidate_id']==p['candidate_id']:
                    internal.append(dict(candidate_id=p['candidate_id'],asr_cues=[other['source_id'],p['source_id']],overlap_ms=min(e,b)-max(s,a)))
                else:
                    raise ValueError('Reconstruction overlaps retained or other approved cue: '+str(p['candidate_id']))
    return sorted(retained+additions,key=lambda r:r[0]), removed, internal


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('merged_srt','merge_manifest','proposals','decisions','output_srt','output_manifest'):
        p.add_argument(name,type=Path)
    a=p.parse_args()
    paths=[a.merged_srt,a.merge_manifest,a.proposals,a.decisions]
    raw=[x.read_bytes() for x in paths]
    m,q,d=map(json.loads,raw[1:])
    if (m.get('schema'),m.get('schema_version'))!=('magpie_merge',1) or (q.get('schema'),q.get('schema_version'))!=('magpie_contextual_review',1):
        p.error('Unsupported schema')
    if d.get('proposal_sha256')!=digest(raw[2]) or m['output']['sha256']!=digest(raw[0]):
        p.error('Proposal or merged SRT hash mismatch')
    for source in m['sources']+q['sources']:
        verify(source)
    if [x['sha256'] for x in m['sources'][1:]] != [x['sha256'] for x in q['sources'][:3]]:
        p.error('Merge and proposal evidence differs')
    rows,removed,internal=apply(parse(raw[0]),m['cues'],q['proposals'],d['decisions'])
    content=''.join(f'{i}\n{stamp(s)} --> {stamp(e)}\n{t}\n\n' for i,(s,e,t,_) in enumerate(rows,1)).encode()
    manifest=dict(schema='magpie_reviewed_merge',schema_version=1,status='provisional',sources=[dict(path=str(x),sha256=digest(r)) for x,r in zip(paths,raw)],output=dict(path=str(a.output_srt),sha256=digest(content)),decisions=d['decisions'],internal_overlaps=internal,cues=[dict(meta,output_id=i,start_ms=s,end_ms=e) for i,(s,e,t,meta) in enumerate(rows,1)])
    created=[]
    try:
        for path,data in [(a.output_srt,content),(a.output_manifest,(json.dumps(manifest,indent=2)+'\n').encode())]:
            with path.open('xb') as f:
                created.append(path); f.write(data)
    except BaseException:
        for path in created: path.unlink()
        raise
    print('Removed original cues:',len(removed))
    print('Reviewed replacement cues:',sum(r[3]['source']=='reviewed_reconstruction' for r in rows))
    print('Total cues:',len(rows))
    print('Internal overlaps:',internal)
    print('Created:',a.output_srt,a.output_manifest)

if __name__=='__main__': main()
