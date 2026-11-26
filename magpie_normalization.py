import argparse
import hashlib
import json
import re
import unicodedata

from collections import Counter
from itertools import combinations
from pathlib import Path

from compare import tokenize, normalize_word
from magpie import recognition_words


# ------------------------------------------------------------
# Normalization strategies
# ------------------------------------------------------------

APOSTROPHES = "'’‘"

STRATEGIES = {
    "A": "Current normalization",
    "B": "Punctuation separators",
    "C": "Apostrophe removal",
    "D": "Apostrophe boundary repair",
}


def normalize(text, strategy):

    if strategy == "A":
        return [
            normalize_word(word)
            for word in tokenize(text)
        ]

    text = text.casefold()

    if strategy == "D":
        text = re.sub(
            r"(?<=[^\W_])\s+(['’‘])(?=[^\W_])",
            r"\1",
            text
        )

    result = []

    for ch in text:

        if ch in APOSTROPHES:

            if strategy == "B":
                result.append(" ")

            continue

        if unicodedata.category(ch).startswith("P"):
            result.append(" ")
        else:
            result.append(ch)

    return "".join(result).split()


# ------------------------------------------------------------
# Synthetic regression cases
# ------------------------------------------------------------

TEST_CASES = [

    # Expected equivalences

    ("Case",
     "Hello", "HELLO", True),

    ("Terminal punctuation",
     "Hello!", "Hello.", True),

    ("Comma separation",
     "Hello,goodbye", "Hello goodbye", True),

    ("Contraction punctuation",
     "Don't", "Dont", True),

    ("Curly apostrophe",
     "Don't", "Don’t", True),

    ("Separated apostrophe",
     "Don't", "Don 't", True),

    ("Possessive",
     "Wesley's", "Wesleys", True),

    ("Hyphenated name",
     "Jean-Luc", "Jean Luc", True),

    ("Quotation marks",
     '"Hello," she said.',
     "Hello she said", True),

    ("Fictional terminology",
     "Lurite-demon", "Lurite demon", True),

    ("Ellipsis",
     "Wait...what?", "Wait what", True),

    # Expected distinctions

    ("Negation",
     "Can't go", "Can go", False),

    ("Missing word",
     "I can go", "I can", False),

    ("Different word",
     "Angel", "Angle", False),

    ("Repeated dialogue",
     "No no", "No", False),

    ("Contraction collision",
     "We'll", "Well", False),

    ("Contraction collision",
     "He'll", "Hell", False),

    ("Contraction collision",
     "We're", "Were", False),

    ("Possessive collision",
     "It's", "Its", False),

    ("Decimal collision",
     "3.14", "3 14", False),

    ("Hyphen collision",
     "Re-sign", "Resign", False),

    ("Quotation boundary",
     "Say 'hello'", "Sayhello", False),

    ("Number separator",
     "1,000", "1 000", False),

    ("Meaningful apostrophe",
     "I'd", "Id", False),
]


def synthetic_tests():

    results = {}

    print()
    print("=" * 72)
    print("SYNTHETIC REGRESSION TESTS")
    print("=" * 72)

    print(
        f"{'Test':30}"
        f"{'A':>9}"
        f"{'B':>9}"
        f"{'C':>9}"
        f"{'D':>9}"
    )

    for strategy in STRATEGIES:
        results[strategy] = Counter()

    for name, left, right, expected in TEST_CASES:

        row = f"{name:30}"

        for strategy in STRATEGIES:

            equivalent = (
                normalize(left, strategy)
                == normalize(right, strategy)
            )

            if equivalent == expected:
                status = "PASS"
                results[strategy]["passed"] += 1

            elif equivalent:
                status = "MERGE"
                results[strategy]["false_equivalence"] += 1

            else:
                status = "SPLIT"
                results[strategy]["false_difference"] += 1

            row += f"{status:>9}"

        print(row)

    return results


# ------------------------------------------------------------
# Timing evidence
# ------------------------------------------------------------

def timing_fingerprint(data):

    evidence = []

    for segment in data["segments"]:

        for obs in segment["observations"]:

            evidence.append({
                "segment_id": segment["id"],
                "pass_id": obs["pass_id"],
                "tokens": obs["tokens"],
                "timestamps": obs["timestamps"],
                "durations": obs["durations"],
            })

    encoded = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":")
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


# ------------------------------------------------------------
# Actual recognition evidence
# ------------------------------------------------------------

def evaluate(data):

    results = {
        strategy: Counter()
        for strategy in STRATEGIES
    }

    details = {
        strategy: {
            "reconstruction_mismatches": [],
            "disputed_segments": [],
            "collapsed_control_pairs": [],
            "new_disagreement_pairs": [],
        }
        for strategy in STRATEGIES
    }

    grouped_mismatches = []

    segment_count = 0
    observation_count = 0

    for segment in data["segments"]:

        segment_count += 1
        segment_id = segment["id"]

        normalized = {
            strategy: {}
            for strategy in STRATEGIES
        }

        for obs in segment["observations"]:

            observation_count += 1

            pass_id = obs["pass_id"]
            decoded = obs["text"]
            raw = "".join(obs["tokens"])

            # Check the actual production reconstruction.

            grouped = recognition_words({
                "tokens": obs["tokens"],
                "timestamps": obs["timestamps"],
                "durations": obs["durations"],
                "source_offset_seconds": 0,
            })

            grouped_words = [
                word["normalized"]
                for word in grouped
            ]

            if grouped_words != normalize(decoded, "A"):

                grouped_mismatches.append({
                    "segment_id": segment_id,
                    "pass_id": pass_id,
                })

            # Compare identical normalization policies
            # on decoded text and concatenated raw tokens.

            for strategy in STRATEGIES:

                stats = results[strategy]

                text_words = normalize(
                    decoded, strategy
                )

                token_words = normalize(
                    raw, strategy
                )

                normalized[strategy][pass_id] = text_words

                stats["observations"] += 1
                stats["text_units"] += len(text_words)
                stats["token_units"] += len(token_words)

                if text_words == token_words:
                    stats["reconstruction_matches"] += 1

                else:
                    stats["reconstruction_mismatches"] += 1

                    details[strategy][
                        "reconstruction_mismatches"
                    ].append({
                        "segment_id": segment_id,
                        "pass_id": pass_id,
                        "text_units": len(text_words),
                        "token_units": len(token_words),
                    })

        # Evaluate cross-pass agreement.

        pass_ids = list(normalized["A"])

        for strategy in STRATEGIES:

            stats = results[strategy]
            observations = normalized[strategy]

            distinct = {
                tuple(words)
                for words in observations.values()
            }

            stats["segments"] += 1
            stats["distinct_hypotheses"] += len(distinct)

            if len(distinct) == 1:

                if next(iter(distinct)):
                    stats["unanimous_lexical"] += 1
                else:
                    stats["all_empty"] += 1

            else:

                stats["disputed_segments"] += 1

                details[strategy][
                    "disputed_segments"
                ].append(segment_id)

            # Every pair of recognition passes.

            for left, right in combinations(pass_ids, 2):

                control_equal = (
                    normalized["A"][left]
                    == normalized["A"][right]
                )

                current_equal = (
                    observations[left]
                    == observations[right]
                )

                stats["pass_pairs"] += 1

                if current_equal:
                    stats["agreeing_pairs"] += 1
                else:
                    stats["disagreeing_pairs"] += 1

                record = {
                    "segment_id": segment_id,
                    "pass_a": left,
                    "pass_b": right,
                }

                if not control_equal and current_equal:

                    stats["collapsed_control_pairs"] += 1

                    details[strategy][
                        "collapsed_control_pairs"
                    ].append(record)

                elif control_equal and not current_equal:

                    stats["new_disagreement_pairs"] += 1

                    details[strategy][
                        "new_disagreement_pairs"
                    ].append(record)

    return {
        "segments": segment_count,
        "observations": observation_count,
        "production_grouped_mismatches": grouped_mismatches,
        "strategies": results,
        "details": details,
    }


# ------------------------------------------------------------
# Reporting
# ------------------------------------------------------------

def print_table(results, rows):

    print(
        f"{'Metric':36}"
        f"{'A':>9}"
        f"{'B':>9}"
        f"{'C':>9}"
        f"{'D':>9}"
    )

    print("-" * 72)

    for label, key in rows:

        row = f"{label:36}"

        for strategy in STRATEGIES:
            row += f"{results[strategy][key]:>9}"

        print(row)


def print_report(evaluation, synthetic):

    print()
    print("=" * 72)
    print("ACTUAL RECOGNITION EVIDENCE")
    print("=" * 72)

    print("Segments:", evaluation["segments"])
    print("Observations:", evaluation["observations"])

    print()
    print("Production word-grouping mismatches:",
          len(evaluation["production_grouped_mismatches"]))

    for item in evaluation["production_grouped_mismatches"]:

        print(
            " ",
            item["segment_id"],
            item["pass_id"]
        )

    print()
    print_table(
        evaluation["strategies"],
        [
            ("Decoded lexical units", "text_units"),
            ("Raw token lexical units", "token_units"),
            ("Reconstruction matches", "reconstruction_matches"),
            ("Reconstruction mismatches", "reconstruction_mismatches"),
            ("Unanimous lexical segments", "unanimous_lexical"),
            ("All-empty segments", "all_empty"),
            ("Disputed segments", "disputed_segments"),
            ("Distinct hypotheses", "distinct_hypotheses"),
            ("Agreeing pass pairs", "agreeing_pairs"),
            ("Disagreeing pass pairs", "disagreeing_pairs"),
            ("Collapsed control pairs", "collapsed_control_pairs"),
            ("New disagreement pairs", "new_disagreement_pairs"),
        ]
    )

    print()
    print("=" * 72)
    print("SYNTHETIC TEST SUMMARY")
    print("=" * 72)

    print_table(
        synthetic,
        [
            ("Passed", "passed"),
            ("False equivalences", "false_equivalence"),
            ("False differences", "false_difference"),
        ]
    )

    print()
    print("=" * 72)
    print("REMAINING RECONSTRUCTION MISMATCHES")
    print("=" * 72)

    for strategy in STRATEGIES:

        mismatches = evaluation["details"][strategy][
            "reconstruction_mismatches"
        ]

        print()
        print(
            strategy,
            "-",
            STRATEGIES[strategy],
            f"({len(mismatches)} mismatches)"
        )

        for item in mismatches[:20]:

            print(
                f"  {item['segment_id']} "
                f"{item['pass_id']}: "
                f"text={item['text_units']} "
                f"tokens={item['token_units']}"
            )

        if len(mismatches) > 20:
            print("  Additional entries in JSON report.")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description="MAGPIE lexical normalization experiment"
    )

    parser.add_argument(
        "input",
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

    if args.input.resolve() == args.json.resolve():
        parser.error("Input and output must be different.")

    raw = args.input.read_bytes()
    input_hash = hashlib.sha256(raw).hexdigest()

    data = json.loads(raw)

    if data.get("schema") != "hehawk.magpie.accumulation":
        parser.error("Unexpected input schema.")

    before = timing_fingerprint(data)

    print("MAGPIE NORMALIZATION EXPERIMENT")
    print("=" * 72)

    for strategy, description in STRATEGIES.items():
        print(strategy, "-", description)

    synthetic = synthetic_tests()
    evaluation = evaluate(data)

    after = timing_fingerprint(data)

    if before != after:
        raise RuntimeError("Timing evidence was modified.")

    if hashlib.sha256(
        args.input.read_bytes()
    ).hexdigest() != input_hash:

        raise RuntimeError("Input file changed during experiment.")

    print_report(evaluation, synthetic)

    report = {
        "schema": "hehawk.magpie.normalization",
        "version": 1,
        "input": {
            "path": str(args.input),
            "sha256": input_hash,
        },
        "strategies": STRATEGIES,
        "synthetic_results": synthetic,
        "evaluation": evaluation,
        "integrity": {
            "input_unchanged": True,
            "timing_evidence_unchanged": True,
            "timing_evidence_sha256": before,
        },
        "limitations": {
            "human_verified": False,
            "agreement_is_accuracy": False,
            "normalized_timing_generated": False,
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
    print("INTEGRITY CHECKS")
    print("=" * 72)
    print("Original input unchanged: PASS")
    print("Original timing evidence unchanged: PASS")
    print("Production code modified: NO")
    print("Recognition rerun: NO")
    print()
    print("Report written to:", args.json)


if __name__ == "__main__":
    main()
