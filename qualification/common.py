"""Explicitly invoked, read-only native audio qualification."""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from hehawk_verify_audio import verify, probe


def run(codec, count, packet_hash, pcm_hash, diagnostic=None):
    parser = argparse.ArgumentParser(description=f'Qualify {codec} against a known specimen')
    parser.add_argument('source', type=Path)
    parser.add_argument('--stream', type=int, required=True)
    parser.add_argument('--temp-dir', type=Path, required=True)
    parser.add_argument('--media-root', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    media = args.media_root.resolve(strict=True)
    temp = args.temp_dir.resolve(strict=True)
    if not media.is_mount() or not source.is_relative_to(media):
        parser.error('Source must be on the mounted media root')
    if temp.is_relative_to(media) or media.is_relative_to(temp):
        parser.error('Temporary directory must be separate from media root')
    if not temp.is_dir() or shutil.disk_usage(temp).free < source.stat().st_size + 20 * 1024**3:
        parser.error('Insufficient temporary storage or invalid directory')
    if probe(source, args.stream)['codec_name'] != codec:
        parser.error('Unexpected source codec')
    def signature():
        s = source.stat()
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns
    before = signature()
    with tempfile.TemporaryDirectory(prefix=f'qualify-{codec}-', dir=temp) as directory:
        resource = Path(directory) / 'native.mka'
        subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-xerror','-n','-copyts','-i',str(source),'-map',f'0:{args.stream}','-c:a','copy','-map_metadata','-1','-map_chapters','-1','-avoid_negative_ts','disabled','-f','matroska',str(resource)], check=True)
        report = verify(source, resource, args.stream, 0, decode=True)
        print(json.dumps(report, indent=2))
        expected = {'count': count, 'sha256': packet_hash}
        checks = {'source unchanged': signature() == before,
                  'schema': report['schema_version'] == 3,
                  'native preservation': report['native_preservation_passed'] is True,
                  'source packets': report['source_packets'] == expected,
                  'resource packets': report['resource_packets'] == expected,
                  'decoded match': report['decoded_match'] is True,
                  'clean equivalence': report['clean_decoded_equivalence'] is (diagnostic is None),
                  'strict result': report['passed'] is (diagnostic is None)}
        for key in ('source_decoder','resource_decoder'):
            d = report[key]
            checks[key] = (d['execution'] == 'completed' and d['exit_status'] == 0 and d['sha256'] == pcm_hash and (d['integrity'] == 'no_diagnostics' and not d['diagnostics'] if diagnostic is None else d['integrity'] == 'reported' and diagnostic in d['diagnostics'] and all(diagnostic in line or 'Last message repeated' in line for line in d['diagnostics'].splitlines() if line.strip())))
        for name, passed in checks.items():
            print(f'{"PASS" if passed else "FAIL"}: {name}')
        passed = all(checks.values())
    print(f'Qualification {"PASS" if passed else "FAIL"}: {codec}')
    return 0 if passed else 1
