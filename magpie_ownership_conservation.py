
import argparse
import hashlib
import json

from collections import Counter, defaultdict
from pathlib import Path

from magpie import recognition_words
from magpie_decoder_reconstruct import reconstruct

from magpie_timing_ownership_audit import (
    merge_intervals,
    subtract_intervals,
    word_intervals,
    token_record,
    timestamp,
)


EPSILON = 0.000001

DASHES = "-\u2010\u2011\u2012\u2013\u2014\u2212"


# ------------------------------------------------------------
# Input handling
# ------------------------------------------------------------

def read_input(path):

    raw = path.read_bytes()

    return (
        json.loads(raw),
        hashlib.sha256(raw).hexdigest()
    )


# ------------------------------------------------------------
# Ownership maps
# ------------------------------------------------------------

def old_ownership(words):

    owners = defaultdict(set)

    for index, word in enumerate(words):

        for token_index in range(
            word["token_start"],
            word["token_end"]
        ):

            owners[token_index].add(index)

    return owners


def new_ownership(words):

    owners = defaultdict(set)

    for index, word in enumerate(words):

        for token_index in word["token_indices"]:

            owners[token_index].add(index)

    return owners


def lexical_token_indices(tokens):

    return {

        index

        for index, token in enumerate(tokens)

        if any(ch.isalnum() for ch in token)

    }


def character_count(text):

    return sum(
        len(ch.casefold())
        for ch in text
        if ch.isalnum()
    )


# ------------------------------------------------------------
# Punctuation classification
# ------------------------------------------------------------

def boundary_type(tokens):

    text = "".join(tokens)

    if not text:
        return "no_intervening_token"

    if any(ch.isalnum() for ch in text):
        return "contains_lexical_characters"

    if any(ch in DASHES for ch in text):
        return "dash_boundary"

    if text.isspace():
        return "whitespace_boundary"

    return "other_nonlexical_boundary"


# ------------------------------------------------------------
# Gap inspection
# ------------------------------------------------------------

def inspect_gap(
    start,
    end,
    segment,
    obs,
    words
):

    offset = segment["start"]

    left_candidates = [

        (index, word)

        for index, word in enumerate(words)

        if offset + word["end"]
        <= start + EPSILON

    ]

    right_candidates = [

        (index, word)

        for index, word in enumerate(words)

        if offset + word["start"]
        >= end - EPSILON

    ]

    if not left_candidates or not right_candidates:

        return {
            "classification": "unbounded_gap",
            "left_word_index": None,
            "right_word_index": None,
            "intervening_tokens": [],
        }

    left_index, left = max(
        left_candidates,
        key=lambda item: item[1]["end"]
    )

    right_index, right = min(
        right_candidates,
        key=lambda item: item[1]["start"]
    )

    first = max(left["token_indices"]) + 1
    last = min(right["token_indices"])

    indices = list(range(first, last))

    classification = boundary_type([

        obs["tokens"][index]

        for index in indices

    ])

    return {
        "classification": classification,
        "left_word_index": left_index,
        "right_word_index": right_index,
        "adjacent_words": (
            right_index == left_index + 1
        ),
        "left_word_end": offset + left["end"],
        "right_word_start": offset + right["start"],
        "intervening_tokens": [

            token_record(obs, index, offset)

            for index in indices

        ],
    }


# ------------------------------------------------------------
# Audit one recognition observation
# ------------------------------------------------------------

def audit_observation(
    segment,
    obs,
    episode_end
):

    tokens = obs["tokens"]

    old = recognition_words({
        "tokens": tokens,
        "timestamps": obs["timestamps"],
        "durations": obs["durations"],
        "source_offset_seconds": 0,
    })

    result = reconstruct(
        obs["text"],
        tokens,
        obs["timestamps"],
        obs["durations"]
    )

    new = result["words"]

    old_map = old_ownership(old)
    new_map = new_ownership(new)

    lexical = lexical_token_indices(tokens)

    old_duplicates = [

        index

        for index in sorted(lexical)

        if len(old_map[index]) > 1

    ]

    new_duplicates = [

        index

        for index in sorted(lexical)

        if len(new_map[index]) > 1

    ]

    unowned = [

        index

        for index in sorted(lexical)

        if not new_map[index]

    ]

    nonlexical_owners = [

        index

        for index, owners in new_map.items()

        if owners and index not in lexical

    ]

    expected_characters = sum(
        character_count(token)
        for token in tokens
    )

    reconstructed_characters = sum(
        word["character_count"]
        for word in new
    )

    decoded_characters = character_count(
        obs["text"]
    )

    characters_conserved = (

        expected_characters

        == reconstructed_characters

        == decoded_characters

    )

    comparable = (

        [w["normalized"] for w in old]

        ==

        [w["normalized"] for w in new]

    )

    removed = []

    if comparable:

        for token_index in sorted(lexical):

            excluded_owners = (

                old_map[token_index]
                - new_map[token_index]

            )

            for owner in sorted(excluded_owners):

                removed.append({
                    "token_index": token_index,
                    "old_word_index": owner,
                    "remaining_word_indices": sorted(
                        new_map[token_index]
                    ),
                    "conserved": bool(
                        new_map[token_index]
                    ),
                    "token": token_record(
                        obs,
                        token_index,
                        segment["start"]
                    ),
                })

    old_intervals = word_intervals(
        old,
        segment["start"],
        episode_end
    )

    new_intervals = word_intervals(
        new,
        segment["start"],
        episode_end
    )

    released = subtract_intervals(
        old_intervals,
        new_intervals
    )

    added = subtract_intervals(
        new_intervals,
        old_intervals
    )

    gaps = []

    for start, end in released:

        details = inspect_gap(
            start,
            end,
            segment,
            obs,
            new
        )

        gaps.append({
            "segment_id": segment["id"],
            "pass_id": obs["pass_id"],
            "start": start,
            "end": end,
            "duration": end - start,
            **details,
        })

    return {
        "segment_id": segment["id"],
        "pass_id": obs["pass_id"],
        "comparable": comparable,
        "lexical_tokens": len(lexical),
        "expected_characters": expected_characters,
        "reconstructed_characters": reconstructed_characters,
        "decoded_characters": decoded_characters,
        "characters_conserved": characters_conserved,
        "old_duplicate_tokens": old_duplicates,
        "new_shared_tokens": new_duplicates,
        "unowned_lexical_tokens": unowned,
        "nonlexical_owned_tokens": nonlexical_owners,
        "removed_lexical_associations": removed,
        "old_intervals": old_intervals,
        "new_intervals": new_intervals,
        "released_intervals": gaps,
        "added_intervals": added,
    }


# ------------------------------------------------------------
# Interval intersection
# ------------------------------------------------------------

def intersect_intervals(a, b):

    result = []

    for start_a, end_a in merge_intervals(a):

        for start_b, end_b in merge_intervals(b):

            start = max(start_a, start_b)
            end = min(end_a, end_b)

            if end - start > EPSILON:

                result.append([start, end])

    return merge_intervals(result)


def duration(intervals):

    return sum(
        end - start
        for start, end in intervals
    )


# ------------------------------------------------------------
# Complete conservation audit
# ------------------------------------------------------------

def audit(data, previous):

    stats = Counter()

    observations = []
    failures = []
    removed = []
    local_gaps = []

    old_coverage = defaultdict(list)
    new_coverage = defaultdict(list)

    episode_end = (

        data["source_samples"]
        / data["sample_rate"]

    )

    for segment in data["segments"]:

        for obs in segment["observations"]:

            record = audit_observation(
                segment,
                obs,
                episode_end
            )

            observations.append(record)

            stats["observations"] += 1

            stats["lexical_tokens"] += (
                record["lexical_tokens"]
            )

            stats["lexical_characters"] += (
                record["expected_characters"]
            )

            stats["old_duplicate_tokens"] += len(
                record["old_duplicate_tokens"]
            )

            stats["new_shared_tokens"] += len(
                record["new_shared_tokens"]
            )

            stats["unowned_lexical_tokens"] += len(
                record["unowned_lexical_tokens"]
            )

            stats["nonlexical_owned_tokens"] += len(
                record["nonlexical_owned_tokens"]
            )

            if record["characters_conserved"]:

                stats["conserved_observations"] += 1

            else:

                failures.append({
                    "segment_id": segment["id"],
                    "pass_id": obs["pass_id"],
                    "reason": "Character count mismatch",
                })

            if record["unowned_lexical_tokens"]:

                failures.append({
                    "segment_id": segment["id"],
                    "pass_id": obs["pass_id"],
                    "reason": "Unowned lexical tokens",
                })

            if record["nonlexical_owned_tokens"]:

                failures.append({
                    "segment_id": segment["id"],
                    "pass_id": obs["pass_id"],
                    "reason": "Nonlexical token ownership",
                })

            if record["old_duplicate_tokens"]:

                stats["old_duplicate_observations"] += 1

            if record["new_shared_tokens"]:

                stats["new_shared_observations"] += 1

            for association in (
                record["removed_lexical_associations"]
            ):

                removed.append({
                    "segment_id": segment["id"],
                    "pass_id": obs["pass_id"],
                    **association,
                })

                stats["removed_associations"] += 1

                if association["conserved"]:

                    stats["reassigned_associations"] += 1

                else:

                    stats["lost_associations"] += 1

            local_gaps.extend(
                record["released_intervals"]
            )

            pass_id = obs["pass_id"]

            old_coverage[pass_id].extend(
                record["old_intervals"]
            )

            new_coverage[pass_id].extend(
                record["new_intervals"]
            )

    # --------------------------------------------------------
    # Verify episode-wide coverage against Experiment 7F.4.
    # --------------------------------------------------------

    coverage_checks = []

    actual_gaps = {}

    for pass_id in old_coverage:

        exposed = subtract_intervals(
            old_coverage[pass_id],
            new_coverage[pass_id]
        )

        added = subtract_intervals(
            new_coverage[pass_id],
            old_coverage[pass_id]
        )

        prior = previous["passes"][pass_id]

        prior_exposed = [

            [gap["start"], gap["end"]]

            for gap in prior["newly_exposed_intervals"]

        ]

        prior_added = prior[
            "newly_covered_intervals"
        ]

        exposed_difference = (

            duration(subtract_intervals(
                exposed, prior_exposed
            ))

            +

            duration(subtract_intervals(
                prior_exposed, exposed
            ))

        )

        added_difference = (

            duration(subtract_intervals(
                added, prior_added
            ))

            +

            duration(subtract_intervals(
                prior_added, added
            ))

        )

        coverage_checks.append({
            "pass_id": pass_id,
            "exposed_difference_seconds": exposed_difference,
            "added_difference_seconds": added_difference,
            "matches_previous": (
                exposed_difference <= EPSILON
                and added_difference <= EPSILON
            ),
        })

        actual_gaps[pass_id] = exposed

    # --------------------------------------------------------
    # Attribute episode-wide gaps to local word boundaries.
    # --------------------------------------------------------

    verified_gaps = []

    for gap in local_gaps:

        overlap = intersect_intervals(

            [[gap["start"], gap["end"]]],

            actual_gaps[gap["pass_id"]]

        )

        for start, end in overlap:

            verified_gaps.append({
                **gap,
                "start": start,
                "end": end,
                "duration": end - start,
            })

    unique_gaps = []

    for start, end in merge_intervals([

        interval

        for intervals in actual_gaps.values()

        for interval in intervals

    ]):

        evidence = [

            gap

            for gap in verified_gaps

            if gap["start"] < end - EPSILON
            and gap["end"] > start + EPSILON

        ]

        dash_coverage = merge_intervals([

            [gap["start"], gap["end"]]

            for gap in evidence

            if gap["classification"] == "dash_boundary"
            and gap.get("adjacent_words", False)

        ])

        unexplained = subtract_intervals(
            [[start, end]],
            dash_coverage
        )

        unique_gaps.append({
            "start": start,
            "end": end,
            "duration": end - start,
            "fully_explained_by_dash_boundaries": (
                duration(unexplained) <= EPSILON
            ),
            "evidence": evidence,
        })

    # --------------------------------------------------------
    # Attribute newly covered audio.
    # --------------------------------------------------------

    added_attribution = []

    for pass_id in old_coverage:

        actual_added = subtract_intervals(
            new_coverage[pass_id],
            old_coverage[pass_id]
        )

        for start, end in actual_added:

            contributors = []

            for record in observations:

                if record["pass_id"] != pass_id:
                    continue

                overlap = intersect_intervals(

                    [[start, end]],

                    record["added_intervals"]

                )

                if overlap:

                    contributors.append({
                        "segment_id": record["segment_id"],
                        "comparable": record["comparable"],
                        "intervals": overlap,
                    })

            t0116_coverage = [

                interval

                for item in contributors

                if item["segment_id"] == "T0116"

                for interval in item["intervals"]

            ]

            remainder = subtract_intervals(
                [[start, end]],
                t0116_coverage
            )

            added_attribution.append({
                "pass_id": pass_id,
                "start": start,
                "end": end,
                "duration": end - start,
                "contributors": contributors,
                "fully_attributed_to_T0116": (
                    duration(remainder) <= EPSILON
                ),
            })

    return {
        "statistics": stats,
        "failures": failures,
        "coverage_checks": coverage_checks,
        "removed_lexical_associations": removed,
        "unique_exposed_gaps": unique_gaps,
        "newly_covered_attribution": added_attribution,
        "observations": observations,
    }


# ------------------------------------------------------------
# Reporting
# ------------------------------------------------------------

def print_report(result):

    stats = result["statistics"]

    print()
    print("=" * 72)
    print("TOKEN OWNERSHIP CONSERVATION")
    print("=" * 72)

    for label, key in [

        ("Observations", "observations"),
        ("Character-conserved observations", "conserved_observations"),
        ("Lexical tokens", "lexical_tokens"),
        ("Lexical characters", "lexical_characters"),
        ("Original duplicate tokens", "old_duplicate_tokens"),
        ("Original duplicate observations", "old_duplicate_observations"),
        ("New shared tokens", "new_shared_tokens"),
        ("New shared observations", "new_shared_observations"),
        ("Unowned lexical tokens", "unowned_lexical_tokens"),
        ("Owned nonlexical tokens", "nonlexical_owned_tokens"),
        ("Removed lexical associations", "removed_associations"),
        ("Reassigned lexical associations", "reassigned_associations"),
        ("Lost lexical associations", "lost_associations"),

    ]:

        print(f"{label:44}{stats[key]:>10}")

    print()
    print("=" * 72)
    print("COVERAGE REPRODUCIBILITY")
    print("=" * 72)

    for check in result["coverage_checks"]:

        status = (

            "PASS"

            if check["matches_previous"]

            else "FAIL"

        )

        print(
            f"{check['pass_id']:12}"
            f"{status}"
        )

    print()
    print("=" * 72)
    print("NEWLY EXPOSED GAP CLASSIFICATION")
    print("=" * 72)

    for gap in result["unique_exposed_gaps"]:

        print()

        print(
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
            f"  Duration: "
            f"{gap['duration']:.3f} s"
        )

        print(
            "  Fully explained by dash boundaries:",
            "YES"
            if gap["fully_explained_by_dash_boundaries"]
            else "NO"
        )

        for evidence in gap["evidence"]:

            print(
                " ",
                evidence["segment_id"],
                evidence["pass_id"],
                evidence["classification"]
            )

            print(
                "    Neighboring word indices:",
                evidence["left_word_index"],
                evidence["right_word_index"]
            )

            for token in evidence["intervening_tokens"]:

                print(
                    "    Token",
                    token["index"],
                    token["category"],
                    repr(token["structure"])
                )

    print()
    print("=" * 72)
    print("NEWLY COVERED AUDIO ATTRIBUTION")
    print("=" * 72)

    for item in result["newly_covered_attribution"]:

        print()

        print(
            item["pass_id"],
            timestamp(item["start"]),
            "-",
            timestamp(item["end"])
        )

        print(
            f"  Decimal seconds: "
            f"{item['start']:.3f} - "
            f"{item['end']:.3f}"
        )

        print(
            f"  Duration: "
            f"{item['duration']:.3f} s"
        )

        print(
            "  Fully attributed to T0116:",
            "YES"
            if item["fully_attributed_to_T0116"]
            else "NO"
        )

        for contributor in item["contributors"]:

            print(
                "  Contributing segment:",
                contributor["segment_id"]
            )

    print()
    print("=" * 72)
    print("CONSERVATION FAILURES")
    print("=" * 72)

    if not result["failures"]:

        print("None")

    else:

        for failure in result["failures"]:

            print(
                failure["segment_id"],
                failure["pass_id"],
                failure["reason"]
            )

    print()
    print("=" * 72)
    print("EXPERIMENT SUMMARY")
    print("=" * 72)

    prior_associations = result[
        "prior_removed_lexical_associations"
    ]

    checks = {

        "Lexical character counts conserved": (
            stats["conserved_observations"]
            == stats["observations"]
        ),

        "Every lexical token has an owner": (
            stats["unowned_lexical_tokens"] == 0
        ),

        "No nonlexical token ownership": (
            stats["nonlexical_owned_tokens"] == 0
        ),

        "Removed lexical associations conserved": (
            stats["lost_associations"] == 0
        ),

        "7F.4 excluded associations reproduced": (
            stats["removed_associations"]
            == prior_associations
        ),

        "Episode coverage reproduced": all(

            check["matches_previous"]

            for check in result["coverage_checks"]

        ),

        "All exposed gaps have dash evidence": all(

            gap["fully_explained_by_dash_boundaries"]

            for gap in result["unique_exposed_gaps"]

        ),

        "Added coverage attributable to T0116": all(

            item["fully_attributed_to_T0116"]

            for item in result["newly_covered_attribution"]

        ),

    }

    for label, passed in checks.items():

        print(
            f"{label:48}"
            f"{'PASS' if passed else 'FAIL'}"
        )

    return checks


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description="MAGPIE token ownership conservation"
    )

    parser.add_argument(
        "recognition",
        type=Path
    )

    parser.add_argument(
        "timing_audit",
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
        args.timing_audit.resolve()

    }:

        parser.error("Output must differ from inputs.")

    data, recognition_hash = read_input(
        args.recognition
    )

    prior, audit_hash = read_input(
        args.timing_audit
    )

    if data.get("schema") != "hehawk.magpie.accumulation":

        parser.error("Unexpected recognition schema.")

    if prior.get("schema") != "hehawk.magpie.timing_ownership":

        parser.error("Unexpected timing audit schema.")

    if data.get("version") != 1:

        parser.error("Unsupported recognition version.")

    if prior.get("version") != 1:

        parser.error("Unsupported timing audit version.")

    if data["source_sha256"] != prior["source_sha256"]:

        parser.error("Source identity mismatch.")

    if recognition_hash != prior["inputs"]["recognition"]["sha256"]:

        parser.error("Recognition evidence hash mismatch.")

    if data.get("observation_timestamp_basis") != "segment_relative":

        parser.error("Unexpected observation timestamp basis.")

    print("MAGPIE TOKEN OWNERSHIP CONSERVATION")
    print("=" * 72)
    print("Recognition provenance: PASS")

    result = audit(
        data,
        prior["results"]
    )

    result["prior_removed_lexical_associations"] = (

        prior["results"]
        ["excluded_token_categories"]
        .get("lexical", 0)

    )

    for path, expected in [

        (args.recognition, recognition_hash),
        (args.timing_audit, audit_hash),

    ]:

        actual = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        if actual != expected:

            raise RuntimeError(
                f"Input changed: {path}"
            )

    checks = print_report(result)

    report = {
        "schema": "hehawk.magpie.ownership_conservation",
        "version": 1,
        "timestamp_basis": "episode",
        "source_sha256": data["source_sha256"],
        "inputs": {
            "recognition": {
                "path": str(args.recognition),
                "sha256": recognition_hash,
            },
            "timing_audit": {
                "path": str(args.timing_audit),
                "sha256": audit_hash,
            },
        },
        "settings": {
            "timing_epsilon_seconds": EPSILON,
            "automatic_acceptance": False,
        },
        "checks": checks,
        "results": result,
        "integrity": {
            "inputs_unchanged": True,
            "recognition_provenance_verified": True,
            "production_code_modified": False,
        },
        "limitations": {
            "character_counts_prove_exact_ownership": False,
            "dash_semantics_verified": False,
            "missing_dialogue_ruled_out": False,
            "acoustic_timing_human_verified": False,
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
