#!/usr/bin/env python3
"""Read-only full-episode cue screening using existing CHIRP evidence."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from chirp_cue_scan import scan


def screen(cues, segments, words, start, end):
    rows = scan(cues, segments, words, [], start, end)
    for row in rows:
        row.pop('acoustic', None)
        for change in row['changes']:
            change.pop('acoustic', None)
        for word in row['words']:
            word.pop('word', None)
        row['uncovered_word_count'] = sum(w['coverage_fraction'] == 0 for w in row['words'])
        row['partially_covered_word_count'] = sum(0 < w['coverage_fraction'] < .999 for w in row['words'])
    return rows


def summarize(rows):
    return dict(speaker_counts=dict(sorted(Counter(r['distinct_speakers'] for r in rows).items())),
                flags=dict(sorted(Counter(f for r in rows for f in r['flags']).items())),
                sequential_three_or_more=sum((r['sequential_turn_count'] or 0) >= 3 for r in rows),
                overlap_seconds_cue_sum=round(sum(r['overlap_seconds'] for r in rows), 6))


def main():
    from gulp import ingest
    from chirp_diarization_correlate import words_from, diarization_segments
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('subtitles', 'diarization', 'recognition'):
        p.add_argument(name, type=Path)
    p.add_argument('--json', required=True, type=Path)
    a = p.parse_args()
    try:
        paths = [a.subtitles, a.diarization, a.recognition]
        raw = [x.read_bytes() for x in paths]
        d, r = map(json.loads, raw[1:])
        start = float(d['source_offset_seconds'])
        end = start + float(d['duration_seconds'])
        if start != 0 or not math.isfinite(end) or end <= 0:
            raise ValueError('Expected full-episode diarization with zero offset')
        cues = ingest(a.subtitles)['cues']
        if a.subtitles.read_bytes() != raw[0]:
            raise ValueError('Subtitle source changed during ingestion')
        words = words_from(r)
        segments = diarization_segments(d, 'regular')
        rows = screen(cues, segments, words, start, end)
        summary = summarize(rows)
        report = dict(schema='hehawk.chirp.full_scan', schema_version=1,
                      timestamp_basis='episode', mode='regular', acoustic_analysis=False,
                      sources=[dict(path=str(x), sha256=hashlib.sha256(y).hexdigest()) for x,y in zip(paths,raw)],
                      audio_window=[start,end], total_cues=len(cues), scanned_cues=len(rows),
                      outside_audio_cue_ids=sorted(set(c['id'] for c in cues)-set(r['cue_id'] for r in rows)),
                      summary=summary, cues=rows)
        payload = json.dumps(report, indent=2, allow_nan=False)+'\n'
        with a.json.open('x', encoding='utf-8') as f:
            f.write(payload)
    except (OSError, ValueError, KeyError, TypeError) as e:
        p.error(str(e))
    print('CHIRP FULL-EPISODE SCREENING — evidence only')
    print(f'Scanned {len(rows)} of {len(cues)} cues')
    for key, value in summary.items():
        print(f'{key}: {value}')
    print('\nMultiple-speaker review candidates:')
    for row in rows:
        if row['distinct_speakers'] > 1:
            print(f"Cue {row['cue_id']:4} {row['start']:9.3f}–{row['end']:9.3f} speakers={row['distinct_speakers']} turns={row['sequential_turn_count']} overlap={row['overlap_seconds']:.3f}")
    print(f'Output: {a.json}')

if __name__ == '__main__':
    main()
