#!/usr/bin/env python3
"""ROOK: experimental caption parser characterization audit."""

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path

import compare
import gulp
import gulp_v4
import magpie_incremental


# ------------------------------------------------------------
# Synthetic caption fixtures
# ------------------------------------------------------------

CASES = [
    ("C001", "ordinary_dialogue",
     "Hello. How are you?"),

    ("C002", "bracket_sound",
     "[ Door closes ]"),

    ("C003", "bracket_dialogue",
     "[ Get out of here! ]"),

    ("C004", "bracket_mixed",
     "[ On radio: Please come here. ]"),

    ("C005", "bracket_delivery",
     "[ Whispering ] Get down."),

    ("C006", "bracket_speaker",
     "[ John ] Stop that!"),

    ("C007", "bracket_language",
     "[ In French: Good morning. ]"),

    ("C008", "bracket_unintelligible",
     "[ Indistinct chatter ]"),

    ("C009", "bracket_multiple",
     "[ Door opens ] Hello. [ Door closes ]"),

    ("C010", "bracket_adjacent",
     "Wait[ coughing ]here."),

    ("C011", "parenthesis_sound",
     "( Door closes )"),

    ("C012", "parenthesis_dialogue",
     "( Get out of here! )"),

    ("C013", "parenthesis_mixed",
     "( On radio: Please come here. )"),

    ("C014", "parenthesis_delivery",
     "( Whispering ) Get down."),

    ("C015", "parenthesis_speaker",
     "( John ) Stop that!"),

    ("C016", "parenthesis_language",
     "( In French: Good morning. )"),

    ("C017", "parenthesis_unintelligible",
     "( Indistinct chatter )"),

    ("C018", "speaker_hyphens",
     "- Where are you going?\n- Home."),

    ("C019", "speaker_hyphens_no_space",
     "-Where are you going?\n-Home."),

    ("C020", "speaker_indentation",
     "Where are you going?\n        Home."),

    ("C021", "speaker_nbsp",
     "Where are you going?\n"
     "\u00a0\u00a0\u00a0\u00a0Home."),

    ("C022", "speaker_names",
     "JOHN: Where are you going?\n"
     "MARY: Home."),

    ("C023", "uppercase",
     "WHERE ARE YOU GOING?"),

    ("C024", "mixed_capitalization",
     "John met E'Hawke and D'Hai."),

    ("C025", "music_dialogue",
     "\u266a We are going home \u266a"),

    ("C026", "music_only",
     "\u266a\u266a"),

    ("C027", "music_description",
     "[ Dramatic music ]"),

    ("C028", "music_mixed",
     "[ Singing ] \u266a Going home \u266a"),

    ("C029", "interruption",
     "I was going to--\n- Don't."),

    ("C030", "stutter",
     "I-I don't know."),

    ("C031", "nested_brackets",
     "[ On radio: [ static ] Hello. ]"),

    ("C032", "nested_mixed",
     "[ On radio ( quietly ): Hello. ]"),

    ("C033", "unmatched_open_bracket",
     "[ Door closes"),

    ("C034", "unmatched_close_bracket",
     "Door closes ]"),

    ("C035", "mismatched_delimiters",
     "[ Door closes )"),

    ("C036", "ordinary_parenthetical",
     "I think ( perhaps ) we should go."),

    ("C037", "punctuation_only",
     "..."),

    ("C038", "bracket_empty",
     "[ ]"),

    ("C039", "parenthesis_empty",
     "( )"),
]


# Format-specific fixtures.
#
# Each entry contains equivalent or deliberately analogous
# SRT and ASS representations.

FORMAT_CASES = [
    (
        "F001", "italic_dialogue",
        "<i>Hello.</i>",
        r"{\i1}Hello.{\i0}",
    ),
    (
        "F002", "bold_dialogue",
        "<b>Hello.</b>",
        r"{\b1}Hello.{\b0}",
    ),
    (
        "F003", "italic_speaker_lines",
        "<i>- Hello.\n- Goodbye.</i>",
        r"{\i1}- Hello.\N- Goodbye.{\i0}",
    ),
    (
        "F004", "formatting_inside_word",
        "Hel<i>lo</i>.",
        r"Hel{\i1}lo{\i0}.",
    ),
    (
        "F005", "explicit_line_break",
        "Hello<br>Goodbye.",
        r"Hello\NGoodbye.",
    ),
    (
        "F006", "unknown_markup",
        "<Unknown> Hello.",
        r"{\unknown} Hello.",
    ),
    (
        "F007", "formatting_only",
        "<i></i>",
        r"{\i1}{\i0}",
    ),
    (
        "F008", "nonbreaking_space",
        "Hello&nbsp;world.",
        r"Hello\hworld.",
    ),
    (
        "F009", "italic_annotation",
        "<i>[ Door closes ]</i>",
        r"{\i1}[ Door closes ]{\i0}",
    ),
    (
        "F010", "literal_angle_brackets",
        "<Alien language>",
        "<Alien language>",
    ),
    (
        "F011", "unknown_markup_between_words",
        "Hello<unknown>world.",
        r"Hello{\unknown}world.",
    ),
    (
        "F012", "drawing_only",
        None,
        r"{\p1}m 0 0 l 10 10{\p0}",
    ),
]


# ------------------------------------------------------------
# Fixture construction
# ------------------------------------------------------------

ASS_HEADER = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, "
    "MarginL, MarginR, MarginV, Effect, Text\n"
)


def make_srt(
    text,
    start="00:00:01,000",
    end="00:00:04,000",
):
    return f"1\n{start} --> {end}\n{text}\n"


def make_ass(
    text,
    start="0:00:01.00",
    end="0:00:04.00",
    speaker="",
):
    return (
        ASS_HEADER
        + f"Dialogue: 0,{start},{end},Default,"
        + f"{speaker},0,0,0,,{text}\n"
    )


def normalized_words(text):
    return [
        compare.normalize_word(word)
        for word in compare.tokenize(text)
    ]


# ------------------------------------------------------------
# Parser adapters
# ------------------------------------------------------------

def legacy_ass(raw):
    # compare.read_ass requires a filename.
    # Only synthetic data is written to this temporary file.

    with tempfile.TemporaryDirectory(
        prefix="rook_audit_"
    ) as directory:

        path = Path(directory) / "fixture.ass"
        path.write_text(raw, encoding="utf-8")

        cues, words = compare.read_ass(path)

    return {
        "cues": cues,
        "words": [
            word["normalized"]
            for word in words
        ],
        "raw_text_available": False,
        "display_text_available": False,
    }


def gulp_adapter(module, kind, raw):

    if kind == "ass":
        cues = module.parse_ass(raw)
    else:
        cues = module.parse_srt(raw)

    words = []

    for cue in cues:
        words.extend(
            normalized_words(
                cue["comparison_text"]
            )
        )

    return {
        "cues": cues,
        "words": words,
        "raw_text_available": True,
        "display_text_available": True,
        "conversion_eligible_cues": sum(
            bool(cue["comparison_text"])
            for cue in cues
        ),
    }


def incremental_srt(raw):

    cues = magpie_incremental.parse_srt(
        raw.encode("utf-8")
    )

    return {
        "cues": cues,
        "words": [
            word
            for cue in cues
            for word in cue["words"]
        ],
        "raw_text_available": False,
        "display_text_available": False,
    }


def run_parser(name, function, raw):

    try:
        result = function(raw)

        return {
            "parser": name,
            "status": "returned",
            "cue_count": len(result["cues"]),
            "word_count": len(result["words"]),
            **result,
        }

    except Exception as exc:
        # Exceptions are observations in a characterization
        # audit, not automatically test failures.

        return {
            "parser": name,
            "status": "exception",
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }


def run_ass(raw):

    return [
        run_parser(
            "compare",
            legacy_ass,
            raw,
        ),
        run_parser(
            "gulp",
            lambda value: gulp_adapter(
                gulp, "ass", value
            ),
            raw,
        ),
        run_parser(
            "gulp_v4",
            lambda value: gulp_adapter(
                gulp_v4, "ass", value
            ),
            raw,
        ),
    ]


def run_srt(raw):

    return [
        run_parser(
            "gulp",
            lambda value: gulp_adapter(
                gulp, "srt", value
            ),
            raw,
        ),
        run_parser(
            "gulp_v4",
            lambda value: gulp_adapter(
                gulp_v4, "srt", value
            ),
            raw,
        ),
        run_parser(
            "magpie_incremental",
            incremental_srt,
            raw,
        ),
    ]


# ------------------------------------------------------------
# Characterization
# ------------------------------------------------------------

def characterize(results):

    returned = [
        result
        for result in results
        if result["status"] == "returned"
    ]

    sequences = {
        tuple(result["words"])
        for result in returned
    }

    cue_counts = {
        result["cue_count"]
        for result in returned
    }

    return {
        "returned": len(returned),
        "exceptions": len(results) - len(returned),
        "lexical_disagreement": len(sequences) > 1,
        "cue_count_disagreement": len(cue_counts) > 1,
        "omitted_cue_parsers": [
            result["parser"]
            for result in returned
            if result["cue_count"] == 0
        ],
        "empty_lexical_parsers": [
            result["parser"]
            for result in returned
            if not result["words"]
        ],
    }


def make_record(case_id, category, kind, raw):

    results = (
        run_ass(raw)
        if kind == "ass"
        else run_srt(raw)
    )

    return {
        "case_id": case_id,
        "category": category,
        "format": kind,
        "input": raw,
        "results": results,
        "observations": characterize(results),
    }


def audit():

    records = []

    for case_id, category, text in CASES:

        records.append(
            make_record(
                case_id,
                category,
                "srt",
                make_srt(text),
            )
        )

        records.append(
            make_record(
                case_id,
                category,
                "ass",
                make_ass(
                    text.replace("\n", r"\N")
                ),
            )
        )

    for case_id, category, srt, ass in FORMAT_CASES:

        if srt is not None:
            records.append(
                make_record(
                    case_id,
                    category,
                    "srt",
                    make_srt(srt),
                )
            )

        if ass is not None:
            records.append(
                make_record(
                    case_id,
                    category,
                    "ass",
                    make_ass(ass),
                )
            )

    # Integrity and metadata fixtures.

    special_cases = [
        (
            "I001", "invalid_timestamp", "ass",
            make_ass("Hello.", start="invalid"),
        ),
        (
            "I002", "reversed_timestamp", "ass",
            make_ass(
                "Hello.",
                start="0:00:05.00",
            ),
        ),
        (
            "I003", "zero_duration", "ass",
            make_ass(
                "Hello.",
                end="0:00:01.00",
            ),
        ),
        (
            "I004", "malformed_fields", "ass",
            ASS_HEADER + "Dialogue: 0,invalid\n",
        ),
        (
            "I005", "invalid_timestamp", "srt",
            make_srt("Hello.", start="invalid"),
        ),
        (
            "I006", "reversed_timestamp", "srt",
            make_srt(
                "Hello.",
                start="00:00:05,000",
            ),
        ),
        (
            "I007", "zero_duration", "srt",
            make_srt(
                "Hello.",
                end="00:00:01,000",
            ),
        ),
        (
            "I008", "ass_speaker_metadata", "ass",
            make_ass("Hello.", speaker="John"),
        ),
        (
            "I009", "malformed_followed_by_valid", "ass",
            ASS_HEADER
            + "Dialogue: 0,invalid\n"
            + "Dialogue: 0,0:00:01.00,"
            + "0:00:04.00,Default,,0,0,0,,Hello.\n",
        ),
    ]

    for case_id, category, kind, raw in special_cases:
        records.append(
            make_record(
                case_id, category, kind, raw
            )
        )

    return records


# ------------------------------------------------------------
# Reproducibility and reporting
# ------------------------------------------------------------

def module_hashes():

    result = {}

    for module in (
        compare,
        gulp,
        gulp_v4,
        magpie_incremental,
    ):
        path = Path(module.__file__)

        result[module.__name__] = {
            "filename": path.name,
            "sha256": hashlib.sha256(
                path.read_bytes()
            ).hexdigest(),
        }

    return result


def summarize(records):

    counts = Counter()
    parsers = {}

    for record in records:

        counts["fixtures"] += 1
        counts[record["format"] + "_fixtures"] += 1

        observations = record["observations"]

        for key in (
            "lexical_disagreement",
            "cue_count_disagreement",
        ):
            counts[key] += int(observations[key])

        for result in record["results"]:

            counts["parser_invocations"] += 1

            name = (
                result["parser"]
                + "/"
                + record["format"]
            )

            stats = parsers.setdefault(
                name, Counter()
            )

            stats["invocations"] += 1

            if result["status"] == "exception":
                stats["exceptions"] += 1
                counts["exceptions"] += 1
                continue

            stats["returned"] += 1

            if result["cue_count"] == 0:
                stats["zero_cues"] += 1
                counts["zero_cues"] += 1

            if result["word_count"] == 0:
                stats["zero_words"] += 1

    return {
        "totals": dict(counts),
        "parsers": {
            name: dict(stats)
            for name, stats in sorted(
                parsers.items()
            )
        },
    }


def print_report(records, statistics):

    print("ROOK caption interpretation audit")
    print("=" * 72)

    for key, value in statistics["totals"].items():
        print(f"{key:30} {value:6}")

    print("\nParser observations")
    print("-" * 72)

    for name, stats in statistics["parsers"].items():

        print(
            f"{name:25}"
            f" calls={stats.get('invocations', 0):3}"
            f" exceptions={stats.get('exceptions', 0):3}"
            f" zero_cues={stats.get('zero_cues', 0):3}"
            f" zero_words={stats.get('zero_words', 0):3}"
        )

    print("\nLexical and structural disagreements")
    print("-" * 72)

    for record in records:

        observations = record["observations"]

        if not (
            observations["lexical_disagreement"]
            or observations["cue_count_disagreement"]
            or observations["exceptions"]
            or observations["omitted_cue_parsers"]
        ):
            continue

        print(
            f"\n{record['case_id']} "
            f"{record['format'].upper()} "
            f"{record['category']}"
        )

        for result in record["results"]:

            if result["status"] == "exception":
                print(
                    f"  {result['parser']:20}"
                    f" EXCEPTION: "
                    f"{result['exception_type']}"
                )
            else:
                print(
                    f"  {result['parser']:20}"
                    f" cues={result['cue_count']}"
                    f" words={result['words']!r}"
                )


def main():

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--json",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    if args.json.exists():
        parser.error(
            f"Output already exists: {args.json}"
        )

    before = module_hashes()

    records = audit()
    statistics = summarize(records)

    after = module_hashes()

    if before != after:
        raise RuntimeError(
            "Parser source changed during audit."
        )

    report = {
        "schema": "hehawk.rook.caption_audit",
        "schema_version": 1,
        "settings": {
            "synthetic_inputs_only": True,
            "characterization_only": True,
            "automatic_acceptance": False,
        },
        "parser_sources": before,
        "statistics": statistics,
        "records": records,
        "integrity": {
            "parser_sources_unchanged": True,
            "production_code_modified": False,
            "episode_files_processed": False,
        },
        "limitations": {
            "semantic_correctness_verified": False,
            "parser_agreement_proves_correctness": False,
            "real_world_frequency_measured": False,
            "conversion_cli_exercised": False,
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

    print_report(records, statistics)

    print("\nIntegrity: PASS")
    print("Parser sources unchanged.")
    print("No episode files processed.")
    print(f"Report: {args.json}")


if __name__ == "__main__":
    main()

