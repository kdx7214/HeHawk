"""Correlate CHIRP consensus peaks with Parakeet word timing; no classification."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from word_timing import word_groups


def load(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def words_from(d):
    if d.get('source_offset_seconds', 0) != 0:
        raise ValueError('Expected full-episode recognition with zero offset')
    tokens = d['tokens']
    words = []
    for raw, a, b, start, end in word_groups(tokens, d['timestamps'], d['durations'], 0, len(tokens)):
        if not any(c.isalnum() for c in raw):
            continue
        if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start <= end:
            raise ValueError('Invalid word timing')
        words.append(dict(token_start=a, token_end=b, start_seconds=round(start, 6), end_seconds=round(end, 6), sentence_end=raw.rstrip('\"\'”’)]} ').endswith(('.', '?', '!'))))
    return sorted(words, key=lambda w: (w['start_seconds'], w['end_seconds']))


def gaps_from(words):
    gaps = []
    if not words:
        return gaps
    left = words[0]
    for right in words[1:]:
        if right['start_seconds'] >= left['end_seconds']:
            gaps.append(dict(start_seconds=left['end_seconds'], end_seconds=right['start_seconds'], duration_seconds=round(right['start_seconds']-left['end_seconds'], 6), left=left, right=right))
        if right['end_seconds'] >= left['end_seconds']:
            left = right
    return gaps


def correlate(t, words, gaps):
    inside = [w for w in words if w['start_seconds'] < t < w['end_seconds']]
    def distance(g):
        return round(max(g['start_seconds']-t, t-g['end_seconds'], 0), 6)
    nearest = min(gaps, key=lambda g: (distance(g), -g['duration_seconds'], g['start_seconds'])) if gaps else None
    at_edge = any(t in (w['start_seconds'], w['end_seconds']) for w in words)
    position = 'inside_word' if inside else 'word_edge' if at_edge else 'interword_gap' if nearest and distance(nearest)==0 else 'outside_recognized_span'
    result = dict(position=position, containing_words=inside, nearest_gap=nearest, distance_to_gap_seconds=distance(nearest) if nearest else None)
    if nearest:
        left = round(t - nearest['start_seconds'], 6)
        right = round(nearest['end_seconds'] - t, 6)
        duration = nearest['duration_seconds']
        result.update(seconds_from_left_word_end=left,
                      seconds_to_right_word_start=right,
                      distance_to_gap_edge_seconds=min(abs(left), abs(right)),
                      relative_gap_position=round(left / duration, 6) if duration > 0 and left >= 0 and right >= 0 else None,
                      within_left_word=nearest['left']['start_seconds'] <= t < nearest['left']['end_seconds'],
                      within_right_word=nearest['right']['start_seconds'] <= t < nearest['right']['end_seconds'])
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('consensus', type=Path)
    p.add_argument('recognition', type=Path)
    p.add_argument('--json', required=True, type=Path)
    a = p.parse_args()
    try:
        d, dh = load(a.consensus)
        r, rh = load(a.recognition)
        if (d.get('schema'), d.get('schema_version'), d.get('timestamp_basis')) != ('hehawk.chirp.consensus', 1, 'episode'):
            raise ValueError('Unsupported consensus schema')
        words = words_from(r)
        if not words:
            raise ValueError('No lexical words')
        gaps = gaps_from(words)
        rows = []
        for c in d['candidates']:
            t = c['primary']['time_seconds']
            if not math.isfinite(t):
                raise ValueError('Invalid acoustic timestamp')
            rows.append(dict(acoustic=c, lexical=correlate(t, words, gaps)))
        result = dict(schema='hehawk.chirp.correlation', schema_version=2, timestamp_basis='episode', sources=dict(consensus=dict(path=str(a.consensus), sha256=dh), recognition=dict(path=str(a.recognition), sha256=rh)), observations=rows)
        payload = json.dumps(result, indent=2, allow_nan=False)+'\n'
        with a.json.open('x') as f:
            f.write(payload)
    except (OSError, ValueError, KeyError, TypeError) as e:
        p.error(str(e))
    print('CHIRP CORRELATION V2 — evidence only')
    print('Episode     Contrast  Prominence  RMS dB  Position                 Gap ms  Distance ms  Left ms  Right ms  Edge ms  Sentence end')
    for row in rows:
        c, l = row['acoustic'], row['lexical']
        if c['status'] != 'PROPOSED':
            continue
        q, g = c['primary'], l['nearest_gap']
        gap = str(round(g['duration_seconds']*1000)) if g else '-'
        dist = str(round(l['distance_to_gap_seconds']*1000)) if g else '-'
        punct = str(g['left']['sentence_end']) if g else '-'
        left = str(round(l['seconds_from_left_word_end']*1000)) if g else '-'
        right = str(round(l['seconds_to_right_word_start']*1000)) if g else '-'
        edge = str(round(l['distance_to_gap_edge_seconds']*1000)) if g else '-'
        print(f"{q['time_seconds']:9.3f}  {q['contrast']:8.3f}  {q['prominence']:10.3f}  {q['rms_change_db']:+6.1f}  {l['position']:23s} {gap:>6s} {dist:>12s} {left:>8s} {right:>9s} {edge:>8s}  {punct}")
    print(f'All {len(rows)} primary candidates preserved; no speaker classification performed.')


if __name__ == '__main__':
    main()
