#!/usr/bin/env python3
"""SWAN Experiment 1: read-only subtitle presentation diagnostics."""
import argparse
import heapq
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Limits:
    gap: int = 24
    duration: int = 600
    lines: int = 2
    width: int = 42
    cps: float = 20.0
    indent: int = 2


def analyze(cues, limits=Limits()):
    from gulp import clean_srt
    issues = defaultdict(list)
    pairs, groups = [], []
    events = defaultdict(int)
    active = {}
    heap = []
    group = []
    frontier = None
    previous = None
    for c in cues:
        i, a, b = c['id'], c['start_ms'], c['end_ms']
        if b <= a:
            raise ValueError(f'Invalid interval at cue {i}')
        if previous is not None and a < previous:
            issues['out_of_order'].append((i, a, previous))
        previous = a
        plain, _ = clean_srt(c['display_text'])
        lines = plain.split('\n')
        if b-a < limits.duration:
            issues['short_duration'].append((i, b-a))
        if len(lines) > limits.lines:
            issues['too_many_lines'].append((i, len(lines)))
        for n, line in enumerate(lines, 1):
            indent = len(line)-len(line.lstrip(' \t\u00a0'))
            if indent >= limits.indent:
                issues['indentation'].append((i,n,indent))
            if len(line) > limits.width:
                issues['long_line'].append((i,n,len(line)))
        cps = len(' '.join(plain.split()))*1000/(b-a)
        if cps > limits.cps:
            issues['reading_speed'].append((i,round(cps,2)))
        events[a] += 1
        events[b] -= 1
    for c in sorted(cues, key=lambda c:c['start_ms']):
        i,a,b = c['id'],c['start_ms'],c['end_ms']
        while heap and heap[0][0] <= a:
            _, j = heapq.heappop(heap)
            del active[j]
        if not active:
            if len(group)>1: groups.append(group)
            group = []
            if frontier is not None and a-frontier[0] < limits.gap:
                issues['insufficient_gap'].append((frontier[1],i,a-frontier[0]))
        for j,end in active.items():
            pairs.append((j,i,min(end,b)-a))
        group.append(i)
        active[i] = b
        heapq.heappush(heap,(b,i))
        if frontier is None or b > frontier[0]: frontier = (b,i)
    if len(group)>1: groups.append(group)
    count = peak = overlap = 0
    last = None
    for t, delta in sorted(events.items()):
        if last is not None and count >= 2: overlap += t-last
        count += delta
        peak = max(peak,count)
        last = t
    return dict(cue_count=len(cues), pairs=pairs, groups=groups,
                peak=peak, overlap_ms=overlap,
                pairwise_ms=sum(p[2] for p in pairs),
                longest_ms=max((p[2] for p in pairs),default=0), issues=dict(issues))


def main():
    from gulp import ingest
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path)
    for name, default in vars(Limits()).items():
        p.add_argument('--'+name,type=type(default),default=default)
    args=p.parse_args()
    limits=Limits(**{k:getattr(args,k) for k in vars(Limits())})
    import math
    if any(not math.isfinite(v) or v<0 for v in vars(limits).values()) or min(limits.lines,limits.width,limits.cps,limits.indent)<=0:
        p.error('Invalid diagnostic thresholds')
    try:
        data=ingest(args.input)
        r=analyze(data['cues'],limits)
    except (OSError,ValueError,KeyError,IndexError) as exc:
        p.exit(1,f'SWAN: {type(exc).__name__}: unable to analyze input\n')
    print(f"SWAN Experiment 1 | {data['format']} | {r['cue_count']} cues")
    print(f'Thresholds: {limits}')
    print(f"Overlapping pairs: {len(r['pairs'])}\nConflict groups: {len(r['groups'])}\nMaximum simultaneous cues: {r['peak']}")
    for key in ('overlap_ms','pairwise_ms','longest_ms'): print(f'{key}: {r[key]}')
    print('\nOVERLAPPING PAIRS (cue positions, milliseconds)')
    for pair in r['pairs']: print(*pair)
    print('\nCONFLICT GROUPS (cue positions)')
    for group in r['groups']: print(*group)
    for kind, entries in sorted(r['issues'].items()):
        print(f'\n{kind}: {len(entries)}')
        for entry in entries: print(*entry)
    return 0

if __name__=='__main__': raise SystemExit(main())
