#!/usr/bin/env python3
"""FEATHER V1: controlled audio treatment experiments."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from hunt_execute import RATE, MODEL, digest, save_new

TREATMENTS = {
    'original': ('anull', 1.0),
    'speech_band': ('highpass=f=120,lowpass=f=3800', 1.0),
    'compression': ('acompressor=threshold=0.063:ratio=3:attack=10:release=150:makeup=2,alimiter=limit=0.95:latency=1', 1.0),
    'noise_reduction': ('afftdn=nr=10:nf=-45', 1.0),
    'slow': ('atempo=0.85', 0.85),
}


def process(audio, filters):
    import numpy as np
    result = subprocess.run(['ffmpeg','-hide_banner','-loglevel','error',
        '-f','f32le','-ar',str(RATE),'-ac','1','-i','pipe:0',
        '-af',filters,'-f','f32le','-ar',str(RATE),'-ac','1','pipe:1'],
        input=audio.astype('<f4').tobytes(), stdout=subprocess.PIPE, check=True)
    out = np.frombuffer(result.stdout, dtype='<f4').copy()
    if not len(out) or not np.isfinite(out).all():
        raise ValueError('Invalid filtered audio')
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('audio', type=Path)
    p.add_argument('--source-start', type=float, default=540)
    p.add_argument('--starts', type=float, nargs='+', default=[573,585,592])
    p.add_argument('--window', type=float, default=30)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--model', type=Path, default=MODEL)
    p.add_argument('--threads', type=int, default=8)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    import soundfile as sf
    import numpy as np
    audio, rate = sf.read(args.audio, dtype='float32')
    if rate != RATE or audio.ndim != 1 or not np.isfinite(audio).all():
        p.error('Require finite mono 16 kHz audio')
    if not all(math.isfinite(x) for x in [args.source_start,args.window,*args.starts]) or args.source_start<0 or args.window<=0 or args.threads<1:
        p.error('Invalid settings')
    work=[]
    for i,start in enumerate(args.starts):
        a=round((start-args.source_start)*RATE)
        b=a+round(args.window*RATE)
        if not 0<=a<b<=len(audio): p.error('Window outside source audio')
        for name,(filters,speed) in TREATMENTS.items():
            work.append((f'feather_w{i+1:02d}_{name}.json',a,b,name,filters,speed))
    print(f'{len(work)} observations planned')
    if args.dry_run:
        for name,a,b,*_ in work: print(f'{name}: {args.source_start+a/RATE:.3f} - {args.source_start+b/RATE:.3f}')
        return
    import sherpa_onnx
    files=['encoder.int8.onnx','decoder.int8.onnx','joiner.int8.onnx','tokens.txt']
    common=dict(version=1,audio_sha256=digest(args.audio),model_sha256={n:digest(args.model/n) for n in files},threads=args.threads,sherpa_version=str(getattr(sherpa_onnx,'__version__','unknown')),ffmpeg_version=subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0])
    args.output_dir.mkdir(parents=True,exist_ok=True)
    recognizer=None
    for filename,a,b,name,filters,speed in work:
        path=args.output_dir/filename
        start,end=args.source_start+a/RATE,args.source_start+b/RATE
        filtered=audio[a:b].copy() if name=='original' else process(audio[a:b],filters)
        meta=dict(common,treatment=name,filter=filters,speed=speed,sample_start=a,sample_end_exclusive=b,processed_samples=len(filtered),processed_sha256=hashlib.sha256(filtered.astype('<f4').tobytes()).hexdigest(),timestamp_mapping='nominal speed scaling; approximate for atempo and filter latency')
        if path.exists():
            old=json.loads(path.read_text())
            if old.get('feather')!=meta or old.get('window_start_seconds')!=start or old.get('window_end_seconds')!=end or old.get('timestamp_basis')!='episode': raise ValueError(f'Existing provenance mismatch: {path}')
            print(f'Reusing {filename}',flush=True)
            continue
        if recognizer is None:
            recognizer=sherpa_onnx.OfflineRecognizer.from_transducer(encoder=str(args.model/files[0]),decoder=str(args.model/files[1]),joiner=str(args.model/files[2]),tokens=str(args.model/files[3]),num_threads=args.threads,provider='cpu',model_type='nemo_transducer')
        t=time.perf_counter()
        stream=recognizer.create_stream()
        stream.accept_waveform(RATE,filtered)
        recognizer.decode_stream(stream)
        r=stream.result
        data=dict(text=r.text,tokens=list(r.tokens),timestamps=[start+float(x)*speed for x in r.timestamps],durations=[float(x)*speed for x in r.durations],source_offset_seconds=0.0,window_start_seconds=start,window_end_seconds=end,timestamp_basis='episode',feather=meta)
        if not len(data['tokens'])==len(data['timestamps'])==len(data['durations']): raise ValueError('Mismatched token arrays')
        if any(not math.isfinite(x) for x in data['timestamps']+data['durations']) or any(x<0 for x in data['durations']): raise ValueError('Invalid timings')
        save_new(path,data)
        print(f'{filename}: {len(data["tokens"])} tokens; {time.perf_counter()-t:.2f}s',flush=True)

if __name__=='__main__': main()
