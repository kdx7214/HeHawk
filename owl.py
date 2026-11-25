#!/usr/bin/env python3
"""OWL V1: local series knowledge, not automatic transcription correction."""
import argparse
import json
import os
import tempfile
import unicodedata
import uuid
from pathlib import Path

STATES = ('discovered', 'supported', 'verified', 'rejected')
KINDS = ('character', 'term', 'location', 'alias', 'other')


def norm(s):
    return ' '.join(unicodedata.normalize('NFKC', s).casefold().split())


def nonempty(s):
    return isinstance(s, str) and bool(s.strip())


def validate(d):
    if not isinstance(d, dict) or d.get('schema') != 'hehawk.owl' or d.get('schema_version') != 1:
        raise ValueError('Unsupported OWL contract')
    if not nonempty(d.get('series')) or not isinstance(d.get('entries'), list):
        raise ValueError('Invalid series or entries')
    ids = set()
    for e in d['entries']:
        if not isinstance(e, dict) or not all(nonempty(e.get(k)) for k in ('id', 'canonical', 'source')):
            raise ValueError('Entry requires ID, canonical text and source')
        if e['id'] in ids or e.get('kind') not in KINDS or e.get('state') not in STATES:
            raise ValueError('Duplicate ID or invalid kind/state')
        ids.add(e['id'])
        if not isinstance(e.get('variants'), list) or not all(nonempty(v) for v in e['variants']):
            raise ValueError('Invalid variants')
        if not isinstance(e.get('notes'), str):
            raise ValueError('Invalid notes')
    return d


def load(path):
    return validate(json.loads(path.read_text(encoding='utf-8')))


def save(path, d, create=False):
    validate(d)
    payload = json.dumps(d, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if create:
        with path.open('x', encoding='utf-8') as f:
            f.write(payload)
        return
    # Atomic replacement for single-writer CLI use.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.owl-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('init', 'add', 'list', 'lookup', 'validate'):
        q = sub.add_parser(name)
        q.add_argument('file', type=Path)
        if name == 'init':
            q.add_argument('--series', required=True)
        elif name == 'add':
            q.add_argument('--canonical', required=True)
            q.add_argument('--kind', choices=KINDS, required=True)
            q.add_argument('--variant', action='append', default=[])
            q.add_argument('--state', choices=STATES, default='discovered')
            q.add_argument('--source', required=True)
            q.add_argument('--notes', default='')
        elif name == 'lookup':
            q.add_argument('query')
    a = p.parse_args()
    try:
        if a.command == 'init':
            a.file.parent.mkdir(parents=True, exist_ok=True)
            save(a.file, dict(schema='hehawk.owl', schema_version=1, series=a.series.strip(), entries=[]), create=True)
            print('Created', a.file)
            return
        d = load(a.file)
        if a.command == 'add':
            if any(norm(e['canonical']) == norm(a.canonical) and e['kind'] == a.kind for e in d['entries']):
                raise ValueError('Canonical entry already exists; no changes made')
            variants = list(dict.fromkeys(v.strip() for v in a.variant))
            d['entries'].append(dict(id=uuid.uuid4().hex, canonical=a.canonical.strip(), kind=a.kind, variants=variants, state=a.state, source=a.source.strip(), notes=a.notes))
            save(a.file, d)
            print('Added entry:', a.canonical)
        elif a.command == 'validate':
            print(f"Valid OWL V1: {len(d['entries'])} entries")
        else:
            entries = d['entries']
            if a.command == 'lookup':
                entries = [e for e in entries if norm(a.query) in [norm(e['canonical']), *(norm(v) for v in e['variants'])]]
            print(json.dumps(entries, ensure_ascii=False, indent=2))
            print(f'{len(entries)} entries; no automatic replacements')
    except (OSError, ValueError, TypeError) as exc:
        p.exit(1, f'OWL: {exc}\n')


if __name__ == '__main__':
    main()
