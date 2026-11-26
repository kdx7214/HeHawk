"""Read-only Experiment 4A: correlate cached speaker scores with speech evidence."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from collections import defaultdict
import numpy as np
import soundfile as sf


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coverage(intervals, start, end):
    """Union of clipped intervals; overlapping speakers count only once."""
    total = 0.0
    cursor = start
    for a, b in sorted(intervals):
        a, b = max(a, start), min(b, end)
        if b > max(a, cursor):
            total += b - max(a, cursor)
            cursor = b
    return min(1.0, total / (end - start))


def main():
    from chirp_diarization_correlate import words_from, diarization_segments
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('scan', 'manifest', 'diarization', 'recognition', 'output'):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    scan, manifest, diar, rec = [json.loads(x.read_text()) for x in (a.scan,a.manifest,a.diarization,a.recognition)]
    if (scan['schema'],scan['schema_version']) != ('hehawk.bowerbird.scan',1):
        raise ValueError('Unsupported scan schema')
    if scan['manifest_sha256'] != digest(a.manifest):
        raise ValueError('Manifest hash mismatch')
    if diar['source_offset_seconds'] != 0:
        raise ValueError('Expected full episode diarization')
    segments = diarization_segments(diar,'regular')
    words = words_from(rec)
    speech = [(s['start_seconds'],s['end_seconds']) for s in segments]
    lexical = [(w['start_seconds'],w['end_seconds']) for w in words]
    truth = {3:['Merle','Gunn'],7:['Wesley','Angel'],8:['Cordelia'],11:['Fred']}
    targets = {s['candidate']:s for s in manifest['samples']}
    root = a.manifest.parent.resolve()
    rows = []
    groups = defaultdict(list)
    for result in scan['results']:
        s = result['target']; cid = s['candidate']
        if s != targets[cid] or s['audio_source_sha256'] != diar['source_sha256']:
            raise ValueError('Target or source hash mismatch')
        if (s['series'],s['episode']) != ('Angel','S03E01') or cid not in truth:
            raise ValueError('Ground truth is specific to Experiment 4A')
        path = (root/s['sample_path']).resolve()
        if not path.is_relative_to(root) or digest(path) != s['audio_sha256']:
            raise ValueError('Sample hash mismatch')
        audio, rate = sf.read(path,dtype='float64',always_2d=True)
        if rate != 16000 or audio.shape[1] != 1:
            raise ValueError('Expected mono 16 kHz')
        print(f'\nCandidate {cid}: expected {", ".join(truth[cid])}')
        for w in result['windows']:
            start,end = w['episode_start_seconds'],w['episode_end_seconds']
            lo,hi = [round(w[k]*rate) for k in ('relative_start_seconds','relative_end_seconds')]
            if not 0 <= lo < hi <= len(audio) or not 0 <= start < end <= diar['duration_seconds']:
                raise ValueError('Window outside audio')
            x = audio[lo:hi,0]
            rms = float(np.sqrt(np.mean(x*x))); peak = float(np.max(np.abs(x)))
            sc = coverage(speech,start,end); wc = coverage(lexical,start,end)
            best = w.get('best')
            expected = best[0] in truth[cid] if best else None
            row = dict(w,candidate=cid,expected_speakers=truth[cid],expected_match=expected,
                       speech_coverage=sc,speech_seconds=sc*(end-start),word_coverage=wc,
                       rms_dbfs=20*math.log10(rms) if rms else None,
                       peak_dbfs=20*math.log10(peak) if peak else None,
                       crest_factor=peak/rms if rms else None)
            rows.append(row)
            if best:
                groups[(w['duration_seconds'],expected)].append(row)
                if not expected:
                    print(f"  {w['duration_seconds']:3.1f}s {lo/rate:5.2f}-{hi/rate:5.2f}: {best[0]} {best[1]:.3f}; speech={sc:5.1%} words={wc:5.1%}; crest={row['crest_factor']}")
    print('\nCoverage summary (expected identity set, not exact turn accuracy)')
    for (duration,expected), rr in sorted(groups.items()):
        print(f'{duration:3.1f}s expected={expected}: n={len(rr)} mean speech={np.mean([r["speech_coverage"] for r in rr]):.1%} mean words={np.mean([r["word_coverage"] for r in rr]):.1%}')
    print('\nSpeech coverage bins: expected / all successful windows')
    for duration in sorted({r['duration_seconds'] for r in rows}):
        for low,high in [(0,.25),(.25,.5),(.5,.75),(.75,1.000001)]:
            rr=[r for r in rows if r['duration_seconds']==duration and r['expected_match'] is not None and low<=r['speech_coverage']<high]
            print(f'{duration:3.1f}s {low:.0%}-{min(high,1):.0%}: {sum(r["expected_match"] for r in rr)}/{len(rr)}')
    with a.output.open('x') as f:
        json.dump(dict(schema='hehawk.bowerbird.coverage',schema_version=1,ground_truth=truth,ground_truth_note='Candidate 8 corrected to Cordelia only; original collection unchanged',speech_basis='union of regular diarization intervals; not independent VAD',recognition_identity_verified=False,inputs={k:digest(getattr(a,k)) for k in ('scan','manifest','diarization','recognition')},windows=rows),f,indent=2,allow_nan=False)
    print(f'Saved {len(rows)} windows: {a.output}')


if __name__ == '__main__':
    main()
