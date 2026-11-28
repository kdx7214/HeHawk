"""Register fresh verification evidence for an existing native audio resource."""
import argparse
import json
import sys
import subprocess
from pathlib import Path
from xml.etree.ElementTree import ParseError
from hehawk_workspace import preflight, safe_path
from hehawk_publication import project_lock, atomic_json, digest, validate_verification
from hehawk_verify_audio import verify


def signature(path):
    s = path.stat()
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def register(video, config, index, decode=False):
    if index < 0:
        raise ValueError('Invalid stream index')
    media, root, mount = preflight(config)
    if not media.is_mount():
        raise ValueError('Media mount unavailable')
    source = Path(video).resolve(strict=True)
    relative = source.relative_to(media)
    project = Path('projects') / relative.with_suffix('')
    resources = safe_path(root, project / 'resources', mount)
    manifest = resources / 'manifest.json'
    project_file = resources.parent / 'project.json'
    journal = resources / '.publication.json'
    target = resources / f'audio/stream-{index:03d}.mka'
    rid = f'native_audio-{index:03d}'
    original = signature(source)
    mount_identity = signature(mount)[:2]
    def check():
        if preflight(config) != (media, root, mount) or not media.is_mount() or signature(mount)[:2] != mount_identity:
            raise ValueError('Mount or configuration changed')
        if signature(source) != original:
            raise ValueError('Source changed')
        for p in (resources, manifest, project_file, journal, target, resources / '.publication.lock'):
            safe_path(root, p.relative_to(root), mount)
        if journal.exists():
            raise ValueError('Pending publication requires reconciliation')
    check()
    with project_lock(resources):
        check()
        state = json.loads(manifest.read_text())
        project_data = json.loads(project_file.read_text())
        entry = state['resources'][rid]
        provenance = entry['provenance']
        recorded = provenance['source']
        if (state['schema_version'] != 1 or project_data['schema_version'] != 1 or
            project_data['project_id'] != provenance['project_id'] or
            project_data['media_relative_path'] != relative.as_posix() or
            project_data['source_size'] != original[2] or
            recorded['relative_path'] != relative.as_posix() or recorded['size'] != original[2] or
            recorded['mtime_ns'] != original[3] or provenance['source_stream'] != index or
            entry['path'] != target.relative_to(resources).as_posix()):
            raise ValueError('Source or resource provenance mismatch')
        before = signature(target)
        if not target.is_file() or before[2] != entry['size'] or digest(target) != entry['sha256']:
            raise ValueError('Resource integrity mismatch')
        report = validate_verification(verify(source, target, index, 0, decode=decode))
        if report.get('packet_match') is not True or (decode and report.get('decoded_match') is not True):
            raise ValueError('Required comparison did not pass')
        check()
        if signature(target) != before or digest(target) != entry['sha256'] or signature(target) != before:
            raise ValueError('Resource changed during verification')
        check()
        previous = entry.get('verification')
        # Do not replace stronger evidence with a packet-only report.
        if not decode and isinstance(previous, dict) and previous.get('decoded_match') is True:
            raise ValueError('Existing PCM evidence requires --decode to refresh')
        changed = previous != report
        if changed:
            entry['verification'] = report
            atomic_json(manifest, state, replace=True)
        return {'status': 'registered' if changed else 'unchanged', 'resource_id': rid, 'resource': entry}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--stream', type=int, required=True)
    parser.add_argument('--decode', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(register(args.video, json.loads(args.config.read_text()), args.stream, args.decode), indent=2))
    except (OSError, ValueError, KeyError, RuntimeError, TypeError, ParseError, subprocess.SubprocessError) as exc:
        print(f'Registration failed: {exc}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
