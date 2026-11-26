"""HUNT 5A: inventory every uncovered word gap with VAD evidence."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def load(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def gaps(intervals, duration):
    cursor = 0.0
    for a, b in sorted(intervals):
        a, b = max(0, a), min(duration, b)
        if b <= a:
            continue
        if a > cursor:
            yield cursor, a
        cursor = max(cursor, b)
    if cursor < duration:
        yield cursor, duration


def measure(a, b, probs, step):
    total = 0.0
    peak = 0.0
    stats = {str(t): dict(seconds=0.0, longest=0.0) for t in (.3,.5,.7)}
    runs = dict.fromkeys(stats, 0.0)
    for i in range(max(0, int(a/step)), min(len(probs), math.ceil(b/step))):
        width = min(b,(i+1)*step)-max(a,i*step)
        if width <= 0:
            continue
        p = probs[i]
        total += p*width
        peak = max(peak,p)
        for key, s in stats.items():
            if p >= float(key):
                s['seconds'] += width
                runs[key] += width
                s['longest'] = max(s['longest'],runs[key])
            else:
                runs[key] = 0.0
    return dict(mean_probability=total/(b-a), peak_probability=peak, thresholds=stats)


def main():
    from magpie import recognition_words
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vad',type=Path)
    parser.add_argument('recognition',type=Path)
    parser.add_argument('--json',required=True,type=Path)
    args = parser.parse_args()
    if args.json.exists():
        parser.error('Output already exists')
    v, vh = load(args.vad)
    r, rh = load(args.recognition)
    if v['schema'] != 'hehawk.lark.probabilities' or v['version'] != 1 or v['timestamp_basis'] != 'episode' or v['source_offset_seconds'] != 0:
        parser.error('Expected full episode LARK v1 evidence')
    rate, frame, samples = (v[k] for k in ('sample_rate','frame_samples','source_samples'))
    if rate != 16000 or frame != 512 or samples <= 0:
        parser.error('Invalid frame geometry')
    probs = v['probabilities']
    if len(probs) != (samples+frame-1)//frame or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs):
        parser.error('Invalid probability stream')
    duration = samples/rate
    words = recognition_words(r)
    if any(w['end'] > duration + .32 or w['start'] > duration or w['end'] < w['start'] for w in words):
        parser.error('Recognition timing outside audio; check source')
    rows = []
    for a,b in gaps([(w['start'],w['end']) for w in words],duration):
        if b-a < 1e-9:  # floating point boundary noise only
            continue
        rows.append(dict(id=len(rows)+1,start=a,end=b,duration=b-a,**measure(a,b,probs,frame/rate)))
    ranked = sorted(rows,key=lambda x:x['thresholds']['0.5']['longest'],reverse=True)
    result = dict(schema='hehawk.hunt.inventory',version=1,timestamp_basis='episode',vad_sha256=vh,recognition_sha256=rh,source_sha256=v['source_sha256'],source_match_verified=False,settings=dict(thresholds=[.3,.5,.7],word_padding=0,ranking='longest_continuous_at_0.5'),duration_seconds=duration,word_count=len(words),gaps=rows,ranked_ids=[x['id'] for x in ranked])
    with args.json.open('x') as f:
        json.dump(result,f,allow_nan=False,indent=2)
        f.write('\n')
    print(f'Words: {len(words)}; uncovered gaps: {len(rows)}')
    print('Source identity assumed: recognition JSON has no verified audio hash in this experiment.')
    for t in (.3,.5,.7):
        print(f'Threshold {t}:')
        for minimum in (.1,.25,.5,1,2):
            print(f'  continuous >= {minimum}s: {sum(x["thresholds"][str(t)]["longest"] >= minimum-1e-9 for x in rows)}')
    print('Top 25 by longest continuous VAD >= 0.5:')
    for x in ranked[:25]:
        s=x['thresholds']['0.5']
        print(f'{x["id"]:5} {x["start"]:9.3f}-{x["end"]:9.3f} gap={x["duration"]:.3f}s speech={s["seconds"]:.3f}s longest={s["longest"]:.3f}s mean={x["mean_probability"]:.3f}')
    print('Positive control near 99s:')
    for x in rows:
        if x['start'] <= 99 < x['end']:
            print(f'ID {x["id"]}: {x["start"]:.3f}-{x["end"]:.3f}, longest={x["thresholds"]["0.5"]["longest"]:.3f}s, rank={result["ranked_ids"].index(x["id"])+1}')
    print(f'Saved: {args.json}')


if __name__ == '__main__':
    main()
