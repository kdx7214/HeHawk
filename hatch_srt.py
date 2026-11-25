#!/usr/bin/env python3
"""Export reviewed HATCH and OWL transcripts without inventing word timings."""
import argparse
import json
from pathlib import Path
from srt_format import build_groups, render_srt


def convert(data, preview=False):
    if data['schema'] not in ('hehawk.hatch', 'hehawk.owl.edited') or (data['schema_version'], data['timestamp_basis']) != (1, 'episode'):
        raise ValueError('Unsupported HATCH contract')
    pending = set(data['pending_groups'])
    pending.update(s['group_id'] for s in data['segments'] if s['text'] is None or s['issues'])
    if pending and not preview:
        raise ValueError(f'Unresolved groups: {sorted(pending)}; use --preview for a marked draft')
    words = []
    estimated = 0
    for s in data['segments']:
        gid = s['group_id']
        if gid in pending:
            words.append(dict(text=f'[REVIEW G{gid:03}]', start=s['start_seconds'], end=s['end_seconds'], isolated=True))
        elif s['text'] == '':
            continue
        elif s['timing_basis'] == 'observed' and s['selected']:
            obs = s['selected']['observation']
            source = obs['words']
            editorial = s.get('editorial_words')
            if not source:
                raise ValueError(f'Empty observation G{gid:03}')
            if editorial is not None:
                if data['schema'] != 'hehawk.owl.edited' or not s.get('owl_edits') or s.get('owl_original_text') != obs['text']:
                    raise ValueError(f'Invalid editorial provenance G{gid:03}')
                if len(source) != len(editorial) or any(
                    {k:v for k,v in a.items() if k != 'text'} !=
                    {k:v for k,v in b.items() if k != 'text'}
                    for a,b in zip(source, editorial)):
                    raise ValueError(f'Editorial timing or token mismatch G{gid:03}')
                if ' '.join(w['text'] for w in editorial) != s['text']:
                    raise ValueError(f'Editorial text mismatch G{gid:03}')
                source = editorial
            elif obs['text'] != s['text']:
                raise ValueError(f'Inconsistent observation G{gid:03}')
            words.extend(dict(text=w['text'], start=w['start_seconds'], end=w['end_seconds']) for w in source)
        elif s['timing_basis'] == 'estimated_group_interval' and not s['selected']:
            words.append(dict(text=s['text'], start=s['start_seconds'], end=s['end_seconds'], isolated=True))
            estimated += 1
        else:
            raise ValueError(f'Unsupported timing basis G{gid:03}')
    groups = build_groups(words)
    return render_srt(groups), len(groups), estimated, len(pending)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path)
    p.add_argument('-o', type=Path)
    p.add_argument('--preview', action='store_true')
    a = p.parse_args()
    output = a.o or a.input.with_suffix('.preview.srt' if a.preview else '.srt')
    try:
        data = json.loads(a.input.read_text(encoding='utf-8'))
        result, count, estimated, pending = convert(data, a.preview)
        with output.open('x', encoding='utf-8') as f:
            f.write(result)
    except (ValueError, KeyError, TypeError, OSError) as e:
        p.error(str(e))
    print(f'Created {output}')
    print(f'Subtitle cues: {count}; estimated groups: {estimated}; pending groups: {pending}')

if __name__ == '__main__':
    main()
