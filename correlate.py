#!/usr/bin/env python3
"""Read-only diagnostic alignment of overlapping Parakeet windows."""
import argparse
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


def report(cols,windows,edge):
    lines=['HEHAWK — CORRELATION DIAGNOSTIC','Agreement is not proof of correctness. No transcript is modified.',f'Boundary margin: {edge:.2f}s','']
    for k,(lo,hi,p,ws) in enumerate(windows,1):
        lines.append(f'W{k}: {fmt(lo)} - {fmt(hi)} | {len(ws)} words | {p.name}')
    lines.append('')
    groups=[]
    for c in cols:
        state=classify(c,windows,edge)
        if groups and groups[-1][0]==state and bounds(c)[0]-bounds(groups[-1][1][-1])[1]<=0.85:
            groups[-1][1].append(c)
        else: groups.append((state,[c]))
    for (label,states),cs in groups:
        a=min(bounds(c)[0] for c in cs); b=max(bounds(c)[1] for c in cs)
        lines.append(f'{fmt(a)} - {fmt(b)} | {label}')
        for k,(lo,hi,_,_) in enumerate(windows):
            ws=[w for c in cs for w in c.get(k,[])]
            if ws:
                x,y=span(ws)
                lines.append(f'  W{k+1}: {phrase(ws)} [edge {min(x-lo,hi-y):.2f}s; tokens {ws[0][1]}:{ws[-1][2]}]')
            else: lines.append(f'  W{k+1}: {states[k]}')
        lines.append('')
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('inputs',nargs='+',type=Path)
    p.add_argument('-o','--output',type=Path,required=True)
    p.add_argument('--edge',type=float,default=1.5)
    args=p.parse_args()
    if len(args.inputs)<2 or len(set(x.resolve() for x in args.inputs))!=len(args.inputs) or not math.isfinite(args.edge) or args.edge<0:
        p.error('Provide distinct input files and a nonnegative finite edge margin')
    windows=sorted((load(x) for x in args.inputs),key=lambda w:(w[0],w[1],str(w[2])))
    cols=[]
    for k,(_,_,_,ws) in enumerate(windows):
        cols=align(cols,ws,k)
    for k,(_,_,_,ws) in enumerate(windows):
        assert [w for c in cols for w in c.get(k,[])]==ws, 'Alignment lost or reordered words'
    with args.output.open('x',encoding='utf-8') as f: f.write(report(cols,windows,args.edge))
    print(f'{len(cols)} alignment columns; report: {args.output}')


if __name__=='__main__': main()
