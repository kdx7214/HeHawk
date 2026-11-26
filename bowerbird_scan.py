"""Experimental local sliding-window speaker evidence; no caption modifications."""
import argparse
import hashlib
import json
from pathlib import Path
from importlib.metadata import version
import numpy as np
from bowerbird_cross_compare import load
from bowerbird_compare import MODEL


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def windows(n, width, step):
    if n < width:
        return []
    starts = list(range(0, n-width+1, step))
    if starts[-1] != n-width:
        starts.append(n-width)
    return [(s,s+width) for s in starts]


def overlap(a,b):
    same_source = a['audio_source_sha256'] == b['audio_source_sha256']
    same_episode = (a['series'],a['episode']) == (b['series'],b['episode'])
    return (same_source or same_episode) and max(a['start_seconds'],b['start_seconds']) < min(a['end_seconds'],b['end_seconds'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest',type=Path)
    p.add_argument('--references',type=Path,nargs='+',required=True)
    p.add_argument('--candidates',type=int,nargs='+',required=True)
    p.add_argument('--threads',type=int,default=8)
    p.add_argument('--json',type=Path,required=True)
    a=p.parse_args()
    if a.json.exists(): raise FileExistsError(a.json)
    if a.threads<1 or len(set(a.candidates))!=len(a.candidates): p.error('Invalid threads or duplicate candidates')
    manifest=json.loads(a.manifest.read_text())
    if (manifest['schema'],manifest['schema_version'])!=('hehawk.bowerbird.collection',1): raise ValueError('Unsupported manifest')
    targets={s['candidate']:s for s in manifest['samples']}
    refs=[]; vectors=[]; provenance=[]
    packages={n:version(n) for n in ('pyannote.audio','torch','numpy','soundfile')}
    for path in a.references:
        d,v,h=load(path)
        if d['model']!=MODEL or d['model_revision'] is not None or d['packages']!=packages: raise ValueError(f'Incompatible model or packages: {path}')
        provenance.append({'path':str(path),'sha256':h})
        for s,z in zip(d['samples'],v):
            if s['status']=='known_single' and s['vocal_mode']=='speech' and len(s['speaker_identities'])==1:
                refs.append(s); vectors.append(z)
    if not refs or len({s['candidate'] for s in refs})!=len(refs): raise ValueError('Empty or duplicate references')
    matrix=np.stack(vectors)
    import soundfile as sf
    import torch
    from huggingface_hub import get_token
    from pyannote.audio import Model, Inference
    torch.set_num_threads(a.threads)
    inference=Inference(Model.from_pretrained(MODEL,token=get_token()),window='whole',device=torch.device('cpu'))
    print('WARNING: model revision unpinned; exact weight identity not verified')
    output=[]
    root=a.manifest.parent.resolve()
    for cid in a.candidates:
        s=targets[cid]
        path=(root/s['sample_path']).resolve()
        if not path.is_relative_to(root) or digest(path)!=s['audio_sha256']: raise ValueError(f'Invalid audio {cid}')
        audio,rate=sf.read(path,dtype='float32',always_2d=True)
        if rate!=16000 or audio.shape[1]!=1: raise ValueError('Expected mono 16 kHz')
        eligible=[i for i,r in enumerate(refs) if not overlap(s,r)]
        if not eligible: raise ValueError('No independent references')
        excluded=[r['candidate'] for i,r in enumerate(refs) if i not in eligible]
        print(f'\nCandidate {cid}: excluded references {excluded}; {len(eligible)} eligible')
        result={'target':s,'excluded_reference_ids':excluded,'eligible_reference_ids':[refs[i]['candidate'] for i in eligible],'windows':[]}
        for duration in (.5,1,2,3):
            counts={}; failures=0
            for lo,hi in windows(len(audio),round(duration*rate),rate//4):
                row={'duration_seconds':duration,'relative_start_seconds':lo/rate,'relative_end_seconds':hi/rate,'episode_start_seconds':s['start_seconds']+lo/rate,'episode_end_seconds':s['start_seconds']+hi/rate}
                try:
                    z=np.asarray(inference({'waveform':torch.from_numpy(audio[lo:hi].T.copy()),'sample_rate':rate}),dtype=float).reshape(-1)
                    norm=np.linalg.norm(z)
                    if not np.isfinite(norm) or norm<=1e-12 or len(z)!=matrix.shape[1]: raise ValueError('Invalid embedding')
                    scores=np.clip(matrix[eligible]@(z/norm),-1,1)
                    by_name={}
                    row['reference_scores']={str(refs[i]['candidate']):float(score) for i,score in zip(eligible,scores)}
                    for i,score in zip(eligible,scores):
                        name=refs[i]['speaker_identities'][0]
                        by_name[name]=max(by_name.get(name,-1),float(score))
                    ranked=sorted(by_name.items(),key=lambda x:(-x[1],x[0]))
                    row['character_scores']=by_name
                    row['best']=ranked[0]; row['runner_up']=ranked[1] if len(ranked)>1 else None
                    row['margin']=ranked[0][1]-ranked[1][1] if len(ranked)>1 else None
                    counts[ranked[0][0]]=counts.get(ranked[0][0],0)+1
                    print(f'  {duration:3.1f}s {lo/rate:6.2f}-{hi/rate:6.2f}: {ranked[0][0]} {ranked[0][1]:.3f}' + (f' / {ranked[1][0]} {ranked[1][1]:.3f}' if len(ranked)>1 else ''),flush=True)
                except (RuntimeError,ValueError) as e:
                    row['error']=str(e); failures+=1
                result['windows'].append(row)
            print(f'  Summary {duration}s: {counts}; failed={failures}',flush=True)
        output.append(result)
    with a.json.open('x') as f:
        json.dump({'schema':'hehawk.bowerbird.scan','schema_version':1,'model':MODEL,'model_revision':None,'packages':packages,'threads':a.threads,'manifest_sha256':digest(a.manifest),'references':provenance,'window_seconds':[.5,1,2,3],'step_seconds':.25,'ranking':'maximum individual reference cosine; not identity assignment','results':output},f,indent=2,allow_nan=False)
    print(f'Saved local results: {a.json}')

if __name__=='__main__': main()
