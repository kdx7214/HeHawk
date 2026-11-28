"""Phase 5A: read-only resource planning; no extraction or publication."""
import argparse
import json
import shutil
import sys
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from hehawk import inspect
from hehawk_tracks import recommend
from hehawk_workspace import preflight, safe_path


def plan(inventory, config):
    media, root, mount = preflight(config)
    source = Path(inventory['source']).resolve(strict=True)
    relative = source.relative_to(media)
    project_rel = Path('projects') / relative.with_suffix('')
    manifest = safe_path(root, project_rel / 'project.json', mount)
    project = json.loads(manifest.read_text())
    stat = source.stat()
    if (project.get('schema_version') != 1 or
            project.get('media_relative_path') != relative.as_posix() or
            project.get('source_size') != stat.st_size):
        raise ValueError('Project/source mismatch; reconciliation required')
    selection = recommend(inventory['streams'])
    streams = {s['index']: s for s in inventory['streams']}
    resources = []

    def add(index, kind, filename, dependency=None):
        rel = Path('resources') / filename
        path = safe_path(root, project_rel / rel, mount)
        resources.append({'id': f'{kind}-{index:03d}', 'kind': kind,
                          'source_stream': index,
                          'source_codec': streams[index].get('codec_name'),
                          'path': rel.as_posix(), 'dependency': dependency,
                          'status': 'existing_unverified' if path.exists() else 'planned',
                          'timeline_mapping': 'unverified'})

    audio = selection['audio']['selected_index']
    if audio is not None:
        add(audio, 'native_audio', f'audio/stream-{audio:03d}.mka')
        if selection['english_recognition_authorization'] == 'metadata_english':
            add(audio, 'recognition_pcm', f'audio/stream-{audio:03d}-16k-mono.wav',
                f'native_audio-{audio:03d}')
    for index in selection['subtitle_preserve_indices']:
        add(index, 'native_subtitle', f'subtitles/stream-{index:03d}.mks')
    duration = Decimal(str(inventory['format']['duration']))
    if not duration.is_finite() or duration <= 0:
        raise ValueError('Invalid duration; storage estimate unavailable')
    pcm = int((duration * 32000).to_integral_value(rounding=ROUND_CEILING)) if any(r['kind']=='recognition_pcm' for r in resources) else 0
    native = stat.st_size if resources else 0
    allowance = max(64 * 1024**2, native // 10) if resources else 0
    estimate = native + pcm + allowance
    free = shutil.disk_usage(mount).free
    reserve = int(config['minimum_free_gib'] * 1024**3)
    resource_manifest = safe_path(root, project_rel / 'resources/manifest.json', mount)
    return {'schema_version': 1, 'mode': 'plan_only', 'project_id': project['project_id'],
            'source': {'relative_path': relative.as_posix(), 'size': stat.st_size,
                       'mtime_ns': stat.st_mtime_ns, 'identity_verification': 'size_and_path_only'},
            'resources': resources, 'resource_manifest_exists': resource_manifest.exists(),
            'storage': {'native_budget_bytes': native, 'pcm_payload_bytes': pcm,
                        'overhead_allowance_bytes': allowance, 'estimated_bytes': estimate,
                        'free_bytes': free, 'reserve_bytes': reserve,
                        'estimate_fits': free >= reserve + estimate},
            'conflicts': [r['path'] for r in resources if r['status']=='existing_unverified'],
            'recognition_ready': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--config', type=Path, default=Path('hehawk_config.json'))
    args = parser.parse_args()
    try:
        result = plan(inspect(args.video), json.loads(args.config.read_text()))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result['storage']['estimate_fits'] and not result['conflicts'] and not result['resource_manifest_exists'] else 1
    except (OSError, ValueError, KeyError, ArithmeticError) as exc:
        print(f'Resource planning failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
