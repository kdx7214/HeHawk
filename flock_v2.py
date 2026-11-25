import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import median


def load(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def assess(t, words, radius):
    inside = [w for w in words if w['start_seconds'] < t < w['end_seconds']]
    left = max((w for w in words if w['end_seconds'] <= t),
               key=lambda w: w['end_seconds'], default=None)
    right = min((w for w in words if w['start_seconds'] >= t),
                key=lambda w: w['start_seconds'], default=None)
    dl = t-left['end_seconds'] if left else None
    dr = right['start_seconds']-t if right else None
    l = dl is not None and dl <= radius
    r = dr is not None and dr <= radius
    boundary = None
    if inside:
        state = 'WITHIN_WORD'
    elif l and r:
        state = 'BETWEEN_WORDS'
        boundary = (left['end_seconds']+right['start_seconds'])/2
    elif l:
        state = 'SPEECH_END'
    elif r:
        state = 'SPEECH_START'
    else:
        state = 'NO_LEXICAL_SUPPORT'
    return dict(state=state, preceding_distance_seconds=dl,
                following_distance_seconds=dr, boundary_seconds=boundary,
                preceding_word=left, following_word=right, overlapping_words=inside,
                sentence_boundary=bool(left and left['text'].rstrip().endswith(('.', '?', '!', '…'))))


def nearest_gap(t, words, max_gap):
    ordered = sorted(words, key=lambda w: w['token_start'])
    gaps = []
    for left, right in zip(ordered, ordered[1:]):
        a, b = left['end_seconds'], right['start_seconds']
        if not 0 <= b-a <= max_gap:
            continue
        # Do not propose a boundary intersecting another recognized word.
        point = min(max(t, a), b)
        if any(w['start_seconds'] < point < w['end_seconds'] for w in ordered):
            continue
        gaps.append(dict(start_seconds=a, end_seconds=b,
                         boundary_seconds=point, displacement_seconds=point-t,
                         preceding_word=left, following_word=right))
    return min(gaps, key=lambda g: (abs(g['displacement_seconds']),
               g['end_seconds']-g['start_seconds'], g['start_seconds']), default=None)


def proximity(evidence, displacement, spread):
    near = [e['nearest_gap'] for e in evidence if e['nearest_gap'] is not None
            and abs(e['nearest_gap']['displacement_seconds']) <= displacement]
    points = [g['boundary_seconds'] for g in near]
    result = dict(support=len(near), coverage=len(evidence),
                  spread_seconds=max(points)-min(points) if points else None,
                  proposed_boundary_seconds=None)
    if not evidence:
        label = 'INSUFFICIENT_COVERAGE'
    elif not near:
        label = 'NO_NEARBY_GAP'
    elif len(near) != len(evidence):
        label = 'MIXED_SUPPORT'
    elif len(near) == 1:
        label = 'SINGLE_WINDOW_GAP'
    elif result['spread_seconds'] > spread:
        label = 'BOUNDARY_DISAGREEMENT'
    else:
        # Require a shared gap, not a synthetic point inside a witness's word.
        lo = max(g['start_seconds'] for g in near)
        hi = min(g['end_seconds'] for g in near)
        if lo > hi:
            label = 'BOUNDARY_DISAGREEMENT'
        else:
            label = 'CORROBORATED_GAP'
            result['proposed_boundary_seconds'] = min(max(median(points), lo), hi)
    result['classification'] = label
    return result


def main():
    p = argparse.ArgumentParser(description='FLOCK V2: acoustic/lexical evidence correlation')
    p.add_argument('consensus', type=Path)
    p.add_argument('roost', type=Path)
    p.add_argument('--radius', type=float, default=1.0)
    p.add_argument('--max-displacement', type=float, default=0.35)
    p.add_argument('--max-gap', type=float, default=1.0)
    p.add_argument('--max-spread', type=float, default=0.20)
    p.add_argument('-o', type=Path, required=True)
    p.add_argument('--json', type=Path, required=True)
    a = p.parse_args()
    if not 0 < a.radius < float('inf'):
        p.error('Radius must be positive and finite')
    if not all(0 < v < float('inf') for v in (a.max_displacement,a.max_gap,a.max_spread)):
        p.error('Boundary settings must be positive and finite')
    paths = [x.resolve() for x in (a.consensus,a.roost,a.o,a.json)]
    if len(set(paths)) != 4 or a.o.exists() or a.json.exists():
        p.error('Inputs and outputs must be distinct; outputs must not exist')
    c, ch = load(a.consensus)
    r, rh = load(a.roost)
    for data, schema in ((c,'hehawk.chirp.consensus'),(r,'hehawk.roost')):
        if data.get('schema') != schema or data.get('schema_version') != 1 or data.get('timestamp_basis') != 'episode':
            raise ValueError('Unsupported schema or timestamp basis: '+schema)
    windows = {w['id']:w for w in r['windows']}
    words = {k:{} for k in windows}
    for col in r['columns']:
        for witness in col['witnesses']:
            obs = witness['observation']
            if obs is None:
                continue
            for w in obs['words']:
                if any(x.isalnum() for x in w['text']):
                    words[witness['window_id']][(w['token_start'],w['token_end_exclusive'])] = w
    results = []
    for i, candidate in enumerate(c['proposed_transitions'],1):
        t = candidate['primary']['time_seconds']
        evidence = []
        for wid,w in windows.items():
            if w['start_seconds'] <= t-a.radius and w['end_seconds'] >= t+a.radius:
                e = assess(t,list(words[wid].values()),a.radius)
                e['nearest_gap'] = nearest_gap(t,list(words[wid].values()),a.max_gap)
                evidence.append(dict(window_id=wid,**e))
        counts = Counter(e['state'] for e in evidence)
        if not evidence:
            label = 'INSUFFICIENT_COVERAGE'
        elif len(counts)>1:
            label = 'LEXICAL_UNCERTAINTY'
        elif len(evidence)==1:
            label = 'SINGLE_WINDOW_'+next(iter(counts))
        else:
            label = next(iter(counts))
        bounds = [e['boundary_seconds'] for e in evidence if e['boundary_seconds'] is not None]
        results.append(dict(id=i,time_seconds=t,classification=label,coverage=len(evidence),
                            state_counts=dict(counts),suggested_boundary_seconds=median(bounds) if bounds and label=='BETWEEN_WORDS' else None,
                            acoustic_candidate=candidate,witnesses=evidence,
                            boundary_proximity=proximity(evidence,a.max_displacement,a.max_spread)))
    totals = Counter(x['classification'] for x in results)
    proximity_totals = Counter(x['boundary_proximity']['classification'] for x in results)
    lines = ['FLOCK V2 — acoustic/lexical correlation',f'Radius: {a.radius:.3f}s',f'Proposals: {len(results)}','']
    for x in results:
        t=x['time_seconds']; m,s=divmod(t,60); h,m=divmod(int(m),60)
        lines.append(f"{h:02d}:{m:02d}:{s:06.3f}  {x['classification']}  coverage={x['coverage']}  {x['state_counts']}")
        q = x['boundary_proximity']
        b = q['proposed_boundary_seconds']
        delta = f'  shift={b-t:+.3f}s' if b is not None else ''
        lines.append(f"    {q['classification']}  support={q['support']}/{q['coverage']}{delta}")
    lines += ['', 'BOUNDARY SUMMARY']+[f'{k}: {v}' for k,v in sorted(proximity_totals.items())]
    lines += ['', 'SUMMARY']+[f'{k}: {v}' for k,v in sorted(totals.items())]
    out=dict(schema='hehawk.flock',schema_version=2,timestamp_basis='episode',consensus_sha256=ch,roost_sha256=rh,settings=dict(radius_seconds=a.radius,max_displacement_seconds=a.max_displacement,max_gap_seconds=a.max_gap,max_spread_seconds=a.max_spread),summary=dict(totals),boundary_summary=dict(proximity_totals),proposals=results)
    with a.json.open('x') as f:
        json.dump(out,f,indent=2,ensure_ascii=False,allow_nan=False)
    with a.o.open('x') as f:
        f.write('\n'.join(lines)+'\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
