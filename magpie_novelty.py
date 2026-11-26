
#!/usr/bin/env python3
"""MAGPIE 7B: reverse incremental dialogue comparison."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from compare import align_words
from magpie_incremental import (
    parse_srt,
    load_recognition,
    timestamp,
    read_input,
)


# ------------------------------------------------------------
# Convert SRT cues into MAGPIE reference words.
# ------------------------------------------------------------

def reference_words(cues):

    result = []

    for cue in cues:

        for index, word in enumerate(cue["words"]):

            result.append({
                "word": word,
                "normalized": word,
                "start": cue["start"],
                "end": cue["end"],
                "cue": cue["id"],
                "cue_word": index,
                "global_index": len(result),
            })

    return result


# ------------------------------------------------------------
# Independently align each existing evidence source.
#
# Do not merge the two sources into a presumed-correct
# transcript.
# ------------------------------------------------------------

def align_source(cues, recognition):

    reference = reference_words(cues)

    operations = align_words(
        reference,
        recognition
    )

    matches = {}

    for kind, ri, ai in operations:

        if kind != "equal":
            continue

        if ri is None or ai is None:
            raise ValueError("Invalid equal alignment.")

        if ai in matches:
            raise ValueError(
                "Recognition word matched twice."
            )

        r = reference[ri]
        a = recognition[ai]

        if r["normalized"] != a["normalized"]:
            raise ValueError("Unequal normalized words.")

        matches[ai] = {
            "cue_id": r["cue"],
            "cue_word": r["cue_word"],
            "reference_index": ri,
            "reference_start": r["start"],
            "reference_end": r["end"],
        }

    return matches


# ------------------------------------------------------------
# Determine whether a recognition word overlaps
# an existing caption interval.
# ------------------------------------------------------------

def overlapping_cues(word, cues):

    return [
        cue["id"]
        for cue in cues
        if cue["start"] < word["end"]
        and cue["end"] > word["start"]
    ]


# ------------------------------------------------------------
# Classify recognition words.
# ------------------------------------------------------------

def classify_words(
    recognition,
    original,
    recovered,
    original_matches,
    recovered_matches,
):

    rows = []

    for index, word in enumerate(recognition):

        original_match = original_matches.get(index)
        recovered_match = recovered_matches.get(index)

        original_hits = overlapping_cues(
            word,
            original
        )

        recovered_hits = overlapping_cues(
            word,
            recovered
        )

        if original_match is not None:
            status = "original"

        elif recovered_match is not None:
            status = "recovered"

        elif original_hits or recovered_hits:
            status = "competing"

        else:
            status = "novel"

        rows.append({
            "index": index,
            "word": word,
            "status": status,
            "original_match": original_match,
            "recovered_match": recovered_match,
            "overlapping_original_cues": original_hits,
            "overlapping_recovered_cues": recovered_hits,
            "short_circuit_eligible": (
                status in ("original", "recovered")
            ),
        })

    return rows


# ------------------------------------------------------------
# Consolidate consecutive unresolved words.
#
# Never combine across known words or across large
# temporal gaps.
# ------------------------------------------------------------

def group_candidates(rows, max_gap):

    candidates = []
    pending = []

    def flush():

        if not pending:
            return

        words = [row["word"] for row in pending]

        counts = Counter(
            row["status"] for row in pending
        )

        original_ids = sorted({
            cue_id
            for row in pending
            for cue_id in row[
                "overlapping_original_cues"
            ]
        })

        recovered_ids = sorted({
            cue_id
            for row in pending
            for cue_id in row[
                "overlapping_recovered_cues"
            ]
        })

        if len(counts) == 1:
            category = next(iter(counts))
        else:
            category = "mixed"

        start = min(w["start"] for w in words)
        end = max(w["end"] for w in words)

        candidates.append({
            "id": f"N{len(candidates) + 1:04d}",
            "category": category,
            "start": start,
            "end": end,
            "duration": end - start,
            "word_count": len(words),
            "word_indices": [
                row["index"] for row in pending
            ],
            "classifications": dict(counts),
            "original_cue_ids": original_ids,
            "recovered_cue_ids": recovered_ids,
            "segment_ids": sorted({
                w["segment_id"] for w in words
            }),
            "text": " ".join(
                w["word"] for w in words
            ),
            "human_verified": False,
        })

        pending.clear()

    for row in rows:

        if row["short_circuit_eligible"]:

            flush()
            continue

        if pending:

            previous_end = max(
                item["word"]["end"]
                for item in pending
            )

            gap = (
                row["word"]["start"]
                - previous_end
            )

            if gap > max_gap:
                flush()

        pending.append(row)

    flush()

    return candidates


# ------------------------------------------------------------
# Main.
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "original_srt",
        type=Path
    )

    parser.add_argument(
        "recovered_srt",
        type=Path
    )

    parser.add_argument(
        "recognition",
        type=Path
    )

    parser.add_argument(
        "--max-gap",
        type=float,
        default=0.750
    )

    parser.add_argument(
        "--json",
        required=True,
        type=Path
    )

    args = parser.parse_args()

    if not 0 <= args.max_gap <= 5:
        parser.error(
            "Maximum gap must be between 0 and 5 seconds."
        )

    if args.json.exists():
        parser.error("Output already exists.")

    paths = {
        "original": args.original_srt,
        "recovered": args.recovered_srt,
        "recognition": args.recognition,
    }

    raw = {}
    hashes = {}

    for label, path in paths.items():

        raw[label], hashes[label] = read_input(path)

    original = parse_srt(raw["original"])
    recovered = parse_srt(raw["recovered"])

    evidence = json.loads(raw["recognition"])

    recognition = load_recognition(evidence)

    duration = (
        evidence["source_samples"]
        / evidence["sample_rate"]
    )

    for label, cues in (
        ("original", original),
        ("recovered", recovered),
    ):

        for cue in cues:

            if cue["end"] > duration:
                raise ValueError(
                    f"{label} cue {cue['id']} "
                    "exceeds source duration."
                )

    print("MAGPIE REVERSE INCREMENTAL COMPARISON")
    print("=" * 64)

    print(f"Original cues:       {len(original)}")
    print(f"Recovered cues:      {len(recovered)}")
    print(f"Recognition words:   {len(recognition)}")

    print("\nAligning original captions...")

    original_matches = align_source(
        original,
        recognition
    )

    print("Aligning recovered dialogue...")

    recovered_matches = align_source(
        recovered,
        recognition
    )

    rows = classify_words(
        recognition,
        original,
        recovered,
        original_matches,
        recovered_matches,
    )

    candidates = group_candidates(
        rows,
        args.max_gap
    )

    counts = Counter(
        row["status"] for row in rows
    )

    candidate_counts = Counter(
        candidate["category"]
        for candidate in candidates
    )

    dual_support = len(
        set(original_matches)
        & set(recovered_matches)
    )

    eligible = (
        counts["original"]
        + counts["recovered"]
    )

    unresolved = (
        counts["competing"]
        + counts["novel"]
    )

    # --------------------------------------------------------
    # Conservation checks.
    # --------------------------------------------------------

    if eligible + unresolved != len(recognition):
        raise RuntimeError(
            "Recognition word conservation failed."
        )

    if sum(
        c["word_count"] for c in candidates
    ) != unresolved:
        raise RuntimeError(
            "Candidate word conservation failed."
        )

    candidate_indices = [
        index
        for candidate in candidates
        for index in candidate["word_indices"]
    ]

    expected_indices = [
        row["index"]
        for row in rows
        if not row["short_circuit_eligible"]
    ]

    if candidate_indices != expected_indices:
        raise RuntimeError(
            "Candidate index conservation failed."
        )

    short_circuit_rate = (
        eligible / len(recognition)
        if recognition
        else 0
    )

    print()
    print("WORD CLASSIFICATIONS")
    print("=" * 64)

    for status in (
        "original",
        "recovered",
        "competing",
        "novel",
    ):

        count = counts[status]

        percent = (
            100 * count / len(recognition)
            if recognition
            else 0
        )

        print(
            f"{status:15s}: "
            f"{count:5d} ({percent:6.2f}%)"
        )

    print()
    print(f"Original source matches:  {len(original_matches)}")
    print(f"Recovered source matches: {len(recovered_matches)}")
    print(f"Supported by both:        {dual_support}")
    print(f"Short-circuit eligible:   {eligible}")
    print(f"Unresolved words:         {unresolved}")
    print(
        f"Short-circuit rate:       "
        f"{100 * short_circuit_rate:.2f}%"
    )

    print()
    print("CONSOLIDATED CANDIDATES")
    print("=" * 64)

    for category in (
        "competing",
        "novel",
        "mixed",
    ):

        print(
            f"{category:15s}: "
            f"{candidate_counts[category]}"
        )

    print(f"Total candidates: {len(candidates)}")

    print()
    print("LONGEST CANDIDATES BY WORD COUNT")
    print("=" * 64)

    ranked = sorted(
        candidates,
        key=lambda c: (
            -c["word_count"],
            c["start"]
        )
    )

    for candidate in ranked[:20]:

        print(
            f"{candidate['id']}  "
            f"{timestamp(candidate['start'])} - "
            f"{timestamp(candidate['end'])}  "
            f"{candidate['category']:10s}  "
            f"words={candidate['word_count']:3d}  "
            f"segments={','.join(candidate['segment_ids'])}"
        )

    output = {
        "schema": "hehawk.magpie.novelty",
        "version": 1,
        "timestamp_basis": "episode",
        "source_sha256": evidence["source_sha256"],
        "inputs": {
            label: {
                "path": str(paths[label]),
                "sha256": hashes[label],
            }
            for label in paths
        },
        "settings": {
            "maximum_candidate_gap_seconds": args.max_gap,
            "alignment": "compare.align_words",
            "independent_reference_alignment": True,
            "original_precedence_for_classification": True,
            "srt_source_identity_verified": False,
            "ground_truth_available": False,
        },
        "statistics": {
            "original_cues": len(original),
            "recovered_cues": len(recovered),
            "recognition_words": len(recognition),
            "word_classifications": dict(counts),
            "original_matches": len(original_matches),
            "recovered_matches": len(recovered_matches),
            "dual_support": dual_support,
            "short_circuit_eligible": eligible,
            "short_circuit_rate": short_circuit_rate,
            "unresolved_words": unresolved,
            "candidate_count": len(candidates),
            "candidate_classifications": dict(
                candidate_counts
            ),
        },
        "words": rows,
        "candidates": candidates,
    }

    for label, path in paths.items():

        current_hash = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

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
