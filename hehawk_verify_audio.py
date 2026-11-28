#!/usr/bin/env python3
"""Read-only native audio conservation verification."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path


def probe(path, index):
    result = subprocess.run(['ffprobe','-v','error','-select_streams',str(index),
        '-show_streams','-show_data_hash','sha256','-of','json',str(path)],
        check=True, capture_output=True, text=True, timeout=120)
    if result.stderr.strip():
        raise ValueError(result.stderr.strip())
    streams = json.loads(result.stdout)['streams']
    if len(streams) != 1 or streams[0]['codec_type'] != 'audio':
        raise ValueError('Expected one selected audio stream')
    return streams[0]


def packet_digest(path, index, time_base):
    # XML preserves packet boundaries and nested side data without buffering
    # the entire inventory. Any diagnostic is a verification failure.
    import tempfile
    import xml.etree.ElementTree as ET
    args = ['ffprobe','-v','error','-select_streams',str(index),'-show_packets',
            '-show_data_hash','sha256','-show_entries',
            'packet=pts,dts,duration,size,data_hash:packet_side_data',
            '-of','xml',str(path)]
    digest = hashlib.sha256()
    count = 0
    with tempfile.TemporaryFile() as errors:
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors) as proc:
            try:
                stack = []
                for event, elem in ET.iterparse(proc.stdout, events=('start','end')):
                    if event == 'start':
                        stack.append(elem)
                        continue
                    if elem.tag == 'packet':
                        row = packet_record(elem, time_base)
                        digest.update((json.dumps(row,sort_keys=True,separators=(',',':'))+'\n').encode())
                        count += 1
                        stack[-2].remove(elem)
                    stack.pop()
            except BaseException:
                proc.kill()
                raise
            if proc.wait():
                raise ValueError('FFprobe packet inspection failed')
        errors.seek(0)
        if errors.read(1):
            raise ValueError('FFprobe reported packet inspection errors')
    if not count:
        raise ValueError('No audio packets')
    return {'count':count,'sha256':digest.hexdigest()}


def packet_record(elem, time_base):
    fields = elem.attrib
    if not all(k in fields for k in ('size','data_hash')):
        raise ValueError('Incomplete packet record')
    if not fields['data_hash'].startswith('SHA256:') or len(fields['data_hash']) != 71:
        raise ValueError('Missing packet payload hash')
    row = [str(Fraction(fields[k])*time_base) if fields.get(k,'N/A') != 'N/A' else None for k in ('pts','dts','duration')]
    def tree(node):
        return [node.tag, dict(node.attrib), (node.text or '').strip(), [tree(child) for child in node]]
    return row + [int(fields['size']), fields['data_hash'], [tree(child) for child in elem]]


def pcm_digest(path,index):
    result = subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-xerror',
        '-i',str(path),'-map',f'0:{index}','-c:a','pcm_f32le','-f','hash','-hash','sha256','-'],
        check=False,capture_output=True,text=True)
    value = result.stdout.strip()
    valid = result.returncode == 0 and re.fullmatch(r'SHA256=[0-9a-fA-F]{64}', value) is not None
    return {'execution':'completed' if result.returncode == 0 else 'failed',
        'exit_status':result.returncode,
        'integrity':'reported' if result.stderr.strip() else 'no_diagnostics',
        'diagnostics':result.stderr.strip(),
        'sha256':value[7:].lower() if valid else None}


def verify(source, resource, source_index, resource_index=0, decode=False):
    source,resource = Path(source).resolve(strict=True),Path(resource).resolve(strict=True)
    def signature(p):
        s=p.stat(); return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns
    before = [signature(p) for p in (source,resource)]
    a,b = probe(source,source_index),probe(resource,resource_index)
    keys=('codec_name','profile','sample_rate','channels','channel_layout','initial_padding','extradata_size','extradata_hash')
    differences=[k for k in keys if a.get(k)!=b.get(k)]
    if any(s.get('extradata_size',0) and not s.get('extradata_hash') for s in (a,b)):
        raise ValueError('Missing codec initialization hash')
    pa=packet_digest(source,source_index,Fraction(a['time_base']))
    pb=packet_digest(resource,resource_index,Fraction(b['time_base']))
    ca,cb=(pcm_digest(source,source_index),pcm_digest(resource,resource_index)) if decode else (None,None)
    da,db=(ca['sha256'],cb['sha256']) if decode else (None,None)
    equivalent = da == db if da is not None and db is not None else None
    native = not differences and pa == pb
    clean = equivalent is True and all(c['integrity']=='no_diagnostics' for c in (ca,cb))

    if before != [signature(p) for p in (source,resource)]:
        raise ValueError('Input changed during verification')
    return {'schema_version':3,'packet_side_data':'ffprobe_exposed_fields','source_stream':source_index,'resource_stream':resource_index,
        'metadata_differences':differences,'source_packets':pa,'resource_packets':pb,
        'packet_match':pa==pb,'source_pcm_sha256':da,'resource_pcm_sha256':db,
        'decoded_match':equivalent,'timeline_mapping':'unverified',
        'native_preservation_passed':native,'source_decoder':ca,'resource_decoder':cb,
        'clean_decoded_equivalence':clean if decode else None,
        'passed':native and (not decode or clean)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path); p.add_argument('resource',type=Path)
    p.add_argument('--source-stream',type=int,required=True)
    p.add_argument('--resource-stream',type=int,default=0)
    p.add_argument('--decode',action='store_true')
    a=p.parse_args()
    try:
        report=verify(a.source,a.resource,a.source_stream,a.resource_stream,a.decode)
        print(json.dumps(report,indent=2)); return 0 if report['passed'] else 1
    except (OSError,ValueError,KeyError,ET.ParseError,subprocess.SubprocessError) as exc:
        print(f'Verification failed: {exc}',file=sys.stderr); return 1

if __name__=='__main__':
    sys.exit(main())
