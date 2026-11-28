"""Read-only regression checks against the local HeHawk media library."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path('/mnt/disk3')
# path, audio index, audio status, subtitle index, subtitle status, preserved, authorization
CASES = [
    ('Series/Angel (1999)/Season 3/S03E01.mkv', 1, 'english_default', 2, 'english_unique', [2], 'metadata_english'),
    ('Movies/The Adam Project (2022).mp4', 1, 'english_default', 2, 'english_default', [2], 'metadata_english'),
    ('Series/The Tomorrow People (1973)/Season 1/S01E01.mkv', 1, 'english_default', None, 'absent', [], 'metadata_english'),
    ('Series/Misfits of Science (1985)/Season 1/S01E01.mkv', 1, 'english_default', None, 'absent', [], 'metadata_english'),
    ('Movies/Let The Right One In (European).avi', 1, 'provisional_language', None, 'absent', [], 'confirmation_required'),
    ('Series/Supernatural (2005)/Season 1/S01E01.mkv', 1, 'english_default', None, 'special_purpose_only', [2], 'metadata_english'),
    ('Movies/Coco (2017).mkv', 1, 'english_default', None, 'unsupported', [2], 'metadata_english'),
    ('Movies/Doctor Strange in the Multiverse of Madness (2022).mkv', 1, 'english_default', None, 'special_purpose_only', [2], 'metadata_english'),
    ('Series/Inuyasha (2000)/Season 1/S01E01.mkv', 1, 'english_default', None, 'unsupported', [3], 'metadata_english'),
    ("Movies/Assassin's Creed (2016).mkv", 1, 'english_default', None, 'unsupported', [2], 'metadata_english'),
]


def main():
    passed = 0
    for path, ai, ac, si, sc, preserve, auth in CASES:
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve().with_name('hehawk.py')), str(ROOT / path)], capture_output=True, text=True, check=True, timeout=150)
            data = json.loads(result.stdout)
            t = data['track_selection']
            actual = (t['audio']['selected_index'], t['audio']['status_code'], t['subtitle']['selected_index'], t['subtitle']['status_code'], t['subtitle_preserve_indices'], t['english_recognition_authorization'], t['relationship'], t['recognition_ready'])
            expected = (ai, ac, si, sc, preserve, auth, 'unverified', False)
            if actual != expected:
                print(f'FAIL {path}\n  Expected: {expected}\n  Actual:   {actual}', flush=True)
                continue
            passed += 1
            print(f'PASS {path}\n  Audio: {ai} ({ac}); subtitle: {si} ({sc}); preserve: {preserve}; authorization: {auth}', flush=True)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
            print(f'FAIL {path}: {exc}', flush=True)
    print(f'\n{passed}/{len(CASES)} passed')
    return 0 if passed == len(CASES) else 1


if __name__ == '__main__':
    sys.exit(main())
