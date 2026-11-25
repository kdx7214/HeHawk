"""Experimental identity-independent CHIRP detector; no model inference."""
import argparse
import hashlib
import json
import math
from pathlib import Path

SCALES = ('0.75', '1.5', '3.0')
SETTINGS = dict(min_primary_contrast=0.07, min_prominence=0.05,
                min_support_contrast=0.10, support_radius_seconds=0.75,
                prominence_radius_seconds=1.0, primary_separation_seconds=0.75)


def peaks(rows, scale, step):
    points = {round(r['time_seconds'], 6): r['scales'][scale]
              for r in rows if scale in r['scales'] and
              r['scales'][scale]['contrast'] is not None}
    result = []
    for t, s in sorted(points.items()):
        c = s['contrast']
        before = points.get(round(t-step, 6))
        after = points.get(round(t+step, 6))
        if before is None or after is None or not (c > 0 and c >= before['contrast'] and c > after['contrast']):
            continue
        radius = SETTINGS['prominence_radius_seconds']
        left = [v['contrast'] for u,v in points.items() if t-radius <= u < t]
        right = [v['contrast'] for u,v in points.items() if t < u <= t+radius]
        prominence = c-max(min(left), min(right))
        result.append(dict(time_seconds=t, scale_seconds=float(scale), contrast=c,
                           prominence=prominence, cross_similarity=s['cross_similarity'],
                           left_rms=s['left_rms'], right_rms=s['right_rms'],
                           rms_change_db=20*math.log10(max(s['right_rms'],1e-12)/max(s['left_rms'],1e-12))))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('evidence', type=Path)
    p.add_argument('--json', required=True, type=Path)
    a = p.parse_args()
    if a.json.exists(): p.error('Output already exists')
    raw = a.evidence.read_bytes()
    d = json.loads(raw)
    if (d.get('schema'),d.get('schema_version'),d.get('timestamp_basis')) != ('hehawk.chirp.local_transitions',1,'episode'):
        p.error('Unsupported evidence schema')
    step = d['settings']['stride_seconds']
    if step != 0.25: p.error('V1 expects 0.25-second stride')
    all_peaks = {s:peaks(d['observations'],s,step) for s in SCALES}
    candidates = []
    for peak in all_peaks['1.5']:
        t = peak['time_seconds']
        support = {}
        for scale in ('0.75','3.0'):
            nearby = [q for q in all_peaks[scale] if abs(q['time_seconds']-t)<=SETTINGS['support_radius_seconds'] and q['contrast']>=SETTINGS['min_support_contrast'] and q['prominence']>=SETTINGS['min_prominence']]
            support[scale] = min(nearby,key=lambda q:(abs(q['time_seconds']-t),-q['contrast'])) if nearby else None
        eligible = peak['contrast']>=SETTINGS['min_primary_contrast'] and peak['prominence']>=SETTINGS['min_prominence'] and any(support.values())
        candidates.append(dict(primary=peak,support=support,status='ELIGIBLE' if eligible else 'WEAK'))
    accepted = []
    for c in sorted(candidates,key=lambda c:(-c['primary']['contrast'],c['primary']['time_seconds'])):
        if c['status']!='ELIGIBLE': continue
        t=c['primary']['time_seconds']
        if any(abs(t-q['primary']['time_seconds'])<SETTINGS['primary_separation_seconds'] for q in accepted):
            c['status']='NEAR_STRONGER_PEAK'
        else:
            c['status']='PROPOSED'; accepted.append(c)
    accepted.sort(key=lambda c:c['primary']['time_seconds'])
    result=dict(schema='hehawk.chirp.consensus',schema_version=1,timestamp_basis='episode', evidence_sha256=hashlib.sha256(raw).hexdigest(),source_sha256=d['source_sha256'],source_offset_seconds=d['source_offset_seconds'],settings=SETTINGS,peaks=all_peaks,candidates=candidates,proposed_transitions=accepted)
    with a.json.open('x') as f: json.dump(result,f,indent=2,allow_nan=False)
    print('CHIRP CONSENSUS V1 — provisional transitions')
    print('Relative   Episode    Contrast  Prominence  Support       RMS change')
    for c in accepted:
        q=c['primary']; t=q['time_seconds']; support=','.join(s for s,v in c['support'].items() if v)
        print(f"{t-d['source_offset_seconds']:8.2f} {t:9.2f} {q['contrast']:10.3f} {q['prominence']:11.3f}  {support:12s} {q['rms_change_db']:+7.1f} dB")
    print(f'Proposed: {len(accepted)}; primary peaks: {len(candidates)}')
    print('All peaks and rejected candidates preserved in JSON.')

if __name__=='__main__': main()
