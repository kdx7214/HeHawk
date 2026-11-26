
import argparse
import hashlib
import json
import math
import re

from collections import Counter
from pathlib import Path

from compare import tokenize, normalize_word
from magpie import recognition_words


# ------------------------------------------------------------
# Lexical representation
# ------------------------------------------------------------

WORD_PATTERN = re.compile(
    r"[^\W_]+(?:['’][^\W_]+)*"
)


def lexical_characters(text):

    characters = []
    positions = []

    for index, ch in enumerate(text):

        if not ch.isalnum():
            continue

        for folded in ch.casefold():

            characters.append(folded)
            positions.append(index)

    return "".join(characters), positions


def decoded_words(text):

    words = []

    for match in WORD_PATTERN.finditer(text):

        raw = match.group()

        words.append({
            "word": raw,
            "normalized": normalize_word(raw),
            "character_start": match.start(),
            "character_end": match.end(),
        })

    expected = [
        normalize_word(word)
        for word in tokenize(text)
    ]

    actual = [
        word["normalized"]
        for word in words
    ]

    if actual != expected:
        raise ValueError(
            "Decoded word pattern differs from compare.tokenize."
        )

    return words


# ------------------------------------------------------------
# Raw token ownership
# ------------------------------------------------------------

def token_character_stream(tokens):

    characters = []
    owners = []

    for token_index, token in enumerate(tokens):

        stream, positions = lexical_characters(token)

        characters.extend(stream)

        owners.extend(
            (token_index, position)
            for position in positions
        )

    return "".join(characters), owners


def validate_timing(tokens, timestamps, durations):

    if not (
        len(tokens)
        == len(timestamps)
        == len(durations)
    ):
        raise ValueError(
            "Token and timing array lengths differ."
        )

    for start, duration in zip(timestamps, durations):

        if not math.isfinite(start):
            raise ValueError("Nonfinite timestamp.")

        if not math.isfinite(duration):
            raise ValueError("Nonfinite duration.")

        if start < 0 or duration < 0:
            raise ValueError("Negative timing value.")


# ------------------------------------------------------------
# Decoder-aware reconstruction
# ------------------------------------------------------------

def reconstruct(text, tokens, timestamps, durations):

    validate_timing(
        tokens,
        timestamps,
        durations
    )

    decoded_stream, decoded_positions = (
        lexical_characters(text)
    )

    token_stream, token_owners = (
        token_character_stream(tokens)
    )

    if decoded_stream != token_stream:

        raise ValueError(
            "Lexical character streams differ."
        )

    words = decoded_words(text)

    reconstructed = []
    consumed = 0

    for word in words:

        character_start = word["character_start"]
        character_end = word["character_end"]

        first = consumed

        while consumed < len(decoded_positions):

            position = decoded_positions[consumed]

            if position >= character_end:
                break

            if position < character_start:

                raise ValueError(
                    "Unaccounted decoded lexical character."
                )

            consumed += 1

        last = consumed

        if first == last:

            raise ValueError(
                "Decoded word has no lexical characters."
            )

        owners = token_owners[first:last]

        token_indices = sorted({
            token_index
            for token_index, position in owners
        })

        start = min(
            timestamps[index]
            for index in token_indices
        )

        end = max(
            timestamps[index] + durations[index]
            for index in token_indices
        )

        reconstructed.append({
            **word,
            "start": start,
            "end": end,
            "token_start": token_indices[0],
            "token_end": token_indices[-1] + 1,
            "token_indices": token_indices,
            "character_count": last - first,
            "character_owners": owners,
        })

    if consumed != len(decoded_stream):

        raise ValueError(
            "Not all lexical characters were consumed."
        )

    # A token may contain characters belonging to
    # more than one decoded word. Preserve that fact.

    token_usage = Counter()

    for word in reconstructed:

        token_usage.update(word["token_indices"])

    shared_tokens = sorted(
        index
        for index, count in token_usage.items()
        if count > 1
    )

    for word in reconstructed:

        word["shared_timing"] = any(
            token_usage[index] > 1
            for index in word["token_indices"]
        )

    return {
        "words": reconstructed,
        "lexical_characters": consumed,
        "shared_tokens": shared_tokens,
    }


# ------------------------------------------------------------
# Synthetic reconstruction tests
# ------------------------------------------------------------

TEST_CASES = [

    (
        "Ordinary words",
        "Hello world",
        [" Hello", " world"],
        True,
        2,
    ),

    (
        "Contraction",
        "Don't",
        [" Don", "'", "t"],
        True,
        1,
    ),

    (
        "Space before apostrophe",
        "Don't",
        [" Don", " ", "'", "t"],
        True,
        1,
    ),

    (
        "Space after apostrophe",
        "Don't",
        [" Don", "'", " ", "t"],
        True,
        1,
    ),

    (
        "Spaces around apostrophe",
        "Don't",
        [" Don", " ", "'", " ", "t"],
        True,
        1,
    ),

    (
        "Missing apostrophe",
        "Don't",
        [" Dont"],
        True,
        1,
    ),

    (
        "Curly apostrophe",
        "Don’t",
        [" Don", "'", "t"],
        True,
        1,
    ),

    (
        "Possessive",
        "Wesley's",
        [" Wesley", " ", "'", "s"],
        True,
        1,
    ),

    (
        "E'Hawke",
        "E'Hawke",
        [" E", " ", "'", "Hawke"],
        True,
        1,
    ),

    (
        "D'Hai",
        "D'Hai",
        [" D", "'", " Hai"],
        True,
        1,
    ),

    (
        "Taelon name",
        "Da'an",
        [" Da", " an"],
        True,
        1,
    ),

    (
        "Taelon name without apostrophe",
        "Zo'or",
        [" Zoor"],
        True,
        1,
    ),

    (
        "Single-character fragment",
        "T'than",
        [" T", " ", "'", "than"],
        True,
        1,
    ),

    (
        "Multiple apostrophes",
        "Ka'ra'than",
        [" Ka", " '", "ra", " '", "than"],
        True,
        1,
    ),

    (
        "Hyphenated name",
        "Jean-Luc",
        [" Jean", "-", "Luc"],
        True,
        2,
    ),

    (
        "Quoted dialogue",
        "Say 'hello'",
        [" Say", " '", "hello", "'"],
        True,
        2,
    ),

    (
        "One token containing two words",
        "Hello world",
        [" Hello world"],
        True,
        2,
    ),

    (
        "Punctuation-only input",
        "...",
        [".", ".", "."],
        True,
        0,
    ),

    (
        "Empty recognition",
        "",
        [],
        True,
        0,
    ),

    (
        "Casefold expansion",
        "Straße",
        [" STRASSE"],
        True,
        1,
    ),

    (
        "Missing lexical character",
        "D'Hai",
        [" D", "'", "Ha"],
        False,
        None,
    ),

    (
        "Additional lexical character",
        "Da'an",
        [" Daanx"],
        False,
        None,
    ),

    (
        "Different name",
        "Da'an",
        [" Zoor"],
        False,
        None,
    ),

    (
        "Missing dialogue",
        "I can go",
        [" I", " can"],
        False,
        None,
    ),

    (
        "Repeated dialogue",
        "No no",
        [" No"],
        False,
        None,
    ),

    (
        "Meaningful negation",
        "Can't",
        [" Can"],
        False,
        None,
    ),

    # These deliberately demonstrate ambiguity.
    # Equal character streams alone do not prove
    # that the decoded interpretation is correct.

    (
        "Ambiguous contraction",
        "We'll",
        [" Well"],
        True,
        1,
    ),

    (
        "Ambiguous word boundary",
        "Now here",
        [" Nowhere"],
        True,
        2,
    ),
]


def run_synthetic_tests():

    results = []

    print()
    print("=" * 72)
    print("SYNTHETIC RECONSTRUCTION TESTS")
    print("=" * 72)

    for (
        name,
        text,
        tokens,
        expected_success,
        expected_words
    ) in TEST_CASES:

        timestamps = [
            index * 0.100
            for index in range(len(tokens))
        ]

        durations = [
            0.080
            for token in tokens
        ]

        try:

            result = reconstruct(
                text,
                tokens,
                timestamps,
                durations
            )

            success = True
            word_count = len(result["words"])

        except ValueError:

            success = False
            word_count = None

        passed = (
            success == expected_success
            and word_count == expected_words
        )

        results.append({
            "name": name,
            "passed": passed,
            "reconstruction_succeeded": success,
            "word_count": word_count,
        })

        print(
            f"{name:48}"
            f"{'PASS' if passed else 'FAIL':>8}"
        )

    return results


# ------------------------------------------------------------
# Timing comparison
# ------------------------------------------------------------

def compare_timing(old_words, new_words):

    old_normalized = [
        word["normalized"]
        for word in old_words
    ]

    new_normalized = [
        word["normalized"]
        for word in new_words
    ]

    if old_normalized != new_normalized:
        return None

    start_deltas = []
    end_deltas = []

    for old, new in zip(old_words, new_words):

        start_deltas.append(
            abs(old["start"] - new["start"])
        )

        end_deltas.append(
            abs(old["end"] - new["end"])
        )

    return start_deltas, end_deltas


def distribution(values):

    if not values:

        return {
            "count": 0,
            "mean": None,
            "maximum": None,
        }

    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "maximum": max(values),
    }


def timestamp(seconds):

    milliseconds = round(seconds * 1000)

    hours, remainder = divmod(
        milliseconds, 3600000
    )

    minutes, remainder = divmod(
        remainder, 60000
    )

    seconds, milliseconds = divmod(
        remainder, 1000
    )

    return (
        f"{hours:02d}:{minutes:02d}:"
        f"{seconds:02d}.{milliseconds:03d}"
    )


# ------------------------------------------------------------
# Episode evaluation
# ------------------------------------------------------------

def evaluate(data):

    stats = Counter()

    failures = []
    recovered = []
    shared_timing = []
    timing_changes = []

    start_deltas = []
    end_deltas = []

    for segment in data["segments"]:

        stats["segments"] += 1

        segment_id = segment["id"]
        segment_offset = segment["start"]

        control_hypotheses = {}
        reconstructed_hypotheses = {}

        for obs in segment["observations"]:

            stats["observations"] += 1

            pass_id = obs["pass_id"]

            record = {
                "segment_id": segment_id,
                "pass_id": pass_id,
            }

            text = obs["text"]
            tokens = obs["tokens"]
            timestamps = obs["timestamps"]
            durations = obs["durations"]

            expected = [
                normalize_word(word)
                for word in tokenize(text)
            ]

            control_hypotheses[pass_id] = tuple(
                expected
            )

            stats["expected_words"] += len(expected)

            old_words = recognition_words({
                "tokens": tokens,
                "timestamps": timestamps,
                "durations": durations,
                "source_offset_seconds": 0,
            })

            old_normalized = [
                word["normalized"]
                for word in old_words
            ]

            old_matches = old_normalized == expected

            if not old_matches:
                stats["old_mismatches"] += 1

            try:

                result = reconstruct(
                    text,
                    tokens,
                    timestamps,
                    durations
                )

            except ValueError as exc:

                stats["reconstruction_failures"] += 1

                failures.append({
                    **record,
                    "reason": str(exc),
                })

                continue

            words = result["words"]

            actual = [
                word["normalized"]
                for word in words
            ]

            reconstructed_hypotheses[pass_id] = tuple(
                actual
            )

            stats["reconstruction_successes"] += 1
            stats["reconstructed_words"] += len(words)

            stats["lexical_characters"] += (
                result["lexical_characters"]
            )

            if actual != expected:

                stats["lexical_sequence_changes"] += 1

            if result["shared_tokens"]:

                stats["shared_timing_observations"] += 1

                stats["shared_tokens"] += len(
                    result["shared_tokens"]
                )

                shared_timing.append({
                    **record,
                    "token_indices": result["shared_tokens"],
                })

            if not old_matches and actual == expected:

                stats["recovered_observations"] += 1

                recovered.append({
                    **record,
                    "old_word_count": len(old_words),
                    "new_word_count": len(words),
                    "expected_word_count": len(expected),
                })

            comparison = compare_timing(
                old_words,
                words
            )

            if comparison is None:

                stats["timing_comparison_unavailable"] += 1
                continue

            starts, ends = comparison

            start_deltas.extend(starts)
            end_deltas.extend(ends)

            for index, (ds, de) in enumerate(
                zip(starts, ends)
            ):

                stats["timing_words_compared"] += 1

                if ds > 0.000001 or de > 0.000001:

                    stats["timing_words_changed"] += 1

                    timing_changes.append({
                        **record,
                        "word_index": index,
                        "old_start": (
                            old_words[index]["start"]
                            + segment_offset
                        ),
                        "old_end": (
                            old_words[index]["end"]
                            + segment_offset
                        ),
                        "new_start": (
                            words[index]["start"]
                            + segment_offset
                        ),
                        "new_end": (
                            words[index]["end"]
                            + segment_offset
                        ),
                        "absolute_start_delta": ds,
                        "absolute_end_delta": de,
                    })

        if (
            control_hypotheses.keys()
            == reconstructed_hypotheses.keys()
        ):

            stats["complete_segments"] += 1

            old_count = len(
                set(control_hypotheses.values())
            )

            new_count = len(
                set(reconstructed_hypotheses.values())
            )

            if old_count != new_count:

                stats["changed_hypothesis_counts"] += 1

    timing_changes.sort(
        key=lambda item: max(
            item["absolute_start_delta"],
            item["absolute_end_delta"]
        ),
        reverse=True
    )

    return {
        "statistics": stats,
        "failures": failures,
        "recovered": recovered,
        "shared_timing": shared_timing,
        "timing_changes": timing_changes,
        "start_delta_seconds": distribution(
            start_deltas
        ),
        "end_delta_seconds": distribution(
            end_deltas
        ),
    }


# ------------------------------------------------------------
# Reporting
# ------------------------------------------------------------

def print_report(evaluation, synthetic):

    stats = evaluation["statistics"]

    print()
    print("=" * 72)
    print("RECONSTRUCTION RESULTS")
    print("=" * 72)

    rows = [

        ("Segments", "segments"),

        ("Observations", "observations"),

        ("Successful reconstructions",
         "reconstruction_successes"),

        ("Failed reconstructions",
         "reconstruction_failures"),

        ("Original reconstruction mismatches",
         "old_mismatches"),

        ("Recovered observations",
         "recovered_observations"),

        ("Expected lexical words",
         "expected_words"),

        ("Reconstructed lexical words",
         "reconstructed_words"),

        ("Lexical sequence changes",
         "lexical_sequence_changes"),

        ("Lexical characters accounted for",
         "lexical_characters"),

        ("Complete reconstructed segments",
         "complete_segments"),

        ("Changed hypothesis counts",
         "changed_hypothesis_counts"),

        ("Shared timing observations",
         "shared_timing_observations"),

        ("Shared timing tokens",
         "shared_tokens"),

        ("Words with comparable timings",
         "timing_words_compared"),

        ("Words with changed timings",
         "timing_words_changed"),

        ("Unavailable timing comparisons",
         "timing_comparison_unavailable"),
    ]

    for label, key in rows:

        print(f"{label:44}{stats[key]:>10}")

    print()
    print("Synthetic tests passed:",
          sum(item["passed"] for item in synthetic),
          "/",
          len(synthetic))

    print()
    print("=" * 72)
    print("RECOVERED OBSERVATIONS")
    print("=" * 72)

    for item in evaluation["recovered"]:

        print(
            item["segment_id"],
            item["pass_id"],
            f"{item['old_word_count']} -> "
            f"{item['new_word_count']} words"
        )

    print()
    print("=" * 72)
    print("TIMING COMPARISON")
    print("=" * 72)

    for label, key in [

        ("Start", "start_delta_seconds"),
        ("End", "end_delta_seconds"),
    ]:

        values = evaluation[key]

        if values["count"]:

            print(
                f"{label} mean absolute change: "
                f"{values['mean'] * 1000:.3f} ms"
            )

            print(
                f"{label} maximum absolute change: "
                f"{values['maximum'] * 1000:.3f} ms"
            )

    print()
    print("Largest timing changes:")

    for item in evaluation["timing_changes"][:10]:

        print()

        print(
            item["segment_id"],
            item["pass_id"],
            "word index",
            item["word_index"]
        )

        print(
            "  Old:",
            timestamp(item["old_start"]),
            "-",
            timestamp(item["old_end"])
        )

        print(
            "  New:",
            timestamp(item["new_start"]),
            "-",
            timestamp(item["new_end"])
        )

        print(
            "  Absolute changes:",
            f"start={item['absolute_start_delta'] * 1000:.3f} ms,",
            f"end={item['absolute_end_delta'] * 1000:.3f} ms"
        )

    print()
    print("=" * 72)
    print("RECONSTRUCTION FAILURES")
    print("=" * 72)

    if not evaluation["failures"]:
        print("None")

    for item in evaluation["failures"][:20]:

        print(
            item["segment_id"],
            item["pass_id"],
            item["reason"]
        )


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Experimental decoder-aware "
            "lexical reconstruction"
        )
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
        parser.error("Input and output must differ.")

    raw = args.input.read_bytes()

    input_hash = hashlib.sha256(raw).hexdigest()

    data = json.loads(raw)

    if data.get("schema") != "hehawk.magpie.accumulation":
        parser.error("Unexpected input schema.")

    print("MAGPIE DECODER-AWARE RECONSTRUCTION")
    print("=" * 72)

    synthetic = run_synthetic_tests()

    evaluation = evaluate(data)

    if hashlib.sha256(
        args.input.read_bytes()
    ).hexdigest() != input_hash:

        raise RuntimeError(
            "Input changed during experiment."
        )

    print_report(
        evaluation,
        synthetic
    )

    report = {
        "schema": "hehawk.magpie.reconstruction",
        "version": 1,
        "input": {
            "path": str(args.input),
            "sha256": input_hash,
        },
        "settings": {
            "decoded_lexical_boundaries": True,
            "character_stream_alignment": "exact",
            "punctuation_independent_mapping": True,
            "token_character_ownership": True,
            "shared_token_timing_preserved": True,
            "automatic_acceptance": False,
        },
        "synthetic_tests": synthetic,
        "evaluation": evaluation,
        "integrity": {
            "input_unchanged": True,
            "production_code_modified": False,
        },
        "limitations": {
            "decoded_text_is_ground_truth": False,
            "character_agreement_proves_accuracy": False,
            "subtoken_timing_available": False,
            "human_verified": False,
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
    print("Original input unchanged: PASS")
    print("Production code modified: NO")
    print("Recognition rerun: NO")
    print()
    print("Report written to:", args.json)


if __name__ == "__main__":
    main()
