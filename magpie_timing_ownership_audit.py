
import argparse
import hashlib
import json
import math
import unicodedata

from collections import Counter
from pathlib import Path

from magpie import recognition_words
from magpie_decoder_reconstruct import reconstruct


EPSILON = 0.000001


# ------------------------------------------------------------
# Input handling
# ------------------------------------------------------------

def read_input(path):

    raw = path.read_bytes()

    return (
        json.loads(raw),
        hashlib.sha256(raw).hexdigest()
    )


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
# Interval arithmetic
# ------------------------------------------------------------

def merge_intervals(intervals):

    result = []

    for start, end in sorted(intervals):

        if end - start <= EPSILON:
            continue

        if result and start <= result[-1][1] + EPSILON:

            result[-1][1] = max(
                result[-1][1], end
            )

        else:

            result.append([start, end])

    return result


def subtract_intervals(source, coverage):

    source = merge_intervals(source)
    coverage = merge_intervals(coverage)

    result = []

    for start, end in source:

        cursor = start

        for a, b in coverage:

            if b <= cursor:
                continue

            if a >= end:
                break

            if a > cursor:

                result.append([
                    cursor,
                    min(a, end)
                ])

            cursor = max(cursor, b)

            if cursor >= end:
                break

        if cursor < end:

            result.append([cursor, end])

    return merge_intervals(result)


def total_duration(intervals):

    return sum(
        end - start
        for start, end in intervals
    )


def word_intervals(words, offset, episode_end):

    return merge_intervals([

        [
            max(0.0, offset + word["start"]),
            min(episode_end, offset + word["end"])
        ]

        for word in words
    ])


# ------------------------------------------------------------
# Token classification
# ------------------------------------------------------------

def token_category(token):

    if not token:
        return "empty"

    if any(ch.isalnum() for ch in token):
        return "lexical"

    if token.isspace():
        return "whitespace"

    if all(
        ch.isspace()
        or unicodedata.category(ch).startswith("P")
        for ch in token
    ):
        return "punctuation"

    return "other_nonlexical"


def masked_token(token):

    return "".join(

        "A" if ch.isalpha()
        else "9" if ch.isdigit()
        else " " if ch.isspace()
        else ch if unicodedata.category(ch).startswith("P")
        else "?"

        for ch in token
    )


def token_record(obs, index, offset):

    token = obs["tokens"][index]

    start = (
        offset + obs["timestamps"][index]
    )

    end = (
        start + obs["durations"][index]
    )

    return {
        "index": index,
        "category": token_category(token),
        "structure": masked_token(token),
        "start": start,
        "end": end,
        "duration": end - start,
    }


# ------------------------------------------------------------
# LARK speech measurements
# ------------------------------------------------------------

def measure_speech(start, end, vad):

    rate = vad["sample_rate"]
    step = vad["frame_samples"] / rate

    probabilities = vad["probabilities"]

    first = max(
        0, math.floor(start / step)
    )

    last = min(
        len(probabilities),
        math.ceil(end / step)
    )

    weighted_sum = 0.0
    covered = 0.0
    peak = 0.0

    thresholds = {
        "0.3": 0.0,
        "0.5": 0.0,
        "0.7": 0.0,
    }

    for index in range(first, last):

        frame_start = index * step
        frame_end = frame_start + step

        overlap = max(
            0.0,
            min(end, frame_end)
            - max(start, frame_start)
        )

        if overlap <= 0:
            continue

        probability = probabilities[index]

        covered += overlap

        weighted_sum += (
            overlap * probability
        )

        peak = max(peak, probability)

        for threshold in thresholds:

            if probability >= float(threshold):

                thresholds[threshold] += overlap

    return {
        "start": start,
        "end": end,
        "duration": end - start,
        "covered_seconds": covered,
        "mean_probability": (
            weighted_sum / covered
            if covered else None
        ),
        "peak_probability": peak,
        "speech_seconds": thresholds,
    }


# ------------------------------------------------------------
# Changed word audit
# ------------------------------------------------------------

def audit_word(
    old,
    new,
    obs,
    offset,
    segment_id,
    word_index
):

    old_start = offset + old["start"]
    old_end = offset + old["end"]

    new_start = offset + new["start"]
    new_end = offset + new["end"]

    old_indices = set(range(
        old["token_start"],
        old["token_end"]
    ))

    new_indices = set(
        new["token_indices"]
    )

    excluded = sorted(
        old_indices - new_indices
    )

    included = sorted(
        new_indices - old_indices
    )

    released = subtract_intervals(
        [[old_start, old_end]],
        [[new_start, new_end]]
    )

    added = subtract_intervals(
        [[new_start, new_end]],
        [[old_start, old_end]]
    )

    old_duration = old_end - old_start
    new_duration = new_end - new_start

    delta = new_duration - old_duration

    if delta < -EPSILON:
        direction = "shortened"

    elif delta > EPSILON:
        direction = "lengthened"

    else:
        direction = "shifted"

    return {
        "segment_id": segment_id,
        "pass_id": obs["pass_id"],
        "word_index": word_index,
        "direction": direction,
        "old_start": old_start,
        "old_end": old_end,
        "new_start": new_start,
        "new_end": new_end,
        "old_duration": old_duration,
        "new_duration": new_duration,
        "duration_delta": delta,
        "released_intervals": released,
        "added_intervals": added,
        "excluded_tokens": [
            token_record(obs, i, offset)
            for i in excluded
        ],
        "included_tokens": [
            token_record(obs, i, offset)
            for i in included
        ],
    }


# ------------------------------------------------------------
# Complete audit
# ------------------------------------------------------------

def audit(data, vad):

    stats = Counter()

    changes = []

    excluded_categories = Counter()
    included_categories = Counter()

    old_coverage = {}
    new_coverage = {}

    comparable_old = {}
    comparable_new = {}

    skipped = []

    episode_end = (
        data["source_samples"]
        / data["sample_rate"]
    )

    for segment in data["segments"]:

        segment_id = segment["id"]
        offset = segment["start"]

        for obs in segment["observations"]:

            stats["observations"] += 1

            pass_id = obs["pass_id"]

            old = recognition_words({
                "tokens": obs["tokens"],
                "timestamps": obs["timestamps"],
                "durations": obs["durations"],
                "source_offset_seconds": 0,
            })

            result = reconstruct(
                obs["text"],
                obs["tokens"],
                obs["timestamps"],
                obs["durations"]
            )

            new = result["words"]

            old_intervals = word_intervals(
                old, offset, episode_end
            )

            new_intervals = word_intervals(
                new, offset, episode_end
            )

            old_coverage.setdefault(
                pass_id, []
            ).extend(old_intervals)

            new_coverage.setdefault(
                pass_id, []
            ).extend(new_intervals)

            old_sequence = [
                w["normalized"] for w in old
            ]

            new_sequence = [
                w["normalized"] for w in new
            ]

            if old_sequence != new_sequence:

                stats["skipped_observations"] += 1

                skipped.append({
                    "segment_id": segment_id,
                    "pass_id": pass_id,
                    "reason": "Lexical boundaries differ",
                })

                continue

            stats["comparable_observations"] += 1

            comparable_old.setdefault(
                pass_id, []
            ).extend(old_intervals)

            comparable_new.setdefault(
                pass_id, []
            ).extend(new_intervals)

            for index, (a, b) in enumerate(
                zip(old, new)
            ):

                stats["comparable_words"] += 1

                if (
                    abs(a["start"] - b["start"])
                    <= EPSILON

                    and

                    abs(a["end"] - b["end"])
                    <= EPSILON
                ):
                    continue

                stats["changed_words"] += 1

                record = audit_word(
                    a,
                    b,
                    obs,
                    offset,
                    segment_id,
                    index
                )

                stats[record["direction"]] += 1

                for token in record["excluded_tokens"]:

                    excluded_categories[
                        token["category"]
                    ] += 1

                for token in record["included_tokens"]:

                    included_categories[
                        token["category"]
                    ] += 1

                changes.append(record)

    # --------------------------------------------------------
    # Episode-wide coverage, separately for each pass.
    #
    # Adjacent words and segments are included so that
    # overlapping coverage is not mistaken for a new gap.
    # --------------------------------------------------------

    pass_results = {}

    for pass_id in old_coverage:

        old = merge_intervals(
            old_coverage[pass_id]
        )

        new = merge_intervals(
            new_coverage[pass_id]
        )

        exposed = subtract_intervals(
            old, new
        )

        newly_covered = subtract_intervals(
            new, old
        )

        # Isolate changes from observations whose
        # lexical sequences were directly comparable.

        comparable_exposed = subtract_intervals(
            comparable_old.get(pass_id, []),
            new
        )

        gaps = [

            measure_speech(start, end, vad)

            for start, end in exposed
        ]

        comparable_gaps = [

            measure_speech(start, end, vad)

            for start, end in comparable_exposed
        ]

        gaps.sort(
            key=lambda gap: (
                gap["speech_seconds"]["0.5"],
                gap["duration"]
            ),
            reverse=True
        )

        pass_results[pass_id] = {
            "old_coverage_seconds": total_duration(old),
            "new_coverage_seconds": total_duration(new),
            "newly_exposed_seconds": total_duration(exposed),
            "newly_covered_seconds": total_duration(
                newly_covered
            ),
            "comparable_exposed_seconds": total_duration(
                comparable_exposed
            ),
            "newly_exposed_intervals": gaps,
            "comparable_exposed_intervals": comparable_gaps,
            "newly_covered_intervals": newly_covered,
            "speech_seconds": {
                threshold: sum(
                    gap["speech_seconds"][threshold]
                    for gap in gaps
                )
                for threshold in ["0.3", "0.5", "0.7"]
            },
        }

    # Union across all four passes.
    # This avoids counting the same audio four times.

    union = merge_intervals([

        [gap["start"], gap["end"]]

        for result in pass_results.values()

        for gap in result["newly_exposed_intervals"]
    ])

    union_gaps = [

        measure_speech(start, end, vad)

        for start, end in union
    ]

    union_gaps.sort(
        key=lambda gap: (
            gap["speech_seconds"]["0.5"],
            gap["duration"]
        ),
        reverse=True
    )

    changes.sort(
        key=lambda record: abs(
            record["duration_delta"]
        ),
        reverse=True
    )

    return {
        "statistics": stats,
        "excluded_token_categories": excluded_categories,
        "included_token_categories": included_categories,
        "changed_words": changes,
        "skipped_observations": skipped,
        "passes": pass_results,
        "union_exposed_seconds": total_duration(union),
        "union_exposed_intervals": union_gaps,
        "union_speech_seconds": {
            threshold: sum(
                gap["speech_seconds"][threshold]
                for gap in union_gaps
            )
            for threshold in ["0.3", "0.5", "0.7"]
        },
    }


# ------------------------------------------------------------
# Reporting
# ------------------------------------------------------------

def print_report(result):

    stats = result["statistics"]

    print()
    print("=" * 72)
    print("TIMING OWNERSHIP SUMMARY")
    print("=" * 72)

    for label, key in [

        ("Observations", "observations"),
        ("Comparable observations", "comparable_observations"),
        ("Skipped observations", "skipped_observations"),
        ("Comparable words", "comparable_words"),
        ("Changed words", "changed_words"),
        ("Shortened words", "shortened"),
        ("Lengthened words", "lengthened"),
        ("Shifted words", "shifted"),

    ]:

        print(f"{label:40}{stats[key]:>10}")

    print()
    print("Tokens excluded from original word spans:")

    for category, count in sorted(
        result["excluded_token_categories"].items()
    ):

        print(f"  {category:30}{count:>8}")

    print()
    print("Tokens added to reconstructed word spans:")

    for category, count in sorted(
        result["included_token_categories"].items()
    ):

        print(f"  {category:30}{count:>8}")

    print()
    print("=" * 72)
    print("LARGEST WORD TIMING CHANGES")
    print("=" * 72)

    for record in result["changed_words"][:12]:

        print()

        print(
            record["segment_id"],
            record["pass_id"],
            "word index",
            record["word_index"],
            record["direction"]
        )

        print(
            "  Old:",
            timestamp(record["old_start"]),
            "-",
            timestamp(record["old_end"])
        )

        print(
            "  New:",
            timestamp(record["new_start"]),
            "-",
            timestamp(record["new_end"])
        )

        print(
            "  Duration change:",
            f"{record['duration_delta'] * 1000:+.3f} ms"
        )

        for label, key in [

            ("Excluded", "excluded_tokens"),
            ("Included", "included_tokens"),

        ]:

            for token in record[key]:

                print(
                    f"  {label} token {token['index']}:",
                    token["category"],
                    repr(token["structure"]),
                    timestamp(token["start"]),
                    "-",
                    timestamp(token["end"])
                )

    print()
    print("=" * 72)
    print("EPISODE COVERAGE BY RECOGNITION PASS")
    print("=" * 72)

    for pass_id, values in result["passes"].items():

        print()
        print("Pass:", pass_id)

        for label, key in [

            ("Original word coverage", "old_coverage_seconds"),
            ("New word coverage", "new_coverage_seconds"),
            ("Newly exposed audio", "newly_exposed_seconds"),
            ("Newly covered audio", "newly_covered_seconds"),
            ("Comparable-only exposed audio", "comparable_exposed_seconds"),

        ]:

            print(
                f"  {label:34}"
                f"{values[key]:>10.3f} s"
            )

        print(
            "  Newly exposed intervals:",
            len(values["newly_exposed_intervals"])
        )

        for threshold, seconds in (
            values["speech_seconds"].items()
        ):

            print(
                f"  Speech probability >= {threshold}: "
                f"{seconds:.3f} s"
            )

    print()
    print("=" * 72)
    print("UNIQUE EXPOSED AUDIO ACROSS ALL PASSES")
    print("=" * 72)

    print(
        "Total exposed audio:",
        f"{result['union_exposed_seconds']:.3f} s"
    )

    for threshold, seconds in (
        result["union_speech_seconds"].items()
    ):

        print(
            f"Speech probability >= {threshold}: "
            f"{seconds:.3f} s"
        )

    print()
    print("Highest-priority newly exposed gaps:")

    for gap in result["union_exposed_intervals"][:15]:

        print()

        print(
            " ",
            timestamp(gap["start"]),
            "-",
            timestamp(gap["end"])
        )

        print(
            f"  Decimal seconds: "
            f"{gap['start']:.3f} - "
            f"{gap['end']:.3f}"
        )

        print(
            f"  Duration: {gap['duration']:.3f} s"
        )

        print(
            f"  Mean speech probability: "
            f"{gap['mean_probability'] or 0.0:.4f}"
        )

        print(
            f"  Peak speech probability: "
            f"{gap['peak_probability']:.4f}"
        )

        print(
            f"  Speech >= 0.5: "
            f"{gap['speech_seconds']['0.5']:.3f} s"
        )


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description="MAGPIE timing ownership audit"
    )

    parser.add_argument(
        "recognition",
        type=Path
    )

    parser.add_argument(
        "vad",
        type=Path
    )

    parser.add_argument(
        "--json",
        type=Path,
        required=True
    )

    args = parser.parse_args()

    if args.json.exists():
        parser.error("Output file already exists.")

    if args.json.resolve() in {

        args.recognition.resolve(),
        args.vad.resolve()

    }:

        parser.error("Output must differ from inputs.")

    data, recognition_hash = read_input(
        args.recognition
    )

    vad, vad_hash = read_input(
        args.vad
    )

    if data.get("schema") != "hehawk.magpie.accumulation":

        parser.error("Unexpected recognition schema.")

    if vad.get("schema") != "hehawk.lark.probabilities":

        parser.error("Unexpected LARK schema.")

    for key in [

        "source_sha256",
        "sample_rate",
        "source_samples",

    ]:

        if key not in data or key not in vad:

            parser.error(
                f"Missing source identity field: {key}"
            )

        if data[key] != vad[key]:

            parser.error(
                f"Source identity mismatch: {key}"
            )

    if vad.get("timestamp_basis") != "episode":

        parser.error("Unexpected LARK timestamp basis.")

    if data.get("observation_timestamp_basis") != "segment_relative":

        parser.error("Unexpected observation timestamp basis.")

    if vad.get("source_offset_seconds", 0) != 0:

        parser.error("Unexpected LARK source offset.")

    if vad["frame_samples"] <= 0:

        parser.error("Invalid LARK frame size.")

    expected_frames = (

        vad["source_samples"]
        + vad["frame_samples"] - 1

    ) // vad["frame_samples"]

    if len(vad["probabilities"]) != expected_frames:

        parser.error("Unexpected LARK frame count.")

    if any(

        not math.isfinite(p)
        or p < 0
        or p > 1

        for p in vad["probabilities"]

    ):

        parser.error("Invalid LARK probabilities.")

    print("MAGPIE TIMING OWNERSHIP AUDIT")
    print("=" * 72)
    print("Recognition and LARK source identity: PASS")

    result = audit(data, vad)

    for path, expected in [

        (args.recognition, recognition_hash),
        (args.vad, vad_hash),

    ]:

        actual = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        if actual != expected:

            raise RuntimeError(
                f"Input changed: {path}"
            )

    print_report(result)

    report = {
        "schema": "hehawk.magpie.timing_ownership",
        "version": 1,
        "timestamp_basis": "episode",
        "source_sha256": data["source_sha256"],
        "inputs": {
            "recognition": {
                "path": str(args.recognition),
                "sha256": recognition_hash,
            },
            "vad": {
                "path": str(args.vad),
                "sha256": vad_hash,
            },
        },
        "settings": {
            "timing_epsilon_seconds": EPSILON,
            "speech_thresholds": [0.3, 0.5, 0.7],
            "episode_wide_coverage": True,
            "automatic_acceptance": False,
        },
        "results": result,
        "integrity": {
            "inputs_unchanged": True,
            "source_identity_verified": True,
        },
        "limitations": {
            "vad_proves_dialogue": False,
            "new_timings_human_verified": False,
            "old_token_spans_are_exact_ownership": False,
            "production_code_modified": False,
        },
    }

    with args.json.open("x", encoding="utf-8") as handle:

        json.dump(
            report,
            handle,
            ensure_ascii=False,
            indent=2
        )

        handle.write("\n")

    print()
    print("=" * 72)
    print("INTEGRITY")
    print("=" * 72)
    print("Original inputs unchanged: PASS")
    print("Production code modified: NO")
    print("Recognition rerun: NO")
    print("LARK rerun: NO")
    print()
    print("Report written to:", args.json)


if __name__ == "__main__":
    main()
