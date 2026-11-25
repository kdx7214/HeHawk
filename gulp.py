#!/usr/bin/env python3
"""GULP: local subtitle ingestion and conservative SRT conversion."""
import argparse
import hashlib
import html
import json
import re
from pathlib import Path


def timestamp(value):
    m = re.fullmatch(r'(\d+):(\d{2}):(\d{2})[,.](\d{1,3})', value.strip())
    if not m:
        raise ValueError(f'Invalid timestamp: {value}')
    h, minute, sec, fraction = m.groups()
    if int(minute) >= 60 or int(sec) >= 60:
        raise ValueError(f'Invalid timestamp: {value}')
    return (int(h)*3600 + int(minute)*60 + int(sec))*1000 + int(fraction.ljust(3, '0'))


def srt_time(ms):
    sec, frac = divmod(ms, 1000)
    minute, sec = divmod(sec, 60)
    hour, minute = divmod(minute, 60)
    return f'{hour:02}:{minute:02}:{sec:02},{frac:03}'


def render(parts):
    plain, display = [], []
    active = ()
    for text, bold, italic in parts:
        plain.append(text)
        wanted = tuple(tag for tag, enabled in [('b', bold), ('i', italic)] if enabled)
        for i, line in enumerate(text.split('\n')):
            if i:
                display.extend(f'</{tag}>' for tag in reversed(active))
                active = ()
                display.append('\n')
            if not line:
                continue
            common = 0
            while common < min(len(active), len(wanted)) and active[common] == wanted[common]:
                common += 1
            display.extend(f'</{tag}>' for tag in reversed(active[common:]))
            display.extend(f'<{tag}>' for tag in wanted[common:])
            active = wanted
            display.append(html.escape(line, quote=False))
    display.extend(f'</{tag}>' for tag in reversed(active))
    return ''.join(plain), ''.join(display)


def clean_srt(raw):
    parts = []
    bold = italic = False
    for token in re.split(r'(<[^>\n]+>|\{\\[^}]*\})', raw):
        tag = token.lower()
        if tag == '<b>': bold = True
        elif tag == '</b>': bold = False
        elif tag == '<i>': italic = True
        elif tag == '</i>': italic = False
        elif re.fullmatch(r'</?(?:font|u|s|strike|span)(?:\s[^>]*)?>', tag): pass
        elif re.fullmatch(r'<br\s*/?>', tag): parts.append(('\n', bold, italic))
        elif token.startswith('{\\'): pass
        else: parts.append((html.unescape(token), bold, italic))
    return render(parts)


def clean_ass(raw, style, styles):
    base = styles.get(style.casefold(), (False, False))
    bold, italic = base
    drawing = False
    parts = []
    for token in re.split(r'(\{[^}]*\})', raw):
        if token.startswith('{') and token.endswith('}'):
            # Ignore nested transform commands rather than applying animated styles.
            block = re.sub(r'\\[a-zA-Z]+\([^)]*\)', '', token[1:-1])
            for command in re.findall(r'\\([^\\]+)', block):
                command = command.strip()
                if re.fullmatch(r'b-?\d+', command): bold = int(command[1:]) != 0
                elif re.fullmatch(r'i-?\d+', command): italic = int(command[1:]) != 0
                elif command == 'b': bold = base[0]
                elif command == 'i': italic = base[1]
                elif command.startswith('r'):
                    bold, italic = styles.get(command[1:].strip().casefold(), base)
                    drawing = False
                elif re.fullmatch(r'p\d+', command): drawing = int(command[1:]) != 0
        elif not drawing:
            parts.append((token.replace(r'\N', '\n').replace(r'\n', ' ').replace(r'\h', '\u00a0'), bold, italic))
    return render(parts)


def cue(index, start, end, raw, cleaned, speaker=None):
    start, end = timestamp(start), timestamp(end)
    if end <= start:
        raise ValueError(f'Cue {index}: end must follow start')
    plain, display = cleaned
    return dict(id=index, start_ms=start, end_ms=end, original_text=raw,
                comparison_text=' '.join(plain.split()), display_text=display,
                speaker=speaker or None)


def parse_srt(text):
    cues = []
    for block in re.split(r'\n[ \t]*\n', text.strip()):
        lines = block.splitlines()
        if not lines: continue
        if lines[0].strip().isdigit(): lines.pop(0)
        if not lines or '-->' not in lines[0]:
            raise ValueError(f'Invalid SRT cue near cue {len(cues)+1}')
        start, end = lines.pop(0).split('-->', 1)
        raw = '\n'.join(lines)
        cues.append(cue(len(cues)+1, start, end.strip().split()[0], raw, clean_srt(raw)))
    return cues


def parse_ass(text):
    section = ''
    fields = []
    styles = {}
    events = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            section = line.casefold(); fields = []; continue
        key, sep, value = line.partition(':')
        if not sep: continue
        key = key.casefold().strip()
        if key == 'format': fields = [x.strip().casefold() for x in value.split(',')]
        elif key == 'style' and section in ('[v4 styles]', '[v4+ styles]', '[v4++ styles]'):
            if not fields: raise ValueError('ASS style missing Format declaration')
            row = dict(zip(fields, (x.strip() for x in value.split(','))))
            styles[row['name'].casefold()] = (int(row.get('bold','0')) != 0, int(row.get('italic','0')) != 0)
        elif key == 'dialogue' and section == '[events]':
            if not fields or fields[-1] != 'text': raise ValueError('ASS event requires Format with Text last')
            values = value.lstrip().split(',', len(fields)-1)
            if len(values) != len(fields): raise ValueError('Malformed ASS dialogue')
            events.append(dict(zip(fields, values)))
    cues = []
    for row in events:
        raw = row['text']
        cues.append(cue(len(cues)+1, row['start'], row['end'], raw,
                        clean_ass(raw, row.get('style','Default').strip(), styles),
                        row.get('name', row.get('actor','')).strip()))
    return cues


def ingest(path):
    raw = path.read_bytes()
    text = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
    text = text.replace('\r\n','\n').replace('\r','\n')
    fmt = 'ass' if re.search(r'^\[Events\]\s*$', text, re.I|re.M) else 'srt'
    cues = parse_ass(text) if fmt == 'ass' else parse_srt(text)
    if not cues: raise ValueError('No dialogue cues found')
    return dict(schema='hehawk.gulp', schema_version=1, timestamp_basis='source',
                source=path.name, source_sha256=hashlib.sha256(raw).hexdigest(),
                format=fmt, cues=cues)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['ingest','convert'])
    parser.add_argument('input', type=Path)
    parser.add_argument('-o','--output', type=Path)
    args = parser.parse_args()
    try:
        data = ingest(args.input)
        output = args.output or args.input.with_suffix('.gulp.json' if args.command == 'ingest' else '.clean.srt')
        if args.command == 'ingest':
            result = json.dumps(data, ensure_ascii=False, indent=2)+'\n'
        else:
            cues = sorted((c for c in data['cues'] if c['comparison_text']), key=lambda c:c['start_ms'])
            result = '\n'.join(f"{i}\n{srt_time(c['start_ms'])} --> {srt_time(c['end_ms'])}\n{c['display_text']}\n" for i,c in enumerate(cues,1))
        with output.open('x', encoding='utf-8') as f: f.write(result)
        print(f"Read {len(data['cues'])} cues ({data['format']}); wrote {output}")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'GULP: {exc}\n')

if __name__ == '__main__': main()
