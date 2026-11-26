#!/usr/bin/env python3
"""HUNT 7H.5: sample-aware evidence associations."""

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_input(path):
    raw = path.read_bytes()

    return json.loads(raw), {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def verify_input(provenance):
    path = Path(provenance["path"])

    digest = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()

    require(
        digest == provenance["sha256"],
        f"Input changed: {path}",
    )


def span(item, rate):
    return (
        round(item["start"] * rate),
        round(item["end"] * rate),
    )


def intersection_samples(first, second):
    return max(
        0,
        min(first[1], second[1])
        - max(first[0], second[0]),
    )


def classification(historical, caption):

    if historical and caption:
        return "historical_and_caption"

    if historical:
        return "historical_only"

    if caption:
        return "caption_only"

    return "acoustic_only"


def main():

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument("hunt", type=Path)
    parser.add_argument("overlay", type=Path)
    parser.add_argument("vad", type=Path)

    parser.add_argument(
        "--json",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    hunt, hunt_input = read_input(args.hunt)
    overlay, overlay_input = read_input(args.overlay)
    vad, vad_input = read_input(args.vad)

    require(
        hunt["schema"] == "hehawk.hunt.shared_gaps",
        "Unexpected HUNT schema",
    )

    require(
        len({
            hunt["source_sha256"],
            overlay["source_sha256"],
            vad["source_sha256"],
        }) == 1,
        "Source identity mismatch",
    )

    require(
        hunt["inputs"]["overlay"]["sha256"]
        == overlay_input["sha256"],
        "Overlay provenance mismatch",
    )

    require(
        hunt["inputs"]["vad"]["sha256"]
        == vad_input["sha256"],
        "VAD provenance mismatch",
    )

    rate = vad["sample_rate"]

    require(
        isinstance(rate, int) and rate > 0,
        "Invalid sample rate",
    )

    sample_seconds = 1 / rate

    # Small arithmetic tolerance, not an acoustic
    # or minimum-gap threshold.

    epsilon = 1e-12

    regions = {}

    for region in overlay["regions"]:

        region_id = region["id"]

        require(
            region_id not in regions,
            f"Duplicate region: {region_id}",
        )

        regions[region_id] = span(region, rate)

    candidates = hunt["candidates"]

    original_inventory = [
        (
            item["id"],
            item["start"],
            item["end"],
            item["duration_samples"],
        )
        for item in candidates
    ]

    require(
        len({row[0] for row in original_inventory})
        == len(original_inventory),
        "Duplicate candidate IDs",
    )

    counts = Counter()
    seconds = defaultdict(float)
    transitions = Counter()

    removed_associations = 0
    added_associations = 0
    overlapping_candidates = 0
    total_samples = 0

    for item in candidates:

        start, end = span(item, rate)

        require(
            0 <= start < end <= vad["source_samples"],
            f"Invalid sample span: {item['id']}",
        )

        require(
            item["start_sample"] == start
            and item["end_sample"] == end
            and item["duration_samples"] == end - start,
            f"Sample metadata mismatch: {item['id']}",
        )

        total_samples += end - start

        coverage = item["coverage"]

        present = {}

        for source in (
            "original",
            "recovered",
            "historical",
        ):

            duration = coverage[source]["seconds"]

            require(
                math.isfinite(duration)
                and duration >= 0,
                f"Invalid coverage: {item['id']}",
            )

            present[source] = (
                duration + epsilon >= sample_seconds
            )

        previous_class = item[
            "evidence_classification"
        ]

        current_class = classification(
            present["historical"],
            present["original"]
            or present["recovered"],
        )

        item["raw_evidence_classification"] = (
            previous_class
        )

        item["meaningful_coverage"] = present

        item["evidence_classification"] = (
            current_class
        )

        if previous_class != current_class:

            transitions[
                (previous_class, current_class)
            ] += 1

        counts[current_class] += 1
        seconds[current_class] += (end - start) / rate

        previous_ids = item[
            "disagreement_region_ids"
        ]

        require(
            set(previous_ids) <= regions.keys(),
            f"Unknown region association: {item['id']}",
        )

        current_ids = [
            region_id
            for region_id, region_span in regions.items()
            if intersection_samples(
                (start, end),
                region_span,
            ) > 0
        ]

        item["raw_disagreement_region_ids"] = (
            list(previous_ids)
        )

        item["disagreement_region_ids"] = (
            current_ids
        )

        removed_associations += len(
            set(previous_ids) - set(current_ids)
        )

        added_associations += len(
            set(current_ids) - set(previous_ids)
        )

        if current_ids:
            overlapping_candidates += 1

    final_inventory = [
        (
            item["id"],
            item["start"],
            item["end"],
            item["duration_samples"],
        )
        for item in candidates
    ]

    require(
        original_inventory == final_inventory,
        "Candidate inventory changed",
    )

    require(
        sum(counts.values()) == len(candidates),
        "Classification accounting mismatch",
    )

    stats = hunt["statistics"]

    stats["evidence_counts"] = dict(counts)
    stats["evidence_seconds"] = dict(seconds)

    stats["overlapping_disagreement_regions"] = (
        overlapping_candidates
    )

    hunt["settings"]["sample_grid"] = {
        "sample_rate": rate,
        "primary_coverage": "integer_samples",
        "recognition_boundary_guard_samples": 0.050,
        "minimum_supplementary_overlap_seconds":
            sample_seconds,
        "supplementary_arithmetic_epsilon_seconds":
            epsilon,
        "magpie_association":
            "positive_sample_intersection",
        "raw_coverage_preserved": True,
        "minimum_candidate_duration_added": False,
    }

    hunt["inputs"]["previous_hunt"] = hunt_input

    hunt["association_audit"] = {
        "classification_changes": [
            {
                "previous": previous,
                "current": current,
                "count": count,
            }
            for (previous, current), count
            in sorted(transitions.items())
        ],
        "removed_magpie_associations":
            removed_associations,
        "added_magpie_associations":
            added_associations,
        "candidate_count": len(candidates),
        "candidate_samples": total_samples,
        "candidate_inventory_preserved": True,
        "raw_classifications_preserved": True,
        "raw_magpie_associations_preserved": True,
    }

    for provenance in (
        hunt_input,
        overlay_input,
        vad_input,
    ):
        verify_input(provenance)

    with args.json.open("x", encoding="utf-8") as output:

        json.dump(
            hunt,
            output,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

        output.write("\n")

    print("HUNT 7H.5 evidence associations")
    print("=" * 72)

    print("Sample rate:", rate)
    print("Candidates:", len(candidates))
    print("Candidate samples:", total_samples)

    print(
        "Minimum supplementary overlap:",
        f"{sample_seconds * 1e6:.3f}us",
    )

    print("\nEvidence classifications")

    for name, count in sorted(counts.items()):

        print(
            f"  {name:30} {count:6}"
            f" {seconds[name]:10.3f}s"
        )

    print("\nClassification transitions")

    for (previous, current), count in sorted(
        transitions.items()
    ):

        print(
            f"  {previous} -> {current}: {count}"
        )

    print("\nMAGPIE associations")

    print("  Removed:", removed_associations)
    print("  Added:", added_associations)
    print("  Overlapping candidates:", overlapping_candidates)

    print("\nCandidate inventory conservation: PASS")
    print("Input integrity: PASS")
    print("Raw evidence preserved.")
    print("Report:", args.json)


if __name__ == "__main__":
    main()
