"""Experiment 4C: correlate cached BOWERBIRD windows with LARK scores."""
import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean

THRESHOLDS = (0.3, 0.5, 0.7)


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def measure(probs, step, samples, rate, start, end):
    # Clip each frame to the actual window and unpadded audio extent.
    a, b = round(start * rate), round(end * rate)
    if not 0 <= a < b <= samples:
        raise ValueError('Window outside source audio')
    weighted = 0.0
    totals = dict.fromkeys(THRESHOLDS, 0)
    runs = dict.fromkeys(THRESHOLDS, 0)
    longest = dict.fromkeys(THRESHOLDS, 0)
    for i in range(a // step, (b - 1) // step + 1):
        n = min(b, (i + 1) * step, samples) - max(a, i * step)
        p = probs[i]
        weighted += n * p
        for t in THRESHOLDS:
            if p >= t:
                totals[t] += n
                runs[t] += n
                longest[t] = max(longest[t], runs[t])
            else:
                runs[t] = 0
    return dict(mean_probability=weighted / (b-a), thresholds={str(t): dict(coverage=totals[t]/(b-a), speech_seconds=totals[t]/rate, longest_run_seconds=longest[t]/rate) for t in THRESHOLDS})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('coverage', 'manifest', 'vad', 'output'):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    if a.output.exists():
        p.error('Output already exists')
    paths = {k:getattr(a,k) for k in ('coverage','manifest','vad')}
    hashes = {k:digest(v) for k,v in paths.items()}
    c,m,v = [json.loads(paths[k].read_text()) for k in paths]
    if (c['schema'],c['schema_version']) != ('hehawk.bowerbird.coverage',1) or (v['schema'],v['version']) != ('hehawk.lark.probabilities',1):
        raise ValueError('Unsupported schema')
    if c['inputs']['manifest'] != hashes['manifest']:
        raise ValueError('Manifest hash mismatch')
    if v['timestamp_basis'] != 'episode' or v['source_offset_seconds'] != 0:
        raise ValueError('Expected full episode VAD')
    rate,step,samples = (v[k] for k in ('sample_rate','frame_samples','source_samples'))
    probs = v['probabilities']
    if rate != 16000 or step != 512 or samples <= 0 or len(probs) != (samples+step-1)//step or not all(math.isfinite(x) and 0<=x<=1 for x in probs):
        raise ValueError('Invalid VAD timeline')
    targets = {s['candidate']:s for s in m['samples']}
    rows=[]; groups=defaultdict(list)
    for w in c['windows']:
        target=targets[w['candidate']]
        if target['audio_source_sha256'] != v['source_sha256']:
            raise ValueError('Audio source hash mismatch')
        start,end=w['episode_start_seconds'],w['episode_end_seconds']
        result=measure(probs,step,samples,rate,start,end)
        r=dict(w,lark=result); rows.append(r)
        if w['expected_match'] is not None:
            groups[(w['duration_seconds'],w['expected_match'])].append(r)
        if w['expected_match'] is False or (w['candidate']==8 and 3<=w['relative_start_seconds']<=4.75):
            cov=result['thresholds']['0.5']
            print(f"C{w['candidate']:02} {w['duration_seconds']:.1f}s {w['relative_start_seconds']:.2f}-{w['relative_end_seconds']:.2f} {w['best'][0]} expected={w['expected_match']} VAD={cov['coverage']:.1%} mean={result['mean_probability']:.3f} longest={cov['longest_run_seconds']:.3f}s words={w['word_coverage']:.1%}")
    print('\nSummary: expected identity set, not exact turn accuracy')
    for (d,e),rr in sorted(groups.items()):
        covs=' '.join(f'{t}: {mean(r["lark"]["thresholds"][str(t)]["coverage"] for r in rr):.1%}' for t in THRESHOLDS)
        print(f'{d:.1f}s expected={e} n={len(rr)} {covs} mean_p={mean(r["lark"]["mean_probability"] for r in rr):.3f} longest@0.5={mean(r["lark"]["thresholds"]["0.5"]["longest_run_seconds"] for r in rr):.3f}s')
    print('\nCoverage bins at threshold 0.5: expected / all')
    for d in sorted({k[0] for k in groups}):
        for lo,hi in ((0,.25),(.25,.5),(.5,.75),(.75,1.000001)):
            rr=[r for r in rows if r['duration_seconds']==d and r['expected_match'] is not None and lo<=r['lark']['thresholds']['0.5']['coverage']<hi]
            print(f'{d:.1f}s {lo:.0%}-{min(hi,1):.0%}: {sum(r["expected_match"] for r in rr)}/{len(rr)}')
    if any(digest(paths[k])!=h for k,h in hashes.items()):
        raise ValueError('Input changed during analysis')
    with a.output.open('x') as f:
        json.dump(dict(schema='hehawk.bowerbird.lark',schema_version=1,inputs=hashes,thresholds=THRESHOLDS,ground_truth=c['ground_truth'],windows=rows),f,indent=2,allow_nan=False)
    print(f'Saved {len(rows)} windows: {a.output}')


if __name__=='__main__':
    main()
