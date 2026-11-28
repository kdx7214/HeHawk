#!/usr/bin/env python3
"""Read-only native subtitle conservation verification."""

import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

from fractions import Fraction
from pathlib import Path

from hehawk_verify_packets import packet_digest


SUPPORTED_CODECS = frozenset({
    "ass",
    "mov_text",
    "hdmv_pgs_subtitle",
    "dvd_subtitle",
    "subrip",
})

INITIALIZATION_REQUIRED = frozenset({
    "ass",
    "mov_text",
    "dvd_subtitle",
})


def probe(path, index):
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-select_streams", str(index),
            "-show_streams",
            "-show_data_hash", "sha256",
            "-of", "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.stderr.strip():
        raise ValueError(result.stderr.strip())

    streams = json.loads(result.stdout)["streams"]

    if len(streams) != 1:
        raise ValueError("Expected one selected subtitle stream")

    stream = streams[0]

    if stream["codec_type"] != "subtitle":
        raise ValueError("Selected stream is not a subtitle")

    if stream["index"] != index:
        raise ValueError("Unexpected stream index")

    return stream


def signature(path):
    stat = path.stat()

    return (
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
    )


def initialization(stream):
    size = int(stream.get("extradata_size", 0))
    digest = stream.get("extradata_hash")

    if size < 0:
        raise ValueError("Invalid initialization data size")

    if size:
        if not isinstance(digest, str) or not re.fullmatch(
            r"SHA256:[0-9a-fA-F]{64}", digest
        ):
            raise ValueError("Missing or invalid initialization hash")

        digest = digest.lower()

    elif digest is not None:
        raise ValueError("Unexpected initialization hash")

    if (
        stream["codec_name"] in INITIALIZATION_REQUIRED
        and size == 0
    ):
        raise ValueError(
            "Required subtitle initialization data is absent"
        )

    return {
        "size": size,
        "sha256": digest,
    }


def canvas(stream):
    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))

    if width < 0 or height < 0:
        raise ValueError("Invalid subtitle canvas dimensions")

    if bool(width) != bool(height):
        raise ValueError("Incomplete subtitle canvas dimensions")

    if width == 0:
        return None

    return {
        "width": width,
        "height": height,
    }


def compare_canvas(codec, source, resource):
    a = canvas(source)
    b = canvas(resource)

    if codec == "dvd_subtitle":
        if a is None or b is None:
            return "required_dimensions_missing"

    if a == b:
        if a is None:
            return "not_reported"

        return "match"

    if codec == "hdmv_pgs_subtitle":
        if a is None and b is not None:
            return "resource_dimensions_discovered"

    return "mismatch"


def metadata_observations(source, resource):
    observations = {}

    fields = (
        "time_base",
        "start_pts",
        "start_time",
        "duration_ts",
        "duration",
        "nb_frames",
        "disposition",
        "tags",
    )

    for field in fields:
        a = source.get(field)
        b = resource.get(field)

        if a != b:
            observations[field] = {
                "source": a,
                "resource": b,
            }

    return observations


def verify(
    source,
    resource,
    source_index,
    resource_index=0,
):
    source = Path(source).resolve(strict=True)
    resource = Path(resource).resolve(strict=True)

    before = [
        signature(source),
        signature(resource),
    ]

    a = probe(source, source_index)
    b = probe(resource, resource_index)

    codec = a["codec_name"]

    if codec not in SUPPORTED_CODECS:
        raise ValueError(
            f"Unsupported subtitle codec: {codec}"
        )

    differences = []

    if codec != b["codec_name"]:
        differences.append("codec_name")

    ia = initialization(a)
    ib = initialization(b)

    if ia != ib:
        differences.append("initialization")

    canvas_status = compare_canvas(codec, a, b)

    if canvas_status in {
        "mismatch",
        "required_dimensions_missing",
    }:
        differences.append("canvas")

    pa = packet_digest(
        source,
        source_index,
        Fraction(a["time_base"]),
    )

    pb = packet_digest(
        resource,
        resource_index,
        Fraction(b["time_base"]),
    )

    packet_match = pa == pb

    native = not differences and packet_match

    after = [
        signature(source),
        signature(resource),
    ]

    if before != after:
        raise ValueError(
            "Input changed during verification"
        )

    return {
        "schema_version": 1,
        "verification_type": "native_subtitle",
        "packet_side_data": "ffprobe_exposed_fields",
        "source_stream": source_index,
        "resource_stream": resource_index,
        "source_codec": codec,
        "resource_codec": b["codec_name"],
        "source_initialization": ia,
        "resource_initialization": ib,
        "initialization_match": ia == ib,
        "source_canvas": canvas(a),
        "resource_canvas": canvas(b),
        "canvas_status": canvas_status,
        "metadata_differences": differences,
        "metadata_observations": metadata_observations(a, b),
        "source_packets": pa,
        "resource_packets": pb,
        "packet_match": packet_match,
        "native_preservation_passed": native,
        "rendering_equivalence": "unverified",
        "external_dependencies": "unverified",
        "timeline_mapping": "unverified",
        "passed": native,
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "source",
        type=Path,
    )

    parser.add_argument(
        "resource",
        type=Path,
    )

    parser.add_argument(
        "--source-stream",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--resource-stream",
        type=int,
        default=0,
    )

    args = parser.parse_args()

    try:
        report = verify(
            args.source,
            args.resource,
            args.source_stream,
            args.resource_stream,
        )

        print(json.dumps(report, indent=2))

        return 0 if report["passed"] else 1

    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ZeroDivisionError,
        ET.ParseError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            f"Verification failed: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    sys.exit(main())
