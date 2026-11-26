
#!/usr/bin/env python3
"""MAGPIE 7E: localize multi-pass lexical disagreements."""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from magpie import recognition_words

from magpie_incremental import (
    read_input,
    timestamp,
)


# ------------------------------------------------------------
# Reconstruct timed words from individual observations.
# ------------------------------------------------------------

def observation_words(observation, offset):

    data = {
        "tokens": observation["tokens"],
        "timestamps": observation["timestamps"],
        "durations": observation["durations"],
        "source_offset_seconds": 0,
    }

    words = recognition_words(data)

    reconstructed = [
        word["normalized"]
        for word in words
    ]

    if reconstructed != observation["normalized_words"]:

        raise ValueError(
            "Token-derived words differ from text-derived words."
        )

    for word in words:

        word["start"] += offset
        word["end"] += offset

    return words


# ------------------------------------------------------------
# Find chronological, one-to-one lexical matches.
#
# Maximize match count, then minimize timing displacement.
# ------------------------------------------------------------

def align_pair(a, b, tolerance):

    n = len(a)
    m = len(b)

    scores = [
        [(0, 0.0)] * (m + 1)
        for _ in range(n + 1)
    ]

    trace = [
        [None] * (m + 1)
        for _ in range(n + 1)
    ]

    for i in range(1, n + 1):
        trace[i][0] = "up"

    for j in range(1, m + 1):
        trace[0][j] = "left"

    for i in range(1, n + 1):

        for j in range(1, m + 1):

            wa = a[i - 1]
            wb = b[j - 1]

            best = scores[i - 1][j]
            direction = "up"

            if scores[i][j - 1] > best:

                best = scores[i][j - 1]
                direction = "left"

            start_delta = abs(
                wa["start"] - wb["start"]
            )

            end_delta = abs(
                wa["end"] - wb["end"]
            )

            if (
                wa["normalized"] == wb["normalized"]
                and start_delta <= tolerance
                and end_delta <= tolerance
            ):

                previous = scores[i - 1][j - 1]

                candidate = (
                    previous[0] + 1,
                    previous[1]
                    - start_delta
                    - end_delta,
                )

                if candidate >= best:

                    best = candidate
                    direction = "match"

            scores[i][j] = best
            trace[i][j] = direction

    matches = {}

    i = n
    j = m

    while i or j:

        direction = trace[i][j]

        if direction == "match":

            matches[i - 1] = j - 1

            i -= 1
            j -= 1

        elif direction == "up":

            i -= 1

        elif direction == "left":

            j -= 1

        else:

            raise RuntimeError(
                "Invalid alignment traceback."
            )

    return matches


# ------------------------------------------------------------
# Identify words supported by every pass.
#
# Baseline words provide anchor coordinates only.
# All intervening words from every pass are preserved.
# ------------------------------------------------------------

def common_anchors(sequences, pass_ids, tolerance):

    baseline = sequences[pass_ids[0]]

    mappings = {}

    for pid in pass_ids[1:]:

        mappings[pid] = align_pair(
            baseline,
            sequences[pid],
            tolerance
        )

    anchors = []

    for index in range(len(baseline)):

        if not all(
            index in mappings[pid]
            for pid in pass_ids[1:]
        ):
            continue

        positions = {
            pass_ids[0]: index
        }

        for pid in pass_ids[1:]:

            positions[pid] = mappings[pid][index]

        words = [
            sequences[pid][positions[pid]]
            for pid in pass_ids
        ]

        # Require agreement across the complete group,
        # not just agreement with the baseline.

        starts = [
            word["start"] for word in words
        ]

        ends = [
            word["end"] for word in words
        ]

        if max(starts) - min(starts) > tolerance:
            continue

        if max(ends) - min(ends) > tolerance:
            continue

        anchors.append({
            "positions": positions,
            "normalized": baseline[index]["normalized"],
            "start": min(starts),
            "end": max(ends),
        })

    return anchors


# ------------------------------------------------------------
# Consolidate lexical alternatives between anchors.
# ------------------------------------------------------------

def make_region(segment, alternatives, pass_ids):

    groups = {}

    all_words = []

    for pid in pass_ids:

        words = alternatives[pid]

        key = tuple(
            word["normalized"]
            for word in words
        )

        groups.setdefault(key, []).append(pid)

        all_words.extend(words)

    if len(groups) <= 1:
        return None

    if not all_words:
        raise RuntimeError(
            "Disagreement has no lexical evidence."
        )

    raw_start = min(
        word["start"]
        for word in all_words
    )

    raw_end = max(
        word["end"]
        for word in all_words
    )

    # Restrict listening coordinates to real source audio.
    # Original recognition timings remain untouched.

    start = min(
        segment["end"],
        max(segment["start"], raw_start)
    )

    end = min(
        segment["end"],
        max(segment["start"], raw_end)
    )

    hypotheses = []

    for key, supporting_passes in groups.items():

        hypotheses.append({
            "normalized_words": list(key),
            "supporting_passes": supporting_passes,
            "support_count": len(supporting_passes),
            "empty": not bool(key),
        })

    return {
        "segment_id": segment["id"],
        "start": start,
        "end": end,
        "raw_start": raw_start,
        "raw_end": raw_end,
        "duration": end - start,
        "timing_clipped": (
            start != raw_start
            or end != raw_end
        ),
        "hypotheses": hypotheses,
        "observations": alternatives,
        "contains_empty_alternative": (
            any(not key for key in groups)
        ),
        "human_verified": False,
    }


# ------------------------------------------------------------
# Localize disagreements within one segment.
# ------------------------------------------------------------

def localize_segment(segment, pass_ids, tolerance):

    observations = {
        item["pass_id"]: item
        for item in segment["observations"]
    }

    if set(observations) != set(pass_ids):
        raise ValueError(
            f"Incomplete observations: {segment['id']}"
        )

    sequences = {}

    for pid in pass_ids:

        sequences[pid] = observation_words(
            observations[pid],
            segment["start"]
        )

    anchors = common_anchors(
        sequences,
        pass_ids,
        tolerance
    )

    # Sentinel anchors preserve disagreements before
    # the first and after the last common word.

    boundaries = [{
        "positions": {
            pid: -1
            for pid in pass_ids
        }
    }]

    boundaries.extend(anchors)

    boundaries.append({
        "positions": {
            pid: len(sequences[pid])
            for pid in pass_ids
        }
    })

    regions = []

    accounted = {
        pid: len(anchors)
        for pid in pass_ids
    }

    agreed_nonanchor_words = {
        pid: 0
        for pid in pass_ids
    }

    for left, right in zip(
        boundaries,
        boundaries[1:]
    ):

        alternatives = {}

        for pid in pass_ids:

            a = left["positions"][pid] + 1
            b = right["positions"][pid]

            if b < a:
                raise RuntimeError(
                    "Nonmonotonic anchor sequence."
                )

            words = sequences[pid][a:b]

            alternatives[pid] = words

            accounted[pid] += len(words)

        region = make_region(
            segment,
            alternatives,
            pass_ids
        )

        if region is not None:

            regions.append(region)

        else:

            for pid in pass_ids:

                agreed_nonanchor_words[pid] += len(
                    alternatives[pid]
                )

    for pid in pass_ids:

        if accounted[pid] != len(sequences[pid]):

            raise RuntimeError(
                f"Word conservation failed: "
                f"{segment['id']} / {pid}"
            )

    return {
        "segment_id": segment["id"],
        "status": segment["status"],
        "start": segment["start"],
        "end": segment["end"],
        "anchor_count": len(anchors),
        "anchors": anchors,
        "word_counts": {
            pid: len(sequences[pid])
            for pid in pass_ids
        },
        "agreed_nonanchor_words":
            agreed_nonanchor_words,
        "regions": regions,
    }


# ------------------------------------------------------------
# Merge intervals and retain contributing region IDs.
# ------------------------------------------------------------

def merge_intervals(intervals, max_gap=0.0):

    result = []

    ordered = sorted(
        intervals,
        key=lambda item: (
            item["start"],
            item["end"]
        )
    )

    for item in ordered:

        if item["end"] < item["start"]:
            raise ValueError("Invalid interval.")

        if (
            result
            and item["start"]
            <= result[-1]["end"] + max_gap
        ):

            result[-1]["end"] = max(
                result[-1]["end"],
                item["end"]
            )

            result[-1]["region_ids"].extend(
                item.get("region_ids", [])
            )

        else:

            result.append({
                "start": item["start"],
                "end": item["end"],
                "region_ids": list(
                    item.get("region_ids", [])
                ),
            })

    for item in result:

        item["duration"] = (
            item["end"] - item["start"]
        )

        item["region_ids"] = sorted(
            set(item["region_ids"])
        )

    return result


def total_duration(intervals):

    return sum(
        item["end"] - item["start"]
        for item in intervals
    )


def review_windows(
    regions,
    context,
    merge_gap,
    duration
):

    intervals = []

    for region in regions:

        intervals.append({
            "start": max(
                0.0,
                region["start"] - context
            ),
            "end": min(
                duration,
                region["end"] + context
            ),
            "region_ids": [region["id"]],
        })

    windows = merge_intervals(
        intervals,
        merge_gap
    )

    for index, window in enumerate(windows, 1):

        window["id"] = f"W{index:04d}"

    return windows


# ------------------------------------------------------------
# Main.
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "accumulation",
        type=Path
    )

    parser.add_argument(
        "--anchor-tolerance",
        type=float,
        default=0.250
    )

    parser.add_argument(
        "--context",
        type=float,
        default=1.0
    )

    parser.add_argument(
        "--merge-gap",
        type=float,
        default=0.500
    )

    parser.add_argument(
        "--json",
        required=True,
        type=Path
    )

    args = parser.parse_args()

    for value in (
        args.anchor_tolerance,
        args.context,
        args.merge_gap
    ):

        if not math.isfinite(value) or value < 0:

            parser.error(
                "Timing parameters must be finite "
                "and nonnegative."
            )

    if args.json.exists():
        parser.error("Output already exists.")

    raw, digest = read_input(args.accumulation)

    data = json.loads(raw)

    if data["schema"] != "hehawk.magpie.accumulation":
        raise ValueError("Unexpected accumulation schema.")

    if data["version"] != 1:
        raise ValueError("Unsupported accumulation version.")

    if data["timestamp_basis"] != "episode":
        raise ValueError("Unexpected segment timestamp basis.")

    if (
        data["observation_timestamp_basis"]
        != "segment_relative"
    ):
        raise ValueError(
            "Unexpected observation timestamp basis."
        )

    pass_ids = [
        entry["id"]
        for entry in data["inputs"]
    ]

    if (
        len(pass_ids) < 2
        or len(set(pass_ids)) != len(pass_ids)
        or pass_ids[0] != "baseline"
    ):
        raise ValueError("Invalid pass inventory.")

    rate = data["sample_rate"]

    duration = data["source_samples"] / rate

    if rate != 16000 or duration <= 0:
        raise ValueError("Invalid source geometry.")

    results = []
    regions = []
    fallback_segments = []

    previous_end = 0

    for segment in data["segments"]:

        if (
            segment["start_sample"] != previous_end
            or segment["end_sample"]
            <= segment["start_sample"]
        ):
            raise ValueError(
                f"Invalid geometry: {segment['id']}"
            )

        previous_end = segment["end_sample"]

        if (
            segment["start"]
            != segment["start_sample"] / rate
            or segment["end"]
            != segment["end_sample"] / rate
        ):
            raise ValueError(
                f"Inconsistent timing: {segment['id']}"
            )

        # Unanimous lexical segments and all-empty
        # segments do not require disagreement localization.
        # They remain available for independent review.

        if segment["status"] in (
            "unanimous",
            "all_empty",
            "nonlexical_only",
        ):
            continue

        try:

            result = localize_segment(
                segment,
                pass_ids,
                args.anchor_tolerance
            )

        except ValueError as error:

            # Do not silently discard evidence when text
            # and token reconstruction disagree.
            # Preserve the complete segment for review.

            fallback_segments.append({
                "segment_id": segment["id"],
                "reason": str(error),
            })

            result = {
                "segment_id": segment["id"],
                "status": segment["status"],
                "start": segment["start"],
                "end": segment["end"],
                "anchor_count": 0,
                "anchors": [],
                "fallback": True,
                "regions": [{
                    "segment_id": segment["id"],
                    "start": segment["start"],
                    "end": segment["end"],
                    "duration": (
                        segment["end"]
                        - segment["start"]
                    ),
                    "fallback": True,
                    "hypotheses": segment["hypotheses"],
                    "observations": segment["observations"],
                    "human_verified": False,
                }],
            }

        if not result["regions"]:

            raise RuntimeError(
                f"Disputed segment has no review region: "
                f"{segment['id']}"
            )

        for region in result["regions"]:

            region["id"] = (
                f"D{len(regions) + 1:04d}"
            )

            regions.append(region)

        results.append(result)

    if previous_end != data["source_samples"]:
        raise ValueError("Incomplete source coverage.")

    # --------------------------------------------------------
    # Measure unique listening duration.
    # --------------------------------------------------------

    full_segments = merge_intervals([
        {
            "start": result["start"],
            "end": result["end"],
        }
        for result in results
    ])

    raw_intervals = merge_intervals([
        {
            "start": region["start"],
            "end": region["end"],
            "region_ids": [region["id"]],
        }
        for region in regions
    ])

    windows = review_windows(
        regions,
        args.context,
        args.merge_gap,
        duration
    )

    full_seconds = total_duration(full_segments)
    raw_seconds = total_duration(raw_intervals)
    review_seconds = total_duration(windows)

    reduction = (
        1.0 - review_seconds / full_seconds
        if full_seconds
        else 0.0
    )

    expected_ids = sorted(
        region["id"]
        for region in regions
    )

    actual_ids = sorted(
        rid
        for window in windows
        for rid in window["region_ids"]
    )

    if expected_ids != actual_ids:
        raise RuntimeError(
            "Review region conservation failed."
        )

    print("MAGPIE LOCALIZED DISAGREEMENT INVENTORY")
    print("=" * 64)

    print(f"Recognition passes:   {len(pass_ids)}")
    print(f"Total segments:       {len(data['segments'])}")
    print(f"Disputed segments:    {len(results)}")
    print(f"Fallback segments:    {len(fallback_segments)}")
    print(f"Localized regions:    {len(regions)}")
    print(f"Review windows:       {len(windows)}")

    print()
    print("LISTENING DURATION")
    print("=" * 64)

    for label, seconds in (
        ("Complete episode", duration),
        ("Complete disputed segments", full_seconds),
        ("Localized disagreement union", raw_seconds),
        ("Review windows with context", review_seconds),
    ):

        print(
            f"{label:32s}: "
            f"{timestamp(seconds)} "
            f"({seconds:.3f}s)"
        )

    print()
    print(
        f"Potential listening-time reduction: "
        f"{100 * reduction:.2f}%"
    )

    if windows:

        print(
            f"Mean review window: "
            f"{review_seconds / len(windows):.3f}s"
        )

    print()
    print("DISAGREEMENT CHARACTERISTICS")
    print("=" * 64)

    print(
        f"Common anchors in disputed segments: "
        f"{sum(r['anchor_count'] for r in results)}"
    )

    print(
        f"Regions with empty alternatives: "
        f"{sum(r.get('contains_empty_alternative', False) for r in regions)}"
    )

    print(
        f"Regions with clipped timing: "
        f"{sum(r.get('timing_clipped', False) for r in regions)}"
    )

    print()
    print("LONGEST REVIEW WINDOWS")
    print("=" * 64)

    ranked = sorted(
        windows,
        key=lambda window: (
            -window["duration"],
            window["start"]
        )
    )

    for window in ranked[:20]:

        print(
            f"{window['id']}  "
            f"{timestamp(window['start'])} - "
            f"{timestamp(window['end'])}  "
            f"{window['duration']:7.3f}s  "
            f"regions={len(window['region_ids'])}"
        )

    print()
    print("FALLBACK SEGMENTS")
    print("=" * 64)

    for segment in fallback_segments:

        print(
            f"{segment['segment_id']}: "
            f"{segment['reason']}"
        )

    output = {
        "schema": "hehawk.magpie.localization",
        "version": 1,
        "timestamp_basis": "episode",
        "source_sha256": data["source_sha256"],
        "sample_rate": rate,
        "source_samples": data["source_samples"],
        "input": {
            "path": str(args.accumulation),
            "sha256": digest,
        },
        "settings": {
            "anchor_tolerance_seconds":
                args.anchor_tolerance,
            "context_seconds":
                args.context,
            "merge_gap_seconds":
                args.merge_gap,
            "all_passes_required_for_anchor": True,
            "automatic_acceptance": False,
            "scope": "lexical_disagreement_only",
        },
        "statistics": {
            "disputed_segments": len(results),
            "fallback_segments": len(fallback_segments),
            "localized_regions": len(regions),
            "review_windows": len(windows),
            "episode_seconds": duration,
            "full_segment_review_seconds": full_seconds,
            "raw_disagreement_seconds": raw_seconds,
            "contextual_review_seconds": review_seconds,
            "potential_listening_time_reduction":
                reduction,
        },
        "fallback_segments": fallback_segments,
        "segments": results,
        "disagreement_intervals": raw_intervals,
        "review_windows": windows,
    }

    _, current_hash = read_input(args.accumulation)

    if current_hash != digest:
        raise RuntimeError("Input changed during processing.")

    with args.json.open("x", encoding="utf-8") as f:

        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False,
            allow_nan=False
        )

        f.write("\n")

    print()
    print("Localized word conservation: PASSED")
    print("Review region conservation:  PASSED")
    print("Input integrity:             PASSED")
    print(f"Saved: {args.json}")
    print("Localization completed successfully.")


if __name__ == "__main__":
    main()
