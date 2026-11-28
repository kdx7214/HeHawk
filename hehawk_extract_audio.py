#!/usr/bin/env python3
"""Phase 5B: explicitly extract one selected native audio stream locally."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from hehawk import inspect
from hehawk_resources import plan
from hehawk_workspace import preflight, safe_path
from hehawk_publication import publish
from hehawk_verify_audio import verify as verify_audio
from xml.etree.ElementTree import ParseError


def extract(video, config, index, decode=False):
    media, root, mount = preflight(config)
    if not media.is_mount():
        raise ValueError('Media mount unavailable')
    source = video.resolve(strict=True)
    relative = source.relative_to(media)
    def signature():
        s = source.stat()
        return (s.st_size, s.st_mtime_ns, s.st_dev, s.st_ino)
    original = signature()
    inventory = inspect(source)
    planned = plan(inventory, config)
    if signature() != original:
        raise ValueError('Source changed during inspection')
    resource = next((r for r in planned['resources'] if r['kind'] == 'native_audio' and r['source_stream'] == index), None)
    if resource is None:
        raise ValueError('Requested stream is not the selected native audio')
    stream = next(s for s in inventory['streams'] if s['index'] == index)
    if stream['codec_name'] != 'aac':
        raise ValueError('Phase 5B.1 supports AAC only')
    project_rel = Path('projects') / relative.with_suffix('')
    resources = safe_path(root, project_rel / 'resources', mount)
    destination = Path(resource['path']).relative_to('resources')
    budget = planned['storage']['native_budget_bytes'] + planned['storage']['overhead_allowance_bytes']
    reserve = planned['storage']['reserve_bytes']
    mount_stat = mount.stat()
    def check():
        if preflight(config) != (media, root, mount) or not media.is_mount():
            raise ValueError('Mount or configuration changed')
        s = mount.stat()
        if (s.st_dev, s.st_ino) != (mount_stat.st_dev, mount_stat.st_ino):
            raise ValueError('Workspace mount changed')
        if signature() != original:
            raise ValueError('Source changed')
        for p in (resources, resources / destination, resources / 'manifest.json', resources / '.publication.json', resources / '.publication.lock'):
            safe_path(root, p.relative_to(root), mount)
        if shutil.disk_usage(mount).free < reserve + budget:
            raise ValueError('Insufficient extraction budget')
    args = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror', '-n', '-copyts', '-i', str(source), '-map', f'0:{index}', '-c:a', 'copy', '-map_metadata', '-1', '-map_chapters', '-1', '-avoid_negative_ts', 'disabled', '-f', 'matroska']
    version = subprocess.check_output(['ffmpeg', '-version'], text=True).splitlines()[0]
    provenance = {'project_id': planned['project_id'], 'source': planned['source'], 'source_stream': index, 'source_codec': stream['codec_name'], 'source_stream_metadata': stream, 'ffmpeg_version': version, 'extraction_parameters': args[1:]+['<temporary-output>']}
    def produce(path):
        subprocess.run(args+[str(path)], check=True)
    def verify(path):
        data = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json','-i',str(path)], text=True, timeout=120))
        tracks = data['streams']
        if len(tracks) != 1 or tracks[0]['codec_type'] != 'audio':
            raise ValueError('Expected exactly one audio stream')
        for key in ('codec_name','channels','sample_rate'):
            if tracks[0].get(key) != stream.get(key):
                raise ValueError(f'Output {key} mismatch')
        check()
        report = verify_audio(source, path, index, 0, decode=decode)
        check()
        return report
    check()
    return publish(resources, destination, resource['id'], produce, verify, check, provenance=provenance, require_verification=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--stream', type=int, required=True)
    parser.add_argument('--decode', action='store_true', help='Also compare decoded PCM hashes')
    args = parser.parse_args()
    try:
        print(json.dumps(extract(args.video, json.loads(args.config.read_text()), args.stream, decode=args.decode), indent=2))
    except (OSError, ValueError, KeyError, RuntimeError, ParseError, subprocess.SubprocessError) as exc:
        print(f'Extraction failed: {exc}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
