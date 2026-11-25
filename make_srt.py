#!/usr/bin/env python3
"""Convert Parakeet transcription JSON into SRT subtitles."""
import argparse
import json
from pathlib import Path
from word_timing import word_groups
from srt_format import build_groups, render_srt

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('input', type=Path)
args = parser.parse_args()
INPUT_FILE = args.input.expanduser()
OUTPUT_FILE = INPUT_FILE.with_suffix('.srt')
with INPUT_FILE.open(encoding='utf-8') as f:
    data = json.load(f)
offset = data['source_offset_seconds']
words = [dict(text=w, start=s+offset, end=e+offset)
         for w,a,b,s,e in word_groups(data['tokens'], data['timestamps'],
                                     data['durations'], 0, len(data['tokens']))]
groups = build_groups(words)
OUTPUT_FILE.write_text(render_srt(groups), encoding='utf-8')
print(f'Created {OUTPUT_FILE}')
print(f'Words processed: {len(words)}')
print(f'Subtitle cues:   {len(groups)}')
