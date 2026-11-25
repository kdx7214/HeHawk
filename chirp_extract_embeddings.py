import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from huggingface_hub import get_token
from pyannote.audio import Model, Inference


MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"


def digest(path):

    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024), b""
        ):
            h.update(block)

    return h.hexdigest()


def main():

    parser = argparse.ArgumentParser(
        description="CHIRP episode embedding extraction"
    )

    parser.add_argument("audio", type=Path)
    parser.add_argument("diarization", type=Path)

    parser.add_argument(
        "--min-duration",
        type=float,
        default=1.5
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

    if (
        not math.isfinite(args.min_duration)
        or args.min_duration <= 0
    ):
        parser.error("Minimum duration must be positive")

    if args.threads < 1:
        parser.error("Threads must be positive")

    torch.set_num_threads(args.threads)

    print("CHIRP - Episode embedding extraction")

    with args.diarization.open(
        encoding="utf-8"
    ) as f:
        diarization = json.load(f)

    if (
        diarization.get("schema")
        != "hehawk.chirp.diarization"
        or diarization.get("schema_version") != 1
        or diarization.get("timestamp_basis") != "episode"
    ):
        raise ValueError("Unsupported diarization format")

    audio_hash = digest(args.audio)

    if audio_hash != diarization["source_sha256"]:
        raise ValueError(
            "Audio does not match diarization source"
        )

    audio, sample_rate = sf.read(
        args.audio,
        dtype="float32",
        always_2d=True
    )

    if sample_rate != diarization["sample_rate"]:
        raise ValueError("Sample rate mismatch")

    if audio.shape[1] != 1:
        raise ValueError("Expected mono audio")

    offset = diarization["source_offset_seconds"]

    segments = diarization["exclusive"]["segments"]

    candidates = [
        s for s in segments
        if s["duration_seconds"] >= args.min_duration
    ]

    print(f"Total segments: {len(segments)}")
    print(f"Embedding candidates: {len(candidates)}")
    print(f"Minimum duration: {args.min_duration}s")

    print("Loading embedding model...")

    model = Model.from_pretrained(
        MODEL,
        token=get_token()
    )

    inference = Inference(
        model,
        window="whole",
        device=torch.device("cpu")
    )

    print("Model loaded.")

    started = time.perf_counter()

    results = []
    skipped = []
    rejected = []

    processed = 0
    dimensions = None

    for segment in segments:

        record = dict(segment)

        if segment["duration_seconds"] < args.min_duration:

            record["embedding_status"] = "TOO_SHORT"
            skipped.append(record)
            continue

        processed += 1

        a = round(
            (segment["start_seconds"] - offset)
            * sample_rate
        )

        b = round(
            (segment["end_seconds"] - offset)
            * sample_rate
        )

        if not 0 <= a < b <= len(audio):

            record["embedding_status"] = "INVALID_RANGE"
            rejected.append(record)
            continue

        waveform = torch.from_numpy(
            audio[a:b].T.copy()
        )

        vector = inference({
            "waveform": waveform,
            "sample_rate": sample_rate
        })

        vector = np.asarray(
            vector,
            dtype=np.float64
        ).reshape(-1)

        norm = np.linalg.norm(vector)

        if (
            not np.all(np.isfinite(vector))
            or not np.isfinite(norm)
            or norm <= 1e-12
        ):

            record["embedding_status"] = "INVALID_VECTOR"
            rejected.append(record)

        else:

            vector = vector / norm

            if dimensions is None:
                dimensions = len(vector)

            if len(vector) != dimensions:
                raise ValueError(
                    "Embedding dimension mismatch"
                )

            record["embedding"] = vector.tolist()
            record["embedding_status"] = "VALID"

            results.append(record)

        if (
            processed % 10 == 0
            or processed == len(candidates)
        ):

            elapsed = time.perf_counter() - started

            print(
                f"Processed {processed:4d}/"
                f"{len(candidates)} "
                f"| Valid: {len(results):4d} "
                f"| Elapsed: {elapsed:.1f}s",
                flush=True
            )

    elapsed = time.perf_counter() - started

    if (
        len(results) + len(skipped) + len(rejected)
        != len(segments)
    ):
        raise RuntimeError("Segment accounting mismatch")

    output = {
        "schema": "hehawk.chirp.segment_embeddings",
        "schema_version": 1,
        "timestamp_basis": "episode",
        "model": MODEL,
        "source": str(args.audio),
        "source_sha256": audio_hash,
        "diarization_sha256": digest(args.diarization),
        "source_offset_seconds": offset,
        "sample_rate": sample_rate,
        "embedding_dimensions": dimensions,
        "settings": {
            "minimum_duration": args.min_duration,
            "threads": args.threads,
            "diarization_type": "exclusive"
        },
        "segments": results,
        "skipped_segments": skipped,
        "rejected_segments": rejected,
        "processing_seconds": elapsed
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
    print("EMBEDDING EXTRACTION COMPLETE")
    print("=" * 76)

    print(f"Original segments: {len(segments)}")
    print(f"Valid embeddings:  {len(results)}")
    print(f"Too short:         {len(skipped)}")
    print(f"Rejected:          {len(rejected)}")
    print(f"Vector dimensions: {dimensions}")
    print(f"Processing time:   {elapsed:.2f}s")

    print()
    print("CANDIDATES BY ORIGINAL SPEAKER")

    for speaker in sorted({
        s["original_speaker"] for s in segments
    }):

        total = sum(
            s["original_speaker"] == speaker
            for s in segments
        )

        valid = sum(
            s["original_speaker"] == speaker
            for s in results
        )

        print(
            f"{speaker:20s}"
            f"{valid:4d}/{total:<4d}"
        )

    print()
    print(f"Results saved to {args.json}")


if __name__ == "__main__":
    main()
