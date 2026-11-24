#!/usr/bin/env python3
"""Controlled overlapping-window recognition experiment."""
import argparse
import json
import time
from pathlib import Path
import sherpa_onnx
import soundfile as sf

MODEL = Path('models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8')
RATE = 16000


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path)
    p.add_argument('--source-offset', type=float, default=540)
    p.add_argument('--starts', type=float, nargs='+', default=[20, 40, 60])
    p.add_argument('--window', type=float, default=60)
    args = p.parse_args()
    audio, rate = sf.read(args.input, dtype='float32')
    if rate != RATE or audio.ndim != 1:
        p.error('Input must be a mono 16 kHz WAV')
    if args.window <= 0 or len(args.starts) < 2 or len(set(args.starts)) != len(args.starts):
        p.error('Use a positive window and at least two distinct starts')
    ranges = [(round(s*RATE), round((s+args.window)*RATE)) for s in args.starts]
    if any(a < 0 or b > len(audio) or b <= a for a,b in ranges):
        p.error('A requested window falls outside the input audio')
    lo = max(a for a,b in ranges)/RATE + args.source_offset
    hi = min(b for a,b in ranges)/RATE + args.source_offset
    if lo >= hi:
        p.error('Windows must share a common region')
    paths = [args.input.with_name(f'{args.input.stem}_window_{i+1:02d}.json') for i in range(len(ranges))]
    report = args.input.with_name(f'{args.input.stem}_sliding_report.txt')
    if any(x.exists() for x in [*paths,report]):
        p.error('Output already exists; archive previous results before rerunning')
    print('Loading Parakeet model...')
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(MODEL/'encoder.int8.onnx'), decoder=str(MODEL/'decoder.int8.onnx'),
        joiner=str(MODEL/'joiner.int8.onnx'), tokens=str(MODEL/'tokens.txt'),
        num_threads=8, provider='cpu', model_type='nemo_transducer')
    lines = [f'COMMON REGION: {fmt(lo)} - {fmt(hi)}', 'All timestamps are episode-relative.', '']
    for i, ((a,b),path) in enumerate(zip(ranges,paths),1):
        offset = a/RATE + args.source_offset
        print(f'Window {i}: {fmt(offset)} - {fmt(b/RATE+args.source_offset)}', flush=True)
        t = time.perf_counter()
        stream = recognizer.create_stream()
        stream.accept_waveform(rate,audio[a:b])
        recognizer.decode_stream(stream)
        r = stream.result
        tokens = list(r.tokens)
        times = [float(x)+offset for x in r.timestamps]
        durations = [float(x) for x in r.durations]
        if not len(tokens)==len(times)==len(durations):
            raise RuntimeError('Mismatched token arrays')
        data = dict(text=r.text,tokens=tokens,timestamps=times,durations=durations,
                    source_offset_seconds=0.0,window_start_seconds=offset,
                    window_end_seconds=b/RATE+args.source_offset,
                    timestamp_basis='episode')
        with path.open('x',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
        lines.extend([f'WINDOW {i}: {fmt(offset)} - {fmt(b/RATE+args.source_offset)}', '-'*64])
        words=[]
        for token,start,duration in zip(tokens,times,durations):
            spoken=any(c.isalnum() for c in token)
            if not words or token.startswith(' '):
                words.append([token.strip(),start,start+duration,spoken])
            else:
                w=words[-1]; w[0]+=token
                if spoken:
                    if not w[3]: w[1],w[2]=start,start+duration
                    else: w[2]=max(w[2],start+duration)
                    w[3]=True
        for word,start,end,spoken in words:
            if spoken and start < hi and end >= lo:
                lines.append(f'{fmt(start)} - {fmt(end)}  {word}')
        lines.extend(['','FULL WINDOW TEXT:',r.text,''])
        print(f'  {len(tokens)} tokens, {time.perf_counter()-t:.2f}s; saved {path.name}')
    with report.open('x',encoding='utf-8') as f:
        f.write('\n'.join(lines)+'\n')
    print(f'Report: {report}')


def fmt(t):
    h,rem=divmod(t,3600); m,s=divmod(rem,60)
    return f'{int(h):02d}:{int(m):02d}:{s:05.2f}'


if __name__=='__main__':
    main()
