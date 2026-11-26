"""LARK: local, threshold-free Silero speech probability timeline."""
import argparse
import hashlib
import importlib.metadata as md
import json
import math
from pathlib import Path
import time


def sha256(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('audio', type=Path)
    p.add_argument('--json', required=True, type=Path)
    args = p.parse_args()
    if args.json.exists():
        p.error('Output already exists; choose a new filename.')
    import numpy as np
    import soundfile as sf
    import torch
    import silero_vad
    from silero_vad import load_silero_vad
    source_hash = sha256(args.audio)
    rate, step = 16000, 512
    started = time.monotonic()
    torch.set_num_threads(1)
    model = load_silero_vad(onnx=True)
    model.reset_states()
    probabilities = []
    with sf.SoundFile(args.audio) as audio:
        if audio.samplerate != rate or audio.channels != 1:
            p.error('Expected mono 16000 Hz audio.')
        samples = len(audio)
        if not samples:
            p.error('Empty audio.')
        total = (samples + step - 1) // step
        with torch.inference_mode():
            for i in range(total):
                frame = audio.read(step, dtype='float32')
                if not np.isfinite(frame).all():
                    raise ValueError('Non-finite audio samples')
                if len(frame) < step:
                    frame = np.pad(frame, (0, step-len(frame)))
                prob = float(model(torch.from_numpy(frame), rate).item())
                if not math.isfinite(prob) or not 0 <= prob <= 1:
                    raise ValueError(f'Invalid probability at frame {i}')
                probabilities.append(prob)
                if (i+1) % 10000 == 0 or i+1 == total:
                    print(f'Frames: {i+1}/{total}', flush=True)
    if sha256(args.audio) != source_hash:
        raise RuntimeError('Source changed during analysis')
    model_files = {str(f.relative_to(Path(silero_vad.__file__).parent)): sha256(f)
                   for f in sorted(Path(silero_vad.__file__).parent.rglob('*.onnx'))}
    result = dict(schema='hehawk.lark.probabilities', version=1,
                  source=str(args.audio), source_sha256=source_hash,
                  timestamp_basis='episode', source_offset_seconds=0,
                  sample_rate=rate, frame_samples=step, source_samples=samples,
                  duration_seconds=samples/rate, model='silero-vad', backend='onnx',
                  bundled_onnx_sha256=model_files,
                  packages={name: md.version(name) for name in
                            ('silero-vad','onnxruntime','torch','numpy','soundfile')},
                  settings={'torch_threads':1,'state_reset':'once_at_start','tail_padding':'zeros'},
                  probabilities=probabilities, processing_seconds=time.monotonic()-started)
    with args.json.open('x', encoding='utf-8') as f:
        json.dump(result, f, allow_nan=False, separators=(',', ':'))
        f.write('\n')
    print(f'Duration: {samples/rate:.3f}s; frames: {total}')
    print(f'Probability min/mean/max: {min(probabilities):.6f}/{np.mean(probabilities):.6f}/{max(probabilities):.6f}')
    for threshold in (0.3, 0.5, 0.7):
        count = sum(x >= threshold for x in probabilities)
        print(f'Frames >= {threshold:.1f}: {count}/{total} ({100*count/total:.2f}%)')
    print(f'Processing: {result["processing_seconds"]:.3f}s')
    print(f'Saved: {args.json}')


if __name__ == '__main__':
    main()
