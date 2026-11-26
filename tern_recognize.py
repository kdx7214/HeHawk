
"""TERN: recognize audio using a validated segmentation manifest."""

import argparse
import hashlib
import importlib.metadata as md
import json
import math
import time
from pathlib import Path

import sherpa_onnx
import soundfile as sf


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

MODEL = Path(
    "models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
)

SAMPLE_RATE = 16000
NUM_THREADS = 8

MODEL_FILES = (
    "encoder.int8.onnx",
    "decoder.int8.onnx",
    "joiner.int8.onnx",
    "tokens.txt",
)


# ------------------------------------------------------------
# Utilities
# ------------------------------------------------------------

def sha256(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save_json(path, data):
    with path.open("x", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        )
        f.write("\n")


# ------------------------------------------------------------
# Manifest validation
# ------------------------------------------------------------

def load_manifest(path, audio_path):
    with path.open("r", encoding="utf-8") as f:
        plan = json.load(f)

    if plan.get("schema") != "hehawk.tern.segmentation":
        raise ValueError("Unrecognized TERN schema.")

    if plan.get("version") != 1:
        raise ValueError("Unsupported TERN version.")

    if plan.get("timestamp_basis") != "episode":
        raise ValueError("Expected episode timestamps.")

    if plan["sample_rate"] != SAMPLE_RATE:
        raise ValueError("Unexpected sample rate.")

    if sha256(audio_path) != plan["source_sha256"]:
        raise ValueError("Audio source hash mismatch.")

    expected_start = 0
    seen_ids = set()

    for segment in plan["segments"]:
        start = segment["start_sample"]
        end = segment["end_sample"]

        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("Non-integer sample offset.")

        if segment["id"] in seen_ids:
            raise ValueError("Duplicate segment ID.")

        seen_ids.add(segment["id"])

        if start != expected_start:
            raise ValueError("Gap or overlap in segmentation.")

        if end <= start:
            raise ValueError("Empty segment.")

        if segment["sample_count"] != end - start:
            raise ValueError("Incorrect segment length.")

        expected_start = end

    if expected_start != plan["source_samples"]:
        raise ValueError("Incomplete audio coverage.")

    return plan


# ------------------------------------------------------------
# Recognition
# ------------------------------------------------------------

def recognize_segment(recognizer, audio, segment):
    start = segment["start_sample"]
    end = segment["end_sample"]

    chunk = audio[start:end]
    offset = start / SAMPLE_RATE

    started = time.perf_counter()

    stream = recognizer.create_stream()

    stream.accept_waveform(
        SAMPLE_RATE,
        chunk
    )

    recognizer.decode_stream(stream)

    result = stream.result

    tokens = list(result.tokens)
    timestamps = [float(t) for t in result.timestamps]
    durations = [float(d) for d in result.durations]

    if not (
        len(tokens) == len(timestamps) == len(durations)
    ):
        raise RuntimeError("Inconsistent token array lengths.")

    for timestamp, duration in zip(timestamps, durations):
        if not math.isfinite(timestamp):
            raise RuntimeError("Non-finite timestamp.")

        if not math.isfinite(duration):
            raise RuntimeError("Non-finite duration.")

        if timestamp < 0 or duration < 0:
            raise RuntimeError("Negative token timing.")

    return {
        "id": segment["id"],
        "start_sample": start,
        "end_sample": end,
        "source_offset_seconds": offset,
        "duration_seconds": len(chunk) / SAMPLE_RATE,
        "text": result.text,
        "tokens": tokens,
        "timestamps": timestamps,
        "durations": durations,
        "processing_seconds": (
            time.perf_counter() - started
        ),
    }


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("audio", type=Path)
    parser.add_argument("manifest", type=Path)

    parser.add_argument(
        "--json",
        required=True,
        type=Path
    )

    parser.add_argument(
        "--evidence",
        required=True,
        type=Path
    )

    args = parser.parse_args()

    if args.json.resolve() == args.evidence.resolve():
        parser.error("Output filenames must be different.")

    for path in (args.json, args.evidence):
        if path.exists():
            parser.error(f"Output already exists: {path}")

    manifest_hash = sha256(args.manifest)

    print("Validating TERN manifest...")

    plan = load_manifest(
        args.manifest,
        args.audio
    )

    print("Reading original audio...")

    audio, rate = sf.read(
        args.audio,
        dtype="float32"
    )

    if rate != SAMPLE_RATE or audio.ndim != 1:
        raise ValueError("Expected mono 16000 Hz audio.")

    if len(audio) != plan["source_samples"]:
        raise ValueError("Audio sample count mismatch.")

    import numpy as np

    if not np.isfinite(audio).all():
        raise ValueError("Non-finite audio samples.")

    print("Calculating model hashes...")

    model_hashes = {
        name: sha256(MODEL / name)
        for name in MODEL_FILES
    }

    print("Loading Parakeet model...")

    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(MODEL / "encoder.int8.onnx"),
        decoder=str(MODEL / "decoder.int8.onnx"),
        joiner=str(MODEL / "joiner.int8.onnx"),
        tokens=str(MODEL / "tokens.txt"),
        num_threads=NUM_THREADS,
        provider="cpu",
        model_type="nemo_transducer",
    )

    print("Model loaded.")

    all_tokens = []
    all_timestamps = []
    all_durations = []
    all_text = []

    evidence_segments = []

    empty_segments = 0
    timing_warnings = 0

    total = len(plan["segments"])
    started = time.perf_counter()

    for number, segment in enumerate(
        plan["segments"],
        start=1
    ):
        recognized = recognize_segment(
            recognizer,
            audio,
            segment
        )

        offset = recognized["source_offset_seconds"]

        first_token = len(all_tokens)

        all_tokens.extend(recognized["tokens"])

        all_timestamps.extend(
            t + offset
            for t in recognized["timestamps"]
        )

        all_durations.extend(recognized["durations"])

        if recognized["text"].strip():
            all_text.append(recognized["text"].strip())
        else:
            empty_segments += 1

        recognized["combined_token_start"] = first_token
        recognized["combined_token_end"] = len(all_tokens)

        # Preserve raw timing evidence, including anomalies.
        # Do not silently clamp timestamps to segment boundaries.

        warnings = []

        for i, (timestamp, duration) in enumerate(zip(
            recognized["timestamps"],
            recognized["durations"]
        )):
            if (
                timestamp + duration
                > recognized["duration_seconds"] + 0.001
            ):
                warnings.append({
                    "token_index": i,
                    "reason": "extends_beyond_segment",
                    "timestamp": timestamp,
                    "duration": duration,
                })

        recognized["timing_warnings"] = warnings
        timing_warnings += len(warnings)

        evidence_segments.append(recognized)

        elapsed = time.perf_counter() - started

        print(
            f"{number:3d}/{total}  "
            f"{segment['id']}  "
            f"{offset:9.3f}s  "
            f"{recognized['duration_seconds']:6.3f}s  "
            f"tokens={len(recognized['tokens']):4d}  "
            f"elapsed={elapsed:.1f}s",
            flush=True
        )

    recognition_time = time.perf_counter() - started

    # --------------------------------------------------------
    # Verify source integrity before publishing results
    # --------------------------------------------------------

    if sha256(args.audio) != plan["source_sha256"]:
        raise RuntimeError("Audio changed during recognition.")

    if sha256(args.manifest) != manifest_hash:
        raise RuntimeError("Manifest changed during recognition.")

    for name, expected in model_hashes.items():
        if sha256(MODEL / name) != expected:
            raise RuntimeError(f"Model file changed: {name}")

    # --------------------------------------------------------
    # Combined recognition output
    # --------------------------------------------------------

    combined = {
        "text": " ".join(all_text),
        "tokens": all_tokens,
        "timestamps": all_timestamps,
        "durations": all_durations,
        "source_offset_seconds": 0.0,
    }

    evidence = {
        "schema": "hehawk.tern.recognition",
        "version": 1,
        "source": str(args.audio),
        "source_sha256": plan["source_sha256"],
        "manifest": str(args.manifest),
        "manifest_sha256": manifest_hash,
        "sample_rate": SAMPLE_RATE,
        "source_samples": len(audio),
        "model": str(MODEL),
        "model_sha256": model_hashes,
        "packages": {
            name: md.version(name)
            for name in (
                "sherpa-onnx",
                "soundfile",
                "numpy",
            )
        },
        "settings": {
            "provider": "cpu",
            "num_threads": NUM_THREADS,
            "model_type": "nemo_transducer",
        },
        "timestamp_basis": "segment_relative",
        "combined_timestamp_basis": "episode",
        "processing_seconds": recognition_time,
        "empty_segments": empty_segments,
        "timing_warning_count": timing_warnings,
        "segments": evidence_segments,
    }

    save_json(args.json, combined)

    evidence["combined_output"] = str(args.json)
    evidence["combined_sha256"] = sha256(args.json)

    save_json(args.evidence, evidence)

    duration = len(audio) / SAMPLE_RATE

    print("\nTERN RECOGNITION REPORT")
    print("=" * 64)

    print(f"Segments:          {total}")
    print(f"Empty segments:    {empty_segments}")
    print(f"Tokens:            {len(all_tokens):,}")
    print(f"Timing warnings:   {timing_warnings}")
    print(f"Audio duration:    {duration:.3f}s")
    print(f"Recognition time:  {recognition_time:.3f}s")
    print(
        f"Processing speed:  "
        f"{duration / recognition_time:.2f}x real time"
    )

    print(f"\nCombined: {args.json}")
    print(f"Evidence: {args.evidence}")


if __name__ == "__main__":
    main()
