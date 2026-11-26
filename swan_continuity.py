#!/usr/bin/env python3
"""SWAN Experiment 1B: read-only, dialogue-free continuity diagnostics."""
import argparse
from collections import defaultdict
from pathlib import Path


def classify(a, b):
    """Compare normalized nonempty lines; findings may coexist."""
    x, y = ' '.join(a).split(), ' '.join(b).split()
    if not x or not y:
        return []
    if x == y:
        return ['identical']
    kinds = []
    if len(x) < len(y) and y[:len(x)] == x:
        kinds.append('progressive_addition')
    if len(y) < len(x) and x[:len(y)] == y:
        kinds.append('progressive_removal')
    if set(a) & set(b):
        kinds.append('shared_lines')
    if any(a[-k:] == b[:k] for k in range(1, min(len(a), len(b)))):
        kinds.append('rollup_candidate')
    return kinds


def analyze(cues, gap=24, duration=600, cps=20.0, continuity_gap=100):
    from gulp import clean_srt
    ordered = sorted(cues, key=lambda c: c['start_ms'])
    lines = []
    for c in ordered:
        plain, _ = clean_srt(c['display_text'])
        lines.append([s for line in plain.split('\n') if (s := ' '.join(line.split()))])
    findings = defaultdict(list)
    for i, (a, b) in enumerate(zip(ordered, ordered[1:])):
        delta = b['start_ms'] - a['end_ms']
        if delta <= continuity_gap:
            for kind in classify(lines[i], lines[i+1]):
                findings[kind].append((a['id'], b['id'], delta))
    # Prefix maximum end includes nested/nonadjacent earlier cues.
    frontier = None
    for i, c in enumerate(ordered):
        start, end = c['start_ms'], c['end_ms']
        length = end - start
        chars = len(' '.join(lines[i]))
        if length <= 0:
            raise ValueError('Invalid interval')
        if length < duration or chars * 1000 / length > cps:
            before = None if frontier is None else start - frontier
            after = None if i+1 == len(ordered) else ordered[i+1]['start_ms'] - end
            left = max(0, before-gap) if before is not None else 0
            right = max(0, after-gap) if after is not None else 0
            import math
            required = max(duration, math.ceil(chars * 1000 / cps))
            findings['timing_slack'].append((c['id'], length, chars, required,
                before, after, left, right, max(0, required-length-left-right)))
        frontier = end if frontier is None else max(frontier, end)
    return dict(findings)


def main():
    from gulp import ingest
    import math
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path)
    p.add_argument('--gap', type=int, default=24)
    p.add_argument('--duration', type=int, default=600)
    p.add_argument('--cps', type=float, default=20.0)
    p.add_argument('--continuity-gap', type=int, default=100)
    args = p.parse_args()
    if min(args.gap, args.duration, args.continuity_gap) < 0 or not math.isfinite(args.cps) or args.cps <= 0:
        p.error('Invalid thresholds')
    try:
        data = ingest(args.input)
        result = analyze(data['cues'], args.gap, args.duration, args.cps, args.continuity_gap)
    except (OSError, ValueError, KeyError, IndexError) as exc:
        p.exit(1, f'SWAN continuity: {type(exc).__name__}: unable to analyze input\n')
    print(f"SWAN Experiment 1B | {data['format']} | {len(data['cues'])} cues")
    print(f'Gap={args.gap} ms; duration={args.duration} ms; CPS={args.cps}; continuity gap={args.continuity_gap} ms')
    for kind in ('identical', 'progressive_addition', 'progressive_removal', 'shared_lines', 'rollup_candidate', 'timing_slack'):
        rows = result.get(kind, [])
        print(f'\n{kind}: {len(rows)}')
        print('cue duration chars required gap_before gap_after slack_before slack_after remaining_deficit' if kind == 'timing_slack' else 'previous next gap_ms')
        for row in rows:
            print(' '.join('NA' if v is None else str(v) for v in row))


if __name__ == '__main__':
    main()
