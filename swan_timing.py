#!/usr/bin/env python3
"""SWAN 2C: start-preserving timing planner with opt-in SRT output."""
import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path
from swan import analyze, Limits

@dataclass(frozen=True)
class Policy:
    gap: int = 24
    duration: int = 600
    cps: float = 20.0
    max_reduction: int = 50


def plan(cues, policy=Policy()):
    from gulp import clean_srt
    if any(not math.isfinite(v) or v < 0 for v in vars(policy).values()) or policy.cps <= 0 or policy.duration <= 0:
        raise ValueError('Invalid policy')
    limits = Limits(gap=policy.gap, duration=policy.duration, cps=policy.cps)
    before = analyze(cues, limits)
    ordered = sorted(cues, key=lambda c: c['start_ms'])
    by_id = {c['id']: c for c in ordered}
    if len(by_id) != len(cues):
        raise ValueError('Duplicate cue IDs')
    protected = set()
    for group in before['groups']:
        if len(group) != 2:
            protected.update(group)
            continue
        a, b = (by_id[i] for i in group)
        cap = b['start_ms'] - policy.gap
        if (a['start_ms'] >= b['start_ms'] or a['end_ms'] >= b['end_ms']
                or a['end_ms'] - cap > policy.max_reduction
                or cap - a['start_ms'] < policy.duration):
            protected.update(group)
    changes, review = [], []
    proposed = []
    for i, c in enumerate(ordered):
        start, end = c['start_ms'], c['end_ms']
        ident = c['id']
        plain, _ = clean_srt(c['display_text'])
        chars = len(' '.join(plain.split()))
        required = max(policy.duration, math.ceil(chars * 1000 / policy.cps))
        cap = ordered[i+1]['start_ms'] - policy.gap if i+1 < len(ordered) else None
        new = end
        reasons = []
        if ident in protected:
            reasons.append('protected_conflict')
        elif cap is not None and end > cap:
            # Permit small overlap repairs; otherwise protect reading duration.
            if end-cap <= policy.max_reduction and cap-start >= (policy.duration if end > ordered[i+1]['start_ms'] else required):
                new = cap
            else:
                reasons.append('unsafe_reduction')
        elif end-start < required:
            if cap is None:
                reasons.append('unknown_media_end')
            else:
                new = max(end, min(start+required, cap))
        if new-start < required:
            reasons.append('reading_deficit')
        if new != end:
            changes.append((ident, start, end, new, end-start, new-start, round(chars*1000/(end-start),2), round(chars*1000/(new-start),2)))
        if reasons:
            review.append((ident, ','.join(reasons), max(0, required-(new-start))))
        proposed.append(dict(c, end_ms=new))
    # Restore original file order for independent diagnostics.
    lookup = {c['id']: c for c in proposed}
    proposed = [lookup[c['id']] for c in cues]
    after = analyze(proposed, limits)
    return dict(before=before, after=after, changes=changes, review=review, proposed=proposed)



def write_srt(source, destination, original, proposed):
    """Patch end timestamps only; preserve all other source bytes."""
    from gulp import srt_time
    if destination.suffix.lower() != '.srt':
        raise ValueError('Output must have .srt extension')
    raw = source.read_bytes()
    # Match only numbered cue headers at the beginning of a block.
    pattern = re.compile(rb'(?m)(?:\A(?:\xef\xbb\xbf)?|(?<=\n)\r?\n)([ \t]*\d+[ \t]*\r?\n[ \t]*)(\d{2,}:\d{2}:\d{2},\d{3})([ \t]+-->[ \t]+)(\d{2,}:\d{2}:\d{2},\d{3})(?=[ \t\r\n]|$)')
    matches = list(pattern.finditer(raw))
    if len(matches) != len(original) or len(original) != len(proposed):
        raise ValueError('Cue count mismatch in raw SRT; no output written')
    def ms(t):
        h,m,s = t.decode('ascii').split(':')
        sec,milli = s.split(',')
        return ((int(h)*60+int(m))*60+int(sec))*1000+int(milli)
    edits = []
    for match, old, new in zip(matches, original, proposed):
        if (ms(match[2]), ms(match[4])) != (old['start_ms'], old['end_ms']):
            raise ValueError('Raw timing mismatch; no output written')
        if any(old[k] != new[k] for k in old if k != 'end_ms'):
            raise ValueError('Non-end-time change; no output written')
        if old['end_ms'] != new['end_ms']:
            edits.append((match.start(4), match.end(4), srt_time(new['end_ms']).encode('ascii')))
    for a,b,value in reversed(edits):
        raw = raw[:a] + value + raw[b:]
    with destination.open('xb') as f:
        f.write(raw)


def main():
    from gulp import ingest
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path)
    for k,v in vars(Policy()).items():
        p.add_argument('--'+k.replace('_','-'), type=type(v), default=v)
    p.add_argument("--output", type=Path, help="Write a new SRT; never overwrite")
    args = p.parse_args()
    policy = Policy(**{k:getattr(args,k) for k in vars(Policy())})
    try:
        data = ingest(args.input)
        result = plan(data['cues'], policy)
    except (OSError, ValueError, KeyError, IndexError) as exc:
        p.exit(1, f'SWAN timing: {type(exc).__name__}: unable to plan\n')
    print(f"SWAN Experiment 2C | {data['format']} | {len(data['cues'])} cues | {'DRY RUN' if not args.output else 'OUTPUT REQUESTED'}")
    print(policy)
    print('Metric before after')
    for key in ('pairs','groups','peak','overlap_ms','pairwise_ms','longest_ms'):
        vals = [result[x][key] for x in ('before','after')]
        print(key, *(len(v) if isinstance(v,list) else v for v in vals))
    for key in ('insufficient_gap','short_duration','reading_speed','out_of_order'):
        print(key, *(len(result[x]['issues'].get(key,[])) for x in ('before','after')))
    changes = result['changes']
    print('Changed cues:',len(changes))
    print('Maximum absolute adjustment:',max((abs(c[3]-c[2]) for c in changes),default=0),'ms')
    print('cue start old_end new_end old_duration new_duration old_cps new_cps')
    for row in changes: print(*row)
    print('REVIEW: cue reasons remaining_deficit_ms')
    for row in result['review']: print(*row)
    if args.output:
        try:
            if data['format'] != 'srt':
                raise ValueError('Output currently requires SRT input')
            write_srt(args.input, args.output, data['cues'], result['proposed'])
        except (OSError, ValueError) as exc:
            p.exit(1, f'SWAN output refused: {exc}\n')
        print('Written:', args.output)
    else:
        print('No files written.')

if __name__ == '__main__': main()
