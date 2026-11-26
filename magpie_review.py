#!/usr/bin/env python3
"""MAGPIE 3C: local, read-only reconstruction review report."""
import argparse
import hashlib
import json
from pathlib import Path


def stamp(ms):
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02}.{ms:03}'


def ready(q):
    return (q['original_words_retained'] and q['candidate_words_retained']
            and not q['other_reference_conflicts'] and not q['foreign_anchor_cues']
            and not q['unanchored_original_cues'] and bool(q['anchor_indices']))


def report(data, digest):
    rows = [q for q in data['proposals'] if ready(q)]
    lines = ['MAGPIE 3C — LOCAL REVIEW ONLY', f'Proposal SHA256: {digest}',
             f'Eligible proposals: {len(rows)}',
             'Check wording, punctuation, speaker changes, sound descriptions, formatting and timing.',
             'No replacement is authorized by this report.', '']
    for q in rows:
        lines.extend(['=' * 72, f"CANDIDATE {q['candidate_id']} | {len(q['anchor_indices'])} exact anchors", 'ORIGINAL:'])
        for cue in q['original_cues']:
            lines.extend([f"Cue {cue['id']} | {stamp(cue['start_ms'])} --> {stamp(cue['end_ms'])}", cue['display_text'], ''])
        lines.append('PROPOSED:')
        for cue in q['parakeet_cues']:
            lines.extend([f"ASR cue {cue['id']} | {stamp(cue['start_ms'])} --> {stamp(cue['end_ms'])}", cue['text'], ''])
        lines.extend(['RECOVERED WORDS:', ' '.join(w['word'] for w in q['recognition_words']), '', 'Decision: PENDING', ''])
    return '\n'.join(lines) + '\n', rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('proposals', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    raw = a.proposals.read_bytes()
    data = json.loads(raw)
    if (data.get('schema'), data.get('schema_version')) != ('magpie_contextual_review', 1):
        p.error('Unsupported proposal schema')
    for source in data['sources']:
        if hashlib.sha256(Path(source['path']).read_bytes()).hexdigest() != source['sha256']:
            p.error('Source hash mismatch: ' + source['path'])
    content, rows = report(data, hashlib.sha256(raw).hexdigest())
    with a.output.open('x', encoding='utf-8') as f:
        f.write(content)
    print('Eligible candidates:', [q['candidate_id'] for q in rows])
    print('Created:', a.output)


if __name__ == '__main__':
    main()
