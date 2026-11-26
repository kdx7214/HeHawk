#!/usr/bin/env python3
"""HUNT 7H: shared recognition coverage gaps."""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from magpie_decoder_reconstruct import reconstruct
from magpie_overlay import (
    require,
    read_json,
    read_input,
    verify_link,
    verify_schema,
    validate_interval,
    historical_words,
    caption_words,
    timestamp,
)


# ------------------------------------------------------------
# Interval operations
# ------------------------------------------------------------

def union(intervals):

    result = []

    for start, end in sorted(intervals):

        validate_interval(
            start, end, "coverage interval"
        )

        if end <= start:
            continue

        if result and start <= result[-1][1]:

            result[-1][1] = max(
                result[-1][1], end
            )

        else:
            result.append([start, end])

    return result


def duration(intervals):

    return sum(
        end - start
        for start, end in intervals
    )


def intersect(first, second):

    result = []
    i = j = 0

    while i < len(first) and j < len(second):

        a, b = first[i]
        c, d = second[j]

        start = max(a, c)
        end = min(b, d)

        if end > start:
            result.append([start, end])

        if b <= d:
            i += 1
        else:
            j += 1

    return result


def subtract(first, second):

    result = []
    j = 0

    for start, end in first:

        cursor = start

        while (
            j < len(second)
            and second[j][1] <= cursor
        ):
            j += 1

        k = j

        while (
            k < len(second)
            and second[k][0] < end
        ):

            low, high = second[k]

            if low > cursor:
                result.append([
                    cursor,
                    min(low, end),
                ])

            cursor = max(cursor, high)

            if cursor >= end:
                break

            k += 1

        if cursor < end:
            result.append([cursor, end])

    return result


def overlap_duration(start, end, intervals):

    return sum(
        max(
            0.0,
            min(end, high) - max(start, low),
        )
        for low, high in intervals
        if high > start and low < end
    )


# ------------------------------------------------------------
# Recognition coverage
# ------------------------------------------------------------

def recognition_coverage(data):

    rate = data["sample_rate"]
    total_samples = data["source_samples"]

    pass_ids = [
        item["id"]
        for item in data["inputs"]
    ]

    require(
        len(pass_ids) == len(set(pass_ids)),
        "Duplicate recognition pass",
    )

    coverage = {
        name: []
        for name in pass_ids
    }

    word_counts = Counter()
    observation_count = 0
    clipped_words = 0
    previous_end = 0

    for segment in data["segments"]:

        first = segment["start_sample"]
        last = segment["end_sample"]

        require(
            first == previous_end,
            "Noncontiguous segment geometry",
        )

        require(
            first < last <= total_samples,
            "Invalid segment geometry",
        )

        previous_end = last

        start = first / rate
        end = last / rate

        observed = set()

        for observation in segment["observations"]:

            name = observation["pass_id"]

            require(
                name in coverage,
                "Unknown recognition pass",
            )

            require(
                name not in observed,
                "Duplicate segment observation",
            )

            observed.add(name)
            observation_count += 1

            result = reconstruct(
                observation["text"],
                observation["tokens"],
                observation["timestamps"],
                observation["durations"],
            )

            words = result["words"]

            require(
                [
                    word["normalized"]
                    for word in words
                ]
                == observation["normalized_words"],
                "Reconstructed lexical sequence differs",
            )

            word_counts[name] += len(words)

            for word in words:

                low = start + word["start"]
                high = start + word["end"]

                validate_interval(
                    low, high, "recognition word"
                )

                if low < start or high > end:
                    clipped_words += 1

                low = max(start, low)
                high = min(end, high)

                if high > low:
                    coverage[name].append([
                        low, high
                    ])

        require(
            observed == set(pass_ids),
            "Incomplete segment observations",
        )

    require(
        previous_end == total_samples,
        "Recognition source coverage incomplete",
    )

    require(
        observation_count
        == data["statistics"]["observations"],
        "Observation count mismatch",
    )

    coverage = {
        name: union(intervals)
        for name, intervals in coverage.items()
    }

    combined = union([
        interval
        for intervals in coverage.values()
        for interval in intervals
    ])

    return coverage, combined, {
        "observations": observation_count,
        "word_counts": dict(word_counts),
        "clipped_words": clipped_words,
    }


# ------------------------------------------------------------
# Speech probability coverage
# ------------------------------------------------------------

def speech_coverage(vad, threshold):

    rate = vad["sample_rate"]
    frame_samples = vad["frame_samples"]
    source_samples = vad["source_samples"]

    probabilities = vad["probabilities"]

    require(
        rate > 0 and frame_samples > 0,
        "Invalid VAD geometry",
    )

    require(
        len(probabilities)
        == math.ceil(
            source_samples / frame_samples
        ),
        "VAD frame count mismatch",
    )

    intervals = []

    for index, probability in enumerate(
        probabilities
    ):

        require(
            math.isfinite(probability)
            and 0 <= probability <= 1,
            "Invalid speech probability",
        )

        if probability < threshold:
            continue

        first = index * frame_samples

        last = min(
            first + frame_samples,
            source_samples,
        )

        if last > first:
            intervals.append([
                first / rate,
                last / rate,
            ])

    return union(intervals)


def probability_summary(vad, start, end):

    rate = vad["sample_rate"]
    frame_samples = vad["frame_samples"]

    frame_seconds = frame_samples / rate

    probabilities = vad["probabilities"]

    first = max(
        0,
        math.floor(start / frame_seconds),
    )

    last = min(
        len(probabilities),
        math.ceil(end / frame_seconds),
    )

    weighted = 0.0
    covered = 0.0
    peak = 0.0

    for index in range(first, last):

        low = index * frame_samples / rate

        high = min(
            (index + 1) * frame_samples,
            vad["source_samples"],
        ) / rate

        overlap = max(
            0.0,
            min(end, high) - max(start, low),
        )

        if overlap <= 0:
            continue

        probability = probabilities[index]

        weighted += probability * overlap
        covered += overlap
        peak = max(peak, probability)

    require(
        math.isclose(
            covered,
            end - start,
            abs_tol=1e-7,
        ),
        "Probability coverage mismatch",
    )

    return {
        "mean": weighted / covered,
        "peak": peak,
    }


# ------------------------------------------------------------
# Additional evidence
# ------------------------------------------------------------

def word_intervals(words, episode_end):

    intervals = []

    for word in words:

        start = word["start"]
        end = word["end"]

        validate_interval(
            start, end, "evidence word"
        )

        start = min(start, episode_end)
        end = min(end, episode_end)

        if end > start:
            intervals.append([start, end])

    return union(intervals)


def caption_intervals(cues, episode_end):

    return union([
        [
            min(cue["start"], episode_end),
            min(cue["end"], episode_end),
        ]
        for cue in cues
    ])


def matching_records(start, end, records):

    return [
        record
        for record in records
        if record["end"] > start
        and record["start"] < end
    ]


# ------------------------------------------------------------
# Candidate inventory
# ------------------------------------------------------------

def build_candidates(
    gaps,
    vad,
    evidence,
    original_cues,
    recovered_cues,
    historical,
    regions,
):

    candidates = []

    for index, (start, end) in enumerate(
        gaps, 1
    ):

        length = end - start

        coverage = {}

        for name, intervals in evidence.items():

            seconds = overlap_duration(
                start, end, intervals
            )

            coverage[name] = {
                "seconds": seconds,
                "fraction": min(
                    1.0, seconds / length
                ),
            }

        original = matching_records(
            start, end, original_cues
        )

        recovered = matching_records(
            start, end, recovered_cues
        )

        history = matching_records(
            start, end, historical
        )

        disagreements = matching_records(
            start, end, regions
        )

        historical_present = (
            coverage["historical"]["seconds"] > 0
        )

        caption_present = (
            coverage["original"]["seconds"] > 0
            or coverage["recovered"]["seconds"] > 0
        )

        if historical_present and caption_present:
            status = "historical_and_caption"

        elif historical_present:
            status = "historical_only"

        elif caption_present:
            status = "caption_only"

        else:
            status = "acoustic_only"

        candidates.append({
            "id": f"G{index:05d}",
            "start": start,
            "end": end,
            "duration": length,
            "speech_probability": (
                probability_summary(
                    vad, start, end
                )
            ),
            "evidence_classification": status,
            "coverage": coverage,
            "original_cue_ids": [
                cue["cue_id"]
                for cue in original
            ],
            "recovered_cue_ids": [
                cue["cue_id"]
                for cue in recovered
            ],
            "historical_word_indices": [
                word["index"]
                for word in history
            ],
            "disagreement_region_ids": [
                region["id"]
                for region in disagreements
            ],
            "requires_review_assessment": True,
            "human_verified": False,
            "confirmed_missing_dialogue": False,
        })

    return candidates


# ------------------------------------------------------------
# Reporting
# ------------------------------------------------------------

def summarize(candidates):

    counts = Counter()
    seconds = Counter()
    duration_bands = Counter()

    for candidate in candidates:

        status = candidate[
            "evidence_classification"
        ]

        length = candidate["duration"]

        counts[status] += 1
        seconds[status] += length

        if length < 0.100:
            band = "under_100ms"

        elif length < 0.250:
            band = "100_to_249ms"

        elif length < 0.500:
            band = "250_to_499ms"

        elif length < 1.000:
            band = "500_to_999ms"

        else:
            band = "1000ms_or_more"

        duration_bands[band] += 1

    return {
        "candidates": len(candidates),
        "candidate_seconds": sum(
            item["duration"]
            for item in candidates
        ),
        "evidence_counts": dict(counts),
        "evidence_seconds": dict(seconds),
        "duration_bands": dict(duration_bands),
        "overlapping_disagreement_regions": sum(
            bool(item["disagreement_region_ids"])
            for item in candidates
        ),
        "confirmed_missing_dialogue": 0,
    }


def print_candidates(title, candidates, limit):

    print(f"\n{title}")
    print("-" * 72)

    ordered = sorted(
        candidates,
        key=lambda item: (
            -item["duration"],
            item["start"],
        ),
    )

    for item in ordered[:limit]:

        print(
            f"  {item['id']} "
            f"{timestamp(item['start'])} - "
            f"{timestamp(item['end'])} "
            f"({item['start']:.3f} - "
            f"{item['end']:.3f}s) "
            f"duration={item['duration']:.3f}s "
            f"mean={item['speech_probability']['mean']:.3f} "
            f"{item['evidence_classification']}"
        )


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "accumulation", type=Path
    )

    parser.add_argument(
        "vad", type=Path
    )

    parser.add_argument(
        "history", type=Path
    )

    parser.add_argument(
        "overlay", type=Path
    )

    parser.add_argument(
        "original", type=Path
    )

    parser.add_argument(
        "recovered", type=Path
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=0.700,
    )

    parser.add_argument(
        "--json",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    require(
        math.isfinite(args.threshold)
        and 0 <= args.threshold <= 1,
        "Invalid speech probability threshold",
    )

    require(
        not args.json.exists(),
        f"Output already exists: {args.json}",
    )

    accumulation, accumulation_input = read_json(
        args.accumulation
    )

    vad, vad_input = read_json(args.vad)

    history, history_input = read_json(
        args.history
    )

    overlay, overlay_input = read_json(
        args.overlay
    )

    original_raw, original_input = read_input(
        args.original
    )

    recovered_raw, recovered_input = read_input(
        args.recovered
    )

    inputs = {
        "accumulation": accumulation_input,
        "vad": vad_input,
        "history": history_input,
        "overlay": overlay_input,
        "original": original_input,
        "recovered": recovered_input,
    }

    verify_schema(
        accumulation,
        "hehawk.magpie.accumulation",
    )

    verify_schema(
        history,
        "hehawk.magpie.history",
    )

    verify_schema(
        overlay,
        "hehawk.magpie.overlay",
    )

    require(
        vad["schema"]
        == "hehawk.lark.probabilities",
        "Unexpected VAD schema",
    )

    require(
        vad.get("version", vad.get("schema_version"))
        == 1,
        "Unsupported VAD version",
    )

    require(
        vad["timestamp_basis"] == "episode",
        "Unexpected VAD timestamp basis",
    )

    require(
        vad.get("source_offset_seconds", 0) == 0,
        "Unexpected VAD source offset",
    )

    hashes = {
        data["source_sha256"]
        for data in (
            accumulation,
            vad,
            history,
            overlay,
        )
    }

    require(
        len(hashes) == 1,
        "Episode source hash mismatch",
    )

    for field in (
        "sample_rate",
        "source_samples",
    ):

        require(
            accumulation[field] == vad[field],
            f"Source geometry mismatch: {field}",
        )

    for name in (
        "accumulation",
        "history",
        "original",
        "recovered",
    ):

        verify_link(
            overlay["inputs"][name],
            inputs[name],
            f"overlay -> {name}",
        )

    episode_end = (
        vad["source_samples"]
        / vad["sample_rate"]
    )

    per_pass, combined, reconstruction = (
        recognition_coverage(accumulation)
    )

    speech = speech_coverage(
        vad, args.threshold
    )

    gaps = subtract(speech, combined)

    recognized_speech = intersect(
        speech, combined
    )

    require(
        math.isclose(
            duration(speech),
            duration(gaps)
            + duration(recognized_speech),
            abs_tol=1e-6,
        ),
        "Speech coverage conservation failed",
    )

    require(
        duration(intersect(gaps, combined))
        < 1e-7,
        "Gap overlaps recognition coverage",
    )

    _, original_cues = caption_words(
        original_raw
    )

    _, recovered_cues = caption_words(
        recovered_raw
    )

    historical = historical_words(history)

    evidence = {
        "original": caption_intervals(
            original_cues, episode_end
        ),
        "recovered": caption_intervals(
            recovered_cues, episode_end
        ),
        "historical": word_intervals(
            historical, episode_end
        ),
    }

    candidates = build_candidates(
        gaps,
        vad,
        evidence,
        original_cues,
        recovered_cues,
        historical,
        overlay["regions"],
    )

    statistics = summarize(candidates)

    require(
        math.isclose(
            statistics["candidate_seconds"],
            duration(gaps),
            abs_tol=1e-6,
        ),
        "Candidate duration conservation failed",
    )

    for name, provenance in inputs.items():

        _, current = read_input(
            provenance["path"]
        )

        verify_link(
            provenance,
            current,
            f"unchanged input: {name}",
        )

    coverage_statistics = {
        "episode_seconds": episode_end,
        "speech_probability_seconds": (
            duration(speech)
        ),
        "combined_recognition_seconds": (
            duration(combined)
        ),
        "recognized_speech_seconds": (
            duration(recognized_speech)
        ),
        "shared_gap_seconds": duration(gaps),
        "per_pass_recognition_seconds": {
            name: duration(intervals)
            for name, intervals
            in per_pass.items()
        },
    }

    report = {
        "schema": "hehawk.hunt.shared_gaps",
        "version": 1,
        "timestamp_basis": "episode",
        "source_sha256": next(iter(hashes)),
        "inputs": inputs,
        "settings": {
            "speech_probability_threshold": (
                args.threshold
            ),
            "minimum_gap_seconds": 0.0,
            "recognition_padding_seconds": 0.0,
            "automatic_acceptance": False,
            "automatic_elimination": False,
        },
        "reconstruction": reconstruction,
        "coverage_statistics": coverage_statistics,
        "statistics": statistics,
        "coverage": {
            "per_pass": per_pass,
            "combined": combined,
            "speech": speech,
            "shared_gaps": gaps,
            "additional_evidence": evidence,
        },
        "candidates": candidates,
        "integrity": {
            "inputs_unchanged": True,
            "recorded_provenance_verified": True,
            "speech_coverage_conserved": True,
            "candidate_duration_conserved": True,
            "gaps_disjoint_from_recognition": True,
        },
        "limitations": {
            "speech_probability_proves_dialogue": False,
            "caption_coverage_proves_dialogue": False,
            "word_intervals_prove_complete_recognition": False,
            "historical_source_identity_verified": False,
            "caption_source_identity_verified": False,
            "acoustic_correctness_verified": False,
            "all_missing_dialogue_detected": False,
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

    print("HUNT 7H shared recognition gaps")
    print("=" * 72)

    print("\nReconstruction")

    print(
        "  Observations:",
        reconstruction["observations"],
    )

    print(
        "  Clipped words:",
        reconstruction["clipped_words"],
    )

    for name, count in (
        reconstruction["word_counts"].items()
    ):

        print(f"  {name:20} {count:6} words")

    print("\nTemporal coverage")

    for name, value in (
        coverage_statistics.items()
    ):

        if isinstance(value, (int, float)):

            print(
                f"  {name:36}"
                f" {value:10.3f}s"
                f" ({timestamp(value)})"
            )

    print("\nPer-pass coverage")

    for name, value in (
        coverage_statistics[
            "per_pass_recognition_seconds"
        ].items()
    ):

        print(f"  {name:20} {value:10.3f}s")

    print("\nCandidate classifications")

    for name, count in sorted(
        statistics["evidence_counts"].items()
    ):

        seconds = statistics[
            "evidence_seconds"
        ][name]

        print(
            f"  {name:30}"
            f" {count:6}"
            f" {seconds:10.3f}s"
        )

    print(
        "\nTotal candidates:",
        statistics["candidates"],
    )

    print(
        "Candidates overlapping 7G regions:",
        statistics[
            "overlapping_disagreement_regions"
        ],
    )

    print("\nDuration distribution")

    for name, count in sorted(
        statistics["duration_bands"].items()
    ):

        print(f"  {name:30} {count:6}")

    print_candidates(
        "Longest shared gaps",
        candidates,
        15,
    )

    print_candidates(
        "Longest gaps without historical "
        "or caption coverage",
        [
            item for item in candidates
            if item["evidence_classification"]
            == "acoustic_only"
        ],
        10,
    )

    print("\nIntegrity: PASS")
    print("No candidates automatically eliminated.")
    print("No missing dialogue automatically confirmed.")
    print(f"Report: {args.json}")


if __name__ == "__main__":
    main()

