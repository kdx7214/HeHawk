#!/usr/bin/env python3
"""Coordinate the local subtitle processing scripts."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SCRIPTS = Path(__file__).resolve().parent


def run(*args):
    cmd = [str(a) for a in args]
    print('\n>>> ' + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, check=True)


def script(name, *args):
    run(sys.executable, SCRIPTS / name, *args)


def ready(path):
    if path.exists():
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Invalid existing output: {path}')
        return True
    return False


def stage(output, name, *args):
    if ready(output):
        print(f'Reusing: {output.name}', flush=True)
        return
    script(name, *args)
    if not ready(output):
        raise ValueError(f'Expected output was not created: {output}')


def extract(video, output, index):
    if ready(output):
        print(f'Reusing: {output.name}')
        return
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 's',
                             '-show_streams', '-of', 'json', str(video)],
                            check=True, capture_output=True, text=True)
    streams = json.loads(result.stdout).get('streams', [])
    if not streams:
        raise ValueError('No embedded subtitles. Use --no-reference to transcribe only.')
    text_codecs = {'ass', 'ssa', 'subrip', 'mov_text', 'webvtt', 'text'}
    print('\nAvailable subtitle streams:')
    for s in streams:
        tags = s.get('tags', {})
        print(f"  {s['index']}: {s.get('codec_name')} | {tags.get('language', 'und')} | {tags.get('title', '')}")
    if index is None:
        candidates = [s for s in streams if s.get('codec_name') in text_codecs]
        english = [s for s in candidates if s.get('tags', {}).get('language', '').lower() in ('eng', 'en')]
        candidates = english or [s for s in candidates if s.get('tags', {}).get('language', 'und').lower() in ('und', '')]
        if len(candidates) != 1:
            raise ValueError('Cannot choose a unique English/untagged text track. Specify --stream INDEX from the list above.')
        chosen = candidates[0]
    else:
        chosen = next((s for s in streams if s['index'] == index), None)
        if chosen is None or chosen.get('codec_name') not in text_codecs:
            raise ValueError('Selected stream is not a supported text subtitle track.')
    codec = 'copy' if chosen['codec_name'] == 'ass' else 'ass'
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        temp = Path(tmp) / 'reference.ass'
        run('ffmpeg', '-nostdin', '-n', '-i', video, '-map', f"0:{chosen['index']}", '-c:s', codec, temp)
        if not ready(temp):
            raise ValueError('Subtitle extraction produced no output.')
        # Exclusive creation protects an existing reference.
        with output.open('xb') as dst, temp.open('rb') as src:
            shutil.copyfileobj(src, dst)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Apply existing review decisions')
    mode.add_argument('--no-reference', action='store_true', help='Generate SRT without comparison')
    parser.add_argument('--stream', type=int, help='Absolute FFmpeg subtitle stream index')
    args = parser.parse_args()
    video = args.video.resolve()
    if not video.is_file():
        raise ValueError(f'Video not found: {video}')
    base = video.stem
    folder = video.parent
    original = folder / (base + '_original.ass')
    transcription = folder / (base + '.json')
    srt = folder / (base + '.srt')
    report = folder / (base + '_comparison.txt')
    review = folder / (base + '_review_v4_timing.txt')
    corrected = folder / (base + '_corrected.json')
    final = folder / (base + '_corrected.srt')
    # The transcription model uses paths relative to the script directory.
    os.chdir(SCRIPTS)
    if args.apply:
        if not ready(review) or not ready(transcription):
            raise ValueError('Review and original transcription must exist before applying corrections.')
        script('apply_review.py', review, transcription, '-o', corrected)
        # Generate in a temporary directory so a failure cannot truncate the old SRT.
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            temp_json = Path(tmp) / corrected.name
            shutil.copy2(corrected, temp_json)
            script('make_srt.py', temp_json)
            temp_srt = temp_json.with_suffix('.srt')
            if not ready(temp_srt):
                raise ValueError('Corrected SRT was not created.')
            if ready(final):
                backup = Path(tmp) / 'backup.srt'
                shutil.copy2(final, backup)
                os.replace(backup, final.with_name(final.name + '.old'))
            os.replace(temp_srt, final)
        print(f'\nCorrected subtitles: {final}')
        return
    if not args.no_reference:
        extract(video, original, args.stream)
    stage(transcription, 'transcribe.py', video)
    # Regenerate from the original JSON using current timing rules.
    # Preserve an existing SRT if the generated content differs.
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        temp_json = Path(tmp) / transcription.name
        shutil.copy2(transcription, temp_json)
        script('make_srt.py', temp_json)
        temp_srt = temp_json.with_suffix('.srt')
        if not ready(temp_srt):
            raise ValueError('Generated SRT was not created.')
        if ready(srt):
            if srt.read_bytes() != temp_srt.read_bytes():
                backup = Path(tmp) / 'backup.srt'
                shutil.copy2(srt, backup)
                os.replace(backup, srt.with_name(srt.name + '.old'))
                os.replace(temp_srt, srt)
        else:
            os.replace(temp_srt, srt)
    if args.no_reference:
        print(f'\nGenerated subtitles: {srt}')
        return
    stage(report, 'compare.py', transcription, original)
    stage(review, 'review.py', transcription, original, '-o', review)
    print(f'\nReview ready: {review}\nEdit the review, then rerun with --apply.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'\nERROR: {exc}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nInterrupted.', file=sys.stderr)
        sys.exit(130)
