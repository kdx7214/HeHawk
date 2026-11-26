"""BOWERBIRD: local, human-reviewed sample collection."""
import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def collect(audio, diarization, review, destination):
    d = json.loads(diarization.read_text())
    r = json.loads(review.read_text())
    if d.get('schema') != 'hehawk.chirp.diarization' or d.get('schema_version') != 1 or d.get('timestamp_basis') != 'episode':
        raise ValueError('Unsupported diarization schema')
    if r.get('schema') != 'hehawk.bowerbird.review' or r.get('schema_version') != 1:
        raise ValueError('Unsupported review schema')
    audio_hash = digest(audio)
    if audio_hash != d['source_sha256']:
        raise ValueError('Audio hash mismatch')
    if destination.exists():
        raise FileExistsError(destination)
    candidates = sorted((s for s in d['regular']['segments'] if s['duration_seconds'] >= r['minimum_duration']), key=lambda s: s['duration_seconds'], reverse=True)
    prepared = []
    seen = set()
    for item in r['reviews']:
        n = item['candidate']
        if type(n) is not int or not 1 <= n <= len(candidates) or n in seen:
            raise ValueError('Invalid or duplicate candidate')
        seen.add(n)
        s = candidates[n-1]
        if s['original_speaker'] != item['cluster'] or abs(s['start_seconds'] - item['start_seconds']) > .001 or abs(s['end_seconds'] - item['end_seconds']) > .001:
            raise ValueError(f'Candidate {n} does not match reviewed interval')
        if item['status'] not in ('known_single', 'mixed', 'unidentified'):
            raise ValueError('Invalid review status')
        a = s['start_seconds'] - d['source_offset_seconds']
        b = s['end_seconds'] - d['source_offset_seconds']
        if not all(map(math.isfinite, (a,b))) or not 0 <= a < b <= d['duration_seconds'] + .001:
            raise ValueError('Invalid audio interval')
        prepared.append((item,s,a,b))
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.bowerbird-', dir=destination.parent))
    try:
        manifest = {'schema':'hehawk.bowerbird.collection','schema_version':1,'series':r['series'],'episode':r['episode'],'audio_source':str(audio),'audio_sha256':audio_hash,'diarization_sha256':digest(diarization),'review_sha256':digest(review),'samples':[]}
        for item,s,a,b in prepared:
            name = f"candidate_{item['candidate']:03d}"
            folder = staging / name
            folder.mkdir()
            out = folder / 'audio.flac'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-n','-i',str(audio),'-ss',f'{a:.9f}','-t',f'{b-a:.9f}','-map','0:a:0','-c:a','flac',str(out)],check=True)
            metadata = {**item,'series':r['series'],'episode':r['episode'],'source_segment':s,'audio_source_sha256':audio_hash,'audio_sha256':digest(out),'verification':'human_reviewed','sample_path':f'{name}/audio.flac'}
            (folder/'metadata.json').write_text(json.dumps(metadata,indent=2,allow_nan=False)+'\n')
            manifest['samples'].append(metadata)
        (staging/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
        shutil.copyfile(review, staging/'review.json')
        if destination.exists():
            raise FileExistsError(destination)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(f'Preserved {len(prepared)} reviewed samples in {destination}')
    for status in ('known_single','mixed','unidentified'):
        print(f'{status}: {sum(i[0]["status"] == status for i in prepared)}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('audio','diarization','review','destination'):
        p.add_argument(name,type=Path)
    a = p.parse_args()
    collect(a.audio,a.diarization,a.review,a.destination)

if __name__ == '__main__':
    main()
