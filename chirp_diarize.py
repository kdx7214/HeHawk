import argparse
import hashlib
import json
import time
from pathlib import Path

import soundfile as sf
import torch

from huggingface_hub import get_token
from pyannote.audio import Pipeline


MODEL = "pyannote/speaker-diarization-community-1"


def digest(path):

    h = hashlib.sha256()

    with path.open("rb") as f:

        for block in iter(
            lambda: f.read(1024 * 1024),
            b""
        ):
            h.update(block)

    return h.hexdigest()


def format_time(seconds):

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds %= 60

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:06.3f}"
    )


def collect(annotation, offset):

    segments = []

    for turn, _, speaker in annotation.itertracks(
        yield_label=True
    ):

        segments.append({
            "start_seconds": float(turn.start) + offset,
            "end_seconds": float(turn.end) + offset,
            "duration_seconds": float(turn.duration),
            "original_speaker": str(speaker)
        })

    segments.sort(
        key=lambda s: (
            s["start_seconds"],
            s["end_seconds"],
            s["original_speaker"]
        )
    )

    for i, segment in enumerate(segments):
        segment["id"] = f"S{i:05d}"

    return segments


def summarize(name, segments):

    speakers = {}

    for segment in segments:

        speaker = segment["original_speaker"]

        if speaker not in speakers:

            speakers[speaker] = {
                "segments": 0,
                "duration_seconds": 0.0
            }

        speakers[speaker]["segments"] += 1

        speakers[speaker]["duration_seconds"] += (
            segment["duration_seconds"]
        )

    print()
    print("=" * 76)
    print(name)
    print("=" * 76)

    print(f"Segments: {len(segments)}")
    print(f"Speakers: {len(speakers)}")
    print()

    print(
        f"{'Speaker':20s}"
        f"{'Segments':>10s}"
        f"{'Speech time':>18s}"
    )

    for speaker, stats in sorted(speakers.items()):

        print(
            f"{speaker:20s}"
            f"{stats['segments']:10d}"
            f"{format_time(stats['duration_seconds']):>18s}"
        )

    print()
    print("SEGMENT DURATION DISTRIBUTION")

    ranges = [
        (0.0, 0.5),
        (0.5, 1.0),
        (1.0, 1.5),
        (1.5, 3.0),
        (3.0, 5.0),
        (5.0, 10.0),
        (10.0, float("inf"))
    ]

    for lo, hi in ranges:

        count = sum(
            lo <= s["duration_seconds"] < hi
            for s in segments
        )

        print(
            f"  {lo:5.1f} - {hi:5.1f}s:"
            f" {count:6d}"
        )

    return speakers


def main():

    parser = argparse.ArgumentParser(
        description="CHIRP general-purpose diarization"
    )

    parser.add_argument(
        "audio",
        type=Path
    )

    parser.add_argument(
        "--source-offset",
        type=float,
        default=0.0
    )

    parser.add_argument(
        "--threads",
        type=int,
        default=8
    )

    parser.add_argument(
        "--json",
        type=Path,
        required=True
    )

    args = parser.parse_args()

    if args.json.exists():
        raise FileExistsError(args.json)

    if args.threads < 1:
        parser.error("Threads must be positive")

    if args.source_offset < 0:
        parser.error("Source offset cannot be negative")

    torch.set_num_threads(args.threads)

    print("CHIRP - General-purpose diarization")
    print(f"Model: {MODEL}")
    print(f"Audio: {args.audio}")
    print(f"Threads: {args.threads}")

    print()
    print("Reading audio...")

    audio, sample_rate = sf.read(
        args.audio,
        dtype="float32",
        always_2d=True
    )

    if len(audio) == 0:
        raise ValueError("Empty audio file")

    duration = len(audio) / sample_rate

    waveform = torch.from_numpy(
        audio.T.copy()
    )

    print(f"Sample rate: {sample_rate}")
    print(f"Channels: {waveform.shape[0]}")
    print(f"Duration: {format_time(duration)}")

    print()
    print("Loading diarization model...")

    pipeline = Pipeline.from_pretrained(
        MODEL,
        token=get_token()
    )

    pipeline.to(torch.device("cpu"))

    print("Model loaded.")
    print()
    print("Processing audio...", flush=True)

    started = time.perf_counter()

    result = pipeline({
        "waveform": waveform,
        "sample_rate": sample_rate
    })

    elapsed = time.perf_counter() - started

    regular = collect(
        result.speaker_diarization,
        args.source_offset
    )

    exclusive = collect(
        result.exclusive_speaker_diarization,
        args.source_offset
    )

    regular_stats = summarize(
        "REGULAR DIARIZATION",
        regular
    )

    exclusive_stats = summarize(
        "EXCLUSIVE DIARIZATION",
        exclusive
    )

    output = {
        "schema": "hehawk.chirp.diarization",
        "schema_version": 1,
        "timestamp_basis": "episode",
        "model": MODEL,
        "source": str(args.audio),
        "source_sha256": digest(args.audio),
        "source_offset_seconds": args.source_offset,
        "sample_rate": sample_rate,
        "duration_seconds": duration,
        "processing_seconds": elapsed,
        "settings": {
            "threads": args.threads,
            "num_speakers": None
        },
        "regular": {
            "segments": regular,
            "speakers": regular_stats
        },
        "exclusive": {
            "segments": exclusive,
            "speakers": exclusive_stats
        }
    }

    with args.json.open(
        "x",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=2,
            allow_nan=False
        )

    print()
    print("=" * 76)
    print("PROCESSING COMPLETE")
    print("=" * 76)

    print(
        f"Audio duration:  "
        f"{format_time(duration)}"
    )

    print(
        f"Processing time: "
        f"{format_time(elapsed)}"
    )

    print(
        f"Processing speed: "
        f"{duration / elapsed:.2f}x real time"
    )

    print(f"Results saved to {args.json}")


if __name__ == "__main__":
    main()
