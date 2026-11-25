import argparse
import json
import hashlib
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from huggingface_hub import get_token
from pyannote.audio import Model, Inference


MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"
THREADS = 8

# Absolute episode timestamps.
#
# Controls contain presumed single-speaker dialogue.
# Targets contain suspected speaker transitions.
#
# Expected identities are for reporting only.

REGIONS = [
    ("C01", "CONTROL", 902.039, 906.933, "Judge"),
    ("C02", "CONTROL", 932.836, 940.008, "Defense"),
    ("C03", "CONTROL", 941.847, 954.537, "Prosecutor"),

    ("S03", "TARGET", 911.270, 914.881, None),
    ("S06", "TARGET", 922.424, 930.980, None),
]


def format_time(seconds):

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:06.3f}"
    )


def sha256(path):

    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024), b""
        ):
            h.update(block)

    return h.hexdigest()


def normalize(vector):

    vector = np.asarray(
        vector,
        dtype=np.float64
    ).reshape(-1)

    magnitude = np.linalg.norm(vector)

    if (
        not np.all(np.isfinite(vector))
        or magnitude <= 0
    ):
        raise ValueError("Invalid embedding")

    return vector / magnitude


def load_profiles(path):

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if (
        data.get("schema")
        != "hehawk.chirp.embeddings"
        or data.get("schema_version") != 1
    ):
        raise ValueError(
            "Unsupported reference embedding schema"
        )

    if data.get("model") != MODEL:
        raise ValueError("Embedding model mismatch")

    profiles = {}

    for sample in data["samples"]:

        speaker = sample["speaker"]

        profiles.setdefault(speaker, []).append({
            "id": sample["id"],
            "vector": normalize(sample["embedding"])
        })

    if len(profiles) < 2:
        raise ValueError(
            "At least two voice profiles required"
        )

    return profiles


def compare_profiles(vector, profiles):

    results = {}

    for speaker, samples in profiles.items():

        individual = {}

        for sample in samples:

            score = float(np.clip(
                vector @ sample["vector"],
                -1.0,
                1.0
            ))

            individual[sample["id"]] = score

        values = list(individual.values())

        results[speaker] = {
            "mean": float(np.mean(values)),
            "maximum": max(values),
            "minimum": min(values),
            "individual": individual
        }

    ranked = sorted(
        results,
        key=lambda s: results[s]["mean"],
        reverse=True
    )

    winner = ranked[0]
    runner_up = ranked[1]

    margin = (
        results[winner]["mean"]
        - results[runner_up]["mean"]
    )

    return results, winner, margin


def window_starts(a, b, length, stride):

    if b - a < length:
        return []

    last = b - length

    starts = list(
        range(a, last + 1, stride)
    )

    # Include the end-aligned window so that
    # the final portion of the region is observed.

    if starts[-1] != last:
        starts.append(last)

    return starts


def main():

    parser = argparse.ArgumentParser(
        description="CHIRP speaker transition experiment"
    )

    parser.add_argument(
        "input",
        type=Path
    )

    parser.add_argument(
        "references",
        type=Path
    )

    parser.add_argument(
        "--source-offset",
        type=float,
        default=900.0
    )

    parser.add_argument(
        "--window",
        type=float,
        default=1.5
    )

    parser.add_argument(
        "--stride",
        type=float,
        default=0.25
    )

    parser.add_argument(
        "--min-similarity",
        type=float,
        default=0.30
    )

    parser.add_argument(
        "--min-margin",
        type=float,
        default=0.10
    )

    parser.add_argument(
        "--json",
        type=Path,
        required=True
    )

    args = parser.parse_args()

    if args.json.exists():
        raise FileExistsError(args.json)

    if not 0 < args.stride <= args.window:
        parser.error("Invalid window or stride")

    if not -1 <= args.min_similarity <= 1:
        parser.error("Invalid minimum similarity")

    if not 0 <= args.min_margin <= 2:
        parser.error("Invalid minimum margin")

    torch.set_num_threads(THREADS)

    profiles = load_profiles(args.references)
    speakers = sorted(profiles)

    audio, rate = sf.read(
        args.input,
        dtype="float32",
        always_2d=True
    )

    length = round(args.window * rate)
    stride = round(args.stride * rate)

    if length < 1 or stride < 1:
        parser.error("Window or stride too small")

    print("CHIRP - Speaker transition experiment")
    print(f"Model: {MODEL}")
    print(f"Window: {args.window:.3f}s")
    print(f"Stride: {args.stride:.3f}s")
    print(f"Minimum similarity: {args.min_similarity}")
    print(f"Minimum margin: {args.min_margin}")
    print()

    print("Reference profiles:")

    for speaker in speakers:
        print(
            f"  {speaker}: "
            f"{len(profiles[speaker])} samples"
        )

    print()
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

    observations = []

    for region_id, kind, start, end, expected in REGIONS:

        a = round(
            (start - args.source_offset) * rate
        )

        b = round(
            (end - args.source_offset) * rate
        )

        if not 0 <= a < b <= len(audio):
            raise ValueError(
                f"Region {region_id} outside audio bounds"
            )

        starts = window_starts(
            a, b, length, stride
        )

        print()
        print("=" * 90)
        print(
            f"{region_id} - {kind}: "
            f"{format_time(start)} - "
            f"{format_time(end)}"
        )

        if expected:
            print(f"Expected speaker: {expected}")

        print("=" * 90)
        print()

        print(
            f"{'Center':>12s} "
            + "".join(
                f"{s:>12s}" for s in speakers
            )
            + f"{'Margin':>9s}  "
            + "Assessment"
        )

        windows = []
        previous = None
        transitions = []

        for i, first in enumerate(starts):

            last = first + length

            waveform = torch.from_numpy(
                audio[first:last].T.copy()
            )

            embedding = normalize(inference({
                "waveform": waveform,
                "sample_rate": rate
            }))

            scores, winner, margin = (
                compare_profiles(
                    embedding,
                    profiles
                )
            )

            t0 = (
                args.source_offset + first / rate
            )

            t1 = (
                args.source_offset + last / rate
            )

            center = (t0 + t1) / 2

            best = scores[winner]["mean"]

            if best < args.min_similarity:
                assessment = "WEAK"

            elif margin < args.min_margin:
                assessment = "AMBIGUOUS"

            else:
                assessment = "MATCH"

            print(
                f"{format_time(center):>12s} "
                + "".join(
                    f"{scores[s]['mean']:12.3f}"
                    for s in speakers
                )
                + f"{margin:9.3f}  "
                + f"{winner} [{assessment}]"
            )

            record = {
                "id": f"W{i:03d}",
                "start_seconds": t0,
                "end_seconds": t1,
                "center_seconds": center,
                "scores": scores,
                "winner": winner,
                "margin": margin,
                "assessment": assessment,
                "embedding": embedding.tolist()
            }

            windows.append(record)

            # Compare consecutive accepted observations.
            # Ambiguous windows do not establish identities.

            if assessment == "MATCH":

                if (
                    previous is not None
                    and previous["winner"] != winner
                ):

                    transitions.append({
                        "from": previous["winner"],
                        "to": winner,
                        "previous_window": previous["id"],
                        "current_window": record["id"],
                        "previous_center_seconds":
                            previous["center_seconds"],
                        "current_center_seconds":
                            center
                    })

                previous = record

        print()
        print("Candidate speaker transitions:")

        if not transitions:
            print("  None detected")

        for transition in transitions:

            print(
                f"  {transition['from']} -> "
                f"{transition['to']}: "
                f"{format_time(transition['previous_center_seconds'])}"
                f" - "
                f"{format_time(transition['current_center_seconds'])}"
            )

        counts = {}

        for w in windows:
            status = w["assessment"]
            counts[status] = counts.get(status, 0) + 1

        print()
        print(f"Windows: {len(windows)}")

        for status, count in sorted(counts.items()):
            print(f"  {status}: {count}")

        observations.append({
            "id": region_id,
            "kind": kind,
            "start_seconds": start,
            "end_seconds": end,
            "expected_speaker": expected,
            "windows": windows,
            "candidate_transitions": transitions,
            "assessment_counts": counts
        })

    result = {
        "schema": "hehawk.chirp.transitions",
        "schema_version": 1,
        "timestamp_basis": "episode",
        "model": MODEL,
        "source": str(args.input),
        "source_sha256": sha256(args.input),
        "reference_sha256": sha256(args.references),
        "source_offset_seconds": args.source_offset,
        "sample_rate": rate,
        "settings": {
            "window_seconds": args.window,
            "stride_seconds": args.stride,
            "min_similarity": args.min_similarity,
            "min_margin": args.min_margin,
            "aggregation": "mean_cosine_similarity"
        },
        "regions": observations
    }

    with args.json.open("x", encoding="utf-8") as f:
        json.dump(
            result,
            f,
            indent=2,
            allow_nan=False
        )

    print()
    print(f"Results saved to {args.json}")


if __name__ == "__main__":
    main()
