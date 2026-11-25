#!/usr/bin/env python3
"""Occurrence-specific OWL editorial decisions; immutable source evidence."""
import argparse
import copy
import json
from pathlib import Path
from owl_scan import read, scan


def prepare(report, digest):
    if report['schema'] != 'hehawk.owl.scan' or report['schema_version'] != 1:
        raise ValueError('Unsupported scan contract')
    return dict(schema='hehawk.owl.review', schema_version=1, scan_sha256=digest,
                decisions=[dict(id=r['id'], recognized=r['recognized'],
                    alternatives=r['alternatives'], context=r['context'],
                    decision='TODO', replacement=None) for r in report['occurrences']])


def apply(h, report, review):
    if (review['schema'], review['schema_version']) != ('hehawk.owl.review', 1):
        raise ValueError('Unsupported review contract')
    if h['pending_groups'] or any(s['issues'] or s['text'] is None for s in h['segments']):
        raise ValueError('Resolve HATCH review first')
    rows = {r['id']:r for r in report['occurrences']}
    decisions = review['decisions']
    if len(decisions)!=len(rows) or {d['id'] for d in decisions}!=set(rows):
        raise ValueError('Decision IDs must match scan exactly')
    out=copy.deepcopy(h)
    segments={s['group_id']:s for s in out['segments']}
    edits={}
    for d in decisions:
        r=rows[d['id']]; action=d['decision']; replacement=d['replacement']
        if action=='KEEP':
            if replacement is not None: raise ValueError('KEEP requires null replacement')
            continue
        if action not in ('SELECT','EDIT'):
            raise ValueError(f"Occurrence {d['id']}: unresolved or invalid decision")
        if not isinstance(replacement,str) or not replacement.strip() or replacement!=replacement.strip() or any(c in replacement for c in '\r\n'):
            raise ValueError('Invalid replacement')
        if action=='SELECT' and replacement not in [a['alternative'] for a in r['alternatives']]:
            raise ValueError('SELECT must use a listed alternative')
        if len(r['parts'])!=1 or len(replacement.split())!=len(r['recognized'].split()):
            raise ValueError('Cross-segment or word-count-changing edit not supported yet')
        p=r['parts'][0]; s=segments[p['group_id']]; a,b=p['char_start'],p['char_end_exclusive']
        if not 0<=a<b<=len(s['text']) or s['text'][a:b]!=r['recognized']:
            raise ValueError('Occurrence text mismatch')
        edits.setdefault(p['group_id'],[]).append((a,b,replacement,d['id']))
    for gid, changes in edits.items():
        s=segments[gid]; original=s['text']; last=len(original)
        for a,b,replacement,oid in sorted(changes,reverse=True):
            if b>last: raise ValueError('Overlapping corrections')
            last=a
        # Preserve source observation; derive separate editorial word text.
        obs=(s.get('selected') or {}).get('observation')
        if s['timing_basis']=='observed' and obs:
            words=copy.deepcopy(obs['words'])
            if ' '.join(w['text'] for w in words)!=original:
                raise ValueError('Cannot map observed words exactly')
            spans=[]; pos=0
            for w in words:
                spans.append((pos,pos+len(w['text']))); pos+=len(w['text'])+1
            for a,b,replacement,oid in sorted(changes,reverse=True):
                hit=[i for i,(x,y) in enumerate(spans) if a<y and b>x]
                if len(hit)!=len(replacement.split()): raise ValueError('Cannot preserve word timing')
                for i,new in zip(hit,replacement.split()):
                    x,y=spans[i]; lo=max(a,x)-x; hi=min(b,y)-x
                    w=words[i]; w['text']=w['text'][:lo]+new+w['text'][hi:]
            s['editorial_words']=words
        elif s['timing_basis']!='estimated_group_interval':
            raise ValueError('Unsupported timing basis')
        for a,b,replacement,oid in sorted(changes,reverse=True):
            s['text']=s['text'][:a]+replacement+s['text'][b:]
        if 'editorial_words' in s and ' '.join(w['text'] for w in s['editorial_words'])!=s['text']:
            raise ValueError('Editorial word mapping mismatch')
        s['owl_original_text']=original
        s['owl_edits']=[dict(id=i,char_start=a,char_end_exclusive=b,replacement=t) for a,b,t,i in sorted(changes)]
    out['schema']='hehawk.owl.edited'
    out['transcript']=' '.join(s['text'] for s in out['segments'] if s['text'])
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='cmd',required=True)
    q=sub.add_parser('prepare'); q.add_argument('scan',type=Path); q.add_argument('output',type=Path)
    q=sub.add_parser('apply')
    for name in ('knowledge','hatch','scan','review','output'): q.add_argument(name,type=Path)
    a=p.parse_args()
    try:
        report,rh=read(a.scan)
        if a.cmd=='prepare': result=prepare(report,rh)
        else:
            k,kh=read(a.knowledge); h,hh=read(a.hatch); v,vh=read(a.review)
            if (report['knowledge_sha256'],report['hatch_sha256'],v['scan_sha256'])!=(kh,hh,rh): raise ValueError('Input hash mismatch')
            if scan(k,h)!=report['occurrences']: raise ValueError('Scan does not reproduce')
            result=apply(h,report,v); result.update(owl_scan_sha256=rh,owl_review_sha256=vh,owl_knowledge_sha256=kh,owl_hatch_sha256=hh)
        payload=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
        with a.output.open('x',encoding='utf-8') as f: f.write(payload)
        print(f'Created {a.output}')
    except (ValueError,KeyError,TypeError,OSError) as e: p.exit(1,f'OWL Review: {e}\n')

if __name__=='__main__': main()
