"""Shared subtitle formatting. All input times are episode-relative seconds."""
import math
import re

MAX_LINE_LENGTH = 42
MAX_LINES = 2
PAUSE_BREAK = 0.65
MIN_CUE_DURATION = 0.60
END_PADDING = 0.12


def wrap_text(text):
    lines = []
    for word in text.split():
        if lines and len(lines[-1]) + 1 + len(word) <= MAX_LINE_LENGTH:
            lines[-1] += ' ' + word
        else:
            lines.append(word)
    return lines


def group_text(group):
    return ' '.join(w['text'] for w in group)


def build_groups(words):
    groups, current = [], []
    for w in words:
        if not (math.isfinite(w['start']) and math.isfinite(w['end']) and 0 <= w['start'] <= w['end']):
            raise ValueError('Invalid timing interval')
        if not w['text'].strip():
            continue
        if current:
            prev = current[-1]
            if (w.get('isolated') or prev.get('isolated') or
                re.search(r'''[.!?]["')\]]*$''', prev['text']) or
                w['start'] - prev['end'] >= PAUSE_BREAK or
                len(wrap_text(group_text(current + [w]))) > MAX_LINES):
                groups.append(current)
                current = []
        current.append(w)
    if current:
        groups.append(current)
    return groups


def timestamp(ms):
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def render_srt(groups):
    cues = []
    for i, group in enumerate(groups):
        lines = wrap_text(group_text(group))
        if len(lines) > MAX_LINES or any(len(x) > MAX_LINE_LENGTH for x in lines):
            raise ValueError(f'Cue {i+1} exceeds formatting limits; review text required')
        start = round(group[0]['start'] * 1000)
        end = max(start + round(MIN_CUE_DURATION * 1000),
                  round((max(w['end'] for w in group) + END_PADDING) * 1000))
        if i+1 < len(groups):
            next_start = round(groups[i+1][0]['start'] * 1000)
            end = min(end, max(start+1, next_start-20), next_start)
        if end <= start:
            raise ValueError(f'Cue {i+1} has no positive display interval; review timing required')
        cues.append(f'{i+1}\n{timestamp(start)} --> {timestamp(end)}\n' + '\n'.join(lines))
    return '\n\n'.join(cues) + ('\n' if cues else '')
