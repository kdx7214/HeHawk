
"""TERN: Temporal Extraction and Recognition Navigation."""

import argparse
import hashlib
import json
import math
import wave
from pathlib import Path


# ------------------------------------------------------------
# Experimental segmentation parameters
# ------------------------------------------------------------

TARGET_SECONDS = 15.0
MIN_SECONDS = 8.0
MAX_SECONDS = 20.0

PAUSE_THRESHOLD = 0.30
MIN_PAUSE_SECONDS = 0.256

SCHEMA = "hehawk.tern.segmentation"
VERSION = 1


# ------------------------------------------------------------
# Source validation
# ------------------------------------------------------------

def sha256(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def load_lark(audio_path, lark_path):
    with lark_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("schema") != "hehawk.lark.probabilities":
        raise ValueError("Unrecognized LARK schema.")

    if data.get("version") != 1:
        raise ValueError("Unsupported LARK version.")

    if data.get("timestamp_basis") != "episode":
        raise ValueError("Expected episode-relative timestamps.")

    if data.get("source_offset_seconds") != 0:
        raise ValueError("Expected full episode audio.")

    if sha256(audio_path) != data["source_sha256"]:
        raise ValueError("Audio does not match LARK source hash.")

    rate = data["sample_rate"]
    step = data["frame_samples"]
    samples = data["source_samples"]
    probabilities = data["probabilities"]

    if rate != 16000 or step != 512 or samples <= 0:
        raise ValueError("Unexpected audio parameters.")

    expected = (samples + step - 1) // step

    if len(probabilities) != expected:
        raise ValueError("Incorrect probability frame count.")

    for probability in probabilities:
        if not math.isfinite(probability):
            raise ValueError("Non-finite speech probability.")

        if not 0 <= probability <= 1:
            raise ValueError("Invalid speech probability.")

    with wave.open(str(audio_path), "rb") as audio:
        if (
            audio.getframerate() != rate
            or audio.getnchannels() != 1
            or audio.getnframes() != samples
        ):
            raise ValueError("WAV metadata does not match LARK.")

    return data


# ------------------------------------------------------------
# Pause detection
# ------------------------------------------------------------

def find_pauses(probabilities, step, samples, rate):
    pauses = []
    first = None

    def add_pause(start_frame, end_frame):
        start = start_frame * step
        end = min(end_frame * step, samples)

        duration = (end - start) / rate

        if duration < MIN_PAUSE_SECONDS:
            return

        values = probabilities[start_frame:end_frame]

        pauses.append({
            "start_sample": start,
            "end_sample": end,
            "midpoint_sample": (start + end) // 2,
            "duration_seconds": duration,
            "mean_probability": sum(values) / len(values),
        })

    for i, probability in enumerate(probabilities):
        if probability < PAUSE_THRESHOLD:
            if first is None:
                first = i
        elif first is not None:
            add_pause(first, i)
            first = None

    if first is not None:
        add_pause(first, len(probabilities))

    return pauses


# ------------------------------------------------------------
# Boundary selection
# ------------------------------------------------------------

def choose_boundary(start, samples, rate, step,
                    probabilities, pauses):

    target = start + round(TARGET_SECONDS * rate)
    earliest = start + round(MIN_SECONDS * rate)
    latest = min(
        start + round(MAX_SECONDS * rate),
        samples
    )

    # Avoid unnecessarily splitting the final segment.

    if samples <= latest:
        return samples, {
            "reason": "end_of_audio"
        }

    candidates = [
        pause for pause in pauses
        if earliest <= pause["midpoint_sample"] <= latest
    ]

    if candidates:

        def score(pause):
            distance = abs(
                pause["midpoint_sample"] - target
            ) / rate

            return (
                distance
                + 2.0 * pause["mean_probability"]
                - min(pause["duration_seconds"], 2.0)
            )

        selected = min(candidates, key=score)

        return selected["midpoint_sample"], {
            "reason": "natural_pause",
            "score": score(selected),
            "pause": selected,
        }

    # No sufficiently long pause was available.
    # Select a low-probability frame, favoring the target.

    first_frame = (earliest + step - 1) // step
    last_frame = min(
        latest // step,
        len(probabilities) - 1
    )

    def fallback_score(i):
        distance = abs(i * step - target) / rate

        return probabilities[i] + 0.05 * distance

    selected = min(
        range(first_frame, last_frame + 1),
        key=fallback_score
    )

    return selected * step, {
        "reason": "fallback_low_probability",
        "speech_probability": probabilities[selected],
        "score": fallback_score(selected),
    }


# ------------------------------------------------------------
# Segmentation
# ------------------------------------------------------------

def build_segments(data, pauses):
    rate = data["sample_rate"]
    step = data["frame_samples"]
    samples = data["source_samples"]
    probabilities = data["probabilities"]

    segments = []
    start = 0

    while start < samples:
        end, boundary = choose_boundary(
            start,
            samples,
            rate,
            step,
            probabilities,
            pauses
        )

        if not start < end <= samples:
            raise RuntimeError("Invalid segment boundary.")

        segments.append({
            "id": f"T{len(segments) + 1:04d}",
            "start_sample": start,
            "end_sample": end,
            "sample_count": end - start,
            "start_seconds": start / rate,
            "end_seconds": end / rate,
            "duration_seconds": (end - start) / rate,
            "end_boundary": boundary,
        })

        start = end

    return segments


# ------------------------------------------------------------
# Independent coverage validation
# ------------------------------------------------------------

def validate_segments(segments, samples, rate):
    expected_start = 0
    total = 0

    for segment in segments:
        start = segment["start_sample"]
        end = segment["end_sample"]

        if start != expected_start:
            raise RuntimeError("Gap or overlap detected.")

        if end <= start:
            raise RuntimeError("Empty segment detected.")

        if end - start > round(MAX_SECONDS * rate):
            raise RuntimeError("Maximum duration exceeded.")

        if segment["sample_count"] != end - start:
            raise RuntimeError("Incorrect segment length.")

        total += end - start
        expected_start = end

    if expected_start != samples or total != samples:
        raise RuntimeError("Incomplete audio coverage.")


# ------------------------------------------------------------
# Reporting
# ------------------------------------------------------------

def report(segments, pauses, samples):
    durations = [
        segment["duration_seconds"]
        for segment in segments
    ]

    natural = sum(
        segment["end_boundary"]["reason"] == "natural_pause"
        for segment in segments
    )

    fallback = sum(
        segment["end_boundary"]["reason"]
        == "fallback_low_probability"
        for segment in segments
    )

    print("\nTERN SEGMENTATION REPORT")
    print("=" * 64)

    print(f"Detected pauses:       {len(pauses)}")
    print(f"Segments:              {len(segments)}")
    print(f"Natural boundaries:    {natural}")
    print(f"Fallback boundaries:   {fallback}")
    print(f"Shortest segment:      {min(durations):.3f}s")
    print(f"Mean segment:          {sum(durations)/len(durations):.3f}s")
    print(f"Longest segment:       {max(durations):.3f}s")
    print(f"Samples covered:       {samples:,}")
    print("Coverage validation:   PASSED")

    print("\nFIRST TEN SEGMENTS")
    print("-" * 64)

    for segment in segments[:10]:
        print_segment(segment)


def print_segment(segment):
    print(
        f"{segment['id']}  "
        f"{segment['start_seconds']:10.3f} - "
        f"{segment['end_seconds']:10.3f}  "
        f"{segment['duration_seconds']:6.3f}s  "
        f"{segment['end_boundary']['reason']}"
    )


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("audio", type=Path)
    parser.add_argument("lark", type=Path)
    parser.add_argument("--json", required=True, type=Path)

    parser.add_argument(
        "--inspect",
        nargs=2,
        type=float,
        action="append",
        default=[],
        metavar=("START", "END")
    )

    args = parser.parse_args()

    if args.json.exists():
        parser.error("Output already exists.")

    for start, end in args.inspect:
        if not (
            math.isfinite(start)
            and math.isfinite(end)
            and 0 <= start < end
        ):
            parser.error("Invalid inspection interval.")

    lark_hash = sha256(args.lark)
    data = load_lark(args.audio, args.lark)

    rate = data["sample_rate"]
    step = data["frame_samples"]
    samples = data["source_samples"]

    pauses = find_pauses(
        data["probabilities"],
        step,
        samples,
        rate
    )

    segments = build_segments(data, pauses)

    validate_segments(segments, samples, rate)

    result = {
        "schema": SCHEMA,
        "version": VERSION,
        "source": str(args.audio),
        "source_sha256": data["source_sha256"],
        "lark_source": str(args.lark),
        "lark_sha256": lark_hash,
        "timestamp_basis": "episode",
        "sample_rate": rate,
        "source_samples": samples,
        "duration_seconds": samples / rate,
        "settings": {
            "target_seconds": TARGET_SECONDS,
            "minimum_seconds": MIN_SECONDS,
            "maximum_seconds": MAX_SECONDS,
            "pause_threshold": PAUSE_THRESHOLD,
            "minimum_pause_seconds": MIN_PAUSE_SECONDS,
            "natural_probability_weight": 2.0,
            "natural_pause_reward_cap_seconds": 2.0,
            "fallback_distance_weight": 0.05,
        },
        "segments": segments,
    }

    if sha256(args.lark) != lark_hash:
        raise RuntimeError("LARK source changed during planning.")

    if sha256(args.audio) != data["source_sha256"]:
        raise RuntimeError("Audio changed during planning.")

    with args.json.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")

    report(segments, pauses, samples)

    for start, end in args.inspect:
        print(f"\nINSPECTION: {start:.3f} - {end:.3f}")
        print("-" * 64)

        for segment in segments:
            if (
                segment["start_seconds"] < end
                and segment["end_seconds"] > start
            ):
                print_segment(segment)

                print(json.dumps(
                    segment["end_boundary"],
                    indent=2
                ))

    print(f"\nSaved: {args.json}")


if __name__ == "__main__":
    main()
