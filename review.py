#!/usr/bin/env python3
"""Generate independent, token-addressed subtitle review items."""
import argparse
import hashlib
import json
from pathlib import Path
from difflib import SequenceMatcher
import compare as c
from word_timing import word_groups


def stamp(t):
    return c.format_time(max(0,t))


def refine(ref, asr, ri, ai):
    # Pair nearby unmatched words monotonically; leave unpaired words separate.
    n,m=len(ri),len(ai)
    dp=[[0.]*(m+1) for _ in range(n+1)]
    trace={}
    for i in range(n+1):
        for j in range(m+1):
            if not i and not j: continue
            choices=[]
            if i: choices.append((dp[i-1][j]+1,'delete'))
            if j: choices.append((dp[i][j-1]+1,'insert'))
            if i and j:
                r,a=ref[ri[i-1]],asr[ai[j-1]]
                distance=c.temporal_distance(r,a)
                similarity=SequenceMatcher(None,r['normalized'],a['normalized']).ratio()
                if distance<=0.75 and (similarity>=0.35 or distance==0):
                    choices.append((dp[i-1][j-1]+1.25+0.5*distance-0.4*similarity,'replace'))
            dp[i][j],trace[i,j]=min(choices)
    out=[]; i,j=n,m
    while i or j:
        tag=trace[i,j]
        out.append((tag,ri[i-1] if tag!='insert' else None,ai[j-1] if tag!='delete' else None))
        i-=tag!='insert'; j-=tag!='delete'
    return out[::-1]


# Only recover unambiguous contiguous phrases inside existing alignment gaps.
MAX_RECOVERY_DISTANCE = 8.0
MIN_RECOVERY_WORDS = 2


def recover(ref, asr, ri, ai):
    if not ri or not ai:
        return refine(ref, asr, ri, ai)
    rwords = [ref[i]['normalized'] for i in ri]
    awords = [asr[i]['normalized'] for i in ai]
    matcher = SequenceMatcher(None, rwords, awords, autojunk=False)
    anchors = []
    for i, j, n in matcher.get_matching_blocks():
        if n < MIN_RECOVERY_WORDS:
            continue
        phrase = rwords[i:i+n]
        if not all(phrase):
            continue
        if any(sum(seq[k:k+n] == phrase for k in range(len(seq)-n+1)) != 1
               for seq in (rwords, awords)):
            continue
        distances = [c.temporal_distance(ref[ri[i+k]], asr[ai[j+k]]) for k in range(n)]
        if max(distances) > MAX_RECOVERY_DISTANCE or max(distances) <= c.MAX_MATCH_DISTANCE:
            continue
        anchors.append((i,j,n))
    out = []
    rpos = apos = 0
    for i,j,n in anchors:
        out.extend(refine(ref, asr, ri[rpos:i], ai[apos:j]))
        out.extend(('timing', ri[i+k], ai[j+k]) for k in range(n))
        rpos, apos = i+n, j+n
    out.extend(refine(ref, asr, ri[rpos:], ai[apos:]))
    return out


def build(ref, asr):
    ops=c.align_words(ref,asr)
    refined=[]; ri=[]; ai=[]
    for tag,r,a in ops+[('equal',None,None)]:
        if tag=='equal':
            if ri or ai: refined.extend(recover(ref,asr,ri,ai))
            ri=[]; ai=[]
            if r is not None: refined.append((tag,r,a))
        elif tag=='delete': ri.append(r)
        else: ai.append(a)
    groups=[]; cursor=0; active=None
    for tag,r,a in refined:
        if tag=='equal':
            active=None; cursor=a+1; continue
        split=active is None or active[0]!=tag
        if not split and a is not None and active[2]:
            split=asr[a]['start']-asr[active[2][-1]]['end']>1.25
        if not split and r is not None and active[1]:
            split=ref[r]['start']-ref[active[1][-1]]['end']>1.25
        if split:
            active=(tag,[],[],cursor); groups.append(active)
        if r is not None: active[1].append(r)
        if a is not None: active[2].append(a); cursor=a+1
    return groups


def suggestion(refwords, old):
    # ASS text is usually uppercase. Preserve ASR edge punctuation for replacements.
    words=[w['word'].lower() if w['word'].isupper() else w['word'] for w in refwords]
    if old and words:
        first=old[0]['word']; last=old[-1]['word']
        if first[:1].isupper(): words[0]=words[0].capitalize()
        import re
        suffix=re.search(r'[^\w\s]+$',last)
        if suffix: words[-1]+=suffix.group()
    return ' '.join(words)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('transcription',type=Path); p.add_argument('ass',type=Path)
    p.add_argument('-o','--output',type=Path); args=p.parse_args()
    output=args.output or args.transcription.with_name(args.transcription.stem+'_review_v4_timing.txt')
    raw=args.transcription.read_bytes(); data=json.loads(raw)
    if data.get('source_offset_seconds',0): p.error('V4 currently requires a full transcription with zero source offset')
    tokens,times,durations=(data[k] for k in ('tokens','timestamps','durations'))
    if not len(tokens)==len(times)==len(durations): p.error('Mismatched arrays')
    _,ref=c.read_ass(args.ass)
    asr=[dict(word=w,normalized=' '.join(c.normalize_word(x) for x in c.tokenize(w)),first=a,last=b,start=s,end=e) for w,a,b,s,e in word_groups(tokens,times,durations,0,len(tokens))]
    if not ref or not asr: p.error('Empty reference or transcription')
    groups=build(ref,asr); sections=[]
    for tag,rr,aa,pos in groups:
        rw=[ref[i] for i in rr]; aw=[asr[i] for i in aa]
        a=aw[0]['first'] if aw else (asr[pos]['first'] if pos<len(asr) else len(tokens))
        b=aw[-1]['last'] if aw else a
        if aw: start,end=aw[0]['start'],aw[-1]['end']
        else:
            start=max(rw[0]['start'],asr[pos-1]['end'] if pos else 0)
            end=min(rw[-1]['end'],times[a] if a<len(tokens) else rw[-1]['end'])
            if end<start: end=start
        label={'timing':'POSSIBLE TIMING DISCREPANCY','replace':'POSSIBLE SUBSTITUTION','insert':'POSSIBLE REFERENCE OMISSION / EXTRA ASR','delete':'POSSIBLE TRANSCRIPTION OMISSION / TIMING MISMATCH'}[tag]
        suggested=suggestion(rw,aw) if rw and tag!='timing' else ''
        timing_info = (f'Reference timing: {stamp(rw[0]["start"])} - {stamp(rw[-1]["end"])}\n'
                       f'Parakeet timing: {stamp(start)} - {stamp(end)}\n'
                       if tag=='timing' else '')
        lo=aa[0] if aa else pos; hi=aa[-1]+1 if aa else pos
        context=' '.join(x['word'] for x in asr[max(0,lo-12):lo])+' >>> '+(' '.join(x['word'] for x in aw) or '(insertion point)')+' <<< '+' '.join(x['word'] for x in asr[hi:hi+12])
        sections.append(f'REVIEW {len(sections)+1:04d} | {stamp(start)} - {stamp(end)}\nType: {label}\nListen from: {stamp(start-2)}\nToken range: {a}:{b}\nStatus: TODO\n{timing_info}\nContext (read only): {context}\nReference target: '+(' '.join(x['word'] for x in rw) or '(none)')+'\nParakeet target: '+(' '.join(x['word'] for x in aw) or '(none)')+f'\nSuggestion: {suggested}\nCorrection:\nNotes:\n')
    header=f'SUBTITLE REVIEW - VERSION 3\nGenerator: Review V4 (V3-compatible format)\nTranscription: {args.transcription.name}\nReference: {args.ass.name}\nTranscription SHA256: {hashlib.sha256(raw).hexdigest()}\nReview sections: {len(sections)}\n\nTODO / UNSURE / KEEP preserve original. ACCEPT uses Suggestion. EDIT uses Correction. DELETE removes target.\nSuggestions are tentative; check spelling, capitalization and audio. Never edit token ranges.\nEmpty insertion ranges may lack timing space; defer if necessary.\nTiming discrepancies have no suggested edit; KEEP preserves audio-derived timing.\n'
    with output.open('x',encoding='utf-8') as f: f.write(header+'\n'+('\n'+'='*72+'\n').join(sections))
    print(f'Timing discrepancy sections: {sum(g[0]=="timing" for g in groups)}\nReview sections: {len(sections)}\nWritten to: {output}')

if __name__=='__main__': main()
