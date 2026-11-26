
#!/usr/bin/env python3
"""MAGPIE 7D: accumulate multi-pass recognition evidence."""

import argparse
import json
from collections import Counter
from pathlib import Path

from compare import tokenize, normalize_word

from magpie_incremental import (
    read_input,
    timestamp,
)


# ------------------------------------------------------------
# Input and provenance validation.
# ------------------------------------------------------------

def load(path):

    raw, digest = read_input(path)

    return json.loads(raw), digest


def normalized_words(text):

    return tuple(
        normalize_word(word)
        for word in tokenize(text)
    )


def validate_baseline(data):

    if data["schema"] != "hehawk.tern.recognition":
        raise ValueError("Unexpected baseline schema.")

    if data["version"] != 1:
        raise ValueError("Unsupported baseline version.")

    if data["timestamp_basis"] != "segment_relative":
        raise ValueError("Unexpected timestamp basis.")

    rate = data["sample_rate"]
    samples = data["source_samples"]

    if rate != 16000 or samples <= 0:
        raise ValueError("Invalid source geometry.")

    previous_end = 0
    seen = set()

    for segment in data["segments"]:

        sid = segment["id"]
        start = segment["start_sample"]
        end = segment["end_sample"]

        if sid in seen:
            raise ValueError(f"Duplicate segment: {sid}")

        seen.add(sid)

        if start != previous_end:
            raise ValueError(f"Noncontiguous segment: {sid}")

        if end <= start or end > samples:
            raise ValueError(f"Invalid segment: {sid}")

        previous_end = end

        validate_tokens(segment)

    if previous_end != samples:
        raise ValueError("Incomplete baseline coverage.")


def validate_tokens(segment):

    import math

    tokens = segment["tokens"]
    times = segment["timestamps"]
    durations = segment["durations"]

    if not len(tokens) == len(times) == len(durations):
        raise ValueError(
            f"Mismatched token arrays: {segment['id']}"
        )

    for t, d in zip(times, durations):

        if (
            not math.isfinite(t)
            or not math.isfinite(d)
            or t < 0
            or d < 0
        ):
            raise ValueError(
                f"Invalid token timing: {segment['id']}"
            )


def validate_padding(data, baseline, baseline_hash):

    if data["schema"] != "hehawk.tern.padding":
        raise ValueError("Unexpected padding schema.")

    if data["version"] != 1:
        raise ValueError("Unsupported padding version.")

    if data["baseline_sha256"] != baseline_hash:
        raise ValueError("Baseline hash mismatch.")

    for key in (
        "source_sha256",
        "sample_rate",
        "source_samples",
        "model_sha256",
        "timestamp_basis",
    ):

        if data[key] != baseline[key]:
            raise ValueError(
                f"Incompatible padding evidence: {key}"
            )

    if len(data["segments"]) != len(baseline["segments"]):
        raise ValueError("Segment count mismatch.")

    for old, new in zip(
        baseline["segments"],
        data["segments"]
    ):

        for key in (
            "id",
            "start_sample",
            "end_sample",
        ):

            if old[key] != new[key]:
                raise ValueError(
                    f"Segment geometry mismatch: {old['id']}"
                )

        validate_tokens(new)


# ------------------------------------------------------------
# Preserve each individual observation.
# ------------------------------------------------------------

def make_observation(pass_id, segment):

    return {
        "pass_id": pass_id,
        "text": segment["text"],
        "tokens": segment["tokens"],
        "timestamps": segment["timestamps"],
        "durations": segment["durations"],
        "normalized_words": list(
            normalized_words(segment["text"])
        ),
        "timing_flags": segment.get(
            "timing_flags",
            segment.get("timing_warnings", [])
        ),
        "padding_samples": segment.get(
            "padding_samples", 0
        ),
    }


# ------------------------------------------------------------
# Group identical lexical hypotheses.
#
# Empty results are retained separately.
# No majority-vote acceptance is performed.
# ------------------------------------------------------------

def accumulate_segment(index, passes, rate):

    baseline = passes[0]["data"]["segments"][index]

    observations = []

    for entry in passes:

        segment = entry["data"]["segments"][index]

        observations.append(
            make_observation(
                entry["id"],
                segment
            )
        )

    groups = {}
    empty_passes = []
    nonlexical_passes = []

    for observation in observations:

        key = tuple(
            observation["normalized_words"]
        )

        if not key:

            if observation["text"].strip():
                nonlexical_passes.append(
                    observation["pass_id"]
                )
            else:
                empty_passes.append(
                    observation["pass_id"]
                )

            continue

        groups.setdefault(key, []).append(
            observation
        )

    hypotheses = []

    for key, members in groups.items():

        supporting_passes = [
            member["pass_id"]
            for member in members
        ]

        hypotheses.append({
            "id": f"H{len(hypotheses) + 1:02d}",
            "normalized_words": list(key),
            "word_count": len(key),
            "supporting_passes": supporting_passes,
            "support_count": len(members),
            "baseline_supported": (
                "baseline" in supporting_passes
            ),
            "text_variants": sorted({
                member["text"]
                for member in members
            }),
            "human_verified": False,
        })

    pass_count = len(passes)

    if not hypotheses:

        if len(empty_passes) == pass_count:
            status = "all_empty"
        else:
            status = "nonlexical_only"

    elif len(hypotheses) == 1:

        if hypotheses[0]["support_count"] == pass_count:
            status = "unanimous"
        else:
            status = "lexical_with_empty_or_nonlexical"

    else:
        status = "competing"

    baseline_words = normalized_words(
        baseline["text"]
    )

    alternative_count = sum(
        not hypothesis["baseline_supported"]
        for hypothesis in hypotheses
    )

    return {
        "id": baseline["id"],
        "start_sample": baseline["start_sample"],
        "end_sample": baseline["end_sample"],
        "start": baseline["start_sample"] / rate,
        "end": baseline["end_sample"] / rate,
        "status": status,
        "pass_count": pass_count,
        "hypothesis_count": len(hypotheses),
        "alternative_hypothesis_count": alternative_count,
        "empty_passes": empty_passes,
        "nonlexical_passes": nonlexical_passes,
        "baseline_has_words": bool(baseline_words),
        "baseline_empty_recovery": (
            not baseline["text"].strip()
            and bool(hypotheses)
        ),
        "baseline_lexical_loss": (
            bool(baseline_words)
            and bool(empty_passes or nonlexical_passes)
        ),
        "hypotheses": hypotheses,
        "observations": observations,
        "human_verified": False,
    }


# ------------------------------------------------------------
# Main.
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "baseline",
        type=Path
    )

    parser.add_argument(
        "padding",
        type=Path,
        nargs="+"
    )

    parser.add_argument(
        "--json",
        type=Path,
        required=True
    )

    args = parser.parse_args()

    if args.json.exists():
        parser.error("Output already exists.")

    baseline, baseline_hash = load(args.baseline)

    validate_baseline(baseline)

    passes = [{
        "id": "baseline",
        "path": args.baseline,
        "sha256": baseline_hash,
        "data": baseline,
    }]

    seen_hashes = {baseline_hash}

    for index, path in enumerate(args.padding, 1):

        data, digest = load(path)

        if digest in seen_hashes:
            raise ValueError(
                f"Duplicate evidence input: {path}"
            )

        seen_hashes.add(digest)

        validate_padding(
            data,
            baseline,
            baseline_hash
        )

        passes.append({
            "id": f"P{index:02d}",
            "path": path,
            "sha256": digest,
            "data": data,
        })

    rate = baseline["sample_rate"]

    segments = [
        accumulate_segment(index, passes, rate)
        for index in range(
            len(baseline["segments"])
        )
    ]

    counts = Counter(
        segment["status"]
        for segment in segments
    )

    hypothesis_count = sum(
        segment["hypothesis_count"]
        for segment in segments
    )

    alternative_count = sum(
        segment["alternative_hypothesis_count"]
        for segment in segments
    )

    support_distribution = Counter(
        hypothesis["support_count"]
        for segment in segments
        for hypothesis in segment["hypotheses"]
    )

    empty_recoveries = [
        segment for segment in segments
        if segment["baseline_empty_recovery"]
    ]

    lexical_losses = [
        segment for segment in segments
        if segment["baseline_lexical_loss"]
    ]

    observation_count = 0

    # --------------------------------------------------------
    # Evidence conservation.
    # --------------------------------------------------------

    expected_passes = {
        entry["id"] for entry in passes
    }

    for segment in segments:

        assigned = []

        for hypothesis in segment["hypotheses"]:

            assigned.extend(
                hypothesis["supporting_passes"]
            )

        assigned.extend(segment["empty_passes"])
        assigned.extend(segment["nonlexical_passes"])

        if (
            len(assigned) != len(passes)
            or set(assigned) != expected_passes
        ):
            raise RuntimeError(
                f"Evidence conservation failed: {segment['id']}"
            )

        observation_count += len(
            segment["observations"]
        )

    if observation_count != len(segments) * len(passes):
        raise RuntimeError(
            "Observation conservation failed."
        )

    print("MAGPIE MULTI-PASS EVIDENCE ACCUMULATION")
    print("=" * 64)

    print(f"Recognition passes: {len(passes)}")
    print(f"Segments:           {len(segments)}")
    print(f"Observations:       {observation_count}")

    print()
    print("INPUT PASSES")
    print("=" * 64)

    for entry in passes:

        print(
            f"{entry['id']:10s}: {entry['path']}"
        )

    print()
    print("SEGMENT CLASSIFICATIONS")
    print("=" * 64)

    for status in (
        "unanimous",
        "competing",
        "lexical_with_empty_or_nonlexical",
        "all_empty",
        "nonlexical_only",
    ):

        print(f"{status:34s}: {counts[status]}")

    print()
    print("LEXICAL HYPOTHESIS SUPPORT")
    print("=" * 64)

    for support in range(1, len(passes) + 1):

        print(
            f"Supported by {support:2d} pass(es): "
            f"{support_distribution[support]}"
        )

    print()
    print(f"Distinct segment hypotheses: {hypothesis_count}")
    print(f"Alternatives to baseline:    {alternative_count}")
    print(f"Baseline empty recoveries:   {len(empty_recoveries)}")
    print(f"Baseline lexical losses:     {len(lexical_losses)}")

    print()
    print("BASELINE EMPTY RECOVERIES")
    print("=" * 64)

    for segment in empty_recoveries:

        print(
            f"{segment['id']}  "
            f"{timestamp(segment['start'])} - "
            f"{timestamp(segment['end'])}  "
            f"hypotheses={segment['hypothesis_count']}  "
            f"empty={','.join(segment['empty_passes'])}"
        )

    print()
    print("SEGMENTS WITH LEXICAL LOSS")
    print("=" * 64)

    for segment in lexical_losses:

        print(
            f"{segment['id']}  "
            f"{timestamp(segment['start'])} - "
            f"{timestamp(segment['end'])}  "
            f"empty={','.join(segment['empty_passes'])}  "
            f"nonlexical="
            f"{','.join(segment['nonlexical_passes'])}"
        )

    print()
    print("MOST VARIABLE SEGMENTS")
    print("=" * 64)

    ranked = sorted(
        segments,
        key=lambda segment: (
            -segment["hypothesis_count"],
            segment["start"]
        )
    )

    for segment in ranked[:20]:

        if segment["hypothesis_count"] < 2:
            break

        support = sorted(
            (
                hypothesis["support_count"]
                for hypothesis in segment["hypotheses"]
            ),
            reverse=True
        )

        print(
            f"{segment['id']}  "
            f"{timestamp(segment['start'])} - "
            f"{timestamp(segment['end'])}  "
            f"hypotheses={segment['hypothesis_count']}  "
            f"support={'+'.join(map(str, support))}"
        )

    output = {
        "schema": "hehawk.magpie.accumulation",
        "version": 1,
        "timestamp_basis": "episode",
        "observation_timestamp_basis":
            "segment_relative",
        "source_sha256": baseline["source_sha256"],
        "model_sha256": baseline["model_sha256"],
        "sample_rate": rate,
        "source_samples": baseline["source_samples"],
        "inputs": [
            {
                "id": entry["id"],
                "path": str(entry["path"]),
                "sha256": entry["sha256"],
                "settings": entry["data"].get(
                    "settings", {}
                ),
            }
            for entry in passes
        ],
        "settings": {
            "hypothesis_scope": "complete_segment",
            "comparison": "normalized_lexical_sequence",
            "empty_observations_preserved": True,
            "same_model_passes_independent": False,
            "automatic_acceptance": False,
        },
        "statistics": {
            "passes": len(passes),
            "segments": len(segments),
            "observations": observation_count,
            "segment_classifications": dict(counts),
            "distinct_hypotheses": hypothesis_count,
            "alternative_hypotheses": alternative_count,
            "support_distribution":
                dict(support_distribution),
            "baseline_empty_recoveries":
                len(empty_recoveries),
            "baseline_lexical_losses":
                len(lexical_losses),
        },
        "segments": segments,
    }

    for entry in passes:

        _, current_hash = read_input(
            entry["path"]
        )

        if current_hash != entry["sha256"]:
            raise RuntimeError(
                f"Input changed: {entry['path']}"
            )

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
    print("Provenance validation:    PASSED")
    print("Evidence conservation:    PASSED")
    print("Observation conservation: PASSED")
    print("Input integrity:          PASSED")
    print(f"Saved: {args.json}")
    print("Accumulation completed successfully.")


if __name__ == "__main__":
    main()
