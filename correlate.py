#!/usr/bin/env python3
"""Read-only diagnostic alignment of overlapping Parakeet windows."""
import argparse
import hashlib
import json
import math
import unicodedata
from pathlib import Path
from difflib import SequenceMatcher
from statistics import median
from word_timing import word_groups


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKC', s).casefold() if c.isalnum())


def fmt(t):
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f'{int(h):02d}:{int(m):02d}:{s:05.2f}'


def load(path):
    d = json.loads(path.read_text(encoding='utf-8'))
    lo, hi = d['window_start_seconds'], d['window_end_seconds']
    if d['timestamp_basis'] != 'episode' or d.get('source_offset_seconds', 0) != 0:
        raise ValueError(f'{path}: expected absolute episode timestamps')
    t, s, z = (d[k] for k in ('tokens', 'timestamps', 'durations'))
    if not math.isfinite(lo) or not math.isfinite(hi) or lo >= hi or any(not math.isfinite(x) for x in s+z) or any(x < 0 for x in z) or any(a>b for a,b in zip(s,s[1:])):
        raise ValueError(f'{path}: invalid timing')
    if any(x < lo-0.001 or x > hi+0.001 for x in s):
        raise ValueError(f'{path}: token outside window')
    words = [w for w in word_groups(t,s,z,0,len(t)) if norm(w[0])]
    return lo, hi, path, words


def span(words):
    return min(w[3] for w in words), max(w[4] for w in words)


def bounds(col):
    spans = [span(w) for w in col.values()]
    return median(x[0] for x in spans), median(x[1] for x in spans)


def phrase(words):
    return ' '.join(w[0] for w in words)


def match(cols, words):
    # Compare only witnesses present throughout this candidate group.
    common = set(cols[0]).intersection(*(set(c) for c in cols))
    best = None
    b0,b1 = span(words)
    b = norm(phrase(words))
    for k in common:
        a_words = [w for c in cols for w in c[k]]
        a0,a1 = span(a_words)
        delta = abs((a0+a1-b0-b1)/2)
        if delta > 0.65 or max(a0,b0)-min(a1,b1)>0.24:
            continue
        a = norm(phrase(a_words))
        sim = SequenceMatcher(None,a,b,autojunk=False).ratio()
        multi = len(cols)>1 or len(words)>1
        if multi and a != b:
            continue
        if not multi and a != b and delta > 0.28:
            continue
        cost = (0 if a==b else 1.15-0.45*sim) + delta + (0.15 if multi else 0)
        best = cost if best is None else min(best,cost)
    return best


def align(cols, words, k):
    n,m = len(cols),len(words)
    dp = [[float('inf')]*(m+1) for _ in range(n+1)]
    back = [[None]*(m+1) for _ in range(n+1)]
    dp[0][0]=0
    for i in range(n+1):
        for j in range(m+1):
            def step(a,b,cost):
                v=dp[i][j]+cost
                if v < dp[i+a][j+b]:
                    dp[i+a][j+b]=v
                    back[i+a][j+b]=(a,b)
            if i<n: step(1,0,1)
            if j<m: step(0,1,1)
            for a,b in ((1,1),(1,2),(2,1),(1,3),(3,1)):
                if i+a<=n and j+b<=m:
                    # Avoid merging groups with inconsistent witness coverage.
                    if a>1 and any(set(c)!=set(cols[i]) for c in cols[i:i+a]):
                        continue
                    cost=match(cols[i:i+a],words[j:j+b])
                    if cost is not None: step(a,b,cost)
    out=[]
    i,j=n,m
    while i or j:
        a,b=back[i][j]
        c={}
        for old in cols[i-a:i]:
            for key,ws in old.items(): c.setdefault(key,[]).extend(ws)
        if b: c[k]=words[j-b:j]
        out.append(c)
        i-=a; j-=b
    return out[::-1]


# Conservative, explicit English homophone classes; not a spelling corrector.
HOMOPHONES = ({'to', 'too', 'two'}, {'there', 'their', 'theyre'},
              {'your', 'youre'}, {'hear', 'here'}, {'right', 'write'},
              {'no', 'know'}, {'one', 'won'}, {'see', 'sea'})


def reconcile(cols, windows, edge):
    """Merge adjacent, disjoint homophone columns only at a window edge."""
    out, audit = [], []
    i = 0
    while i < len(cols):
        a = cols[i]
        if i+1 < len(cols):
            b = cols[i+1]
            if not (set(a) & set(b)) and all(len(ws)==1 for ws in list(a.values())+list(b.values())):
                av = {norm(ws[0][0]) for ws in a.values()}
                bv = {norm(ws[0][0]) for ws in b.values()}
                x,y = bounds(a),bounds(b)
                delta = abs(sum(x)/2-sum(y)/2)
                gap = max(x[0],y[0])-min(x[1],y[1])
                def near(k,ws):
                    lo,hi,_,_ = windows[k]
                    u,v = span(ws)
                    return min(u-lo,hi-v)<edge
                # Require an edge-only minority and corroborated interior majority.
                def opposed(small,large):
                    return (len(small)==1 and all(near(k,w) for k,w in small.items())
                            and sum(not near(k,w) for k,w in large.items())>=2)
                if (len(av)==len(bv)==1 and av!=bv and any(av|bv <= h for h in HOMOPHONES)
                    and delta<=0.65 and gap<=0.45 and (opposed(a,b) or opposed(b,a))):
                    out.append({**a,**b})
                    audit.append(dict(original_column_ids=[i,i+1], variants=sorted(av|bv),
                                      midpoint_delta_seconds=delta, interval_gap_seconds=gap,
                                      reason='Adjacent disjoint homophones with edge-only minority'))
                    i+=2
                    continue
        out.append(a)
        i+=1
    return out,audit


def classify(c, windows, edge):
    a,b=bounds(c)
    states=[]
    for k,(lo,hi,_,_) in enumerate(windows):
        if k in c: states.append('heard')
        elif b<=lo or a>=hi: states.append('outside')
        elif a<lo+edge or b>hi-edge: states.append('edge')
        else: states.append('missing')
    variants={norm(phrase(w)) for w in c.values()}
    if len(variants)>1: label='ALTERNATIVE'
    elif 'missing' in states: label='POSSIBLE OMISSION'
    elif 'edge' in states: label='BOUNDARY UNCERTAIN'
    elif len(c)>1: label='AGREEMENT'
    else: label='SINGLE COVERAGE'
    return label,tuple(states)


def group_phrases(cols, windows, edge, gap=0.85):
    """FPP: group adjacent disagreements without mixing witnesses."""
    uncertain = {'ALTERNATIVE', 'POSSIBLE OMISSION', 'BOUNDARY UNCERTAIN'}
    groups = []
    for c in cols:
        state = classify(c, windows, edge)
        if groups:
            prev_state, prev_cols = groups[-1]
            close = bounds(c)[0] - bounds(prev_cols[-1])[1] <= gap
            # Do not cross a coverage transition into/out of a window.
            same_coverage = all((a == 'outside') == (b == 'outside')
                                for a,b in zip(prev_state[1], state[1]))
            # A sentence-ending observation followed by a pause is a hard break.
            if bounds(c)[0] - bounds(prev_cols[-1])[1] >= 0.35 and any(phrase(ws).endswith((".", "?", "!")) for ws in prev_cols[-1].values()):
                close = False
            if close and (state == prev_state or
                          (same_coverage and state[0] in uncertain and
                           prev_state[0] in uncertain)):
                prev_cols.append(c)
                groups[-1] = (state, prev_cols)
                continue
        groups.append((state, [c]))
    assert [c for _,cs in groups for c in cs] == cols
    return [cs for _,cs in groups]


def report(cols,windows,edge,gap=0.85):
    lines=['HEHAWK — CORRELATION DIAGNOSTIC V2 (FPP)',
           'Agreement is not proof of correctness. No transcript is modified.',
           f'Boundary margin: {edge:.2f}s; grouping gap: {gap:.2f}s','']
    for k,(lo,hi,p,ws) in enumerate(windows,1):
        lines.append(f'W{k}: {fmt(lo)} - {fmt(hi)} | {len(ws)} words | {p.name}')
    lines.append('')
    for cs in group_phrases(cols,windows,edge,gap):
        evidence=[classify(c,windows,edge) for c in cs]
        labels=list(dict.fromkeys(label for label,_ in evidence))
        label=labels[0] if len(labels)==1 else 'COMPOUND DISAGREEMENT'
        a=min(bounds(c)[0] for c in cs); b=max(bounds(c)[1] for c in cs)
        lines.append(f'{fmt(a)} - {fmt(b)} | {label}')
        if len(labels)>1: lines.append('  Evidence: '+', '.join(labels))
        variants=[]
        for k,(lo,hi,_,_) in enumerate(windows):
            ws=[w for c in cs for w in c.get(k,[])]
            states=list(dict.fromkeys(st[k] for _,st in evidence))
            if ws:
                x,y=span(ws)
                wording=phrase(ws)
                variants.append(wording)
                lines.append(f'  W{k+1}: {wording} [edge {min(x-lo,hi-y):.2f}s; tokens {ws[0][1]}:{ws[-1][2]}]')
                if states != ['heard']: lines.append('    Coverage: '+', '.join(states))
            else: lines.append(f'  W{k+1}: '+', '.join(states))
        if len(variants)>1 and len({norm(v) for v in variants})==1 and len(set(variants))>1:
            lines.append('  Surface variation: capitalization, punctuation or segmentation')
        lines.append('')
    return '\n'.join(lines)+'\n'


def roost(cols, windows, edge, gap):
    """ROOST schema 1: preserve aligned lexical evidence and FPP groups."""
    def observation(ws, lo, hi):
        if not ws:
            return None
        a, b = span(ws)
        return dict(text=phrase(ws), normalized=norm(phrase(ws)),
                    start_seconds=a, end_seconds=b,
                    edge_distance_seconds=min(a-lo, hi-b),
                    words=[dict(text=w[0], token_start=w[1],
                                token_end_exclusive=w[2], start_seconds=w[3],
                                end_seconds=w[4]) for w in ws])

    sources = [dict(id=f'W{k+1}', filename=p.name,
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                    start_seconds=lo, end_seconds=hi, word_count=len(ws))
               for k,(lo,hi,p,ws) in enumerate(windows)]
    columns = []
    for i,c in enumerate(cols):
        label, states = classify(c, windows, edge)
        a,b = bounds(c)
        columns.append(dict(id=i, label=label, start_seconds=a, end_seconds=b,
                            witnesses=[dict(window_id=f'W{k+1}', state=states[k],
                                            observation=observation(c.get(k,[]),lo,hi))
                                       for k,(lo,hi,_,_) in enumerate(windows)]))
    groups = []
    offset = 0
    for i,cs in enumerate(group_phrases(cols,windows,edge,gap)):
        ids = list(range(offset,offset+len(cs)))
        offset += len(cs)
        evidence = [columns[j] for j in ids]
        labels = list(dict.fromkeys(c['label'] for c in evidence))
        witnesses = []
        for k,(lo,hi,_,_) in enumerate(windows):
            ws = [w for c in cs for w in c.get(k,[])]
            witnesses.append(dict(window_id=f'W{k+1}',
                                  states=[c['witnesses'][k]['state'] for c in evidence],
                                  observation=observation(ws,lo,hi)))
        groups.append(dict(id=i, column_ids=ids, evidence_labels=labels,
                           label=labels[0] if len(labels)==1 else 'COMPOUND DISAGREEMENT',
                           start_seconds=min(c['start_seconds'] for c in evidence),
                           end_seconds=max(c['end_seconds'] for c in evidence),
                           witnesses=witnesses))
    assert offset == len(cols)
    return dict(schema='hehawk.roost', schema_version=1, timestamp_basis='episode',
                settings=dict(edge_seconds=edge, grouping_gap_seconds=gap),
                windows=sources, columns=columns, groups=groups)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('inputs',nargs='+',type=Path)
    p.add_argument('-o','--output',type=Path,required=True)
    p.add_argument('--edge',type=float,default=1.5)
    p.add_argument('--gap',type=float,default=0.85)
    p.add_argument('--no-reconcile',action='store_true',help='Disable TALON V3 second pass')
    p.add_argument('--json',type=Path,help='Optional ROOST evidence output')
    args=p.parse_args()
    outputs=[args.output]+([args.json] if args.json is not None else [])
    if len({x.resolve() for x in outputs}) != len(outputs): p.error('Output paths must differ')
    if any(x.exists() for x in outputs): p.error('Output already exists; choose a new filename')
    if not math.isfinite(args.gap) or args.gap<0: p.error('Gap must be finite and nonnegative')
    if len(args.inputs)<2 or len(set(x.resolve() for x in args.inputs))!=len(args.inputs) or not math.isfinite(args.edge) or args.edge<0:
        p.error('Provide distinct input files and a nonnegative finite edge margin')
    windows=sorted((load(x) for x in args.inputs),key=lambda w:(w[0],w[1],str(w[2])))
    cols=[]
    for k,(_,_,_,ws) in enumerate(windows):
        cols=align(cols,ws,k)
    audit=[]
    if not args.no_reconcile:
        cols,audit=reconcile(cols,windows,args.edge)
    for k,(_,_,_,ws) in enumerate(windows):
        assert [w for c in cols for w in c.get(k,[])]==ws, 'Alignment lost or reordered words'
    payload=roost(cols,windows,args.edge,args.gap) if args.json is not None else None
    if payload is not None:
        payload['talon_reconciliation'] = dict(version=3, enabled=not args.no_reconcile, merges=audit)
    with args.output.open('x',encoding='utf-8') as f:
        f.write(report(cols,windows,args.edge,args.gap))
        f.write('TALON V3 reconciliation: '+str(len(audit))+' merges\n')
        for item in audit: f.write(json.dumps(item)+'\n')
    if args.json is not None:
        with args.json.open('x',encoding='utf-8') as f:
            json.dump(payload,f,ensure_ascii=False,indent=2,allow_nan=False)
            f.write('\n')
        print(f'ROOST evidence: {args.json}')
    print(f'{len(cols)} alignment columns; report: {args.output}')


if __name__=='__main__': main()
