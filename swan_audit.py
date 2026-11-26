#!/usr/bin/env python3
"""Independent, read-only audit of SWAN timing-only SRT output."""
import argparse
import re
from pathlib import Path
from dataclasses import dataclass

@dataclass(frozen=True)
class Cue:
    start: int
    end: int


def timestamp(value):
    h, m, s, ms = map(int, re.split(rb'[:,]', value))
    if m >= 60 or s >= 60:
        raise ValueError('Invalid timestamp')
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def parse(raw):
    # Split into conventional numbered SRT blocks, preserving original bytes.
    cues, spans = [], []
    offset = 0
    for block in re.split(rb'(\r?\n[ \t]*\r?\n(?:[ \t]*\r?\n)*)', raw):
        if block.strip():
            lines = block.splitlines(keepends=True)
            if len(lines) < 3 or not lines[0].removeprefix(b'\xef\xbb\xbf').strip().isdigit():
                raise ValueError('Unsupported or malformed numbered SRT block')
            match = re.fullmatch(rb'[ \t]*(\d{2,}:\d{2}:\d{2},\d{3})[ \t]+-->[ \t]+(\d{2,}:\d{2}:\d{2},\d{3})[^\r\n]*(?:\r?\n)?', lines[1])
            if not match:
                raise ValueError('Malformed timing line')
            start, end = map(timestamp, match.groups())
            if end <= start:
                raise ValueError('Nonpositive cue duration')
            cues.append(Cue(start, end))
            base = offset + len(lines[0])
            spans.append((base + match.start(2), base + match.end(2)))
        offset += len(block)
    if not cues:
        raise ValueError('No cues found')
    parts, pos = [], 0
    for a, b in spans:
        parts.extend((raw[pos:a], b'<END>'))
        pos = b
    parts.append(raw[pos:])
    return cues, b''.join(parts)


def overlaps(cues):
    # Independent pairwise check; cue identities are file positions.
    return {(i+1,j+1): min(a.end,b.end)-max(a.start,b.start)
            for i,a in enumerate(cues) for j,b in enumerate(cues[i+1:],i+1)
            if min(a.end,b.end)>max(a.start,b.start)}


def audit(original, output, gap=24, max_reduction=50, duration=600):
    if min(gap,max_reduction) < 0 or duration <= 0:
        raise ValueError('Invalid policy')
    old, old_mask = parse(original)
    new, new_mask = parse(output)
    errors = []
    if len(old)!=len(new):
        return ['Cue count changed'], {}
    if old_mask != new_mask:
        errors.append('Bytes outside ending timestamps changed')
    order = sorted(range(len(old)), key=lambda i: old[i].start)
    caps = {i: old[j].start-gap for i,j in zip(order,order[1:])}
    deltas = [b.end-a.end for a,b in zip(old,new)]
    for i,(a,b,d) in enumerate(zip(old,new,deltas)):
        if d < -max_reduction:
            errors.append(f'Cue {i+1}: excessive shortening')
        if d < 0 and b.end-b.start < duration:
            errors.append(f'Cue {i+1}: shortened below minimum duration')
        if d > 0 and (i not in caps or b.end > caps[i]):
            errors.append(f'Cue {i+1}: extension exceeds next-cue boundary or unknown media end')
    before, after = overlaps(old), overlaps(new)
    for pair, amount in after.items():
        if amount > before.get(pair,0):
            errors.append(f'Cues {pair}: new or worsened overlap')
    stats = dict(cues=len(old), extended=sum(d>0 for d in deltas), shortened=sum(d<0 for d in deltas), untouched=sum(d==0 for d in deltas), largest_extension_ms=max([0]+deltas), largest_reduction_ms=-min([0]+deltas), overlaps_before=len(before), overlaps_after=len(after))
    return errors, stats


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('original',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--gap',type=int,default=24)
    p.add_argument('--max-reduction',type=int,default=50)
    p.add_argument('--duration',type=int,default=600)
    a=p.parse_args()
    try:
        errors, stats=audit(a.original.read_bytes(),a.output.read_bytes(),a.gap,a.max_reduction,a.duration)
    except (OSError,ValueError) as e:
        errors,stats=[str(e)],{}
    for k,v in stats.items(): print(f'{k}: {v}')
    for e in errors: print('ERROR:',e)
    print('FAIL' if errors else 'PASS')
    return int(bool(errors))

if __name__=='__main__':
    raise SystemExit(main())
