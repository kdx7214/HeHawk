#!/usr/bin/env python3
"""Shared native media packet conservation verification."""
import hashlib
import json
import subprocess
from fractions import Fraction


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
        raise ValueError('No packets')
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
