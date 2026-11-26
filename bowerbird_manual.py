"""Collect manually reviewed episode audio intervals without diarization."""
import argparse
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from bowerbird import digest


def collect(audio, review, destination):
    r = json.loads(review.read_text())
    if (r.get('schema'), r.get('schema_version')) != ('hehawk.bowerbird.manual_review', 1):
        raise ValueError('Unsupported manual review schema')
    if destination.exists():
        raise FileExistsError(destination)
    probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','a:0','-show_streams','-show_format','-of','json',str(audio)]))
    stream = probe['streams'][0]
    if int(stream['sample_rate']) != 16000 or stream['channels'] != 1:
        raise ValueError('Expected mono 16 kHz episode audio')
    duration = float(probe['format']['duration'])
    source_hash = digest(audio)
    seen = set()
    for s in r['reviews']:
        n = s['candidate']
        a,b = s['start_seconds'],s['end_seconds']
        if type(n) is not int or n < 1 or n in seen:
            raise ValueError('Invalid or duplicate candidate')
        seen.add(n)
        if not all(map(math.isfinite,(a,b))) or not 0 <= a < b <= duration:
            raise ValueError(f'Invalid interval: {n}')
        if s['status'] != 'known_single' or len(s['speaker_identities']) != 1 or not s['speaker_identities'][0]:
            raise ValueError(f'Expected one reviewed identity: {n}')
    if not seen:
        raise ValueError('Empty review')
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.bowerbird-manual-',dir=destination.parent))
    try:
        manifest = dict(schema='hehawk.bowerbird.collection',schema_version=1,series=r['series'],episode=r['episode'],audio_source=str(audio),audio_sha256=source_hash,review_sha256=digest(review),collection_method='manual',source_offset_seconds=0,samples=[])
        for s in r['reviews']:
            name = f"manual_{s['candidate']:03d}"
            folder = staging/name
            folder.mkdir()
            out = folder/'audio.flac'
            a,b = s['start_seconds'],s['end_seconds']
            subprocess.run(['ffmpeg','-nostdin','-v','error','-n','-i',str(audio),'-ss',str(a),'-t',str(b-a),'-map','0:a:0','-c:a','flac',str(out)],check=True)
            metadata = dict(s,series=r['series'],episode=r['episode'],collection_method='manual',timestamp_precision='approximate',verification='human_reviewed',boundary_verification='pending',audio_source_sha256=source_hash,audio_sha256=digest(out),sample_path=f'{name}/audio.flac')
            (folder/'metadata.json').write_text(json.dumps(metadata,indent=2,allow_nan=False)+'\n')
            manifest['samples'].append(metadata)
        (staging/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
        shutil.copyfile(review,staging/'review.json')
        if destination.exists():
            raise FileExistsError(destination)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(f'Preserved {len(seen)} manual samples in {destination}')
    print(f"Total selected duration: {sum(s['end_seconds']-s['start_seconds'] for s in r['reviews']):.3f} seconds")
    print('Boundary verification pending for all samples')

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('audio','review','destination'):
        p.add_argument(name,type=Path)
    a=p.parse_args()
    collect(a.audio,a.review,a.destination)
