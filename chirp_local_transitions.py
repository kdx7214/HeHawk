import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from huggingface_hub import get_token
from pyannote.audio import Model, Inference

MODEL = 'pyannote/wespeaker-voxceleb-resnet34-LM'
SCALES = (0.75, 1.5, 3.0)
STRIDE = 0.25


def main():
    p = argparse.ArgumentParser()
    p.add_argument('audio', type=Path)
    p.add_argument('--source-offset', type=float, default=900)
    p.add_argument('--duration', type=float, default=60)
    p.add_argument('--threads', type=int, default=8)
    p.add_argument('--json', type=Path, required=True)
    args = p.parse_args()
    if args.json.exists():
        p.error('Output already exists')
    audio, rate = sf.read(args.audio, dtype='float32', always_2d=True)
    if audio.shape[1] != 1 or rate != 16000:
        p.error('Expected mono 16 kHz audio')
    limit = min(len(audio), round(args.duration * rate))
    if limit < 6 * rate or not np.isfinite(audio[:limit]).all():
        p.error('Need at least six seconds of finite audio')
    torch.set_num_threads(args.threads)
    model = Model.from_pretrained(MODEL, token=get_token())
    inference = Inference(model, window='whole', device=torch.device('cpu'))
    cache = {}
    started = time.monotonic()

    def embed(a, b):
        key = (a, b)
        if key not in cache:
            wave = audio[a:b, 0]
            rms = float(np.sqrt(np.mean(wave.astype(np.float64)**2)))
            if rms < 1e-6:
                cache[key] = (None, rms)
            else:
                v = np.asarray(inference({'waveform': torch.from_numpy(wave.copy()).unsqueeze(0), 'sample_rate': rate}), dtype=np.float64).reshape(-1)
                norm = np.linalg.norm(v)
                cache[key] = (v / norm if np.isfinite(v).all() and norm > 0 else None, rms)
        return cache[key]

    def similarity(a, b):
        return None if a is None or b is None else float(np.clip(a @ b, -1, 1))

    rows = []
    step = round(STRIDE * rate)
    for center in range(0, limit + 1, step):
        row = {'time_seconds': args.source_offset + center / rate, 'scales': {}}
        for scale in SCALES:
            n = round(scale * rate)
            if center - n < 0 or center + n > limit:
                continue
            left, lr = embed(center-n, center)
            right, rr = embed(center, center+n)
            # Internal comparisons use halves of each side. Short halves
            # are exploratory, not calibrated speaker evidence.
            la, _ = embed(center-n, center-n//2)
            lb, _ = embed(center-n//2, center)
            ra, _ = embed(center, center+n//2)
            rb, _ = embed(center+n//2, center+n)
            cross = similarity(left, right)
            ls, rs = similarity(la, lb), similarity(ra, rb)
            contrast = None if None in (cross, ls, rs) else (ls+rs)/2-cross
            row['scales'][str(scale)] = dict(cross_similarity=cross, left_internal=ls, right_internal=rs, contrast=contrast, left_rms=lr, right_rms=rr)
        if row['scales']:
            rows.append(row)
    result = dict(schema='hehawk.chirp.local_transitions', schema_version=1, timestamp_basis='episode', source=args.audio.name, source_sha256=hashlib.sha256(args.audio.read_bytes()).hexdigest(), model=MODEL, source_offset_seconds=args.source_offset, duration_seconds=limit/rate, settings=dict(scales_seconds=SCALES,stride_seconds=STRIDE,threads=args.threads), observations=rows)
    with args.json.open('x') as f:
        json.dump(result, f, indent=2, allow_nan=False)
    print(f'Boundaries examined: {len(rows)}; unique windows: {len(cache)}; elapsed: {time.monotonic()-started:.2f}s')
    print('Time (episode seconds) | cross similarity at 0.75 / 1.5 / 3.0 seconds')
    for row in rows:
        values = [row['scales'].get(str(s), {}).get('cross_similarity') for s in SCALES]
        print(f"{row['time_seconds']:9.2f} | " + '  '.join('   n/a' if v is None else f'{v:6.3f}' for v in values))
    print('\nLowest cross-similarity local minima (per scale; not classified transitions)')
    for scale in SCALES:
        points = [(r['time_seconds'], r['scales'].get(str(scale), {}).get('cross_similarity')) for r in rows]
        minima = [(t,v) for i,(t,v) in enumerate(points) if 0<i<len(points)-1 and v is not None and points[i-1][1] is not None and points[i+1][1] is not None and v<=points[i-1][1] and v<points[i+1][1]]
        print(f'\nScale {scale}s:')
        for t,v in sorted(minima,key=lambda x:x[1])[:12]:
            print(f'  {t:9.2f}  {v:7.3f}')


if __name__ == '__main__':
    main()
