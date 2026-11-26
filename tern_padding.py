
"""TERN 6J: experimental padded segment recognition."""

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import sherpa_onnx


MODEL = Path(
    "models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
)

MODEL_FILES = (
    "encoder.int8.onnx",
    "decoder.int8.onnx",
    "joiner.int8.onnx",
    "tokens.txt",
)

THREADS = 8
PADDING_SECONDS = 0.240
DEFAULT_SEED = 42


def sha256(path):
    digest = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            block = f.read(1024 * 1024)

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def timestamp(seconds):
    ms = round(seconds * 1000)

    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)

    if hours:
        return (
            f"{hours:02d}:{minutes:02d}:"
            f"{seconds:02d}.{ms:03d}"
        )

    return f"{minutes:02d}:{seconds:02d}.{ms:03d}"


def make_padding(count, rms, seed, segment_index):
    if rms == 0:
        return np.zeros(count, dtype=np.float32)

    rng = np.random.default_rng(
        np.random.SeedSequence([seed, segment_index])
    )

    noise = rng.standard_normal(count)

    noise -= np.mean(noise)
    noise /= np.sqrt(np.mean(noise ** 2))
    noise *= rms

    # Reproduce the PCM quantization used in Experiment 6I.

    pcm = np.clip(
        np.rint(noise * 32768),
        -32768,
        32767
    ).astype(np.int16)

    return pcm.astype(np.float32) / 32768


def make_recognizer():
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(MODEL / "encoder.int8.onnx"),
        decoder=str(MODEL / "decoder.int8.onnx"),
        joiner=str(MODEL / "joiner.int8.onnx"),
        tokens=str(MODEL / "tokens.txt"),
        num_threads=THREADS,
        sample_rate=16000,
        feature_dim=80,
        provider="cpu",
        model_type="nemo_transducer",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("audio", type=Path)
    parser.add_argument("baseline", type=Path)

    parser.add_argument(
        "--rms",
        required=True,
        type=float
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED
    )

    parser.add_argument(
        "--json",
        required=True,
        type=Path
    )

    args = parser.parse_args()

    if args.json.exists():
        parser.error("Output already exists.")

    if not math.isfinite(args.rms) or not 0 <= args.rms <= 0.1:
        parser.error("Invalid padding RMS.")

    if args.seed < 0:
        parser.error("Seed must be nonnegative.")

    audio_hash = sha256(args.audio)
    baseline_hash = sha256(args.baseline)

    with args.baseline.open() as f:
        baseline = json.load(f)

    if (
        baseline["schema"] != "hehawk.tern.recognition"
        or baseline["version"] != 1
    ):
        raise ValueError("Expected TERN recognition evidence.")

    if baseline["source_sha256"] != audio_hash:
        raise ValueError("Baseline audio hash mismatch.")

    model_hashes = {
        name: sha256(MODEL / name)
        for name in MODEL_FILES
    }

    if baseline["model_sha256"] != model_hashes:
        raise ValueError("Recognition model hash mismatch.")

    audio, rate = sf.read(
        str(args.audio),
        dtype="float32"
    )

    if audio.ndim != 1 or rate != 16000:
        raise ValueError("Expected mono 16kHz audio.")

    if not np.all(np.isfinite(audio)):
        raise ValueError("Invalid audio samples.")

    if len(audio) != baseline["source_samples"]:
        raise ValueError("Audio sample count mismatch.")

    if rate != baseline["sample_rate"]:
        raise ValueError("Sample rate mismatch.")

    segments = baseline["segments"]

    cursor = 0

    for segment in segments:
        a = segment["start_sample"]
        b = segment["end_sample"]

        if a != cursor or not a < b <= len(audio):
            raise ValueError("Invalid baseline segmentation.")

        cursor = b

    if cursor != len(audio):
        raise ValueError("Incomplete baseline segmentation.")

    padding_samples = round(PADDING_SECONDS * rate)

    print("TERN PADDING EXPERIMENT")
    print("=" * 64)
    print(f"Segments: {len(segments)}")
    print(f"Padding: {PADDING_SECONDS:.3f}s")
    print(f"Padding RMS: {args.rms:.6f}")
    print(f"Seed: {args.seed}")
    print("Source and model verification: PASSED")

    print("\nLoading Parakeet...")
    recognizer = make_recognizer()

    rows = []
    empty_count = 0
    changed_count = 0
    padding_token_count = 0
    crossing_token_count = 0
    outside_input_count = 0

    started = time.perf_counter()

    for index, segment in enumerate(segments):

        a = segment["start_sample"]
        b = segment["end_sample"]

        original = audio[a:b]

        padding = make_padding(
            padding_samples,
            args.rms,
            args.seed,
            index
        )

        waveform = np.concatenate(
            (original, padding)
        )

        if not np.array_equal(
            waveform[:len(original)],
            original
        ):
            raise RuntimeError("Original samples changed.")

        duration = len(original) / rate
        input_duration = len(waveform) / rate

        segment_started = time.perf_counter()

        stream = recognizer.create_stream()

        stream.accept_waveform(rate, waveform)
        recognizer.decode_stream(stream)

        result = stream.result

        text = result.text
        tokens = list(result.tokens)
        timestamps = [
            float(t) for t in result.timestamps
        ]
        durations = [
            float(t) for t in result.durations
        ]

        elapsed = time.perf_counter() - segment_started

        if not (
            len(tokens)
            == len(timestamps)
            == len(durations)
        ):
            raise RuntimeError("Token array length mismatch.")

        timing_flags = []

        for i, (t, d) in enumerate(
            zip(timestamps, durations)
        ):
            if (
                not math.isfinite(t)
                or not math.isfinite(d)
                or t < 0
                or d < 0
            ):
                raise RuntimeError("Invalid token timing.")

            end = t + d

            flags = []

            if t >= duration:
                flags.append("starts_in_padding")
                padding_token_count += 1

            elif end > duration + 0.001:
                flags.append("crosses_padding_boundary")
                crossing_token_count += 1

            if end > input_duration + 0.001:
                flags.append("extends_beyond_input")
                outside_input_count += 1

            if flags:
                timing_flags.append({
                    "token_index": i,
                    "timestamp": t,
                    "duration": d,
                    "flags": flags,
                })

        changed = text.strip() != segment["text"].strip()

        if changed:
            changed_count += 1

        if not text.strip():
            empty_count += 1

        actual_rms = float(
            np.sqrt(
                np.mean(
                    padding.astype(np.float64) ** 2
                )
            )
        )

        rows.append({
            "id": segment["id"],
            "start_sample": a,
            "end_sample": b,
            "source_offset_seconds": a / rate,
            "duration_seconds": duration,
            "input_duration_seconds": input_duration,
            "padding_samples": padding_samples,
            "padding_rms": actual_rms,
            "padding_sha256": hashlib.sha256(
                padding.astype("<f4").tobytes()
            ).hexdigest(),
            "text": text,
            "tokens": tokens,
            "timestamps": timestamps,
            "durations": durations,
            "timing_flags": timing_flags,
            "text_changed": changed,
            "processing_seconds": elapsed,
        })

        print(
            f"{segment['id']} "
            f"{timestamp(a / rate)} - "
            f"{timestamp(b / rate)} "
            f"tokens={len(tokens):3d} "
            f"changed={'YES' if changed else 'no'} "
            f"flags={len(timing_flags)}"
        )

    elapsed = time.perf_counter() - started

    output = {
        "schema": "hehawk.tern.padding",
        "version": 1,
        "source": str(args.audio),
        "source_sha256": audio_hash,
        "baseline": str(args.baseline),
        "baseline_sha256": baseline_hash,
        "sample_rate": rate,
        "source_samples": len(audio),
        "timestamp_basis": "segment_relative",
        "model_sha256": model_hashes,
        "settings": {
            "padding_seconds": PADDING_SECONDS,
            "padding_samples": padding_samples,
            "padding_rms": args.rms,
            "seed": args.seed,
            "seed_policy": "seed_and_segment_index",
            "padding_quantization": "pcm_s16",
            "provider": "cpu",
            "num_threads": THREADS,
        },
        "processing_seconds": elapsed,
        "empty_segments": empty_count,
        "changed_segments": changed_count,
        "tokens_starting_in_padding": padding_token_count,
        "tokens_crossing_padding_boundary": crossing_token_count,
        "tokens_outside_input": outside_input_count,
        "segments": rows,
    }

    if sha256(args.audio) != audio_hash:
        raise RuntimeError("Source audio changed.")

    if sha256(args.baseline) != baseline_hash:
        raise RuntimeError("Baseline evidence changed.")

    for name, expected in model_hashes.items():
        if sha256(MODEL / name) != expected:
            raise RuntimeError("Model changed.")

    with args.json.open("x", encoding="utf-8") as f:
        json.dump(
            output,
            f,
            indent=2,
            allow_nan=False
        )
        f.write("\n")

    print("\nTERN PADDING REPORT")
    print("=" * 64)
    print(f"Segments: {len(rows)}")
    print(f"Changed segments: {changed_count}")
    print(f"Empty segments: {empty_count}")
    print(f"Tokens starting in padding: {padding_token_count}")
    print(f"Tokens crossing boundary: {crossing_token_count}")
    print(f"Tokens outside input: {outside_input_count}")
    print(f"Processing time: {elapsed:.3f}s")
    print(f"Saved: {args.json}")


if __name__ == "__main__":
    main()
