#!/usr/bin/env python3
"""Phase 4: media inventory, workspace initialization and track recommendations."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from hehawk_nfo import inspect_nfo
from hehawk_workspace import initialize
from hehawk_tracks import recommend


def identify(path):
    result = {'type': 'unknown', 'nfo': None}
    episode = re.fullmatch(r'S(\d+)E(\d+)', path.stem, re.I)
    season = re.fullmatch(r'Season\s+(\d+)', path.parent.name, re.I)
    if episode and season and int(episode[1]) == int(season[1]):
        series = path.parent.parent
        title = re.fullmatch(r'(.+) \((\d{4})\)', series.name)
        nfo = series / 'tvshow.nfo'
        result.update(type='episode', series=title[1] if title else series.name,
                      year=int(title[2]) if title else None,
                      season=int(episode[1]), episode=int(episode[2]),
                      nfo=str(nfo), nfo_present=nfo.is_file())
    elif path.parent.name == 'Movies':
        title = re.fullmatch(r'(.+) \((\d{4})\)', path.stem)
        result.update(type='movie', title=title[1] if title else path.stem,
                      year=int(title[2]) if title else None)
    return result


def inspect(path):
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError('Source is not a regular file')
    proc = subprocess.run(['ffprobe', '-v', 'error', '-show_format',
                           '-show_streams', '-of', 'json', '-i', str(path)],
                          capture_output=True, text=True, check=True, timeout=120)
    data = json.loads(proc.stdout)
    identity = identify(path)
    metadata = inspect_nfo(identity['nfo'], identity) if identity.get('nfo') else None
    return {'source': str(path), 'identity': identity, 'nfo_metadata': metadata,
            'format': data.get('format', {}), 'streams': data.get('streams', [])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--config", type=Path, default=Path("hehawk_config.json"))
    args = parser.parse_args()
    try:
        result = inspect(args.video)
        result["track_selection"] = recommend(result["streams"])
        if args.init:
            result["workspace"] = initialize(result, json.loads(args.config.read_text()))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f'Inspection failed: {exc}', file=sys.stderr)
        if getattr(exc, 'stderr', None):
            print(exc.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
