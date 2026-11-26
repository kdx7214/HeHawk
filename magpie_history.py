
#!/usr/bin/env python3
"""MAGPIE 7C: historical recognition comparison."""

import argparse
import json
from collections import Counter
from pathlib import Path

import compare

from magpie import recognition_words

from magpie_incremental import (
    read_input,
    load_recognition,
    timestamp,
)


# ------------------------------------------------------------
# Align complete recognition sequences.
# ------------------------------------------------------------

def align_history(history, current):

    operations = compare.align_words(
        history,
        current
    )

    matches = {}
    historical_only = []

    for kind, hi, ci in operations:

        if kind == "equal":

            if hi is None or ci is None:
                raise ValueError("Invalid equal operation.")

            if ci in matches:
                raise ValueError("Duplicate current match.")

            old = history[hi]
            new = current[ci]

            if old["normalized"] != new["normalized"]:
                raise ValueError("Unequal normalized words.")

            matches[ci] = {
                "historical_index": hi,
                "historical_word": old,
                "start_shift": new["start"] - old["start"],
                "end_shift": new["end"] - old["end"],
            }

        elif kind == "delete":

            historical_only.append(hi)

        elif kind != "insert":

            raise ValueError(
                f"Unknown alignment operation: {kind}"
            )

    if len(matches) + len(historical_only) != len(history):
        raise RuntimeError(
            "Historical word conservation failed."
        )

    if len({
        match["historical_index"]
        for match in matches.values()
    }) != len(matches):
        raise RuntimeError(
            "Historical word matched more than once."
        )

    return matches, historical_only


# ------------------------------------------------------------
# Annotate the existing 7B word inventory.
# ------------------------------------------------------------

def annotate_words(rows, current, matches):

    if len(rows) != len(current):
        raise ValueError(
            "7B recognition word count differs."
        )

    result = []

    for index, row in enumerate(rows):

        if row["index"] != index:
            raise ValueError(
                f"Unexpected 7B word index: {index}"
            )

        if row["word"] != current[index]:
            raise ValueError(
                f"Recognition evidence differs at word {index}"
            )

        match = matches.get(index)

        if match is not None:
            history_status = "previously_observed"
        else:
            history_status = "new_hypothesis"

        annotated = dict(row)

        annotated["history_status"] = history_status
        annotated["historical_match"] = match

        # Preserve the original 7B decision.
        #
        # Historical recognition agreement is not
        # equivalent to caption reconciliation.

        annotated["requires_caption_investigation"] = (
            not row["short_circuit_eligible"]
        )

        annotated["new_unresolved_hypothesis"] = (
            not row["short_circuit_eligible"]
            and match is None
        )

        result.append(annotated)

    return result


# ------------------------------------------------------------
# Annotate existing candidate passages.
# ------------------------------------------------------------

def annotate_candidates(candidates, rows):

    result = []
    seen_indices = []

    for candidate in candidates:

        indices = candidate["word_indices"]

        if not indices:
            raise ValueError("Empty candidate.")

        if len(indices) != candidate["word_count"]:
            raise ValueError(
                "Candidate word count differs."
            )

        words = [rows[index] for index in indices]

        if any(
            row["short_circuit_eligible"]
            for row in words
        ):
            raise ValueError(
                "Supported word found in unresolved candidate."
            )

        seen_indices.extend(indices)

        counts = Counter(
            row["history_status"]
            for row in words
        )

        old_count = counts["previously_observed"]
        new_count = counts["new_hypothesis"]

        if new_count == 0:
            status = "entirely_observed"

        elif old_count == 0:
            status = "entirely_new"

        else:
            status = "mixed"

        # Determine whether all words form a contiguous
        # sequence in the historical recognition.
        #
        # Individual matches alone do not establish
        # that the entire phrase was previously observed.

        contiguous = False

        if new_count == 0:

            historical_indices = [
                row["historical_match"]["historical_index"]
                for row in words
            ]

            contiguous = (
                historical_indices
                == list(range(
                    historical_indices[0],
                    historical_indices[0] + len(words)
                ))
            )

        annotated = dict(candidate)

        annotated.update({
            "history_status": status,
            "previously_observed_words": old_count,
            "new_hypothesis_words": new_count,
            "historical_phrase_contiguous": contiguous,
            "no_new_lexical_hypothesis": contiguous,
            "requires_caption_investigation": True,
        })

        result.append(annotated)

    expected_indices = [
        row["index"]
        for row in rows
        if not row["short_circuit_eligible"]
    ]

    if seen_indices != expected_indices:
        raise RuntimeError(
            "Candidate index conservation failed."
        )

    return result


# ------------------------------------------------------------
# Main.
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "novelty",
        type=Path
    )

    parser.add_argument(
        "historical_recognition",
        type=Path
    )

    parser.add_argument(
        "current_recognition",
        type=Path
    )

    parser.add_argument(
        "--json",
        required=True,
        type=Path
    )

    args = parser.parse_args()

    if args.json.exists():
        parser.error("Output already exists.")

    paths = {
        "novelty": args.novelty,
        "historical_recognition":
            args.historical_recognition,
        "current_recognition":
            args.current_recognition,
    }

    raw = {}
    hashes = {}

    for label, path in paths.items():

        raw[label], hashes[label] = read_input(path)

    novelty = json.loads(raw["novelty"])

    historical_data = json.loads(
        raw["historical_recognition"]
    )

    current_data = json.loads(
        raw["current_recognition"]
    )

    if novelty["schema"] != "hehawk.magpie.novelty":
        raise ValueError("Unexpected novelty schema.")

    if novelty["version"] != 1:
        raise ValueError("Unsupported novelty version.")

    if novelty["timestamp_basis"] != "episode":
        raise ValueError("Unexpected timestamp basis.")

    if (
        novelty["inputs"]["recognition"]["sha256"]
        != hashes["current_recognition"]
    ):
        raise ValueError(
            "Current recognition does not match 7B input."
        )

    if (
        novelty["source_sha256"]
        != current_data["source_sha256"]
    ):
        raise ValueError("Source hash mismatch.")

    if historical_data.get(
        "source_offset_seconds", 0
    ) != 0:
        raise ValueError(
            "Historical recognition must cover full episode."
        )

    history = recognition_words(historical_data)

    current = load_recognition(current_data)

    duration = (
        current_data["source_samples"]
        / current_data["sample_rate"]
    )

    for word in history:

        if word["end"] > duration + 0.320:
            raise ValueError(
                "Historical recognition exceeds source duration."
            )

    print("MAGPIE HISTORICAL RECOGNITION COMPARISON")
    print("=" * 64)
    print(f"Historical recognition words: {len(history)}")
    print(f"Current recognition words:    {len(current)}")
    print(
        f"Existing candidates:           "
        f"{len(novelty['candidates'])}"
    )

    print("\nAligning complete recognition sequences...")

    matches, historical_only = align_history(
        history,
        current
    )

    rows = annotate_words(
        novelty["words"],
        current,
        matches
    )

    candidates = annotate_candidates(
        novelty["candidates"],
        rows
    )

    unresolved = [
        row for row in rows
        if not row["short_circuit_eligible"]
    ]

    counts = Counter(
        row["history_status"]
        for row in unresolved
    )

    candidate_counts = Counter(
        candidate["history_status"]
        for candidate in candidates
    )

    previously_observed = counts["previously_observed"]
    new_hypotheses = counts["new_hypothesis"]

    contiguous_candidates = sum(
        candidate["historical_phrase_contiguous"]
        for candidate in candidates
    )

    supported = len(rows) - len(unresolved)

    if previously_observed + new_hypotheses != len(unresolved):
        raise RuntimeError(
            "Unresolved word conservation failed."
        )

    if sum(candidate_counts.values()) != len(candidates):
        raise RuntimeError(
            "Candidate conservation failed."
        )

    if sum(
        candidate["new_hypothesis_words"]
        for candidate in candidates
    ) != new_hypotheses:
        raise RuntimeError(
            "New hypothesis conservation failed."
        )

    print()
    print("COMPLETE RECOGNITION ALIGNMENT")
    print("=" * 64)
    print(f"Matched words:        {len(matches)}")
    print(f"Historical only:      {len(historical_only)}")
    print(f"Current only:         {len(current) - len(matches)}")

    print()
    print("UNRESOLVED WORDS FROM EXPERIMENT 7B")
    print("=" * 64)
    print(f"Unresolved words:     {len(unresolved)}")
    print(f"Previously observed:  {previously_observed}")
    print(f"New hypotheses:       {new_hypotheses}")

    if unresolved:

        print(
            f"Historical support:   "
            f"{100 * previously_observed / len(unresolved):.2f}%"
        )

    print()
    print("CLASSIFICATION BREAKDOWN")
    print("=" * 64)

    breakdown = {}

    for category in ("competing", "novel"):

        subset = [
            row for row in unresolved
            if row["status"] == category
        ]

        category_counts = Counter(
            row["history_status"]
            for row in subset
        )

        breakdown[category] = dict(category_counts)

        print(
            f"{category:12s}: "
            f"observed={category_counts['previously_observed']:4d}  "
            f"new={category_counts['new_hypothesis']:4d}"
        )

    print()
    print("CANDIDATE CLASSIFICATIONS")
    print("=" * 64)

    for status in (
        "entirely_observed",
        "mixed",
        "entirely_new",
    ):

        print(
            f"{status:22s}: "
            f"{candidate_counts[status]}"
        )

    print(f"Contiguous historical phrases: {contiguous_candidates}")

    print()
    print("LAYERED EVIDENCE SUMMARY")
    print("=" * 64)
    print(f"Already caption-supported: {supported}")
    print(f"Historical unresolved:     {previously_observed}")
    print(f"New unresolved hypotheses: {new_hypotheses}")

    if rows:

        known = supported + previously_observed

        print(
            f"Previously known words:    "
            f"{100 * known / len(rows):.2f}%"
        )

        print(
            f"New unresolved hypotheses: "
            f"{100 * new_hypotheses / len(rows):.2f}%"
        )

    print()
    print("TOP CANDIDATES WITH NEW HYPOTHESES")
    print("=" * 64)

    ranked = sorted(
        candidates,
        key=lambda candidate: (
            -candidate["new_hypothesis_words"],
            candidate["start"]
        )
    )

    for candidate in ranked[:20]:

        if candidate["new_hypothesis_words"] == 0:
            break

        print(
            f"{candidate['id']}  "
            f"{timestamp(candidate['start'])} - "
            f"{timestamp(candidate['end'])}  "
            f"new={candidate['new_hypothesis_words']:2d}/"
            f"{candidate['word_count']:2d}  "
            f"{candidate['category']:10s}  "
            f"{candidate['history_status']}"
        )

    output = {
        "schema": "hehawk.magpie.history",
        "version": 1,
        "timestamp_basis": "episode",
        "source_sha256": current_data["source_sha256"],
        "inputs": {
            label: {
                "path": str(paths[label]),
                "sha256": hashes[label],
            }
            for label in paths
        },
        "settings": {
            "alignment": "compare.align_words",
            "max_match_distance":
                compare.MAX_MATCH_DISTANCE,
            "gap_cost":
                compare.GAP_COST,
            "time_penalty_per_second":
                compare.TIME_PENALTY_PER_SECOND,
            "max_time_penalty":
                compare.MAX_TIME_PENALTY,
            "full_sequence_alignment": True,
            "historical_source_identity_verified": False,
            "historical_agreement_is_ground_truth": False,
        },
        "statistics": {
            "historical_words": len(history),
            "current_words": len(current),
            "complete_alignment_matches": len(matches),
            "historical_only": len(historical_only),
            "current_only": len(current) - len(matches),
            "caption_supported": supported,
            "unresolved_words": len(unresolved),
            "previously_observed_unresolved":
                previously_observed,
            "new_unresolved_hypotheses": new_hypotheses,
            "classification_breakdown": breakdown,
            "candidate_classifications":
                dict(candidate_counts),
            "contiguous_historical_candidates":
                contiguous_candidates,
        },
        "historical_only_words": [
            history[index]
            for index in historical_only
        ],
        "words": rows,
        "candidates": candidates,
    }

    for label, path in paths.items():

        _, current_hash = read_input(path)

        if current_hash != hashes[label]:
            raise RuntimeError(
                f"Input changed during comparison: {label}"
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
    print("Word conservation:      PASSED")
    print("Candidate conservation: PASSED")
    print("Input integrity:       PASSED")
    print(f"Saved: {args.json}")
    print("Comparison completed successfully.")


if __name__ == "__main__":
    main()
