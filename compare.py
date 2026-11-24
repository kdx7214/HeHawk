
import argparse
import json
import re
from array import array
from difflib import SequenceMatcher
from pathlib import Path

from metaphone import doublemetaphone

# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

CONTEXT_WORDS = 8
GAP_COST = 1.0

MAX_MATCH_DISTANCE = 1.50
TIME_PENALTY_PER_SECOND = 0.45
MAX_TIME_PENALTY = 0.75

SPLIT_GAP_SECONDS = 1.25

# Phonetic candidate settings
PHONETIC_MAX_DISTANCE = 2.50
MIN_SPELLING_SIMILARITY = 0.60
MIN_PHONETIC_SIMILARITY = 0.65

# A high spelling score usually indicates a spelling or
# inflection difference rather than a genuine phonetic error.
ORTHOGRAPHIC_SIMILARITY = 0.88

# Minimum shared substring length for compound detection.
MIN_COMPOUND_LENGTH = 4

PHONETIC_STOP_WORDS = {
    "about", "after", "again", "against", "being", "could",
    "every", "first", "from", "have", "here", "into", "just",
    "know", "like", "little", "look", "more", "most", "never",
    "only", "other", "over", "people", "really", "right",
    "said", "some", "something", "that", "their", "there",
    "these", "they", "thing", "things", "this", "those",
    "through", "under", "very", "want", "were", "what",
    "when", "where", "which", "while", "with", "would",
    "your"
}


# ------------------------------------------------------------
# Time and text utilities
# ------------------------------------------------------------

def ass_time_to_seconds(value):
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def format_time(seconds):
    if seconds is None:
        return "??:??:??.??"

    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60

    return f"{hours:02d}:{minutes:02d}:{secs:05.2f}"


def clean_subtitle_text(text):
    text = re.sub(r"\{[^}]*\}", "", text)
    text = text.replace(r"\N", " ")
    text = text.replace(r"\n", " ")
    text = text.replace(r"\h", " ")
    text = re.sub(r"\[[^\]]*\]", " ", text)
    return text


def normalize_word(word):
    return word.casefold().replace("’", "'").replace("‘", "'")


def tokenize(text):
    return re.findall(
        r"[^\W_]+(?:['’][^\W_]+)*",
        text,
        re.UNICODE
    )


def midpoint(word):
    return (word["start"] + word["end"]) / 2


# ------------------------------------------------------------
# Read original ASS subtitles
# ------------------------------------------------------------

def read_ass(filename):
    cues = []

    with open(filename, "r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file):
            if not line.startswith("Dialogue:"):
                continue

            fields = line.rstrip("\n").split(",", 9)

            if len(fields) < 10:
                continue

            try:
                start = ass_time_to_seconds(fields[1])
                end = ass_time_to_seconds(fields[2])
            except ValueError:
                continue

            if end < start:
                continue

            cue_words = tokenize(clean_subtitle_text(fields[9]))

            if not cue_words:
                continue

            cues.append({
                "start": start,
                "end": end,
                "words": cue_words,
                "source_line": line_number + 1,
            })

    cues.sort(key=lambda cue: cue["start"])
    words = []

    for cue_number, cue in enumerate(cues):
        cue["number"] = cue_number

        for word in cue["words"]:
            words.append({
                "word": word,
                "normalized": normalize_word(word),
                "start": cue["start"],
                "end": cue["end"],
                "cue": cue_number,
                "global_index": len(words),
            })

    return cues, words


# ------------------------------------------------------------
# Read Parakeet transcription
# ------------------------------------------------------------

def read_parakeet(filename):
    with open(filename, "r", encoding="utf-8") as file:
        data = json.load(file)

    tokens = data["tokens"]
    timestamps = data["timestamps"]
    durations = data["durations"]

    if not (len(tokens) == len(timestamps) == len(durations)):
        raise ValueError(
            "Parakeet JSON has mismatched token, timestamp, "
            "and duration counts."
        )

    words = []
    current_text = ""
    current_start = None
    current_end = None

    def save_word():
        nonlocal current_text, current_start, current_end

        if not current_text:
            return

        for word in tokenize(current_text):
            words.append({
                "word": word,
                "normalized": normalize_word(word),
                "start": current_start,
                "end": current_end,
                "global_index": len(words),
            })

        current_text = ""
        current_start = None
        current_end = None

    for token, timestamp, duration in zip(tokens, timestamps, durations):
        token_start = float(timestamp)
        token_end = token_start + float(duration)

        if token and token[0].isspace():
            save_word()
            current_text = token.strip()
            current_start = token_start
            current_end = token_end

        elif not current_text:
            current_text = token.strip()
            current_start = token_start
            current_end = token_end

        else:
            current_text += token
            current_end = token_end

    save_word()
    words.sort(key=lambda word: word["start"])

    for index, word in enumerate(words):
        word["global_index"] = index

    return words


# ------------------------------------------------------------
# Time-aware global alignment
# ------------------------------------------------------------

def temporal_distance(reference_word, asr_word):
    word_time = midpoint(asr_word)

    if word_time < reference_word["start"]:
        return reference_word["start"] - word_time

    if word_time > reference_word["end"]:
        return word_time - reference_word["end"]

    return 0.0


def match_cost(reference_word, asr_word):
    if reference_word["normalized"] != asr_word["normalized"]:
        return None

    distance = temporal_distance(reference_word, asr_word)

    if distance > MAX_MATCH_DISTANCE:
        return None

    penalty = min(
        distance * TIME_PENALTY_PER_SECOND,
        MAX_TIME_PENALTY
    )

    return 0.01 + penalty


def align_words(reference, parakeet):
    n = len(reference)
    m = len(parakeet)
    width = m + 1

    previous = array("d", [0.0]) * width
    current = array("d", [0.0]) * width
    trace = bytearray((n + 1) * width)

    # 1 = match, 2 = reference missing, 3 = ASR extra.
    for j in range(1, width):
        previous[j] = j * GAP_COST
        trace[j] = 3

    print("Aligning chronological word sequences...")

    for i in range(1, n + 1):
        current[0] = i * GAP_COST
        trace[i * width] = 2

        ref_word = reference[i - 1]

        for j in range(1, m + 1):
            asr_word = parakeet[j - 1]

            best_cost = previous[j] + GAP_COST
            direction = 2

            insert_cost = current[j - 1] + GAP_COST

            if insert_cost < best_cost:
                best_cost = insert_cost
                direction = 3

            lexical_cost = match_cost(ref_word, asr_word)

            if lexical_cost is not None:
                matched_cost = previous[j - 1] + lexical_cost

                if matched_cost <= best_cost:
                    best_cost = matched_cost
                    direction = 1

            current[j] = best_cost
            trace[i * width + j] = direction

        previous, current = current, previous

        if i % 500 == 0:
            print(f"  Aligned {i:,} / {n:,} reference words")

    operations = []
    i = n
    j = m

    while i > 0 or j > 0:
        direction = trace[i * width + j]

        if direction == 1:
            operations.append(("equal", i - 1, j - 1))
            i -= 1
            j -= 1

        elif direction == 2:
            operations.append(("delete", i - 1, None))
            i -= 1

        elif direction == 3:
            operations.append(("insert", None, j - 1))
            j -= 1

        else:
            raise RuntimeError(
                f"Invalid alignment direction at {i}, {j}"
            )

    operations.reverse()
    return operations


# ------------------------------------------------------------
# Phonetic comparison
# ------------------------------------------------------------

def metaphone_codes(word):
    return tuple(
        code for code in doublemetaphone(word)
        if code
    )


def phonetic_similarity(reference_word, asr_word):
    ref_text = reference_word["normalized"]
    asr_text = asr_word["normalized"]

    if ref_text == asr_text:
        return 0.0, 0.0

    if len(ref_text) < 4 or len(asr_text) < 4:
        return 0.0, 0.0

    if ref_text in PHONETIC_STOP_WORDS:
        return 0.0, 0.0

    if asr_text in PHONETIC_STOP_WORDS:
        return 0.0, 0.0

    spelling_score = SequenceMatcher(
        None, ref_text, asr_text
    ).ratio()

    ref_codes = metaphone_codes(ref_text)
    asr_codes = metaphone_codes(asr_text)

    phonetic_score = 0.0

    for ref_code in ref_codes:
        for asr_code in asr_codes:
            score = SequenceMatcher(
                None, ref_code, asr_code
            ).ratio()

            phonetic_score = max(phonetic_score, score)

    return spelling_score, phonetic_score


# ------------------------------------------------------------
# Candidate classification
# ------------------------------------------------------------

def orthographic_forms(word):
    """Return common spelling and inflection forms of a word."""

    forms = {word}

    if word.endswith("'s") and len(word) > 3:
        forms.add(word[:-2])

    if word.endswith("'ve") and len(word) > 4:
        forms.add(word[:-3])

    if word.endswith("'re") and len(word) > 4:
        forms.add(word[:-3])

    if word.endswith("'ll") and len(word) > 4:
        forms.add(word[:-3])

    if word.endswith("ies") and len(word) > 4:
        forms.add(word[:-3] + "y")

    if word.endswith("es") and len(word) > 4:
        forms.add(word[:-2])

    if word.endswith("s") and len(word) > 3:
        forms.add(word[:-1])

    if word.endswith("ed") and len(word) > 4:
        forms.add(word[:-2])

    if word.endswith("d") and len(word) > 3:
        forms.add(word[:-1])

    if word.endswith("ing") and len(word) > 5:
        stem = word[:-3]
        forms.add(stem)
        forms.add(stem + "e")

    return forms


def is_orthographic_variant(reference_text, asr_text, spelling_score):
    if spelling_score >= ORTHOGRAPHIC_SIMILARITY:
        return True

    ref_forms = orthographic_forms(reference_text)
    asr_forms = orthographic_forms(asr_text)

    return bool(ref_forms & asr_forms)


def is_compound_or_partial(reference_text, asr_text):
    """Detect one word contained within another, allowing simple plurals."""

    ref_forms = orthographic_forms(reference_text)
    asr_forms = orthographic_forms(asr_text)

    for ref_form in ref_forms:
        for asr_form in asr_forms:
            if ref_form == asr_form:
                continue

            if len(ref_form) < MIN_COMPOUND_LENGTH:
                continue

            if len(asr_form) < MIN_COMPOUND_LENGTH:
                continue

            if ref_form in asr_form or asr_form in ref_form:
                return True

    return False


def classify_candidate(ref_word, asr_word, spelling_score, phonetic_score):
    ref_text = ref_word["normalized"]
    asr_text = asr_word["normalized"]

    if is_compound_or_partial(ref_text, asr_text):
        return "compound"

    if is_orthographic_variant(
        ref_text,
        asr_text,
        spelling_score
    ):
        return "orthographic"

    return "phonetic"


# ------------------------------------------------------------
# Find phonetic and spelling candidates
# ------------------------------------------------------------

def find_phonetic_candidates(operations, reference, parakeet):
    """Find possible counterparts among unmatched words."""

    missing_words = []
    extra_words = []

    for tag, ref_index, asr_index in operations:
        if tag == "delete":
            missing_words.append(reference[ref_index])

        elif tag == "insert":
            extra_words.append(parakeet[asr_index])

    candidates = []

    for ref_word in missing_words:
        for asr_word in extra_words:
            distance = temporal_distance(ref_word, asr_word)

            if distance > PHONETIC_MAX_DISTANCE:
                continue

            spelling_score, phonetic_score = phonetic_similarity(
                ref_word, asr_word
            )

            if (
                spelling_score < MIN_SPELLING_SIMILARITY
                and phonetic_score < MIN_PHONETIC_SIMILARITY
            ):
                continue

            category = classify_candidate(
                ref_word,
                asr_word,
                spelling_score,
                phonetic_score
            )

            score = max(spelling_score, phonetic_score)

            candidates.append({
                "reference": ref_word,
                "parakeet": asr_word,
                "spelling": spelling_score,
                "phonetic": phonetic_score,
                "score": score,
                "distance": distance,
                "category": category,
            })

    # Prefer stronger similarities, then closer timestamps.
    candidates.sort(
        key=lambda item: (
            -item["score"],
            item["distance"]
        )
    )

    # Each unmatched word can appear in only one candidate.
    selected = []
    used_reference = set()
    used_parakeet = set()

    for candidate in candidates:
        ref_index = candidate["reference"]["global_index"]
        asr_index = candidate["parakeet"]["global_index"]

        if ref_index in used_reference:
            continue

        if asr_index in used_parakeet:
            continue

        selected.append(candidate)
        used_reference.add(ref_index)
        used_parakeet.add(asr_index)

    selected.sort(
        key=lambda item: midpoint(item["parakeet"])
    )

    return selected


# ------------------------------------------------------------
# Discrepancy and context utilities
# ------------------------------------------------------------

def describe_words(words):
    if not words:
        return "(none)"

    return " ".join(word["word"] for word in words)


def time_range(words):
    if not words:
        return "unknown"

    start = min(word["start"] for word in words)
    end = max(word["end"] for word in words)

    return f"{format_time(start)} - {format_time(end)}"


def split_word_runs(words, max_gap=SPLIT_GAP_SECONDS):
    if not words:
        return []

    runs = []
    current = [words[0]]

    for word in words[1:]:
        previous = current[-1]
        gap = word["start"] - previous["end"]

        if gap > max_gap:
            runs.append(current)
            current = [word]
        else:
            current.append(word)

    runs.append(current)
    return runs


def make_difference(tag, words, all_words):
    indices = [word["global_index"] for word in words]
    first = min(indices)
    last = max(indices)

    left = max(0, first - CONTEXT_WORDS)
    right = min(len(all_words), last + 1 + CONTEXT_WORDS)

    before = describe_words(all_words[left:first])
    affected = describe_words(words)
    after = describe_words(all_words[last + 1:right])

    return {
        "tag": tag,
        "start": min(word["start"] for word in words),
        "end": max(word["end"] for word in words),
        "text": affected,
        "before": before,
        "after": after,
        "time": time_range(words),
        "count": len(words),
    }


# ------------------------------------------------------------
# Collect discrepancies
# ------------------------------------------------------------

def collect_differences(operations, reference, parakeet):
    differences = []
    missing_words = []
    extra_words = []
    matching = 0

    for tag, ref_index, asr_index in operations:
        if tag == "equal":
            matching += 1

        elif tag == "delete":
            missing_words.append(reference[ref_index])

        elif tag == "insert":
            extra_words.append(parakeet[asr_index])

    for run in split_word_runs(missing_words):
        differences.append(
            make_difference("delete", run, reference)
        )

    for run in split_word_runs(extra_words):
        differences.append(
            make_difference("insert", run, parakeet)
        )

    differences.sort(key=lambda item: item["start"])

    return (
        differences,
        matching,
        len(missing_words),
        len(extra_words)
    )


# ------------------------------------------------------------
# Write comparison report
# ------------------------------------------------------------

def write_candidate_section(report, title, candidates):
    report.write(f"\n\n{title}\n")
    report.write("=" * 72 + "\n")

    if not candidates:
        report.write("No candidates found.\n")
        return

    for number, candidate in enumerate(candidates, start=1):
        ref_word = candidate["reference"]
        asr_word = candidate["parakeet"]

        report.write(f"\n[{number}] ")
        report.write(
            f"{ref_word['word']}  <->  {asr_word['word']}\n"
        )
        report.write(
            f"    Reference cue: "
            f"{format_time(ref_word['start'])} - "
            f"{format_time(ref_word['end'])}\n"
        )
        report.write(
            f"    Parakeet time: "
            f"{format_time(asr_word['start'])} - "
            f"{format_time(asr_word['end'])}\n"
        )
        report.write(
            f"    Spelling similarity: "
            f"{candidate['spelling']:.2f}\n"
        )
        report.write(
            f"    Phonetic similarity: "
            f"{candidate['phonetic']:.2f}\n"
        )
        report.write(
            f"    Time distance: "
            f"{candidate['distance']:.2f} seconds\n"
        )


def write_report(
    output_path,
    ass_path,
    json_path,
    cues,
    reference,
    parakeet,
    differences,
    matching,
    missing,
    extra,
    phonetic_candidates
):
    orthographic = [
        item for item in phonetic_candidates
        if item["category"] == "orthographic"
    ]

    phonetic = [
        item for item in phonetic_candidates
        if item["category"] == "phonetic"
    ]

    compound = [
        item for item in phonetic_candidates
        if item["category"] == "compound"
    ]

    with open(output_path, "w", encoding="utf-8") as report:
        report.write("SUBTITLE COMPARISON REPORT - VERSION 6\n")
        report.write("=" * 72 + "\n\n")

        report.write(f"Reference file: {ass_path.name}\n")
        report.write(f"Parakeet file:  {json_path.name}\n\n")

        report.write("SUMMARY\n")
        report.write("-" * 72 + "\n")
        report.write(f"ASS dialogue cues:          {len(cues)}\n")
        report.write(f"Reference words:            {len(reference)}\n")
        report.write(f"Parakeet words:             {len(parakeet)}\n")
        report.write(f"Matching words:             {matching}\n")
        report.write(f"Missing words:              {missing}\n")
        report.write(f"Parakeet-only words:        {extra}\n")
        report.write(f"Difference sections:        {len(differences)}\n")
        report.write(f"All candidate suggestions:  {len(phonetic_candidates)}\n")
        report.write(f"  Orthographic variants:    {len(orthographic)}\n")
        report.write(f"  Phonetic candidates:      {len(phonetic)}\n")
        report.write(f"  Compound/partial:          {len(compound)}\n")

        report.write("\nALIGNMENT METHOD\n")
        report.write("-" * 72 + "\n")
        report.write(
            "The complete reference and Parakeet word sequences are "
            "aligned chronologically.\n"
        )
        report.write(
            "Exact normalized words may match across ASS cue boundaries.\n"
        )
        report.write(
            f"A match is rejected when its timestamp is more than "
            f"{MAX_MATCH_DISTANCE:.2f} seconds from its reference cue.\n"
        )
        report.write(
            "Missing reference words and Parakeet-only words are "
            "reported independently.\n"
        )
        report.write(
            "Unmatched passages are split at substantial time gaps.\n"
        )
        report.write(
            "The displayed discrepancy text contains only unmatched words; "
            "context is shown separately.\n"
        )
        report.write("Punctuation is ignored during word comparison.\n")
        report.write(
            "Candidate suggestions do not change alignment results "
            "or matching counts.\n"
        )
        report.write("All discrepancies require human review.\n")

        report.write("\n\nDIFFERENCES\n")
        report.write("=" * 72 + "\n")

        for number, difference in enumerate(differences, start=1):
            report.write(
                f"\n[{number}] "
                f"{format_time(difference['start'])} - "
                f"{format_time(difference['end'])}\n"
            )

            if difference["tag"] == "delete":
                report.write(
                    "Type: REFERENCE ONLY (possibly missed)\n"
                )
                report.write(f"Words: {difference['count']}\n\n")
                report.write("REFERENCE:\n")

            else:
                report.write(
                    "Type: PARAKEET ONLY (possibly additional dialogue)\n"
                )
                report.write(f"Words: {difference['count']}\n\n")
                report.write("PARAKEET:\n")

            report.write(f"  Time:   {difference['time']}\n")
            report.write(f"  Before: {difference['before']}\n")
            report.write(f"  Text:   {difference['text']}\n")
            report.write(f"  After:  {difference['after']}\n")
            report.write("\n" + "-" * 72 + "\n")

        report.write("\n\nCANDIDATE SUGGESTIONS\n")
        report.write("=" * 72 + "\n")
        report.write(
            "These are unmatched words that may represent the same "
            "spoken word or expression.\n"
        )
        report.write(
            "They are suggestions only. Listen to the audio before "
            "making corrections.\n"
        )
        report.write(
            "No candidate is automatically substituted into either "
            "transcription.\n"
        )

        write_candidate_section(
            report,
            "ORTHOGRAPHIC VARIANTS",
            orthographic
        )

        write_candidate_section(
            report,
            "PHONETIC CANDIDATES",
            phonetic
        )

        write_candidate_section(
            report,
            "POSSIBLE COMPOUND/PARTIAL MATCHES",
            compound
        )


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Compare Parakeet transcription against ASS subtitles "
            "using chronological alignment and candidate suggestions."
        )
    )

    parser.add_argument(
        "json_file",
        help="Parakeet JSON transcription file"
    )

    parser.add_argument(
        "ass_file",
        help="Original ASS subtitle file"
    )

    args = parser.parse_args()

    json_path = Path(args.json_file)
    ass_path = Path(args.ass_file)

    if not json_path.exists():
        parser.error(f"JSON file not found: {json_path}")

    if not ass_path.exists():
        parser.error(f"ASS file not found: {ass_path}")

    output_path = json_path.with_name(
        json_path.stem + "_comparison.txt"
    )

    print("Reading original subtitles...")
    cues, reference = read_ass(ass_path)

    print("Reading Parakeet transcription...")
    parakeet = read_parakeet(json_path)

    print(f"ASS cues:        {len(cues)}")
    print(f"Reference words: {len(reference)}")
    print(f"Parakeet words:  {len(parakeet)}")
    print()

    operations = align_words(reference, parakeet)

    differences, matching, missing, extra = collect_differences(
        operations,
        reference,
        parakeet
    )

    print()
    print("Finding possible phonetic matches...")

    phonetic_candidates = find_phonetic_candidates(
        operations,
        reference,
        parakeet
    )

    orthographic = sum(
        1 for item in phonetic_candidates
        if item["category"] == "orthographic"
    )

    phonetic = sum(
        1 for item in phonetic_candidates
        if item["category"] == "phonetic"
    )

    compound = sum(
        1 for item in phonetic_candidates
        if item["category"] == "compound"
    )

    print(f"Found {len(phonetic_candidates)} candidate suggestions.")
    print(f"  Orthographic variants: {orthographic}")
    print(f"  Phonetic candidates:   {phonetic}")
    print(f"  Compound/partial:      {compound}")

    print()
    print("Writing comparison report...")

    write_report(
        output_path,
        ass_path,
        json_path,
        cues,
        reference,
        parakeet,
        differences,
        matching,
        missing,
        extra,
        phonetic_candidates
    )

    print()
    print("Comparison complete.")
    print(f"Matching words:      {matching}")
    print(f"Missing words:       {missing}")
    print(f"Parakeet-only words: {extra}")
    print(f"Difference sections: {len(differences)}")
    print(f"Candidate suggestions: {len(phonetic_candidates)}")
    print()
    print(f"Report written to: {output_path}")


if __name__ == "__main__":
    main()

