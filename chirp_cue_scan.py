#!/usr/bin/env python3
"""CHIRP cue-centric experiment: read-only speaker evidence, no automatic edits."""
import argparse
import hashlib
import json
from pathlib import Path


def scan(cues, segments, words, peaks, start, end):
    results = []
    for cue in cues:
        a, b = cue['start_ms']/1000, cue['end_ms']/1000
        if a >= end or b <= start:
            continue
        lo, hi = max(a,start), min(b,end)
        hits = [dict(s, clipped_start=max(lo,s['start_seconds']),
                     clipped_end=min(hi,s['end_seconds'])) for s in segments
                if s['start_seconds'] < hi and s['end_seconds'] > lo]
        edges = sorted({lo,hi} | {s[k] for s in hits for k in ('clipped_start','clipped_end')})
        spans = []
        for x,y in zip(edges,edges[1:]):
            labels = sorted({s['speaker'] for s in hits if s['clipped_start'] < y and s['clipped_end'] > x})
            if spans and spans[-1]['speakers']==labels:
                spans[-1]['end']=y
            else:
                spans.append(dict(start=x,end=y,speakers=labels))
        turns=[]
        for s in spans:
            if not s['speakers']:
                continue
            if turns and turns[-1]['speakers']==s['speakers']:
                turns[-1]['end']=s['end']
            else:
                turns.append(dict(s))
        changes=[]
        for left,right in zip(turns,turns[1:]):
            x,y=left['end'],right['start']
            changes.append(dict(left=left['speakers'],right=right['speakers'],
                                bracket_start=x,bracket_end=y,
                                acoustic=[p for p in peaks if x<=p['primary']['time_seconds']<=y]))
        labels=sorted({s['speaker'] for s in hits})
        overlap=sum(s['end']-s['start'] for s in spans if len(s['speakers'])>1)
        speech=sum(s['end']-s['start'] for s in spans if s['speakers'])
        lexical=[]
        for w in words:
            x,y=max(lo,w['start_seconds']),min(hi,w['end_seconds'])
            if y<=x: continue
            covered=sum(max(0,min(y,s['end'])-max(x,s['start'])) for s in spans if s['speakers'])
            lexical.append(dict(w,coverage_fraction=min(1,covered/(y-x))))
        flags=[]
        if lo>a or hi<b: flags.append('PARTIAL_AUDIO_WINDOW')
        if not hits: flags.append('NO_DIARIZED_SPEECH')
        if any(w['coverage_fraction']<0.999 for w in lexical): flags.append('INCOMPLETE_WORD_COVERAGE')
        if overlap>0: flags.append('OVERLAPPING_SPEAKERS')
        if len(labels)>1: flags.append('MULTIPLE_SPEAKERS_REVIEW')
        if not lexical: flags.append('NO_RECOGNIZED_WORDS')
        results.append(dict(cue_id=cue['id'],start=a,end=b,flags=flags,
                            distinct_speakers=len(labels),speaker_activity_runs=len(turns),
                            sequential_turn_count=len(turns) if overlap==0 else None,
                            speech_seconds=speech,overlap_seconds=overlap,
                            segments=hits,activity=spans,changes=changes,words=lexical,
                            acoustic=[p for p in peaks if lo<p['primary']['time_seconds']<hi]))
    return results


def main():
    from gulp import ingest
    from chirp_diarization_correlate import words_from, diarization_segments
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('subtitles','diarization','consensus','recognition'):
        p.add_argument(name,type=Path)
    p.add_argument('--json',required=True,type=Path)
    a=p.parse_args()
    paths=[a.subtitles,a.diarization,a.consensus,a.recognition]
    raw=[x.read_bytes() for x in paths]
    d,c,r=map(json.loads,raw[1:])
    if not d.get('source_sha256') or d['source_sha256']!=c.get('source_sha256'):
        p.error('Diarization and consensus audio hashes differ or are absent')
    if (c.get('schema'),c.get('schema_version'),c.get('timestamp_basis'))!=('hehawk.chirp.consensus',1,'episode'):
        p.error('Unsupported consensus schema')
    start=float(d['source_offset_seconds']); end=start+float(d['duration_seconds'])
    if start!=float(c['source_offset_seconds']): p.error('Audio offsets differ')
    cues=ingest(a.subtitles)['cues']
    rows=scan(cues,diarization_segments(d,'regular'),words_from(r),c['candidates'],start,end)
    report=dict(schema='hehawk.chirp.cue_scan',schema_version=1,timestamp_basis='episode',
                sources=[dict(path=str(x),sha256=hashlib.sha256(y).hexdigest()) for x,y in zip(paths,raw)],
                audio_window=[start,end],total_cues=len(cues),scanned_cues=len(rows),cues=rows)
    with a.json.open('x',encoding='utf-8') as f: json.dump(report,f,indent=2,ensure_ascii=False,allow_nan=False)
    print(f'Scanned {len(rows)} of {len(cues)} cues; audio window {start:.3f}–{end:.3f}')
    for row in rows:
        print(f"Cue {row['cue_id']:4} {row['start']:9.3f}–{row['end']:9.3f} speakers={row['distinct_speakers']} turns={row['sequential_turn_count']} overlap={row['overlap_seconds']:.3f} flags={','.join(row['flags']) or 'none'}")

if __name__=='__main__': main()
