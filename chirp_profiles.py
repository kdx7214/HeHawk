import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from huggingface_hub import get_token
from pyannote.audio import Model, Inference

MODEL = 'pyannote/wespeaker-voxceleb-resnet34-LM'


def unit(x):
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    n = np.linalg.norm(x)
    if not np.isfinite(n) or n == 0:
        raise ValueError('Invalid embedding')
    return x / n


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cluster(vectors, threshold):
    sim = vectors @ vectors.T
    groups = [[i] for i in range(len(vectors))]
    while len(groups) > 1:
        score, a, b = max(
            (float(sim[np.ix_(groups[i], groups[j])].mean()), i, j)
            for i in range(len(groups)) for j in range(i + 1, len(groups))
        )
        if score < threshold:
            break
        groups[a] = sorted(groups[a] + groups[b])
        del groups[b]
    return sorted(groups, key=lambda g: g[0])


def main():
    p = argparse.ArgumentParser(description='CHIRP autonomous profile experiment')
    p.add_argument('audio', type=Path)
    p.add_argument('segments', type=Path)
    p.add_argument('--json', type=Path, required=True)
    p.add_argument('--audit', type=Path, required=True)
    p.add_argument('--min-duration', type=float, default=1.5)
    p.add_argument('--cluster-threshold', type=float, default=.34)
    p.add_argument('--min-similarity', type=float, default=.30)
    p.add_argument('--min-margin', type=float, default=.10)
    p.add_argument('--window', type=float, default=1.5)
    p.add_argument('--stride', type=float, default=.25)
    args = p.parse_args()
    paths = [x.resolve() for x in (args.audio,args.segments,args.json,args.audit)]
    if len(set(paths)) != 4 or args.json.exists() or args.audit.exists():
        p.error('Use distinct, new output paths')
    if not 0 < args.stride <= args.window or args.min_duration <= 0:
        p.error('Invalid duration or stride')
    if not -1 <= args.cluster_threshold <= 1 or not -1 <= args.min_similarity <= 1 or not 0 <= args.min_margin <= 2:
        p.error('Invalid thresholds')
    data = json.loads(args.segments.read_text())
    if data.get('schema') != 'hehawk.chirp.segment_embeddings' or data.get('schema_version') != 1 or data.get('model') != MODEL:
        raise ValueError('Unsupported segment evidence')
    offset = float(data['source_offset_seconds'])
    if Path(data['source']).resolve() != args.audio.resolve():
        raise ValueError('Audio path differs from segment evidence')
    audio, rate = sf.read(args.audio, dtype='float32', always_2d=True)
    if rate != data['sample_rate']:
        raise ValueError('Sample rate mismatch')
    segments = sorted(data['segments'], key=lambda s:s['start_seconds'])
    anchors = [s for s in segments if s['end_seconds']-s['start_seconds'] >= args.min_duration]
    if not anchors:
        raise ValueError('No potential anchors')
    vectors = np.stack([unit(s['embedding']) for s in anchors])
    groups = cluster(vectors, args.cluster_threshold)
    names = [f'VOICE_{i:02d}' for i in range(len(groups))]
    print('PROVISIONAL CLUSTERS')
    for name, group in zip(names, groups):
        print(name, ', '.join(anchors[i]['id'] for i in group))
    torch.set_num_threads(8)
    model = Model.from_pretrained(MODEL, token=get_token())
    infer = Inference(model, window='whole', device=torch.device('cpu'))
    length, stride = round(args.window*rate), round(args.stride*rate)
    if min(length,stride)<1:
        raise ValueError('Window or stride too small')
    audit = []
    accepted = []
    print('\nANCHOR CONSISTENCY (leave-one-segment-out)')
    for k, group in enumerate(groups):
        for i in group:
            s = anchors[i]
            a = round((s['start_seconds']-offset)*rate)
            b = round((s['end_seconds']-offset)*rate)
            if not 0 <= a < b <= len(audio):
                raise ValueError(f"Segment outside audio: {s['id']}")
            peers = {names[j]:[n for n in g if n != i] for j,g in enumerate(groups)}
            peers = {name:g for name,g in peers.items() if g}
            windows = []
            if b-a >= length and names[k] in peers and len(peers)>=2:
                starts = list(range(a,b-length+1,stride))
                if starts[-1] != b-length:
                    starts.append(b-length)
                for first in starts:
                    v = unit(infer({'waveform':torch.from_numpy(audio[first:first+length].T.copy()),'sample_rate':rate}))
                    scores = {name:float((vectors[g] @ v).mean()) for name,g in peers.items()}
                    ranked = sorted(scores,key=scores.get,reverse=True)
                    winner = ranked[0]
                    margin = scores[winner]-scores[ranked[1]]
                    status = 'WEAK' if scores[winner]<args.min_similarity else 'AMBIGUOUS' if margin<args.min_margin else 'MATCH'
                    windows.append(dict(start_seconds=offset+first/rate,end_seconds=offset+(first+length)/rate,scores=scores,winner=winner,margin=margin,status=status,embedding=v.tolist()))
            good = sum(w['status']=='MATCH' and w['winner']==names[k] for w in windows)
            rival = sum(w['status']=='MATCH' and w['winner']!=names[k] for w in windows)
            # Strict exploratory gate: no confident rival and at least 80% own matches.
            keep = bool(windows) and rival==0 and good/len(windows)>=.8
            print(f"{s['id']} {names[k]}: {good}/{len(windows)} own, {rival} rival -> {'ANCHOR' if keep else 'QUARANTINE'}")
            audit.append(dict(segment_id=s['id'],provisional_voice=names[k],accepted=keep,windows=windows))
            if keep:
                accepted.append(dict(id=s['id'],speaker=names[k],start_seconds=s['start_seconds'],end_seconds=s['end_seconds'],embedding=vectors[i].tolist()))
    # Do not silently promote a singleton into a validated profile.
    counts = {name:sum(s['speaker']==name for s in accepted) for name in names}
    samples = [s for s in accepted if counts[s['speaker']]>=2]
    print('\nFINAL PROFILES')
    for name in names:
        print(name, ', '.join(s['id'] for s in samples if s['speaker']==name) or 'UNRESOLVED')
    settings = dict(min_duration=args.min_duration,cluster_threshold=args.cluster_threshold,min_similarity=args.min_similarity,min_margin=args.min_margin,window=args.window,stride=args.stride,minimum_own_fraction=.8,minimum_anchors=2)
    provenance = dict(model=MODEL,source=str(args.audio),source_sha256=digest(args.audio),segment_sha256=digest(args.segments),source_offset_seconds=offset,timestamp_basis='episode',sample_rate=rate,settings=settings)
    with args.audit.open('x') as f:
        json.dump(dict(schema='hehawk.chirp.profile_audit',schema_version=1,**provenance,clusters=[dict(speaker=n,segments=[anchors[i]['id'] for i in g]) for n,g in zip(names,groups)],anchors=audit),f,indent=2,allow_nan=False)
    with args.json.open('x') as f:
        json.dump(dict(schema='hehawk.chirp.embeddings',schema_version=1,**provenance,embedding_dimensions=int(vectors.shape[1]),samples=samples),f,indent=2,allow_nan=False)
    print(f'\nSaved {len(samples)} anchors across {len(set(s["speaker"] for s in samples))} profiles.')
    if len(set(s['speaker'] for s in samples))<2:
        print('Insufficient profiles for transition experiment; inspect audit first.')


if __name__ == '__main__':
    main()
