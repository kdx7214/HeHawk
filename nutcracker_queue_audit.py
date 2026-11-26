#!/usr/bin/env python3
"""NUTCRACKER 7I.1: review queue consolidation audit."""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from magpie_overlay import (
    require,
    read_json,
    read_input,
    verify_link,
    verify_schema,
    timestamp,
)

from hunt_shared import (
    union,
    duration,
    overlap_duration,
)


# ------------------------------------------------------------
# Experimental scheduling policies
# ------------------------------------------------------------

POLICIES = {
    "comprehensive": {
        "minimum_seconds": 0.0,
        "historical_minimum_seconds": 0.0,
    },
    "balanced": {
        "minimum_seconds": 0.250,
        "historical_minimum_seconds": 0.100,
    },
    "focused": {
        "minimum_seconds": 0.500,
        "historical_minimum_seconds": 0.500,
    },
}


def selected(candidate, policy):

    length = candidate["duration"]

    if length + 1e-9 >= policy["minimum_seconds"]:
        return True

    if "meaningful_coverage" in candidate:
        historical = candidate["meaningful_coverage"][
            "historical"
        ]
    else:
        historical = candidate["coverage"][
            "historical"
        ]["seconds"] > 0

    return (
        historical
        and length + 1e-9
        >= policy["historical_minimum_seconds"]
    )


# ------------------------------------------------------------
# Window construction
# ------------------------------------------------------------

def build_windows(
    regions,
    candidates,
    policy,
    episode_end,
    context,
    merge_gap,
):

    seeds = []

    for region in regions:

        seeds.append({
            "start": region["start"],
            "end": region["end"],
            "kind": "magpie",
            "id": region["id"],
        })

    for candidate in candidates:

        if selected(candidate, policy):

            seeds.append({
                "start": candidate["start"],
                "end": candidate["end"],
                "kind": "hunt",
                "id": candidate["id"],
            })

    seeds.sort(
        key=lambda item: (
            item["start"],
            item["end"],
            item["id"],
        )
    )

    windows = []

    for seed in seeds:

        start = max(
            0.0,
            seed["start"] - context,
        )

        end = min(
            episode_end,
            seed["end"] + context,
        )

        if (
            windows
            and start
            <= windows[-1]["end"] + merge_gap
        ):

            window = windows[-1]

            window["end"] = max(
                window["end"], end
            )

            window["seeds"].append(seed)

        else:

            windows.append({
                "start": start,
                "end": end,
                "seeds": [seed],
            })

    for index, window in enumerate(
        windows, 1
    ):

        window["id"] = f"W{index:04d}"

        window["duration"] = (
            window["end"] - window["start"]
        )

        window["magpie_region_ids"] = [
            seed["id"]
            for seed in window["seeds"]
            if seed["kind"] == "magpie"
        ]

        window["hunt_seed_ids"] = [
            seed["id"]
            for seed in window["seeds"]
            if seed["kind"] == "hunt"
        ]

        window["hunt_contained_ids"] = []
        window["hunt_partial_ids"] = []

        for candidate in candidates:

            start = candidate["start"]
            end = candidate["end"]

            if (
                start >= window["start"] - 1e-9
                and end <= window["end"] + 1e-9
            ):

                window[
                    "hunt_contained_ids"
                ].append(candidate["id"])

            elif (
                end > window["start"]
                and start < window["end"]
            ):

                window[
                    "hunt_partial_ids"
                ].append(candidate["id"])

    return windows


# ------------------------------------------------------------
# Independent accounting
# ------------------------------------------------------------

def audit_windows(
    windows,
    regions,
    candidates,
    policy,
    episode_end,
):

    expected_regions = {
        item["id"]
        for item in regions
    }

    expected_seeds = {
        item["id"]
        for item in candidates
        if selected(item, policy)
    }

    region_counts = Counter()
    seed_counts = Counter()

    contained = set()
    partial = set()

    intervals = []

    previous_end = 0.0

    for window in windows:

        start = window["start"]
        end = window["end"]

        require(
            0 <= start < end <= episode_end,
            "Invalid review window",
        )

        require(
            start >= previous_end,
            "Review windows overlap",
        )

        previous_end = end

        intervals.append([start, end])

        region_counts.update(
            window["magpie_region_ids"]
        )

        seed_counts.update(
            window["hunt_seed_ids"]
        )

        contained.update(
            window["hunt_contained_ids"]
        )

        partial.update(
            window["hunt_partial_ids"]
        )

    require(
        set(region_counts) == expected_regions,
        "MAGPIE region conservation failed",
    )

    require(
        all(
            count == 1
            for count in region_counts.values()
        ),
        "Duplicate MAGPIE region assignment",
    )

    require(
        set(seed_counts) == expected_seeds,
        "HUNT seed conservation failed",
    )

    require(
        all(
            count == 1
            for count in seed_counts.values()
        ),
        "Duplicate HUNT seed assignment",
    )

    require(
        expected_seeds <= contained,
        "HUNT seed not fully contained",
    )

    intervals = union(intervals)

    all_ids = {
        item["id"]
        for item in candidates
    }

    partial -= contained

    deferred = all_ids - contained - partial

    require(
        len(contained)
        + len(partial)
        + len(deferred)
        == len(candidates),
        "Candidate accounting failed",
    )

    covered_seconds = 0.0
    total_gap_seconds = 0.0

    classifications = {}

    for candidate in candidates:

        candidate_id = candidate["id"]

        covered = overlap_duration(
            candidate["start"],
            candidate["end"],
            intervals,
        )

        length = candidate["duration"]

        total_gap_seconds += length
        covered_seconds += covered

        if candidate_id in contained:

            status = "contained"

            require(
                math.isclose(
                    covered,
                    length,
                    abs_tol=1e-7,
                ),
                "Contained candidate coverage mismatch",
            )

        elif candidate_id in partial:

            status = "partial"

        else:

            status = "deferred"

            require(
                covered < 1e-7,
                "Deferred candidate has coverage",
            )

        classification = candidate[
            "evidence_classification"
        ]

        classifications.setdefault(
            classification, Counter()
        )[status] += 1

    listening_seconds = duration(intervals)

    longest = max(
        windows,
        key=lambda item: item["duration"],
        default=None,
    )

    return {
        "windows": len(windows),
        "magpie_regions": len(region_counts),
        "hunt_seeds": len(expected_seeds),
        "hunt_contained": len(contained),
        "hunt_partial": len(partial),
        "hunt_deferred": len(deferred),
        "listening_seconds": listening_seconds,
        "episode_fraction": (
            listening_seconds / episode_end
        ),
        "mean_window_seconds": (
            listening_seconds / len(windows)
            if windows else 0.0
        ),
        "longest_window": longest,
        "covered_gap_seconds": covered_seconds,
        "total_gap_seconds": total_gap_seconds,
        "gap_coverage_fraction": (
            covered_seconds / total_gap_seconds
            if total_gap_seconds else 0.0
        ),
        "evidence_classifications": {
            name: dict(counts)
            for name, counts
            in classifications.items()
        },
        "contained_ids": sorted(contained),
        "partial_ids": sorted(partial),
        "deferred_ids": sorted(deferred),
    }


# ------------------------------------------------------------
# Known problem checks
# ------------------------------------------------------------

def known_problem_checks(candidates, statistics):

    checks = []

    targets = [
        (
            "T0028 recognition regression",
            413.184,
            414.624,
        ),
        (
            "T0015 fictional language",
            213.888,
            214.976,
        ),
    ]

    contained = set(
        statistics["contained_ids"]
    )

    partial = set(
        statistics["partial_ids"]
    )

    for label, start, end in targets:

        matching = [
            item
            for item in candidates
            if math.isclose(
                item["start"],
                start,
                abs_tol=0.001,
            )
            and math.isclose(
                item["end"],
                end,
                abs_tol=0.001,
            )
        ]

        if len(matching) != 1:

            checks.append({
                "label": label,
                "status": "target_not_unique",
            })

            continue

        candidate = matching[0]

        candidate_id = candidate["id"]

        if candidate_id in contained:
            status = "contained"

        elif candidate_id in partial:
            status = "partial"

        else:
            status = "deferred"

        checks.append({
            "label": label,
            "candidate_id": candidate_id,
            "start": start,
            "end": end,
            "status": status,
        })

    return checks


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "overlay", type=Path
    )

    parser.add_argument(
        "hunt", type=Path
    )

    parser.add_argument(
        "--context",
        type=float,
        default=1.000,
    )

    parser.add_argument(
        "--merge-gap",
        type=float,
        default=0.500,
    )

    parser.add_argument(
        "--json",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    for value in (
        args.context,
        args.merge_gap,
    ):

        require(
            math.isfinite(value)
            and value >= 0,
            "Invalid window setting",
        )

    require(
        not args.json.exists(),
        f"Output already exists: {args.json}",
    )

    overlay, overlay_input = read_json(
        args.overlay
    )

    hunt, hunt_input = read_json(
        args.hunt
    )

    verify_schema(
        overlay,
        "hehawk.magpie.overlay",
    )

    verify_schema(
        hunt,
        "hehawk.hunt.shared_gaps",
    )

    verify_link(
        hunt["inputs"]["overlay"],
        overlay_input,
        "HUNT -> MAGPIE overlay",
    )

    require(
        overlay["source_sha256"]
        == hunt["source_sha256"],
        "Episode source hash mismatch",
    )

    episode_end = hunt[
        "coverage_statistics"
    ]["episode_seconds"]

    regions = overlay["regions"]
    candidates = hunt["candidates"]

    require(
        len({r["id"] for r in regions})
        == len(regions),
        "Duplicate region IDs",
    )

    require(
        len({c["id"] for c in candidates})
        == len(candidates),
        "Duplicate candidate IDs",
    )

    results = {}

    print("NUTCRACKER 7I.1 queue audit")
    print("=" * 72)

    print(f"MAGPIE regions: {len(regions)}")
    print(f"HUNT candidates: {len(candidates)}")

    print(
        f"Episode: {timestamp(episode_end)}"
        f" ({episode_end:.3f}s)"
    )

    for name, policy in POLICIES.items():

        windows = build_windows(
            regions,
            candidates,
            policy,
            episode_end,
            args.context,
            args.merge_gap,
        )

        statistics = audit_windows(
            windows,
            regions,
            candidates,
            policy,
            episode_end,
        )

        checks = known_problem_checks(
            candidates,
            statistics,
        )

        results[name] = {
            "policy": policy,
            "statistics": statistics,
            "known_problem_checks": checks,
            "windows": windows,
        }

        print("\n" + name.upper())
        print("-" * 72)

        for key in (
            "windows",
            "magpie_regions",
            "hunt_seeds",
            "hunt_contained",
            "hunt_partial",
            "hunt_deferred",
        ):

            print(
                f"  {key:30}"
                f" {statistics[key]:6}"
            )

        seconds = statistics[
            "listening_seconds"
        ]

        print(
            f"  Listening time:"
            f" {timestamp(seconds)}"
            f" ({seconds:.3f}s)"
        )

        print(
            f"  Episode coverage:"
            f" {statistics['episode_fraction']:.2%}"
        )

        print(
            f"  Gap duration coverage:"
            f" {statistics['gap_coverage_fraction']:.2%}"
        )

        print(
            f"  Mean window:"
            f" {statistics['mean_window_seconds']:.3f}s"
        )

        longest = statistics["longest_window"]

        if longest:

            print(
                f"  Longest window:"
                f" {longest['duration']:.3f}s"
            )

            print(
                f"    {timestamp(longest['start'])}"
                f" - {timestamp(longest['end'])}"
                f" ({longest['start']:.3f}"
                f" - {longest['end']:.3f}s)"
            )

        print("\n  Evidence coverage:")

        for classification, counts in sorted(
            statistics[
                "evidence_classifications"
            ].items()
        ):

            print(
                f"    {classification:25}"
                f" contained={counts.get('contained', 0):4}"
                f" partial={counts.get('partial', 0):4}"
                f" deferred={counts.get('deferred', 0):4}"
            )

        print("\n  Known problem checks:")

        for check in checks:

            print(
                f"    {check['label']}:"
                f" {check['status']}"
            )

    # More inclusive scheduling policies must
    # contain every fully covered candidate
    # from less inclusive policies.

    comprehensive = set(
        results["comprehensive"]["statistics"][
            "contained_ids"
        ]
    )

    balanced = set(
        results["balanced"]["statistics"][
            "contained_ids"
        ]
    )

    focused = set(
        results["focused"]["statistics"][
            "contained_ids"
        ]
    )

    require(
        focused <= balanced <= comprehensive,
        "Scheduling policy nesting failed",
    )

    require(
        len(comprehensive) == len(candidates),
        "Comprehensive policy lost candidates",
    )

    inputs = {
        "overlay": overlay_input,
        "hunt": hunt_input,
    }

    for name, provenance in inputs.items():

        _, current = read_input(
            provenance["path"]
        )

        verify_link(
            provenance,
            current,
            f"unchanged input: {name}",
        )

    report = {
        "schema": "hehawk.nutcracker.queue_audit",
        "version": 1,
        "timestamp_basis": "episode",
        "source_sha256": overlay["source_sha256"],
        "inputs": inputs,
        "settings": {
            "context_seconds": args.context,
            "merge_gap_seconds": args.merge_gap,
            "scheduling_only": True,
            "automatic_acceptance": False,
            "automatic_elimination": False,
        },
        "results": results,
        "integrity": {
            "inputs_unchanged": True,
            "region_conservation_verified": True,
            "candidate_accounting_verified": True,
            "policy_nesting_verified": True,
        },
        "limitations": {
            "actual_review_time_measured": False,
            "candidate_accuracy_verified": False,
            "persistent_decisions_implemented": False,
            "known_problem_checks_episode_specific": True,
        },
    }

    with args.json.open(
        "x", encoding="utf-8"
    ) as output:

        json.dump(
            report,
            output,
            ensure_ascii=False,
            indent=2,
        )

        output.write("\n")

    print("\nIntegrity: PASS")
    print("All candidates accounted for.")
    print("No candidates eliminated.")
    print("No human decisions modified.")
    print(f"Report: {args.json}")


if __name__ == "__main__":
    main()

