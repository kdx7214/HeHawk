
"""HUNT 6D: differential speech coverage and empty-segment analysis."""

import argparse
import math
import json
from pathlib import Path

from hunt_inventory import load, measure


THRESHOLDS = (0.3, 0.5, 0.7)
TIMING_TOLERANCE = 0.100
MIN_REPORT_DURATION = 0.250

CLASSES = (
    "recovered",
    "regressed",
    "persistent",
    "shared",
)


# ------------------------------------------------------------
# Human-readable timestamps
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# Validation
# ------------------------------------------------------------

def validate_inventory(inventory, vad, vad_hash):
    if inventory.get("schema") != "hehawk.hunt.inventory":
        raise ValueError("Invalid HUNT inventory.")

    if inventory.get("version") != 1:
        raise ValueError("Unsupported HUNT version.")

    if inventory["vad_sha256"] != vad_hash:
        raise ValueError("HUNT/LARK hash mismatch.")

    if inventory["source_sha256"] != vad["source_sha256"]:
        raise ValueError("Source hash mismatch.")

    if inventory["timestamp_basis"] != "episode":
        raise ValueError("Expected episode timestamps.")

    if inventory["settings"]["word_padding"] != 0:
        raise ValueError("Expected unpadded word coverage.")

    duration = vad["source_samples"] / vad["sample_rate"]

    if abs(inventory["duration_seconds"] - duration) > 1e-6:
        raise ValueError("Duration mismatch.")

    previous_end = 0.0

    for gap in inventory["gaps"]:
        a, b = gap["start"], gap["end"]

        if not (
            math.isfinite(a)
            and math.isfinite(b)
            and 0 <= a < b <= duration + 1e-6
        ):
            raise ValueError("Invalid gap interval.")

        if a < previous_end - 1e-9:
            raise ValueError("Overlapping or unordered gaps.")

        previous_end = b


# ------------------------------------------------------------
# Convert gaps to sample intervals
# ------------------------------------------------------------

def sample_gaps(inventory, rate, samples, tolerance):
    result = []

    padding = round(tolerance * rate)

    for gap in inventory["gaps"]:
        start = max(0, round(gap["start"] * rate))
        end = min(samples, round(gap["end"] * rate))

        # Expand neighboring word coverage into each gap.
        # Do not pad beyond the beginning or end of the audio.

        if start > 0:
            start += padding

        if end < samples:
            end -= padding

        if end > start:
            result.append((start, end))

    return result


# ------------------------------------------------------------
# Exact interval comparison
# ------------------------------------------------------------

def compare_coverage(
    original,
    tern,
    probabilities,
    frame_samples,
    source_samples,
    rate,
    threshold,
):
    # Sweep across all boundaries where either recognition
    # coverage or LARK speech classification can change.

    boundaries = {0, source_samples}

    for intervals in (original, tern):
        for a, b in intervals:
            boundaries.add(a)
            boundaries.add(b)

    boundaries.update(
        range(0, source_samples, frame_samples)
    )

    boundaries = sorted(boundaries)

    original_index = 0
    tern_index = 0

    runs = {name: [] for name in CLASSES}

    for a, b in zip(boundaries, boundaries[1:]):
        if probabilities[a // frame_samples] < threshold:
            continue

        while (
            original_index < len(original)
            and original[original_index][1] <= a
        ):
            original_index += 1

        while (
            tern_index < len(tern)
            and tern[tern_index][1] <= a
        ):
            tern_index += 1

        original_gap = (
            original_index < len(original)
            and original[original_index][0] <= a
            < original[original_index][1]
        )

        tern_gap = (
            tern_index < len(tern)
            and tern[tern_index][0] <= a
            < tern[tern_index][1]
        )

        if original_gap and tern_gap:
            category = "persistent"
        elif original_gap:
            category = "recovered"
        elif tern_gap:
            category = "regressed"
        else:
            category = "shared"

        rows = runs[category]

        if rows and rows[-1][1] == a:
            rows[-1][1] = b
        else:
            rows.append([a, b])

    result = {}

    for category, rows in runs.items():
        intervals = [
            {
                "start_sample": a,
                "end_sample": b,
                "start": a / rate,
                "end": b / rate,
                "duration": (b - a) / rate,
            }
            for a, b in rows
        ]

        result[category] = {
            "seconds": sum(
                b - a for a, b in rows
            ) / rate,
            "runs": len(rows),
            "longest": max(
                ((b - a) / rate for a, b in rows),
                default=0.0
            ),
            "intervals": intervals,
        }

    expected_samples = sum(
        min(
            frame_samples,
            source_samples - i * frame_samples
        )
        for i, p in enumerate(probabilities)
        if p >= threshold
    )

    classified_samples = sum(
        row["end_sample"] - row["start_sample"]
        for category in result.values()
        for row in category["intervals"]
    )

    if expected_samples != classified_samples:
        raise RuntimeError("Speech coverage accounting failed.")

    return result


# ------------------------------------------------------------
# Empty TERN segments
# ------------------------------------------------------------

def empty_segment_analysis(evidence, vad):
    rate = vad["sample_rate"]
    step = vad["frame_samples"] / rate
    probabilities = vad["probabilities"]

    rows = []

    for segment in evidence["segments"]:
        if segment["text"].strip():
            continue

        a = segment["start_sample"] / rate
        b = segment["end_sample"] / rate

        stats = measure(
            a,
            b,
            probabilities,
            step
        )

        rows.append({
            "id": segment["id"],
            "start": a,
            "end": b,
            "duration": b - a,
            "token_count": len(segment["tokens"]),
            **stats,
        })

    if len(rows) != evidence["empty_segments"]:
        raise ValueError("Empty segment count mismatch.")

    return sorted(
        rows,
        key=lambda row: (
            row["thresholds"]["0.5"]["longest"]
        ),
        reverse=True
    )


# ------------------------------------------------------------
# Reports
# ------------------------------------------------------------

def print_summary(results):
    for threshold, result in results.items():
        print(f"\nLARK threshold: {threshold}")

        print(
            f'{"Category":12} '
            f'{"Speech (s)":>12} '
            f'{"Runs":>8} '
            f'{"Longest":>10}'
        )

        print("-" * 48)

        for category in CLASSES:
            row = result[category]

            print(
                f"{category:12} "
                f"{row['seconds']:12.3f} "
                f"{row['runs']:8d} "
                f"{row['longest']:10.3f}"
            )

        recovered = result["recovered"]["seconds"]
        regressed = result["regressed"]["seconds"]

        print(
            f"Net speech coverage gain: "
            f"{recovered - regressed:+.3f}s"
        )


def print_ranked(title, intervals):
    print(f"\n{title}")
    print("-" * 64)

    ranked = sorted(
        intervals,
        key=lambda row: row["duration"],
        reverse=True
    )

    selected = [
        row for row in ranked
        if row["duration"] >= MIN_REPORT_DURATION
    ]

    if not selected:
        print("None meeting minimum duration.")
        return

    for row in selected[:15]:
        a, b = row["start"], row["end"]

        print(
            f"{timestamp(a)} - {timestamp(b)}  "
            f"{row['duration']:.3f}s  "
            f"({a:.3f}-{b:.3f})"
        )


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("vad", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("tern", type=Path)
    parser.add_argument("evidence", type=Path)

    parser.add_argument(
        "--json",
        required=True,
        type=Path
    )

    args = parser.parse_args()

    if args.json.exists():
        parser.error("Output already exists.")

    vad, vad_hash = load(args.vad)
    original, original_hash = load(args.original)
    tern, tern_hash = load(args.tern)
    evidence, evidence_hash = load(args.evidence)

    if (
        vad["schema"] != "hehawk.lark.probabilities"
        or vad["version"] != 1
        or vad["timestamp_basis"] != "episode"
        or vad["source_offset_seconds"] != 0
    ):
        raise ValueError("Expected full episode LARK v1.")

    rate = vad["sample_rate"]
    frame = vad["frame_samples"]
    samples = vad["source_samples"]
    probabilities = vad["probabilities"]

    if rate != 16000 or frame != 512 or samples <= 0:
        raise ValueError("Invalid LARK geometry.")

    if len(probabilities) != (samples + frame - 1) // frame:
        raise ValueError("Invalid LARK frame count.")

    if any(
        not math.isfinite(p) or not 0 <= p <= 1
        for p in probabilities
    ):
        raise ValueError("Invalid LARK probabilities.")

    validate_inventory(original, vad, vad_hash)
    validate_inventory(tern, vad, vad_hash)

    # Verify TERN's provenance against the LARK source
    # and the recognition hash recorded by HUNT.

    if (
        evidence["schema"] != "hehawk.tern.recognition"
        or evidence["version"] != 1
    ):
        raise ValueError("Invalid TERN evidence.")

    if evidence["source_sha256"] != vad["source_sha256"]:
        raise ValueError("TERN/LARK source mismatch.")

    if evidence["combined_sha256"] != tern["recognition_sha256"]:
        raise ValueError("TERN recognition hash mismatch.")

    if (
        evidence["sample_rate"] != rate
        or evidence["source_samples"] != samples
    ):
        raise ValueError("TERN audio geometry mismatch.")

    cursor = 0

    for segment in evidence["segments"]:
        a = segment["start_sample"]
        b = segment["end_sample"]

        if a != cursor or b <= a or b > samples:
            raise ValueError("Invalid TERN segment coverage.")

        cursor = b

    if cursor != samples:
        raise ValueError("Incomplete TERN segment coverage.")

    print("TERN provenance chain: PASSED")
    print("Original recognition source: ASSUMED")

    comparisons = {}

    for name, tolerance in (
        ("exact", 0.0),
        ("tolerant", TIMING_TOLERANCE),
    ):
        original_gaps = sample_gaps(
            original, rate, samples, tolerance
        )

        tern_gaps = sample_gaps(
            tern, rate, samples, tolerance
        )

        comparisons[name] = {}

        for threshold in THRESHOLDS:
            comparisons[name][str(threshold)] = (
                compare_coverage(
                    original_gaps,
                    tern_gaps,
                    probabilities,
                    frame,
                    samples,
                    rate,
                    threshold,
                )
            )

    print("\nEXACT SPEECH COVERAGE")
    print("=" * 64)

    print_summary(comparisons["exact"])

    print("\nTIMING-TOLERANT SPEECH COVERAGE")
    print("=" * 64)
    print("Word boundary tolerance: 100ms")

    print_summary(comparisons["tolerant"])

    tolerant = comparisons["tolerant"]["0.5"]

    for category in (
        "recovered",
        "regressed",
        "persistent",
    ):
        print_ranked(
            f"TOP {category.upper()} INTERVALS "
            "(threshold 0.5, tolerance 100ms)",
            tolerant[category]["intervals"]
        )

    empty = empty_segment_analysis(evidence, vad)

    print("\nEMPTY TERN SEGMENTS")
    print("=" * 64)

    for row in empty:
        stats = row["thresholds"]["0.5"]

        coverage = (
            100 * stats["seconds"] / row["duration"]
        )

        print(
            f"{row['id']}  "
            f"{timestamp(row['start'])} - "
            f"{timestamp(row['end'])}  "
            f"speech={stats['seconds']:.3f}s  "
            f"({coverage:.1f}%)  "
            f"longest={stats['longest']:.3f}s"
        )

    output = {
        "schema": "hehawk.hunt.differential",
        "version": 1,
        "timestamp_basis": "episode",
        "source_sha256": vad["source_sha256"],
        "vad_sha256": vad_hash,
        "original_inventory_sha256": original_hash,
        "tern_inventory_sha256": tern_hash,
        "tern_evidence_sha256": evidence_hash,
        "tern_provenance_chain_verified": True,
        "original_source_match_verified": False,
        "settings": {
            "thresholds": list(THRESHOLDS),
            "timing_tolerance_seconds": TIMING_TOLERANCE,
            "minimum_report_duration": MIN_REPORT_DURATION,
        },
        "comparisons": comparisons,
        "empty_segments": empty,
    }

    # Ensure that none of our input files changed.

    for path, expected in (
        (args.vad, vad_hash),
        (args.original, original_hash),
        (args.tern, tern_hash),
        (args.evidence, evidence_hash),
    ):
        _, current = load(path)

        if current != expected:
            raise RuntimeError(f"Input changed: {path}")

    with args.json.open("x", encoding="utf-8") as f:
        json.dump(
            output,
            f,
            indent=2,
            allow_nan=False
        )
        f.write("\n")

    print("\nSpeech coverage accounting: PASSED")
    print(f"Saved: {args.json}")


if __name__ == "__main__":
    main()
