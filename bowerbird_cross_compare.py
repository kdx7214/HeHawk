"""Compare two cached BOWERBIRD collections locally, without model inference."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def load(path):
    raw = path.read_bytes()
    d = json.loads(raw)
    if (d.get('schema'), d.get('schema_version')) != ('hehawk.bowerbird.similarity', 1):
        raise ValueError(f'Unsupported schema: {path}')
    manifest = path.parent / 'manifest.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != d['manifest_sha256']:
        raise ValueError(f'Manifest hash mismatch: {manifest}')
    samples = d['samples']
    if [s['candidate'] for s in samples] != d['candidate_ids']:
        raise ValueError('Candidate order mismatch')
    v = np.asarray(d['embeddings'], dtype=float)
    if v.ndim != 2 or len(v) != len(samples) or not np.isfinite(v).all() or not np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-6):
        raise ValueError('Invalid cached embeddings')
    return d, v, hashlib.sha256(raw).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('assisted', type=Path)
    p.add_argument('manual', type=Path)
    p.add_argument('--json', type=Path, required=True)
    a = p.parse_args()
    if a.json.exists():
        raise FileExistsError(a.json)
    x, u, hx = load(a.assisted)
    y, v, hy = load(a.manual)
    for key in ('model', 'model_revision', 'packages'):
        if x[key] != y[key]:
            raise ValueError(f'Incompatible {key}')
    if x['model_revision'] is None:
        print('WARNING: model revision unpinned; exact weight identity not verified')
    samples = x['samples'] + y['samples']
    ids = [s['candidate'] for s in samples]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate candidate IDs')
    z = np.concatenate((u,v), axis=0)
    matrix = np.clip(z @ z.T, -1, 1)
    print('\nCROSS-COLLECTION COSINE SIMILARITY')
    print('    ' + ''.join(f'{i:7d}' for i in y['candidate_ids']))
    for i, s in enumerate(x['samples']):
        print(f"{s['candidate']:3d} " + ''.join(f'{w:7.3f}' for w in matrix[i,len(u):]))
    def speech(s):
        return s['status']=='known_single' and s['vocal_mode']=='speech' and len(s['speaker_identities'])==1
    print('\nCROSS-COLLECTION SPEECH PAIRS (manual boundaries provisional)')
    for same in (True,False):
        pairs = [(float(matrix[i,j]),ids[i],ids[j]) for i in range(len(u)) for j in range(len(u),len(z)) if speech(samples[i]) and speech(samples[j]) and (samples[i]['speaker_identities']==samples[j]['speaker_identities'])==same]
        print('Same identity' if same else 'Different identities',len(pairs))
        if pairs:
            print(f'Min {min(pairs)[0]:.4f}, mean {np.mean([t[0] for t in pairs]):.4f}, max {max(pairs)[0]:.4f}')
            for score,i,j in (sorted(pairs) if same else sorted(pairs,reverse=True)[:5]):
                print(f'{i:3d} / {j:3d}: {score:.4f}')
    with a.json.open('x') as f:
        json.dump({'schema':'hehawk.bowerbird.cross_similarity','schema_version':1,'input_sha256':[hx,hy],'model':x['model'],'model_revision':x['model_revision'],'candidate_ids':ids,'samples':samples,'cosine_similarity':matrix.tolist()},f,indent=2,allow_nan=False)
    print(f'\nSaved local results: {a.json}')


if __name__=='__main__':
    main()
