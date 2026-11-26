
"""Compare two MAGPIE disagreement localization reports."""

import argparse
import hashlib
import json

from collections import Counter
from pathlib import Path


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

    milliseconds = round(seconds * 1000)

    hours, milliseconds = divmod(
        milliseconds, 3600000
    )

    minutes, milliseconds = divmod(
        milliseconds, 60000
    )

    secs, milliseconds = divmod(
        milliseconds, 1000
    )

    return (
        f"{hours:02d}:{minutes:02d}:"
        f"{secs:02d}.{milliseconds:03d}"
    )


# ------------------------------------------------------------
# Interval arithmetic
# ------------------------------------------------------------

def merge_intervals(intervals):

    merged = []

    for start, end in sorted(intervals):

        if end - start <= EPSILON:
            continue

        if (
            not merged
            or start > merged[-1][1] + EPSILON
        ):

            merged.append([start, end])

        else:

            merged[-1][1] = max(
                merged[-1][1], end
            )

    return merged


def subtract_intervals(source, excluded):

    source = merge_intervals(source)
    excluded = merge_intervals(excluded)

    result = []

    for start, end in source:

        cursor = start

        for other_start, other_end in excluded:

            if other_end <= cursor:
                continue

            if other_start >= end:
                break

            if other_start > cursor + EPSILON:

                result.append([
                    cursor,
                    min(other_start, end)
                ])

            cursor = max(cursor, other_end)

            if cursor >= end:
                break

        if end - cursor > EPSILON:

            result.append([cursor, end])

    return merge_intervals(result)


def duration(intervals):

    return sum(

        end - start

        for start, end in intervals

    )


def interval_records(intervals):

    return [

        {
            "start": start,
            "end": end,
            "duration": end - start,
        }

        for start, end in intervals

    ]


def get_intervals(records):

    return merge_intervals([

        [record["start"], record["end"]]

        for record in records

    ])


def interval_difference(old, new):

    removed = subtract_intervals(old, new)
    added = subtract_intervals(new, old)

    return {
        "old_seconds": duration(old),
        "new_seconds": duration(new),
        "removed_seconds": duration(removed),
        "added_seconds": duration(added),
        "net_reduction_seconds": (
            duration(old) - duration(new)
        ),
        "removed_intervals": interval_records(
            removed
        ),
        "added_intervals": interval_records(
            added
        ),
    }


# ------------------------------------------------------------
# Report indexing
# ------------------------------------------------------------

def index_segments(records, key):

    result = {}

    for record in records:

        identity = record[key]

        if identity in result:

            raise ValueError(
                f"Duplicate segment identity: "
                f"{identity}"
            )

        result[identity] = record

    return result


def fallback_ids(report):

    return {

        record["segment_id"]

        for record in report["fallback_segments"]

    }


# ------------------------------------------------------------
# Structural signatures
# ------------------------------------------------------------

def anchor_signature(anchor):

    return (

        anchor["normalized"],

        tuple(sorted(
            anchor["positions"].items()
        ))

    )


def anchor_map(segment):

    result = {}

    for anchor in segment.get("anchors", []):

        signature = anchor_signature(anchor)

        if signature in result:

            raise ValueError(
                "Duplicate anchor signature"
            )

        result[signature] = anchor

    return result


def hypothesis_signature(hypothesis):

    return (

        tuple(
            hypothesis["normalized_words"]
        ),

        tuple(sorted(
            hypothesis["supporting_passes"]
        ))

    )


def region_signature(region):

    return tuple(sorted(

        hypothesis_signature(hypothesis)

        for hypothesis in region["hypotheses"]

    ))


def region_signatures(segment):

    return Counter(

        region_signature(region)

        for region in segment["regions"]

    )


def same_time(a, b):

    return abs(a - b) <= EPSILON


# ------------------------------------------------------------
# Lexical evidence verification
# ------------------------------------------------------------

def expected_sequences(source):

    return {

        obs["pass_id"]: obs["normalized_words"]

        for obs in source["observations"]

    }


def verify_hypothesis_support(
    region,
    expected_passes
):

    seen = set()

    for hypothesis in region["hypotheses"]:

        supporters = hypothesis[
            "supporting_passes"
        ]

        if len(supporters) != len(set(supporters)):

            raise ValueError(
                "Duplicate hypothesis supporter"
            )

        if seen.intersection(supporters):

            raise ValueError(
                "Pass supports multiple alternatives "
                "within one region"
            )

        if (
            "support_count" in hypothesis
            and hypothesis["support_count"]
            != len(supporters)
        ):

            raise ValueError(
                "Incorrect hypothesis support count"
            )

        seen.update(supporters)

    if seen != expected_passes:

        raise ValueError(
            "Region does not account for every pass"
        )


def verify_segment(segment, source, fallback):

    expected = expected_sequences(source)

    passes = set(expected)

    for region in segment["regions"]:

        verify_hypothesis_support(
            region,
            passes
        )

    if fallback:

        return {
            "support_verified": True,
            "anchor_positions_verified": False,
            "word_counts_verified": False,
            "fallback": True,
        }

    counts = segment["word_counts"]

    if set(counts) != passes:

        raise ValueError(
            "Word-count pass identities differ"
        )

    for pass_id, words in expected.items():

        if counts[pass_id] != len(words):

            raise ValueError(
                f"Word count differs for {pass_id}"
            )

    previous = {
        pass_id: -1
        for pass_id in passes
    }

    for anchor in segment["anchors"]:

        positions = anchor["positions"]

        if set(positions) != passes:

            raise ValueError(
                "Anchor does not contain every pass"
            )

        for pass_id, position in positions.items():

            words = expected[pass_id]

            if not 0 <= position < len(words):

                raise ValueError(
                    "Anchor position out of bounds"
                )

            if position <= previous[pass_id]:

                raise ValueError(
                    "Nonmonotonic anchor positions"
                )

            if words[position] != anchor["normalized"]:

                raise ValueError(
                    "Anchor lexical mismatch"
                )

            previous[pass_id] = position

    # Independently reconstruct the expected disagreement
    # signatures from the source words between anchors.

    expected_regions = Counter()

    boundaries = [

        {
            pass_id: -1
            for pass_id in passes
        }

    ]

    boundaries.extend(

        anchor["positions"]

        for anchor in segment["anchors"]

    )

    boundaries.append({

        pass_id: len(words)

        for pass_id, words in expected.items()

    })

    for left, right in zip(
        boundaries,
        boundaries[1:]
    ):

        groups = {}

        for pass_id in sorted(passes):

            sequence = tuple(

                expected[pass_id][
                    left[pass_id] + 1:
                    right[pass_id]
                ]

            )

            groups.setdefault(
                sequence, []
            ).append(pass_id)

        if len(groups) <= 1:
            continue

        signature = tuple(sorted(

            (sequence, tuple(supporters))

            for sequence, supporters
            in groups.items()

        ))

        expected_regions[signature] += 1

    actual_regions = region_signatures(
        segment
    )

    if actual_regions != expected_regions:

        raise ValueError(
            "Disagreement alternatives differ from "
            "source sequences between anchors"
        )

    return {
        "support_verified": True,
        "anchor_positions_verified": True,
        "word_counts_verified": True,
        "disagreement_sequences_verified": True,
        "fallback": False,
    }


# ------------------------------------------------------------
# Compare one disputed segment
# ------------------------------------------------------------

def compare_segment(
    old,
    new,
    source,
    old_fallback,
    new_fallback
):

    old_anchors = anchor_map(old)
    new_anchors = anchor_map(new)

    old_keys = set(old_anchors)
    new_keys = set(new_anchors)

    added_anchors = new_keys - old_keys
    removed_anchors = old_keys - new_keys

    changed_anchor_times = 0

    for key in old_keys & new_keys:

        a = old_anchors[key]
        b = new_anchors[key]

        if (
            not same_time(a["start"], b["start"])
            or not same_time(a["end"], b["end"])
        ):

            changed_anchor_times += 1

    old_regions = region_signatures(old)
    new_regions = region_signatures(new)

    removed_regions = old_regions - new_regions
    added_regions = new_regions - old_regions

    timing = interval_difference(

        get_intervals(old["regions"]),

        get_intervals(new["regions"])

    )

    changes = []

    if old_fallback != new_fallback:

        changes.append("fallback_status")

    if added_anchors or removed_anchors:

        changes.append("anchor_membership")

    if changed_anchor_times:

        changes.append("anchor_timing")

    if added_regions or removed_regions:

        changes.append("region_alternatives")

    if (
        timing["removed_seconds"] > EPSILON
        or timing["added_seconds"] > EPSILON
    ):

        changes.append("disagreement_coverage")

    return {
        "segment_id": source["id"],
        "start": source["start"],
        "end": source["end"],
        "old_fallback": old_fallback,
        "new_fallback": new_fallback,
        "old_anchor_count": len(old_anchors),
        "new_anchor_count": len(new_anchors),
        "added_anchors": len(added_anchors),
        "removed_anchors": len(removed_anchors),
        "changed_anchor_times": changed_anchor_times,
        "old_region_count": len(old["regions"]),
        "new_region_count": len(new["regions"]),
        "removed_region_signatures": sum(
            removed_regions.values()
        ),
        "added_region_signatures": sum(
            added_regions.values()
        ),
        "coverage": timing,
        "changes": changes,
        "old_verification": verify_segment(
            old, source, old_fallback
        ),
        "new_verification": verify_segment(
            new, source, new_fallback
        ),
    }


# ------------------------------------------------------------
# Complete differential audit
# ------------------------------------------------------------

def audit(old, new, source):

    old_segments = index_segments(
        old["segments"],
        "segment_id"
    )

    new_segments = index_segments(
        new["segments"],
        "segment_id"
    )

    source_segments = index_segments(
        source["segments"],
        "id"
    )

    if set(old_segments) != set(new_segments):

        raise ValueError(
            "Disputed segment identities differ"
        )

    old_fallbacks = fallback_ids(old)
    new_fallbacks = fallback_ids(new)

    comparisons = []

    failures = []

    for segment_id in sorted(old_segments):

        try:

            record = compare_segment(

                old_segments[segment_id],

                new_segments[segment_id],

                source_segments[segment_id],

                segment_id in old_fallbacks,

                segment_id in new_fallbacks

            )

            comparisons.append(record)

        except (ValueError, KeyError) as exc:

            failures.append({
                "segment_id": segment_id,
                "reason": str(exc),
            })

    changed = [

        record

        for record in comparisons

        if record["changes"]

    ]

    change_types = Counter(

        change

        for record in changed

        for change in record["changes"]

    )

    raw_coverage = interval_difference(

        get_intervals(
            old["disagreement_intervals"]
        ),

        get_intervals(
            new["disagreement_intervals"]
        )

    )

    review_coverage = interval_difference(

        get_intervals(
            old["review_windows"]
        ),

        get_intervals(
            new["review_windows"]
        )

    )

    return {
        "statistics": {
            "disputed_segments": len(old_segments),
            "verified_comparisons": len(comparisons),
            "changed_segments": len(changed),
            "unchanged_segments": (
                len(comparisons) - len(changed)
            ),
            "old_fallbacks": len(old_fallbacks),
            "new_fallbacks": len(new_fallbacks),
            "added_anchors": sum(
                item["added_anchors"]
                for item in comparisons
            ),
            "removed_anchors": sum(
                item["removed_anchors"]
                for item in comparisons
            ),
            "changed_anchor_times": sum(
                item["changed_anchor_times"]
                for item in comparisons
            ),
            "change_types": dict(change_types),
        },
        "changed_segment_ids": [
            item["segment_id"]
            for item in changed
        ],
        "raw_coverage": raw_coverage,
        "review_coverage": review_coverage,
        "segments": comparisons,
        "failures": failures,
    }


# ------------------------------------------------------------
# Reporting
# ------------------------------------------------------------

def print_interval(record):

    print(
        f"  {timestamp(record['start'])} - "
        f"{timestamp(record['end'])}  "
        f"{record['duration']:.3f}s"
    )

    print(
        f"    Decimal seconds: "
        f"{record['start']:.3f} - "
        f"{record['end']:.3f}"
    )


def print_coverage(title, coverage):

    print()
    print(title)
    print("=" * 72)

    for label, key in [

        ("Original coverage", "old_seconds"),
        ("New coverage", "new_seconds"),
        ("Removed coverage", "removed_seconds"),
        ("Added coverage", "added_seconds"),
        ("Net reduction", "net_reduction_seconds"),

    ]:

        print(
            f"{label:32}"
            f"{coverage[key]:10.3f}s"
        )

    print()
    print("Removed intervals:")

    for record in coverage["removed_intervals"]:

        print_interval(record)

    if not coverage["removed_intervals"]:

        print("  None")

    print()
    print("Added intervals:")

    for record in coverage["added_intervals"]:

        print_interval(record)

    if not coverage["added_intervals"]:

        print("  None")


def print_report(result):

    print()
    print("MAGPIE LOCALIZATION DIFFERENTIAL")
    print("=" * 72)

    stats = result["statistics"]

    for key, value in stats.items():

        if key == "change_types":
            continue

        print(
            f"{key.replace('_', ' ').capitalize():40}"
            f"{value:>8}"
        )

    print()
    print("CHANGED SEGMENTS")
    print("=" * 72)

    for record in result["segments"]:

        if not record["changes"]:
            continue

        print()

        print(
            record["segment_id"],
            timestamp(record["start"]),
            "-",
            timestamp(record["end"])
        )

        print(
            f"  Decimal seconds: "
            f"{record['start']:.3f} - "
            f"{record['end']:.3f}"
        )

        print(
            "  Changes:",
            ", ".join(record["changes"])
        )

        print(
            "  Fallback:",
            record["old_fallback"],
            "->",
            record["new_fallback"]
        )

        print(
            "  Anchors:",
            record["old_anchor_count"],
            "->",
            record["new_anchor_count"]
        )

        print(
            "  Regions:",
            record["old_region_count"],
            "->",
            record["new_region_count"]
        )

        print(
            "  Anchor additions:",
            record["added_anchors"]
        )

        print(
            "  Anchor removals:",
            record["removed_anchors"]
        )

        print(
            "  Changed anchor timings:",
            record["changed_anchor_times"]
        )

        print(
            "  Removed region signatures:",
            record["removed_region_signatures"]
        )

        print(
            "  Added region signatures:",
            record["added_region_signatures"]
        )

        print(
            f"  Raw coverage reduction: "
            f"{record['coverage']['net_reduction_seconds']:.3f}s"
        )

    print_coverage(
        "RAW DISAGREEMENT COVERAGE",
        result["raw_coverage"]
    )

    print_coverage(
        "CONTEXTUAL REVIEW COVERAGE",
        result["review_coverage"]
    )

    print()
    print("LEXICAL CONSERVATION FAILURES")
    print("=" * 72)

    for failure in result["failures"]:

        print(
            failure["segment_id"],
            failure["reason"]
        )

    if not result["failures"]:

        print("None")

    print()
    print("EXPERIMENT SUMMARY")
    print("=" * 72)

    print(
        "Disputed segment identity: PASS"
    )

    print(
        "Localized evidence conservation:",
        "PASS" if not result["failures"]
        else "FAIL"
    )

    print(
        "Changes confined to T0116:",
        "YES"
        if result["changed_segment_ids"] == ["T0116"]
        else "NO"
    )


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description="MAGPIE localization differential audit"
    )

    parser.add_argument(
        "original",
        type=Path
    )

    parser.add_argument(
        "updated",
        type=Path
    )

    parser.add_argument(
        "recognition",
        type=Path
    )

    parser.add_argument(
        "--json",
        type=Path,
        required=True
    )

    args = parser.parse_args()

    if args.json.exists():

        parser.error(
            "Output file already exists"
        )

    input_paths = [

        args.original,
        args.updated,
        args.recognition,

    ]

    if args.json.resolve() in {

        path.resolve()
        for path in input_paths

    }:

        parser.error(
            "Output must differ from inputs"
        )

    old, old_hash = read_input(
        args.original
    )

    new, new_hash = read_input(
        args.updated
    )

    source, source_hash = read_input(
        args.recognition
    )

    for report in (old, new):

        if report.get("schema") != (
            "hehawk.magpie.localization"
        ):

            parser.error(
                "Unexpected localization schema"
            )

        if report.get("version") != 1:

            parser.error(
                "Unsupported localization version"
            )

        if report["source_sha256"] != (
            source["source_sha256"]
        ):

            parser.error(
                "Audio source identity mismatch"
            )

        if report["input"]["sha256"] != source_hash:

            parser.error(
                "Recognition evidence hash mismatch"
            )

        if report.get("timestamp_basis") != "episode":

            parser.error(
                "Unexpected localization timestamp basis"
            )

    if source.get("schema") != (
        "hehawk.magpie.accumulation"
    ):

        parser.error(
            "Unexpected recognition schema"
        )

    if source.get("version") != 1:

        parser.error(
            "Unsupported recognition version"
        )

    if old["settings"] != new["settings"]:

        parser.error(
            "Localization settings differ"
        )

    if old_hash == new_hash:

        parser.error(
            "Localization reports are identical"
        )

    print("Recognition provenance: PASS")
    print("Localization settings: PASS")

    result = audit(
        old,
        new,
        source
    )

    for path, expected_hash in zip(

        input_paths,

        [old_hash, new_hash, source_hash]

    ):

        actual_hash = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        if actual_hash != expected_hash:

            raise RuntimeError(
                f"Input changed: {path}"
            )

    print_report(result)

    report = {
        "schema": "hehawk.magpie.localization_diff",
        "version": 1,
        "timestamp_basis": "episode",
        "source_sha256": source["source_sha256"],
        "inputs": {
            "original": {
                "path": str(args.original),
                "sha256": old_hash,
            },
            "updated": {
                "path": str(args.updated),
                "sha256": new_hash,
            },
            "recognition": {
                "path": str(args.recognition),
                "sha256": source_hash,
            },
        },
        "settings": {
            "timing_epsilon_seconds": EPSILON,
            "automatic_acceptance": False,
            "localization_settings": old["settings"],
        },
        "results": result,
        "integrity": {
            "inputs_unchanged": True,
            "recognition_provenance_verified": True,
            "localization_settings_identical": True,
            "production_code_modified": False,
        },
        "limitations": {
            "acoustic_accuracy_verified": False,
            "actual_human_review_time_measured": False,
            "fallback_word_conservation_verified": False,
            "region_order_independently_verified": False,
            "all_recognition_omissions_detected": False,
        },
    }

    with args.json.open(
        "x",
        encoding="utf-8"
    ) as handle:

        json.dump(
            report,
            handle,
            indent=2,
            ensure_ascii=False
        )

        handle.write("\n")

    print()
    print("Original inputs unchanged: PASS")
    print("Production code modified: NO")
    print("Recognition rerun: NO")
    print("LARK rerun: NO")
    print()
    print("Report written to:", args.json)

    return 1 if result["failures"] else 0


if __name__ == "__main__":

    raise SystemExit(main())
