#!/usr/bin/env python3
"""Execute HUNT V1 plans on the original mono 16 kHz WAV."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time

RATE = 16000
MODEL = Path('models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def jobs(plan, samples):
    if (plan['schema'], plan['schema_version'], plan['timestamp_basis']) != ('hehawk.hunt', 1, 'episode'):
        raise ValueError('Expected HUNT V1 episode-relative plan')
    lo, hi = (float(plan['settings'][k]) for k in ('source_start', 'source_end'))
    if not math.isfinite(lo) or not math.isfinite(hi) or lo < 0 or round((hi-lo)*RATE) != samples:
        raise ValueError('WAV length does not match planned source interval')
    seen = set()
    for region in plan['regions']:
        for i, w in enumerate(region['windows']):
            if w['status'] != 'planned':
                continue
            a, b = (round((float(w[k])-lo)*RATE) for k in ('start_seconds','end_seconds'))
            name = f"hunt_r{int(region['id']):03d}_w{i+1:02d}.json"
            if name in seen or not 0 <= a < b <= samples:
                raise ValueError('Duplicate job ID or invalid audio range')
            seen.add(name)
            yield name, a, b, lo, region


def validate(data, meta, start, end):
    if data.get('hunt') != meta or data.get('timestamp_basis') != 'episode' or data.get('source_offset_seconds') != 0 or data.get('window_start_seconds') != start or data.get('window_end_seconds') != end:
        raise ValueError('Observation provenance or interval mismatch')
    if not isinstance(data['text'], str) or not all(isinstance(t,str) for t in data['tokens']):
        raise ValueError('Invalid transcription text')
    if not len(data['tokens']) == len(data['timestamps']) == len(data['durations']):
        raise ValueError('Mismatched token arrays')
    if any(not math.isfinite(x) for x in data['timestamps']+data['durations']) or any(x < 0 for x in data['durations']):
        raise ValueError('Invalid token timing')


def save_new(path, data):
    # Publish only complete files, without replacing existing evidence.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        try:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
            os.link(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('plan', type=Path)
    p.add_argument('audio', type=Path)
    p.add_argument('--output-dir', required=True, type=Path)
    p.add_argument('--model', type=Path, default=MODEL)
    p.add_argument('--threads', type=int, default=8)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    import soundfile as sf
    audio, rate = sf.read(args.audio, dtype='float32')
    if rate != RATE or audio.ndim != 1 or args.threads < 1:
        p.error('Require mono 16 kHz WAV and positive thread count')
    raw = args.plan.read_bytes()
    plan = json.loads(raw)
    work = list(jobs(plan, len(audio)))
    print(f'{len(work)} planned observations')
    if args.dry_run:
        for name,a,b,lo,_ in work:
            print(f'{name}: {lo+a/RATE:.3f} - {lo+b/RATE:.3f}')
        return
    import sherpa_onnx
    model_files = ['encoder.int8.onnx','decoder.int8.onnx','joiner.int8.onnx','tokens.txt']
    common = dict(plan_sha256=hashlib.sha256(raw).hexdigest(), audio_sha256=digest(args.audio), model_sha256={n:digest(args.model/n) for n in model_files}, threads=args.threads, sherpa_version=str(getattr(sherpa_onnx,'__version__','unknown')))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pending=[]
    for name,a,b,lo,region in work:
        path=args.output_dir/name
        meta=dict(common, region_id=region['id'], group_ids=region['group_ids'], sample_start=a, sample_end_exclusive=b)
        start,end=lo+a/RATE,lo+b/RATE
        if path.exists():
            validate(json.loads(path.read_text(encoding='utf-8')),meta,start,end)
            print(f'Reusing {name}')
        else:
            pending.append((path,a,b,start,end,meta))
    if pending:
        print('Loading Parakeet model...',flush=True)
        recognizer=sherpa_onnx.OfflineRecognizer.from_transducer(encoder=str(args.model/model_files[0]),decoder=str(args.model/model_files[1]),joiner=str(args.model/model_files[2]),tokens=str(args.model/model_files[3]),num_threads=args.threads,provider='cpu',model_type='nemo_transducer')
        for path,a,b,start,end,meta in pending:
            t=time.perf_counter()
            stream=recognizer.create_stream()
            stream.accept_waveform(rate,audio[a:b])
            recognizer.decode_stream(stream)
            r=stream.result
            data=dict(text=r.text,tokens=list(r.tokens),timestamps=[float(x)+start for x in r.timestamps],durations=[float(x) for x in r.durations],source_offset_seconds=0.0,window_start_seconds=start,window_end_seconds=end,timestamp_basis='episode',hunt=meta)
            validate(data,meta,start,end)
            save_new(path,data)
            print(f'{path.name}: {len(data["tokens"])} tokens; {time.perf_counter()-t:.2f}s',flush=True)
    print(f'{len(work)} observations available; {len(pending)} newly transcribed')


if __name__ == '__main__':
    main()
