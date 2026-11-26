
import argparse
import json
import hashlib
import math
import re
import sys
import unittest

from collections import Counter, defaultdict
from pathlib import Path

from magpie_decoder_reconstruct import reconstruct


EPSILON = 0.000001

WORD_PATTERN = re.compile(
    r"[^\W_]+(?:['’][^\W_]+)*"
)


# ------------------------------------------------------------
# Independent verification helpers
# ------------------------------------------------------------

def expected_characters(tokens):

    result = []

    for token_index, token in enumerate(tokens):

        for position, character in enumerate(token):

            if character.isalnum():

                for folded in character.casefold():

                    result.append((
                        token_index,
                        position,
                        folded
                    ))

    return result


def lexical_stream(text):

    return "".join(

        character.casefold()

        for character in text

        if character.isalnum()

    )


def lexical_units(text):

    return [

        word.casefold().replace("’", "'")

        for word in WORD_PATTERN.findall(text)

    ]


def boundary_units(text):

    # Apostrophes and other punctuation remain
    # lexical boundaries for this comparison.

    return [

        lexical_stream(unit)

        for unit in re.findall(
            r"[^\W_]+",
            text
        )

    ]


def classify_boundary_agreement(text, tokens):

    raw = "".join(tokens)

    if lexical_stream(raw) != lexical_stream(text):

        return "character_mismatch"

    if lexical_units(raw) == lexical_units(text):

        return "lexical_agreement"

    if boundary_units(raw) == boundary_units(text):

        return "punctuation_boundary_agreement"

    return "boundary_disagreement"


# ------------------------------------------------------------
# Exact ownership verification
# ------------------------------------------------------------

def verify_ownership(
    text,
    tokens,
    timestamps,
    durations,
    result
):

    expected = expected_characters(tokens)

    expected_words = WORD_PATTERN.findall(text)

    words = result["words"]

    if len(words) != len(expected_words):

        raise AssertionError(
            "Decoded word count mismatch"
        )

    actual_owners = []

    token_owners = defaultdict(set)

    cursor = 0

    for word_index, (word, expected_word) in enumerate(
        zip(words, expected_words)
    ):

        expected_stream = lexical_stream(
            expected_word
        )

        if word["word"] != expected_word:

            raise AssertionError(
                f"Word {word_index}: "
                "decoded spelling changed"
            )

        count = len(expected_stream)

        expected_slice = expected[
            cursor:cursor + count
        ]

        cursor += count

        expected_owners = [

            (token_index, position)

            for token_index, position, character
            in expected_slice

        ]

        owners = [

            tuple(owner)

            for owner in word["character_owners"]

        ]

        if owners != expected_owners:

            raise AssertionError(
                f"Word {word_index}: "
                "incorrect character ownership"
            )

        actual_stream = "".join(

            character

            for token_index, position, character
            in expected_slice

        )

        if actual_stream != expected_stream:

            raise AssertionError(
                f"Word {word_index}: "
                "character sequence mismatch"
            )

        if word["character_count"] != count:

            raise AssertionError(
                f"Word {word_index}: "
                "character count mismatch"
            )

        indices = sorted({

            token_index

            for token_index, position in owners

        })

        if word["token_indices"] != indices:

            raise AssertionError(
                f"Word {word_index}: "
                "incorrect token ownership"
            )

        if word["token_start"] != min(indices):

            raise AssertionError(
                f"Word {word_index}: "
                "incorrect token range start"
            )

        if word["token_end"] != max(indices) + 1:

            raise AssertionError(
                f"Word {word_index}: "
                "incorrect token range end"
            )

        expected_start = min(

            timestamps[index]

            for index in indices

        )

        expected_end = max(

            timestamps[index] + durations[index]

            for index in indices

        )

        if not math.isclose(
            word["start"],
            expected_start,
            rel_tol=0,
            abs_tol=EPSILON
        ):

            raise AssertionError(
                f"Word {word_index}: "
                "incorrect start timing"
            )

        if not math.isclose(
            word["end"],
            expected_end,
            rel_tol=0,
            abs_tol=EPSILON
        ):

            raise AssertionError(
                f"Word {word_index}: "
                "incorrect end timing"
            )

        actual_owners.extend(owners)

        for index in indices:

            token_owners[index].add(word_index)

    expected_all_owners = [

        (token_index, position)

        for token_index, position, character
        in expected

    ]

    if actual_owners != expected_all_owners:

        raise AssertionError(
            "Global character ownership mismatch"
        )

    if cursor != len(expected):

        raise AssertionError(
            "Unconsumed lexical characters"
        )

    # Unicode case folding may expand one original
    # character into multiple normalized characters.
    #
    # Compare multiplicities rather than requiring
    # original character positions to be unique.

    if Counter(actual_owners) != Counter(
        expected_all_owners
    ):

        raise AssertionError(
            "Character ownership multiplicity mismatch"
        )

    shared = {

        index

        for index, owners in token_owners.items()

        if len(owners) > 1

    }

    for word_index, word in enumerate(words):

        expected_shared = any(

            index in shared

            for index in word["token_indices"]

        )

        if bool(word["shared_timing"]) != expected_shared:

            raise AssertionError(
                f"Word {word_index}: "
                "incorrect shared timing flag"
            )

    return {
        "words": len(words),
        "characters": len(expected),
        "shared_tokens": len(shared),
    }


# ------------------------------------------------------------
# Synthetic regression tests
# ------------------------------------------------------------

class TestDecoderReconstruction(unittest.TestCase):

    def check_case(
        self,
        text,
        tokens,
        expected_owners=None,
        expected_times=None,
        expected_boundary=None,
        timestamps=None,
        durations=None
    ):

        if timestamps is None:

            timestamps = [

                index * 0.125

                for index in range(len(tokens))

            ]

        if durations is None:

            durations = [

                0.125

                for token in tokens

            ]

        result = reconstruct(
            text,
            tokens,
            timestamps,
            durations
        )

        verify_ownership(
            text,
            tokens,
            timestamps,
            durations,
            result
        )

        words = result["words"]

        if expected_owners is not None:

            self.assertEqual(

                [
                    word["token_indices"]
                    for word in words
                ],

                expected_owners

            )

        if expected_times is not None:

            self.assertEqual(
                len(words),
                len(expected_times)
            )

            for word, (start, end) in zip(
                words,
                expected_times
            ):

                self.assertAlmostEqual(
                    word["start"],
                    start,
                    places=6
                )

                self.assertAlmostEqual(
                    word["end"],
                    end,
                    places=6
                )

        if expected_boundary is not None:

            self.assertEqual(

                classify_boundary_agreement(
                    text,
                    tokens
                ),

                expected_boundary

            )

        return result

    # --------------------------------------------------------
    # Ordinary lexical ownership
    # --------------------------------------------------------

    def test_01_ordinary_words(self):

        self.check_case(
            "Hello world.",
            [" Hello", " world", "."],
            expected_owners=[[0], [1]],
            expected_times=[
                (0.000, 0.125),
                (0.125, 0.250)
            ]
        )

    def test_02_fragmented_words(self):

        self.check_case(
            "Hello world",
            [" Hel", "lo", " wor", "ld"],
            expected_owners=[[0, 1], [2, 3]]
        )

    def test_03_repeated_words(self):

        self.check_case(
            "No no no",
            [" No", " no", " no"],
            expected_owners=[[0], [1], [2]]
        )

    def test_04_repeated_fragments(self):

        self.check_case(
            "Banana banana",
            [" Ba", "na", "na", " ba", "na", "na"],
            expected_owners=[[0, 1, 2], [3, 4, 5]]
        )

    def test_05_zero_duration_token(self):

        self.check_case(
            "Hello",
            [" Hel", "lo"],
            timestamps=[0.000, 0.125],
            durations=[0.125, 0.000],
            expected_times=[(0.000, 0.125)]
        )

    def test_06_overlapping_tokens(self):

        self.check_case(
            "Hello",
            [" Hel", "lo"],
            timestamps=[0.000, 0.125],
            durations=[0.500, 0.125],
            expected_times=[(0.000, 0.500)]
        )

    # --------------------------------------------------------
    # Apostrophes
    # --------------------------------------------------------

    def test_07_normal_contraction(self):

        self.check_case(
            "We'll",
            [" We", "'", "ll"],
            expected_owners=[[0, 2]]
        )

    def test_08_space_before_apostrophe(self):

        self.check_case(
            "We'll",
            [" We", " ", "'", "ll"],
            expected_owners=[[0, 3]],
            expected_boundary=(
                "punctuation_boundary_agreement"
            )
        )

    def test_09_space_after_apostrophe(self):

        self.check_case(
            "We'll",
            [" We", "'", " ll"],
            expected_owners=[[0, 2]]
        )

    def test_10_curly_apostrophe(self):

        self.check_case(
            "We’ll",
            [" We", "'", "ll"],
            expected_owners=[[0, 2]],
            expected_boundary="lexical_agreement"
        )

    def test_11_fictional_name(self):

        self.check_case(
            "E'Hawke",
            [" E", " ", "'", "Haw", "ke"],
            expected_owners=[[0, 3, 4]]
        )

    def test_12_multiple_apostrophes(self):

        self.check_case(
            "Ka'ra'than",
            [" Ka", "'", "ra", " ", "'", "than"],
            expected_owners=[[0, 2, 5]]
        )

    def test_13_possessive(self):

        self.check_case(
            "Angel's",
            [" Angel", "'", "s"],
            expected_owners=[[0, 2]]
        )

    # --------------------------------------------------------
    # Dash and speaker-marker structures
    # --------------------------------------------------------

    def test_14_hyphenated_word(self):

        self.check_case(
            "well-known",
            [" well", "-", "known"],
            expected_owners=[[0], [2]],
            expected_times=[
                (0.000, 0.125),
                (0.250, 0.375)
            ]
        )

    def test_15_speaker_marker_with_space(self):

        self.check_case(
            "- Hello",
            ["-", " Hello"],
            expected_owners=[[1]]
        )

    def test_16_speaker_marker_without_space(self):

        self.check_case(
            "-Hello",
            ["-", "Hello"],
            expected_owners=[[1]]
        )

    def test_17_multiple_speaker_lines(self):

        self.check_case(
            "- Hello\n- Goodbye",
            ["-", " Hello", "\n", "-", " Goodbye"],
            expected_owners=[[1], [4]]
        )

    def test_18_em_dash(self):

        self.check_case(
            "Wait—what?",
            [" Wait", "—", "what", "?"],
            expected_owners=[[0], [2]]
        )

    def test_19_en_dash(self):

        self.check_case(
            "Monday–Friday",
            [" Monday", "–", "Friday"],
            expected_owners=[[0], [2]]
        )

    def test_20_stutter(self):

        self.check_case(
            "I-I-I don't know",
            [" I", "-", "I", "-", "I",
             " don't", " know"],
            expected_owners=[
                [0], [2], [4], [5], [6]
            ]
        )

    def test_21_interrupted_speech(self):

        self.check_case(
            "But I—",
            [" But", " I", "—"],
            expected_owners=[[0], [1]]
        )

    # --------------------------------------------------------
    # Shared timing
    # --------------------------------------------------------

    def test_22_one_token_two_words(self):

        result = self.check_case(
            "Hello world",
            [" Hello world"],
            expected_owners=[[0], [0]],
            expected_times=[
                (0.000, 0.125),
                (0.000, 0.125)
            ]
        )

        self.assertTrue(
            result["words"][0]["shared_timing"]
        )

        self.assertTrue(
            result["words"][1]["shared_timing"]
        )

    def test_23_partial_shared_token(self):

        self.check_case(
            "Hello world",
            [" Hel", "lo wor", "ld"],
            expected_owners=[[0, 1], [1, 2]]
        )

    def test_24_hyphen_inside_token(self):

        self.check_case(
            "well-known",
            [" well-known"],
            expected_owners=[[0], [0]]
        )

    # --------------------------------------------------------
    # Unicode and nonlexical content
    # --------------------------------------------------------

    def test_25_casefold_expansion(self):

        self.check_case(
            "STRASSE",
            [" Straße"],
            expected_owners=[[0]]
        )

    def test_26_nonbreaking_space(self):

        self.check_case(
            "Hello\u00a0world",
            [" Hello", "\u00a0", "world"],
            expected_owners=[[0], [2]]
        )

    def test_27_nonlexical_only(self):

        self.check_case(
            "...!",
            [".", ".", ".", "!"],
            expected_owners=[]
        )

    def test_28_empty_observation(self):

        self.check_case(
            "",
            [],
            expected_owners=[]
        )

    def test_29_trailing_punctuation(self):

        self.check_case(
            "Hello...",
            [" Hello", "..."],
            expected_owners=[[0]],
            expected_times=[(0.000, 0.125)]
        )

    def test_30_punctuation_inside_token(self):

        self.check_case(
            "Hello!",
            [" Hello!"],
            expected_owners=[[0]]
        )

    # --------------------------------------------------------
    # Boundary ambiguity
    #
    # These cases document existing reconstruction
    # behavior. Acceptance is NOT lexical equivalence.
    # --------------------------------------------------------

    def test_31_well_vs_well_contraction(self):

        self.check_case(
            "We'll",
            [" Well"],
            expected_boundary="boundary_disagreement"
        )

    def test_32_now_here_vs_nowhere(self):

        self.check_case(
            "Nowhere",
            [" Now", " here"],
            expected_boundary="boundary_disagreement"
        )

    def test_33_a_part_vs_apart(self):

        self.check_case(
            "Apart",
            [" A", " part"],
            expected_boundary="boundary_disagreement"
        )

    def test_34_resign_vs_re_sign(self):

        self.check_case(
            "Resign",
            [" Re", "-", "sign"],
            expected_boundary="boundary_disagreement"
        )

    def test_35_its_vs_its_contraction(self):

        self.check_case(
            "It's",
            [" Its"],
            expected_boundary="boundary_disagreement"
        )

    def test_36_were_vs_were_contraction(self):

        self.check_case(
            "We're",
            [" Were"],
            expected_boundary="boundary_disagreement"
        )

    def test_37_decimal_boundary(self):

        self.check_case(
            "12",
            [" 1", ".", "2"],
            expected_boundary="boundary_disagreement"
        )

    def test_38_comma_boundary(self):

        self.check_case(
            "1000",
            [" 1", ",", "000"],
            expected_boundary="boundary_disagreement"
        )

    # --------------------------------------------------------
    # Inputs that must be rejected
    # --------------------------------------------------------

    def assert_rejected(
        self,
        text,
        tokens,
        timestamps=None,
        durations=None
    ):

        if timestamps is None:

            timestamps = [
                index * 0.125
                for index in range(len(tokens))
            ]

        if durations is None:

            durations = [
                0.125
                for token in tokens
            ]

        with self.assertRaises(ValueError):

            reconstruct(
                text,
                tokens,
                timestamps,
                durations
            )

    def test_39_missing_character(self):

        self.assert_rejected(
            "Hello",
            [" Hell"]
        )

    def test_40_extra_character(self):

        self.assert_rejected(
            "Hello",
            [" Helloo"]
        )

    def test_41_changed_character(self):

        self.assert_rejected(
            "Hello",
            [" Hallo"]
        )

    def test_42_missing_word(self):

        self.assert_rejected(
            "Hello world",
            [" Hello"]
        )

    def test_43_repeated_extra_word(self):

        self.assert_rejected(
            "No",
            [" No", " no"]
        )

    def test_44_missing_negation(self):

        self.assert_rejected(
            "I cannot go",
            [" I", " can", " go"]
        )

    def test_45_mismatched_arrays(self):

        self.assert_rejected(
            "Hello",
            [" Hello"],
            timestamps=[],
            durations=[0.125]
        )

    def test_46_negative_duration(self):

        self.assert_rejected(
            "Hello",
            [" Hello"],
            durations=[-0.125]
        )

    def test_47_negative_timestamp(self):

        self.assert_rejected(
            "Hello",
            [" Hello"],
            timestamps=[-0.125]
        )

    def test_48_nan_timestamp(self):

        self.assert_rejected(
            "Hello",
            [" Hello"],
            timestamps=[float("nan")]
        )

    def test_49_infinite_duration(self):

        self.assert_rejected(
            "Hello",
            [" Hello"],
            durations=[float("inf")]
        )

    # --------------------------------------------------------
    # Negative controls for the independent verifier
    # --------------------------------------------------------

    def test_50_swapped_character_owners(self):

        result = reconstruct(
            "No no",
            [" No", " no"],
            [0.000, 0.125],
            [0.125, 0.125]
        )

        first = result["words"][0]
        second = result["words"][1]

        (
            first["character_owners"],
            second["character_owners"]
        ) = (
            second["character_owners"],
            first["character_owners"]
        )

        with self.assertRaises(AssertionError):

            verify_ownership(
                "No no",
                [" No", " no"],
                [0.000, 0.125],
                [0.125, 0.125],
                result
            )

    def test_51_corrupted_timing(self):

        result = reconstruct(
            "Hello world",
            [" Hello", " world"],
            [0.000, 0.125],
            [0.125, 0.125]
        )

        result["words"][0]["end"] = 0.250

        with self.assertRaises(AssertionError):

            verify_ownership(
                "Hello world",
                [" Hello", " world"],
                [0.000, 0.125],
                [0.125, 0.125],
                result
            )


# ------------------------------------------------------------
# Full episode audit
# ------------------------------------------------------------

def audit_episode(path):

    raw = path.read_bytes()

    original_hash = hashlib.sha256(
        raw
    ).hexdigest()

    data = json.loads(raw)

    if data.get("schema") != "hehawk.magpie.accumulation":

        raise ValueError(
            "Unexpected recognition schema"
        )

    if data.get("version") != 1:

        raise ValueError(
            "Unsupported recognition version"
        )

    if data.get(
        "observation_timestamp_basis"
    ) != "segment_relative":

        raise ValueError(
            "Unexpected observation timestamp basis"
        )

    stats = Counter()

    boundary_classes = Counter()

    boundary_cases = []

    failures = []

    for segment in data["segments"]:

        for obs in segment["observations"]:

            stats["observations"] += 1

            try:

                result = reconstruct(
                    obs["text"],
                    obs["tokens"],
                    obs["timestamps"],
                    obs["durations"]
                )

                verified = verify_ownership(
                    obs["text"],
                    obs["tokens"],
                    obs["timestamps"],
                    obs["durations"],
                    result
                )

                stats.update(verified)

                stats["verified"] += 1

                classification = (
                    classify_boundary_agreement(
                        obs["text"],
                        obs["tokens"]
                    )
                )

                boundary_classes[classification] += 1

                if classification != "lexical_agreement":

                    boundary_cases.append({
                        "segment_id": segment["id"],
                        "pass_id": obs["pass_id"],
                        "classification": classification,
                    })

            except (
                AssertionError,
                ValueError,
                KeyError,
                TypeError
            ) as exc:

                failures.append({
                    "segment_id": segment["id"],
                    "pass_id": obs["pass_id"],
                    "reason": str(exc),
                })

    current_hash = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()

    if current_hash != original_hash:

        raise RuntimeError(
            "Recognition input changed during audit"
        )

    return {
        "input": {
            "path": str(path),
            "sha256": original_hash,
        },
        "source_sha256": data["source_sha256"],
        "statistics": dict(stats),
        "boundary_classifications": dict(
            boundary_classes
        ),
        "boundary_cases": boundary_cases,
        "failures": failures,
        "input_unchanged": True,
    }


# ------------------------------------------------------------
# Reporting
# ------------------------------------------------------------

def print_episode_report(report):

    print()
    print("=" * 72)
    print("FULL EPISODE CHARACTER OWNERSHIP AUDIT")
    print("=" * 72)

    stats = report["statistics"]

    for label, key in [

        ("Observations", "observations"),
        ("Verified observations", "verified"),
        ("Reconstructed words", "words"),
        ("Lexical characters", "characters"),
        ("Shared lexical tokens", "shared_tokens"),

    ]:

        print(
            f"{label:44}"
            f"{stats.get(key, 0):>10}"
        )

    print()
    print("=" * 72)
    print("BOUNDARY CLASSIFICATIONS")
    print("=" * 72)

    for classification, count in sorted(
        report["boundary_classifications"].items()
    ):

        print(
            f"{classification:44}"
            f"{count:>10}"
        )

    print()
    print("=" * 72)
    print("NONIDENTICAL LEXICAL BOUNDARIES")
    print("=" * 72)

    for case in report["boundary_cases"]:

        print(
            case["segment_id"],
            case["pass_id"],
            case["classification"]
        )

    if not report["boundary_cases"]:

        print("None")

    print()
    print("=" * 72)
    print("OWNERSHIP FAILURES")
    print("=" * 72)

    for failure in report["failures"]:

        print(
            failure["segment_id"],
            failure["pass_id"],
            failure["reason"]
        )

    if not report["failures"]:

        print("None")

    print()
    print("Original recognition input unchanged: PASS")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=(
            "MAGPIE adversarial reconstruction tests"
        )
    )

    parser.add_argument(
        "--episode",
        type=Path
    )

    parser.add_argument(
        "--json",
        type=Path
    )

    args = parser.parse_args()

    if args.json and args.json.exists():

        parser.error(
            "Output file already exists"
        )

    if args.json and not args.episode:

        parser.error(
            "--json requires --episode"
        )

    if args.json and args.episode:

        if args.json.resolve() == args.episode.resolve():

            parser.error(
                "Output must differ from input"
            )

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        TestDecoderReconstruction
    )

    runner = unittest.TextTestRunner(
        verbosity=2,
        stream=sys.stdout
    )

    synthetic = runner.run(suite)

    report = {
        "schema": "hehawk.magpie.adversarial_reconstruction",
        "version": 1,
        "synthetic_tests": {
            "tests_run": synthetic.testsRun,
            "failures": len(synthetic.failures),
            "errors": len(synthetic.errors),
            "skipped": len(synthetic.skipped),
            "passed": synthetic.wasSuccessful(),
        },
        "settings": {
            "exact_character_position_verification": True,
            "timing_ownership_verification": True,
            "boundary_classification_experimental": True,
            "automatic_acceptance": False,
        },
        "limitations": {
            "decoded_text_is_ground_truth": False,
            "character_agreement_proves_lexical_equivalence": False,
            "speaker_marker_semantics_verified": False,
            "acoustic_timing_verified": False,
        },
        "production_code_modified": False,
    }

    episode_passed = True

    if args.episode:

        episode = audit_episode(
            args.episode
        )

        report["episode"] = episode

        print_episode_report(episode)

        episode_passed = not episode["failures"]

    if args.json:

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
        print("Report written to:", args.json)

    print()
    print("=" * 72)
    print("EXPERIMENT SUMMARY")
    print("=" * 72)

    print(
        "Synthetic regression tests:",
        "PASS"
        if synthetic.wasSuccessful()
        else "FAIL"
    )

    if args.episode:

        print(
            "Episode ownership verification:",
            "PASS" if episode_passed else "FAIL"
        )

    print("Production code modified: NO")
    print("Recognition rerun: NO")
    print("LARK rerun: NO")

    return (
        0
        if synthetic.wasSuccessful() and episode_passed
        else 1
    )


if __name__ == "__main__":

    sys.exit(main())
