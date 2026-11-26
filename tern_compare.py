
"""TERN 6K: pairwise recognition stability analysis."""

import argparse
import hashlib
import itertools
import json
import re
import statistics
from collections import Counter
from pathlib import Path


WORD_PATTERN = re.compile(
    r"[^\W_]+(?:['’][^\W_]+)*",
    re.UNICODE
)


def load(path):
    raw = path.read_bytes()

    return (
        json.loads(raw),
        hashlib.sha256(raw).hexdigest()
    )


def normalize(text):
    return text.casefold().replace("’", "'")


def words(text):
    return [
        normalize(m.group())
        for m in WORD_PATTERN.finditer(text)
    ]


def timestamp(seconds):
    ms = round(seconds * 1000)

    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)

    return (
        f"{hours:02d}:{minutes:02d}:"
        f"{seconds:02d}.{ms:03d}"
    )


# ------------------------------------------------------------
# Reconstruct lexical words with token timing.
# ------------------------------------------------------------

def timed_words(segment):
    tokens = segment["tokens"]
    timestamps = segment["timestamps"]
    durations = segment["durations"]

    if not (
        len(tokens)
        == len(timestamps)
        == len(durations)
    ):
        raise ValueError("Token array length mismatch.")

    pieces = []
    owners = []

    for i, token in enumerate(tokens):
        pieces.append(token)
        owners.extend([i] * len(token))

    reconstructed = "".join(pieces)

    result = []

    for match in WORD_PATTERN.finditer(reconstructed):
        indices = sorted(set(
            owners[match.start():match.end()]
        ))

        start = min(
            timestamps[i] for i in indices
        )

        end = max(
            timestamps[i] + durations[i]
            for i in indices
        )

        result.append({
            "word": normalize(match.group()),
            "start": start,
            "end": end,
            "token_indices": indices,
        })

    # Do not silently accept a disagreement between
    # reconstructed tokens and the recognizer's text.

    valid = (
        [w["word"] for w in result]
        == words(segment["text"])
    )

    return result, valid


# ------------------------------------------------------------
# Minimum edit distance with deterministic traceback.
# ------------------------------------------------------------

def align(a, b):
    n = len(a)
    m = len(b)

    dp = [
        [0] * (m + 1)
        for _ in range(n + 1)
    ]

    for i in range(n + 1):
        dp[i][0] = i

    for j in range(m + 1):
        dp[0][j] = j

    for i in range(1, n + 1):
        for j in range(1, m + 1):

            cost = int(a[i - 1] != b[j - 1])

            dp[i][j] = min(
                dp[i - 1][j - 1] + cost,
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
            )

    operations = []

    i = n
    j = m

    while i or j:

        if (
            i and j
            and a[i - 1] == b[j - 1]
            and dp[i][j] == dp[i - 1][j - 1]
        ):
            operations.append({
                "type": "match",
                "a": i - 1,
                "b": j - 1,
            })

            i -= 1
            j -= 1

        elif (
            i and j
            and dp[i][j] == dp[i - 1][j - 1] + 1
        ):
            operations.append({
                "type": "substitution",
                "a": i - 1,
                "b": j - 1,
            })

            i -= 1
            j -= 1

        elif (
            i
            and dp[i][j] == dp[i - 1][j] + 1
        ):
            operations.append({
                "type": "deletion",
                "a": i - 1,
                "b": None,
            })

            i -= 1

        else:
            operations.append({
                "type": "insertion",
                "a": None,
                "b": j - 1,
            })

            j -= 1

    operations.reverse()

    return operations


def distribution(values):
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p95": None,
            "maximum": None,
        }

    ordered = sorted(values)

    p95_index = round(
        0.95 * (len(ordered) - 1)
    )

    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "p95": ordered[p95_index],
        "maximum": ordered[-1],
    }


# ------------------------------------------------------------
# Input verification.
# ------------------------------------------------------------

def verify(baseline, baseline_hash, candidate):

    if candidate["schema"] != "hehawk.tern.padding":
        raise ValueError("Invalid padding evidence schema.")

    if candidate["version"] != 1:
        raise ValueError("Unsupported padding evidence version.")

    if candidate["baseline_sha256"] != baseline_hash:
        raise ValueError("Baseline hash mismatch.")

    for key in (
        "source_sha256",
        "source_samples",
        "sample_rate",
        "model_sha256",
        "timestamp_basis",
    ):
        if candidate[key] != baseline[key]:
            raise ValueError(f"Metadata mismatch: {key}")

    if len(candidate["segments"]) != len(baseline["segments"]):
        raise ValueError("Segment count mismatch.")

    for a, b in zip(
        baseline["segments"],
        candidate["segments"]
    ):
        for key in (
            "id",
            "start_sample",
            "end_sample",
        ):
            if a[key] != b[key]:
                raise ValueError(
                    f"Segment mismatch: {a['id']} {key}"
                )


# ------------------------------------------------------------
# Pairwise comparison.
# ------------------------------------------------------------

def compare(label_a, data_a, label_b, data_b):

    counts = Counter()
    start_shifts = []
    end_shifts = []

    rows = []

    for sa, sb in zip(
        data_a["segments"],
        data_b["segments"]
    ):
        a = words(sa["text"])
        b = words(sb["text"])

        ta, valid_a = timed_words(sa)
        tb, valid_b = timed_words(sb)

        counts["words_a"] += len(a)
        counts["words_b"] += len(b)

        exact = sa["text"].strip() == sb["text"].strip()

        if exact:
            category = "identical_text"

        elif a == b:
            category = "cosmetic_change"

        else:
            category = "lexical_change"

        counts[category] += 1

        if not a and b:
            counts["empty_to_nonempty"] += 1

        if a and not b:
            counts["nonempty_to_empty"] += 1

        if not a and not b:
            counts["both_empty"] += 1

        operations = align(a, b)

        segment_counts = Counter()
        changes = []
        local_start_shifts = []
        local_end_shifts = []

        if not (valid_a and valid_b):
            counts["timing_unavailable_segments"] += 1

        for op in operations:

            kind = op["type"]
            ia = op["a"]
            ib = op["b"]

            counts[kind] += 1
            segment_counts[kind] += 1

            if kind != "match":
                changes.append({
                    "type": kind,
                    "a_index": ia,
                    "b_index": ib,
                    "a_word": a[ia] if ia is not None else None,
                    "b_word": b[ib] if ib is not None else None,
                })

            elif valid_a and valid_b:

                start_shift = (
                    tb[ib]["start"] - ta[ia]["start"]
                )

                end_shift = (
                    tb[ib]["end"] - ta[ia]["end"]
                )

                start_shifts.append(abs(start_shift))
                end_shifts.append(abs(end_shift))

                local_start_shifts.append(abs(start_shift))
                local_end_shifts.append(abs(end_shift))

                if abs(start_shift) > 0.100:
                    counts["start_shift_over_100ms"] += 1

                if abs(start_shift) > 0.250:
                    counts["start_shift_over_250ms"] += 1

                if abs(start_shift) > 0.500:
                    counts["start_shift_over_500ms"] += 1

        rows.append({
            "id": sa["id"],
            "start_sample": sa["start_sample"],
            "end_sample": sa["end_sample"],
            "category": category,
            "text_a": sa["text"],
            "text_b": sb["text"],
            "words_a": len(a),
            "words_b": len(b),
            "operations": dict(segment_counts),
            "changes": changes,
            "timing_available": valid_a and valid_b,
            "start_shift_seconds": distribution(
                local_start_shifts
            ),
            "end_shift_seconds": distribution(
                local_end_shifts
            ),
        })

    edits = (
        counts["insertion"]
        + counts["deletion"]
        + counts["substitution"]
    )

    assert (
        counts["match"]
        + counts["deletion"]
        + counts["substitution"]
        == counts["words_a"]
    )

    assert (
        counts["match"]
        + counts["insertion"]
        + counts["substitution"]
        == counts["words_b"]
    )

    return {
        "a": label_a,
        "b": label_b,
        "counts": dict(counts),
        "edit_count": edits,
        "relative_edit_rate": (
            edits / counts["words_a"]
            if counts["words_a"]
            else None
        ),
        "start_shift_seconds": distribution(start_shifts),
        "end_shift_seconds": distribution(end_shifts),
        "segments": rows,
    }


# ------------------------------------------------------------
# Four-way agreement.
# ------------------------------------------------------------

def agreement(datasets):

    labels = list(datasets)
    count = len(datasets[labels[0]]["segments"])

    patterns = Counter()
    rows = []

    for index in range(count):

        groups = {}

        for label in labels:

            segment = datasets[label]["segments"][index]

            key = tuple(words(segment["text"]))

            groups.setdefault(key, []).append(label)

        sizes = sorted(
            [len(group) for group in groups.values()],
            reverse=True
        )

        pattern = "+".join(map(str, sizes))

        patterns[pattern] += 1

        rows.append({
            "id": datasets[labels[0]]["segments"][index]["id"],
            "pattern": pattern,
            "groups": [
                {
                    "passes": group,
                    "normalized_words": list(key),
                }
                for key, group in groups.items()
            ],
        })

    return {
        "patterns": dict(patterns),
        "segments": rows,
    }


# ------------------------------------------------------------
# Synthetic padding token inspection.
# ------------------------------------------------------------

def padding_flags(data):

    result = []

    for segment in data["segments"]:

        for flag in segment.get("timing_flags", []):

            index = flag["token_index"]

            result.append({
                "id": segment["id"],
                "token_index": index,
                "token": segment["tokens"][index],
                "segment_relative_start": flag["timestamp"],
                "duration": flag["duration"],
                "original_duration": segment["duration_seconds"],
                "flags": flag["flags"],
                "contains_lexical_characters": bool(
                    words(segment["tokens"][index])
                ),
            })

    return result


# ------------------------------------------------------------
# Terminal reporting.
# ------------------------------------------------------------

def print_pair(pair):

    c = Counter(pair["counts"])
    timing = pair["start_shift_seconds"]

    print()
    print(f"{pair['a']} -> {pair['b']}")
    print("-" * 64)

    print(f"Identical text:       {c['identical_text']}")
    print(f"Cosmetic changes:     {c['cosmetic_change']}")
    print(f"Lexical changes:      {c['lexical_change']}")
    print(f"Words A:              {c['words_a']}")
    print(f"Words B:              {c['words_b']}")
    print(f"Matching words:       {c['match']}")
    print(f"Insertions:           {c['insertion']}")
    print(f"Deletions:            {c['deletion']}")
    print(f"Substitutions:        {c['substitution']}")
    print(f"Total edits:          {pair['edit_count']}")

    rate = pair["relative_edit_rate"]

    if rate is not None:
        print(f"Relative edit rate:   {rate * 100:.3f}%")

    print(f"Empty -> nonempty:    {c['empty_to_nonempty']}")
    print(f"Nonempty -> empty:    {c['nonempty_to_empty']}")
    print(f"Both empty:           {c['both_empty']}")

    print(
        "Timing unavailable:   "
        f"{c['timing_unavailable_segments']} segments"
    )

    if timing["count"]:

        print(
            f"Timed matches:        {timing['count']}"
        )

        for key in ("mean", "median", "p95", "maximum"):
            print(
                f"Start shift {key:8s}: "
                f"{timing[key] * 1000:.1f}ms"
            )

        print(
            f"Start shift >100ms:   "
            f"{c['start_shift_over_100ms']}"
        )

        print(
            f"Start shift >250ms:   "
            f"{c['start_shift_over_250ms']}"
        )

        print(
            f"Start shift >500ms:   "
            f"{c['start_shift_over_500ms']}"
        )


# ------------------------------------------------------------
# Main.
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument("baseline", type=Path)
    parser.add_argument("silence", type=Path)
    parser.add_argument("noise_low", type=Path)
    parser.add_argument("noise_high", type=Path)

    parser.add_argument(
        "--inspect",
        action="append",
        default=[]
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
        "BASELINE": args.baseline,
        "SILENCE": args.silence,
        "NOISE_LOW": args.noise_low,
        "NOISE_HIGH": args.noise_high,
    }

    datasets = {}
    hashes = {}

    for label, path in paths.items():
        datasets[label], hashes[label] = load(path)

    baseline = datasets["BASELINE"]

    if (
        baseline["schema"] != "hehawk.tern.recognition"
        or baseline["version"] != 1
    ):
        raise ValueError("Invalid baseline schema.")

    expected_rms = {
        "SILENCE": 0,
        "NOISE_LOW": 0.001,
        "NOISE_HIGH": 0.01,
    }

    for label, rms in expected_rms.items():

        candidate = datasets[label]

        verify(
            baseline,
            hashes["BASELINE"],
            candidate
        )

        settings = candidate["settings"]

        if settings["padding_rms"] != rms:
            raise ValueError(f"Unexpected RMS: {label}")

        if settings["padding_seconds"] != 0.240:
            raise ValueError(f"Unexpected padding: {label}")

    ids = [
        s["id"]
        for s in baseline["segments"]
    ]

    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate segment IDs.")

    for segment_id in args.inspect:
        if segment_id not in ids:
            parser.error(
                f"Unknown segment ID: {segment_id}"
            )

    print("TERN RECOGNITION STABILITY REPORT")
    print("=" * 64)
    print(f"Segments: {len(ids)}")
    print("Input provenance verification: PASSED")

    pairs = []

    for a, b in itertools.combinations(datasets, 2):

        pair = compare(
            a, datasets[a],
            b, datasets[b]
        )

        pairs.append(pair)
        print_pair(pair)

    consensus = agreement(datasets)

    print()
    print("FOUR-WAY LEXICAL AGREEMENT")
    print("=" * 64)

    descriptions = {
        "4": "All four agree",
        "3+1": "Three agree, one differs",
        "2+2": "Two opposing pairs",
        "2+1+1": "One pair, two different",
        "1+1+1+1": "All four differ",
    }

    for pattern, description in descriptions.items():

        count = consensus["patterns"].get(pattern, 0)

        print(f"{description:28s}: {count}")

    print()
    print("EMPTY SEGMENT TRANSITIONS")
    print("=" * 64)

    empty_rows = []

    for index, segment_id in enumerate(ids):

        states = {
            label: not bool(
                words(data["segments"][index]["text"])
            )
            for label, data in datasets.items()
        }

        if len(set(states.values())) > 1:

            empty_rows.append({
                "id": segment_id,
                "empty": states,
            })

            description = "  ".join(
                f"{label}={'EMPTY' if empty else 'WORDS'}"
                for label, empty in states.items()
            )

            print(f"{segment_id}  {description}")

    if not empty_rows:
        print("No transitions.")

    print()
    print("SYNTHETIC PADDING TOKEN FLAGS")
    print("=" * 64)

    flags = {}

    for label in expected_rms:

        flags[label] = padding_flags(datasets[label])

        print()
        print(label)

        for flag in flags[label]:

            print(
                f"  {flag['id']} "
                f"token={flag['token_index']} "
                f"{flag['token']!r} "
                f"local={timestamp(flag['segment_relative_start'])} "
                f"lexical={flag['contains_lexical_characters']} "
                f"{', '.join(flag['flags'])}"
            )

        if not flags[label]:
            print("  None")

    rate = baseline["sample_rate"]

    for segment_id in args.inspect:

        index = ids.index(segment_id)
        segment = baseline["segments"][index]

        print()
        print(f"INSPECT {segment_id}")
        print("=" * 64)

        print(
            f"{timestamp(segment['start_sample'] / rate)}"
            " - "
            f"{timestamp(segment['end_sample'] / rate)}"
        )

        for label, data in datasets.items():

            print()
            print(label)
            print(data["segments"][index]["text"])

    output = {
        "schema": "hehawk.tern.comparison",
        "version": 1,
        "source_sha256": baseline["source_sha256"],
        "sample_rate": rate,
        "source_samples": baseline["source_samples"],
        "inputs": {
            label: {
                "path": str(paths[label]),
                "sha256": hashes[label],
            }
            for label in paths
        },
        "settings": {
            "alignment": "minimum_lexical_edit_distance",
            "substitution_cost": 1,
            "insertion_cost": 1,
            "deletion_cost": 1,
            "timing_unit": "seconds",
            "ground_truth_available": False,
        },
        "pairwise": pairs,
        "agreement": consensus,
        "empty_transitions": empty_rows,
        "padding_flags": flags,
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
    print("Comparison completed successfully.")
    print(f"Saved: {args.json}")


if __name__ == "__main__":
    main()
