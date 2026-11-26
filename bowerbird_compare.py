"""Compare local BOWERBIRD samples using CHIRP's speaker embedding model."""
import argparse
import hashlib
import json
from pathlib import Path

MODEL = 'pyannote/wespeaker-voxceleb-resnet34-LM'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path)
    p.add_argument('--json', type=Path, required=True)
    p.add_argument('--threads', type=int, default=8)
    a = p.parse_args()
    if a.threads < 1:
        p.error('threads must be positive')
    if a.json.exists():
        raise FileExistsError(a.json)
    manifest = json.loads(a.manifest.read_text())
    if (manifest.get('schema'), manifest.get('schema_version')) != ('hehawk.bowerbird.collection', 1):
        raise ValueError('Unsupported collection')
    root = a.manifest.parent.resolve()
    samples = sorted(manifest['samples'], key=lambda s: s['candidate'])
    if not samples or len({s['candidate'] for s in samples}) != len(samples):
        raise ValueError('Empty collection or duplicate candidates')
    paths = []
    for s in samples:
        path = (root / s['sample_path']).resolve()
        if not path.is_relative_to(root) or digest(path) != s['audio_sha256']:
            raise ValueError(f"Invalid sample: {s['candidate']}")
        paths.append(path)
    import numpy as np
    import soundfile as sf
    import torch
    from huggingface_hub import get_token
    from pyannote.audio import Model, Inference
    from importlib.metadata import version
    torch.set_num_threads(a.threads)
    model = Model.from_pretrained(MODEL, token=get_token())
    inference = Inference(model, window='whole', device=torch.device('cpu'))
    vectors = []
    for s, path in zip(samples, paths):
        audio, rate = sf.read(path, dtype='float32', always_2d=True)
        if rate != 16000 or audio.shape[1] != 1 or not len(audio):
            raise ValueError(f'Expected nonempty mono 16 kHz audio: {path}')
        vector = np.asarray(inference({'waveform': torch.from_numpy(audio.T.copy()), 'sample_rate': rate}), dtype=np.float64).reshape(-1)
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm <= 1e-12:
            raise ValueError(f'Invalid embedding: {path}')
        vectors.append(vector / norm)
        print(f"Embedded candidate {s['candidate']:03d}", flush=True)
    matrix = np.clip(np.stack(vectors) @ np.stack(vectors).T, -1, 1)
    ids = [s['candidate'] for s in samples]
    print('\nCOSINE SIMILARITY (not probability)')
    print('    ' + ''.join(f'{n:6d}' for n in ids))
    for n, row in zip(ids, matrix):
        print(f'{n:3d} ' + ''.join(f'{v:6.2f}' for v in row))
    print('\nCANDIDATE KEY')
    for s in samples:
        print(s['candidate'], s['status'], ', '.join(s['speaker_identities']), s['vocal_mode'])
    print('\nKNOWN SINGLE-SPEAKER SPEECH PAIRS')
    for same in (True, False):
        pairs = [(float(matrix[i,j]), ids[i], ids[j]) for i,s in enumerate(samples) for j,t in enumerate(samples) if i<j and s['status']==t['status']=='known_single' and s['vocal_mode']==t['vocal_mode']=='speech' and (s['speaker_identities']==t['speaker_identities'])==same]
        print('Same identity' if same else 'Different identities', f'({len(pairs)} pairs)')
        if pairs:
            print(f'Min {min(pairs)[0]:.4f}, mean {np.mean([v for v,_,_ in pairs]):.4f}, max {max(pairs)[0]:.4f}')
            if same:
                for v,i,j in sorted(pairs):
                    print(f'  {i:3d} / {j:3d}: {v:.4f}')
    output = {'schema':'hehawk.bowerbird.similarity','schema_version':1,'manifest_sha256':digest(a.manifest),'model':MODEL,'model_revision':None,'packages':{n:version(n) for n in ('pyannote.audio','torch','numpy','soundfile')},'threads':a.threads,'candidate_ids':ids,'samples':samples,'embeddings':[v.tolist() for v in vectors],'cosine_similarity':matrix.tolist()}
    with a.json.open('x') as f:
        json.dump(output,f,indent=2,allow_nan=False)
    print(f'\nSaved local results: {a.json}')


if __name__ == '__main__':
    main()
