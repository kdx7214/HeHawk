#!/usr/bin/env python3
"""MAGPIE 7G: localized disagreement evidence overlay."""

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import compare
import gulp_v4


# ------------------------------------------------------------
# Input and provenance
# ------------------------------------------------------------

def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_input(path):
    path = Path(path)
    raw = path.read_bytes()

    return raw, {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def read_json(path):
    raw, provenance = read_input(path)
    return json.loads(raw), provenance


def verify_link(record, provenance, label):
    require(
        record["sha256"] == provenance["sha256"],
        f"Provenance mismatch: {label}",
    )


def verify_schema(data, schema):
    require(
        data["schema"] == schema,
        f"Unexpected schema: {data['schema']}",
    )
    require(
        data["version"] == 1,
        f"Unsupported version: {schema}",
    )
    require(
        data["timestamp_basis"] == "episode",
        f"Unexpected timestamp basis: {schema}",
    )


def timestamp(seconds):
    ms = round(seconds * 1000)
    seconds, fraction = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    return (
        f"{hours:02}:{minutes:02}:"
        f"{seconds:02}.{fraction:03}"
    )


def validate_interval(start, end, label):
    require(
        math.isfinite(start)
        and math.isfinite(end)
        and 0 <= start <= end,
        f"Invalid interval: {label}",
    )


# ------------------------------------------------------------
# Caption evidence
# ------------------------------------------------------------

def caption_words(raw):

    text = gulp_v4.decode_text(raw)
    cues = gulp_v4.parse_srt(text)

    words = []
    cue_records = []

    for cue in sorted(
        cues,
        key=lambda item: (
            item["start_ms"],
            item["id"],
        ),
    ):

        start = cue["start_ms"] / 1000
        end = cue["end_ms"] / 1000

        validate_interval(
            start, end, "caption cue"
        )

        tokens = compare.tokenize(
            cue["comparison_text"]
        )

        cue_records.append({
            "cue_id": cue["id"],
            "start": start,
            "end": end,
            "original_text": cue["original_text"],
            "display_text": cue["display_text"],
            "word_count": len(tokens),
        })

        for position, token in enumerate(tokens):

            words.append({
                "index": len(words),
                "normalized": (
                    compare.normalize_word(token)
                ),
                "word": token,
                "start": start,
                "end": end,
                "cue_id": cue["id"],
                "cue_word": position,
                "timing_basis": "cue_interval",
            })

    return words, cue_records


# ------------------------------------------------------------
# Historical recognition inventory
# ------------------------------------------------------------

def historical_words(history):

    inventory = {}

    def add(word, index):

        require(
            index == word["global_index"],
            "Historical word index mismatch",
        )

        require(
            index not in inventory,
            f"Duplicate historical index: {index}",
        )

        validate_interval(
            word["start"],
            word["end"],
            "historical word",
        )

        inventory[index] = {
            **word,
            "index": index,
            "timing_basis": "recognition_word",
        }

    for row in history["words"]:

        match = row["historical_match"]

        if match is not None:
            add(
                match["historical_word"],
                match["historical_index"],
            )

    for word in history["historical_only_words"]:
        add(word, word["global_index"])

    expected = history["statistics"][
        "historical_words"
    ]

    require(
        len(inventory) == expected,
        "Historical inventory count mismatch",
    )

    require(
        sorted(inventory) == list(range(expected)),
        "Historical inventory indices incomplete",
    )

    return [
        inventory[index]
        for index in range(expected)
    ]


# ------------------------------------------------------------
# Lexical evidence comparison
# ------------------------------------------------------------

def overlaps(start, end, low, high):
    return end >= low and start <= high


def nearby_words(words, low, high):

    return [
        word for word in words
        if overlaps(
            word["start"],
            word["end"],
            low,
            high,
        )
    ]


def exact_matches(query, nearby):

    matches = []
    size = len(query)

    if not size:
        return matches

    for offset in range(
        len(nearby) - size + 1
    ):

        candidate = nearby[
            offset:offset + size
        ]

        sequence = [
            word["normalized"]
            for word in candidate
        ]

        if sequence != query:
            continue

        indices = [
            word["index"]
            for word in candidate
        ]

        # Prevent a match from jumping across
        # words excluded by the timing window.

        if indices != list(range(
            indices[0],
            indices[0] + size,
        )):
            continue

        matches.append({
            "word_indices": indices,
            "start": min(
                word["start"]
                for word in candidate
            ),
            "end": max(
                word["end"]
                for word in candidate
            ),
            "cue_ids": sorted({
                word["cue_id"]
                for word in candidate
                if "cue_id" in word
            }),
            "words": candidate,
        })

    return matches


def partial_match(query, nearby):

    # Longest common subsequence.
    # This measures ordered lexical overlap,
    # not semantic or acoustic correctness.

    source = [
        word["normalized"]
        for word in nearby
    ]

    n = len(query)
    m = len(source)

    table = [
        [0] * (m + 1)
        for _ in range(n + 1)
    ]

    for i in range(1, n + 1):

        for j in range(1, m + 1):

            if query[i - 1] == source[j - 1]:
                table[i][j] = (
                    table[i - 1][j - 1] + 1
                )
            else:
                table[i][j] = max(
                    table[i - 1][j],
                    table[i][j - 1],
                )

    i, j = n, m
    pairs = []

    while i and j:

        if query[i - 1] == source[j - 1]:

            pairs.append({
                "hypothesis_index": i - 1,
                "source_word": nearby[j - 1],
            })

            i -= 1
            j -= 1

        elif table[i - 1][j] >= table[i][j - 1]:
            i -= 1

        else:
            j -= 1

    pairs.reverse()

    return {
        "matched_words": len(pairs),
        "hypothesis_words": n,
        "coverage": len(pairs) / n if n else None,
        "pairs": pairs,
        "unique_alignment_verified": False,
    }


def compare_evidence(query, nearby):

    result = {
        "nearby_word_count": len(nearby),
        "exact_matches": [],
        "partial_match": None,
    }

    if not query:
        result["status"] = "empty_alternative"
        return result

    if not nearby:
        result["status"] = "no_nearby_evidence"
        return result

    matches = exact_matches(query, nearby)

    result["exact_matches"] = matches

    if matches:

        result["status"] = (
            "exact_unique"
            if len(matches) == 1
            else "exact_ambiguous"
        )

        return result

    partial = partial_match(query, nearby)

    result["partial_match"] = partial

    result["status"] = (
        "partial"
        if partial["matched_words"]
        else "no_lexical_match"
    )

    return result


# ------------------------------------------------------------
# Baseline provenance
# ------------------------------------------------------------

def baseline_inventory(novelty, history):

    original = novelty["words"]
    historical = history["words"]

    require(
        len(original) == len(historical),
        "Baseline inventory length mismatch",
    )

    result = {}

    for first, second in zip(
        original, historical
    ):

        require(
            first["index"] == second["index"],
            "Baseline index mismatch",
        )

        require(
            first["word"] == second["word"],
            "Baseline word mismatch",
        )

        require(
            first["index"] not in result,
            "Duplicate baseline index",
        )

        result[first["index"]] = {
            "novelty": first,
            "history": second,
        }

    require(
        sorted(result) == list(range(len(result))),
        "Baseline indices incomplete",
    )

    return result


# ------------------------------------------------------------
# Region overlay
# ------------------------------------------------------------

def overlay_region(
    region,
    segment,
    sources,
    caption_records,
    baseline,
    tolerance,
):

    start = region["start"]
    end = region["end"]

    validate_interval(
        start, end, region["id"]
    )

    low = max(0.0, start - tolerance)
    high = end + tolerance

    nearby = {
        name: nearby_words(words, low, high)
        for name, words in sources.items()
    }

    nearby_cues = {
        name: [
            cue for cue in cues
            if overlaps(
                cue["start"],
                cue["end"],
                low,
                high,
            )
        ]
        for name, cues in caption_records.items()
    }

    baseline_context = [
        row for row in baseline.values()
        if row["novelty"]["word"]["segment_id"]
        == region["segment_id"]
        and overlaps(
            row["novelty"]["word"]["start"],
            row["novelty"]["word"]["end"],
            low,
            high,
        )
    ]

    left_anchors = [
        anchor for anchor in segment["anchors"]
        if anchor["end"] <= start
    ]

    right_anchors = [
        anchor for anchor in segment["anchors"]
        if anchor["start"] >= end
    ]

    hypotheses = []

    for hypothesis in region["hypotheses"]:

        query = hypothesis["normalized_words"]

        evidence = {
            name: compare_evidence(query, words)
            for name, words in nearby.items()
        }

        exact_sources = [
            name
            for name, item in evidence.items()
            if item["status"] in (
                "exact_unique",
                "exact_ambiguous",
            )
        ]

        hypotheses.append({
            **hypothesis,
            "evidence": evidence,
            "exact_lexical_sources": exact_sources,
            "automatic_acceptance": False,
            "human_verified": False,
        })

    supported = [
        index
        for index, hypothesis in enumerate(
            hypotheses
        )
        if hypothesis["exact_lexical_sources"]
    ]

    if len(supported) == 0:
        status = "no_exact_corroboration"

    elif len(supported) == 1:
        status = "one_exactly_corroborated"

    else:
        status = "multiple_exactly_corroborated"

    return {
        "id": region["id"],
        "segment_id": region["segment_id"],
        "start": start,
        "end": end,
        "search_start": low,
        "search_end": high,
        "left_anchor": (
            left_anchors[-1]
            if left_anchors else None
        ),
        "right_anchor": (
            right_anchors[0]
            if right_anchors else None
        ),
        "nearby_caption_cues": nearby_cues,
        "baseline_context": baseline_context,
        "hypotheses": hypotheses,
        "status": status,
        "contains_empty_alternative": (
            region["contains_empty_alternative"]
        ),
        "requires_human_review": True,
        "human_verified": False,
    }


# ------------------------------------------------------------
# Statistics
# ------------------------------------------------------------

def summarize(regions):

    region_statuses = Counter()
    source_statuses = {}
    hypothesis_count = 0
    empty_count = 0
    corroborated = 0
    nonbaseline_corroborated = 0

    for region in regions:

        region_statuses[region["status"]] += 1

        for hypothesis in region["hypotheses"]:

            hypothesis_count += 1

            if not hypothesis["normalized_words"]:
                empty_count += 1

            if hypothesis["exact_lexical_sources"]:

                corroborated += 1

                if (
                    "baseline"
                    not in hypothesis["supporting_passes"]
                ):
                    nonbaseline_corroborated += 1

            for name, evidence in (
                hypothesis["evidence"].items()
            ):

                source_statuses.setdefault(
                    name, Counter()
                )[evidence["status"]] += 1

    return {
        "regions": len(regions),
        "hypotheses": hypothesis_count,
        "empty_hypotheses": empty_count,
        "nonempty_hypotheses": (
            hypothesis_count - empty_count
        ),
        "exactly_corroborated_hypotheses": (
            corroborated
        ),
        "nonbaseline_exactly_corroborated": (
            nonbaseline_corroborated
        ),
        "region_statuses": dict(region_statuses),
        "source_statuses": {
            name: dict(counts)
            for name, counts
            in source_statuses.items()
        },
        "automatically_accepted": 0,
        "automatically_eliminated": 0,
        "regions_requiring_review": len(regions),
    }


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument("novelty", type=Path)
    parser.add_argument("history", type=Path)
    parser.add_argument("accumulation", type=Path)
    parser.add_argument("localization", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("recovered", type=Path)

    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.500,
    )

    parser.add_argument(
        "--json",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    require(
        math.isfinite(args.tolerance)
        and args.tolerance >= 0,
        "Invalid timing tolerance",
    )

    require(
        not args.json.exists(),
        f"Output already exists: {args.json}",
    )

    novelty, novelty_input = read_json(
        args.novelty
    )

    history, history_input = read_json(
        args.history
    )

    accumulation, accumulation_input = read_json(
        args.accumulation
    )

    localization, localization_input = read_json(
        args.localization
    )

    original_raw, original_input = read_input(
        args.original
    )

    recovered_raw, recovered_input = read_input(
        args.recovered
    )

    inputs = {
        "novelty": novelty_input,
        "history": history_input,
        "accumulation": accumulation_input,
        "localization": localization_input,
        "original": original_input,
        "recovered": recovered_input,
    }

    verify_schema(
        novelty, "hehawk.magpie.novelty"
    )

    verify_schema(
        history, "hehawk.magpie.history"
    )

    verify_schema(
        accumulation, "hehawk.magpie.accumulation"
    )

    verify_schema(
        localization, "hehawk.magpie.localization"
    )

    source_hashes = {
        data["source_sha256"]
        for data in (
            novelty,
            history,
            accumulation,
            localization,
        )
    }

    require(
        len(source_hashes) == 1,
        "Episode source hash mismatch",
    )

    verify_link(
        history["inputs"]["novelty"],
        novelty_input,
        "history -> novelty",
    )

    verify_link(
        localization["input"],
        accumulation_input,
        "localization -> accumulation",
    )

    verify_link(
        novelty["inputs"]["original"],
        original_input,
        "novelty -> original captions",
    )

    verify_link(
        novelty["inputs"]["recovered"],
        recovered_input,
        "novelty -> recovered captions",
    )

    baseline_inputs = [
        item for item in accumulation["inputs"]
        if item["id"] == "baseline"
    ]

    require(
        len(baseline_inputs) == 1,
        "Expected exactly one baseline input",
    )

    verify_link(
        novelty["inputs"]["recognition"],
        baseline_inputs[0],
        "novelty -> baseline recognition",
    )

    verify_link(
        history["inputs"]["current_recognition"],
        baseline_inputs[0],
        "history -> baseline recognition",
    )

    for field in ("sample_rate", "source_samples"):

        require(
            accumulation[field] == localization[field],
            f"Source geometry mismatch: {field}",
        )

    original_words, original_cues = caption_words(
        original_raw
    )

    recovered_words, recovered_cues = caption_words(
        recovered_raw
    )

    historical = historical_words(history)

    baseline = baseline_inventory(
        novelty, history
    )

    sources = {
        "original": original_words,
        "recovered": recovered_words,
        "historical": historical,
    }

    caption_records = {
        "original": original_cues,
        "recovered": recovered_cues,
    }

    regions = []
    region_ids = set()

    for segment in localization["segments"]:

        for region in segment["regions"]:

            require(
                region["id"] not in region_ids,
                "Duplicate region ID",
            )

            require(
                region["segment_id"]
                == segment["segment_id"],
                "Region segment mismatch",
            )

            region_ids.add(region["id"])

            regions.append(
                overlay_region(
                    region,
                    segment,
                    sources,
                    caption_records,
                    baseline,
                    args.tolerance,
                )
            )

    require(
        len(regions)
        == localization["statistics"][
            "localized_regions"
        ],
        "Localized region count mismatch",
    )

    window_regions = {
        region_id
        for window in localization["review_windows"]
        for region_id in window["region_ids"]
    }

    require(
        window_regions == region_ids,
        "Review window region coverage mismatch",
    )

    statistics = summarize(regions)

    # Ensure the input files have not changed.

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
        "schema": "hehawk.magpie.overlay",
        "version": 1,
        "timestamp_basis": "episode",
        "source_sha256": next(iter(source_hashes)),
        "inputs": inputs,
        "settings": {
            "tolerance_seconds": args.tolerance,
            "caption_parser": "gulp_v4",
            "caption_timing_basis": "cue_interval",
            "historical_timing_basis": (
                "recognition_word"
            ),
            "automatic_acceptance": False,
            "automatic_elimination": False,
            "sources_independent": False,
        },
        "source_inventory": {
            "original_cues": len(original_cues),
            "original_words": len(original_words),
            "recovered_cues": len(recovered_cues),
            "recovered_words": len(recovered_words),
            "historical_words": len(historical),
            "baseline_words": len(baseline),
        },
        "statistics": statistics,
        "regions": regions,
        "review_windows": localization[
            "review_windows"
        ],
        "integrity": {
            "inputs_unchanged": True,
            "recorded_provenance_verified": True,
            "historical_indices_complete": True,
            "region_coverage_verified": True,
        },
        "limitations": {
            "caption_semantics_verified": False,
            "caption_source_identity_verified": False,
            "historical_source_identity_verified": False,
            "anchor_conditioned_matching": False,
            "acoustic_correctness_verified": False,
            "exact_match_proves_correctness": False,
            "shared_recognition_omissions_detected": False,
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

    print("MAGPIE 7G evidence overlay")
    print("=" * 72)

    print("\nSource inventories")

    for name, count in (
        report["source_inventory"].items()
    ):
        print(f"  {name:35} {count:6}")

    print("\nHypothesis statistics")

    for name, value in statistics.items():

        if isinstance(value, int):
            print(f"  {name:42} {value:6}")

    print("\nRegion classifications")

    for name, count in (
        statistics["region_statuses"].items()
    ):
        print(f"  {name:42} {count:6}")

    print("\nEvidence classifications")

    for source, counts in (
        statistics["source_statuses"].items()
    ):

        print(f"\n  {source.upper()}")

        for name, count in sorted(counts.items()):
            print(f"    {name:35} {count:6}")

    print("\nNonbaseline corroboration")

    for region in regions:

        count = sum(
            bool(h["exact_lexical_sources"])
            and "baseline" not in h["supporting_passes"]
            for h in region["hypotheses"]
        )

        if count:

            print(
                f"  {region['id']} "
                f"{region['segment_id']} "
                f"{timestamp(region['start'])} - "
                f"{timestamp(region['end'])} "
                f"({region['start']:.3f} - "
                f"{region['end']:.3f}s)"
                f" alternatives={count}"
            )

    print("\nIntegrity: PASS")
    print("No hypotheses accepted or eliminated.")
    print(f"Report: {args.json}")


if __name__ == "__main__":
    main()

