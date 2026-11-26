#!/usr/bin/env python3
"""HUNT 7H.2: sample-grid coverage arithmetic."""

import json
import math
import sys
from pathlib import Path

import hunt_shared as hunt


original_recognition = hunt.recognition_coverage
original_speech = hunt.speech_coverage
original_union = hunt.union
original_intersect = hunt.intersect
original_subtract = hunt.subtract
original_build_candidates = hunt.build_candidates
original_word_intervals = hunt.word_intervals
original_caption_intervals = hunt.caption_intervals

SAMPLE_RATE = None

# Experimental guard, expressed in audio samples.
# Unexpected off-grid timing must not be silently
# rounded without investigation.
MAX_BOUNDARY_ERROR = 0.050

statistics = {
    "boundaries_checked": 0,
    "maximum_error_samples": 0.0,
}


# ------------------------------------------------------------
# Sample-grid conversion
# ------------------------------------------------------------

def sample_index(seconds):

    require_rate()

    position = seconds * SAMPLE_RATE

    if not math.isfinite(position):
        raise ValueError("Nonfinite sample position")

    index = round(position)
    error = abs(position - index)

    statistics["boundaries_checked"] += 1

    statistics["maximum_error_samples"] = max(
        statistics["maximum_error_samples"],
        error,
    )

    if error > MAX_BOUNDARY_ERROR:

        raise ValueError(
            f"Off-grid boundary: {seconds:.12f}s "
            f"({error:.9f} samples)"
        )

    return index


def require_rate():

    if SAMPLE_RATE is None:
        raise RuntimeError(
            "Sample rate has not been initialized"
        )


def to_samples(intervals):

    return [
        [
            sample_index(start),
            sample_index(end),
        ]
        for start, end in intervals
    ]


def to_seconds(intervals):

    require_rate()

    return [
        [
            start / SAMPLE_RATE,
            end / SAMPLE_RATE,
        ]
        for start, end in intervals
    ]


# ------------------------------------------------------------
# Integer interval operations
# ------------------------------------------------------------

def sample_union(intervals):

    return to_seconds(
        original_union(
            to_samples(intervals)
        )
    )


def sample_intersect(first, second):

    return to_seconds(
        original_intersect(
            to_samples(first),
            to_samples(second),
        )
    )


def sample_subtract(first, second):

    return to_seconds(
        original_subtract(
            to_samples(first),
            to_samples(second),
        )
    )


# ------------------------------------------------------------
# Recognition and speech coverage
# ------------------------------------------------------------

def recognition_coverage(data):

    global SAMPLE_RATE

    SAMPLE_RATE = data["sample_rate"]

    if (
        not isinstance(SAMPLE_RATE, int)
        or SAMPLE_RATE <= 0
    ):

        raise ValueError("Invalid sample rate")

    # The original function invokes hunt.union.
    # That function now performs integer arithmetic,
    # including the initial per-pass coverage unions.

    return original_recognition(data)


def speech_coverage(vad, threshold):

    if vad["sample_rate"] != SAMPLE_RATE:

        raise ValueError(
            "Recognition/VAD sample rate mismatch"
        )

    return original_speech(vad, threshold)


# ------------------------------------------------------------
# Candidate validation
# ------------------------------------------------------------

def historical_intervals(words, episode_end):

    saved_union = hunt.union
    hunt.union = original_union

    try:
        return original_word_intervals(
            words, episode_end
        )
    finally:
        hunt.union = saved_union


def caption_intervals(cues, episode_end):

    saved_union = hunt.union
    hunt.union = original_union

    try:
        return original_caption_intervals(
            cues, episode_end
        )
    finally:
        hunt.union = saved_union


def build_candidates(
    gaps,
    vad,
    evidence,
    original_cues,
    recovered_cues,
    historical,
    regions,
):

    candidates = original_build_candidates(
        gaps,
        vad,
        evidence,
        original_cues,
        recovered_cues,
        historical,
        regions,
    )

    total_samples = 0

    for item in candidates:

        start = sample_index(item["start"])
        end = sample_index(item["end"])

        if not (
            0 <= start < end
            <= vad["source_samples"]
        ):

            raise ValueError(
                f"Invalid sample span: {item['id']}"
            )

        item["start_sample"] = start
        item["end_sample"] = end
        item["duration_samples"] = end - start

        total_samples += end - start

    statistics["candidate_count"] = len(
        candidates
    )

    statistics["candidate_samples"] = (
        total_samples
    )

    statistics["zero_sample_candidates"] = 0

    return candidates


# ------------------------------------------------------------
# Adapter entry point
# ------------------------------------------------------------

def main():

    # This adapter uses the same CLI as hunt_shared.
    # A distinct output path is required.

    hunt.recognition_coverage = (
        recognition_coverage
    )

    hunt.speech_coverage = speech_coverage

    hunt.union = sample_union
    hunt.intersect = sample_intersect
    hunt.subtract = sample_subtract

    hunt.word_intervals = historical_intervals
    hunt.caption_intervals = caption_intervals

    hunt.build_candidates = build_candidates

    hunt.main()

    print("\nSample-grid precision audit")
    print("=" * 72)

    print("Sample rate:", SAMPLE_RATE)

    print(
        "Boundary conversions:",
        statistics["boundaries_checked"],
    )

    print(
        "Maximum boundary error:",
        f"{statistics['maximum_error_samples']:.12f}",
        "samples",
    )

    print(
        "Maximum permitted boundary error:",
        MAX_BOUNDARY_ERROR,
        "samples",
    )

    print(
        "Candidate count:",
        statistics["candidate_count"],
    )

    print(
        "Candidate audio samples:",
        statistics["candidate_samples"],
    )

    print(
        "Zero-sample candidates:",
        statistics["zero_sample_candidates"],
    )

    print("Sample-grid integrity: PASS")


if __name__ == "__main__":
    main()

