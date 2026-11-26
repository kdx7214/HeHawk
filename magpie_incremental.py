
#!/usr/bin/env python3
"""MAGPIE 7A: incremental missing-dialogue comparison."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from magpie import recognition_words
from compare import tokenize, normalize_word


TIME_PATTERN = re.compile(
    r"(\d{2,}):(\d{2}):(\d{2}),(\d{3})"
)

TIMING_TOLERANCE = 0.500


def read_input(path):
    raw = path.read_bytes()

    return raw, hashlib.sha256(raw).hexdigest()


def timestamp(seconds):
    ms = round(seconds * 1000)

    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)

    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def parse_time(value):
    match = TIME_PATTERN.fullmatch(value.strip())

    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value}")

    h, m, s, ms = map(int, match.groups())

    if m >= 60 or s >= 60:
        raise ValueError(f"Invalid SRT timestamp: {value}")

    return h * 3600 + m * 60 + s + ms / 1000


def normalized_words(text):
    return [
        normalize_word(word)
        for word in tokenize(text)
    ]


# ------------------------------------------------------------
# Read previously acquired SRT evidence.
# ------------------------------------------------------------

def parse_srt(raw):
    text = raw.decode("utf-8-sig")
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    cues = []
    seen = set()

    for block in re.split(r"\n[ \t]*\n", text.strip()):

        lines = block.splitlines()

        if len(lines) < 3:
            raise ValueError(f"Malformed SRT block: {block!r}")

        cue_id = int(lines[0].strip())

        if cue_id in seen:
            raise ValueError(f"Duplicate cue ID: {cue_id}")

        seen.add(cue_id)

        start_text, end_text = lines[1].split("-->")

        start = parse_time(start_text)
        end = parse_time(end_text)

        if end <= start:
            raise ValueError(f"Invalid duration: cue {cue_id}")

        dialogue = " ".join(lines[2:]).strip()

        # Remove conventional SRT formatting tags.
        comparison_text = re.sub(r"<[^>]+>", "", dialogue)

        cues.append({
            "id": cue_id,
            "start": start,
            "end": end,
            "text": dialogue,
            "words": normalized_words(comparison_text),
        })

    return sorted(
        cues,
        key=lambda cue: (cue["start"], cue["id"])
    )


# ------------------------------------------------------------
# Reconstruct episode-relative recognition evidence.
# ------------------------------------------------------------

def load_recognition(data):

    if data["schema"] != "hehawk.tern.recognition":
        raise ValueError("Unexpected recognition schema.")

    if data["version"] != 1:
        raise ValueError("Unsupported recognition version.")

    if data["timestamp_basis"] != "segment_relative":
        raise ValueError("Unexpected timestamp basis.")

    rate = data["sample_rate"]
    source_samples = data["source_samples"]

    if rate != 16000 or source_samples <= 0:
        raise ValueError("Invalid source geometry.")

    result = []
    previous_end = 0
    seen = set()

    for segment in data["segments"]:

        sid = segment["id"]
        a = segment["start_sample"]
        b = segment["end_sample"]

        if sid in seen:
            raise ValueError(f"Duplicate segment: {sid}")

        seen.add(sid)

        if a != previous_end or b <= a or b > source_samples:
            raise ValueError(f"Invalid segment geometry: {sid}")

        previous_end = b

        offset = a / rate

        local = {
            "tokens": segment["tokens"],
            "timestamps": segment["timestamps"],
            "durations": segment["durations"],
            "source_offset_seconds": 0,
        }

        words = recognition_words(local)

        for word in words:

            word["start"] += offset
            word["end"] += offset
            word["segment_id"] = sid

            result.append(word)

    if previous_end != source_samples:
        raise ValueError("Incomplete episode coverage.")

    result.sort(key=lambda word: word["start"])

    for index, word in enumerate(result):
        word["global_index"] = index

    return result


# ------------------------------------------------------------
# Longest common subsequence.
#
# Used only to quantify partial agreement.
# Full corroboration requires contiguous words.
# ------------------------------------------------------------

def lcs_length(a, b):

    previous = [0] * (len(b) + 1)

    for word_a in a:

        current = [0]

        for j, word_b in enumerate(b, 1):

            if word_a == word_b:
                current.append(previous[j - 1] + 1)
            else:
                current.append(
                    max(previous[j], current[j - 1])
                )

        previous = current

    return previous[-1]


# ------------------------------------------------------------
# Compare one previously acquired cue.
# ------------------------------------------------------------

def compare_cue(cue, recognition, tolerance):

    expected = cue["words"]

    window_start = max(0, cue["start"] - tolerance)
    window_end = cue["end"] + tolerance

    nearby = [
        word for word in recognition
        if word["end"] > window_start
        and word["start"] < window_end
    ]

    observed = [
        word["normalized"]
        for word in nearby
    ]

    matches = []

    if expected:

        for i in range(len(observed) - len(expected) + 1):

            if observed[i:i + len(expected)] != expected:
                continue

            group = nearby[i:i + len(expected)]

            # Do not match across skipped recognition words.
            indices = [w["global_index"] for w in group]

            if indices != list(
                range(indices[0], indices[0] + len(indices))
            ):
                continue

            start = min(w["start"] for w in group)
            end = max(w["end"] for w in group)

            # Require the entire match to fit the window.
            if start < window_start or end > window_end:
                continue

            matches.append({
                "start": start,
                "end": end,
                "start_shift": start - cue["start"],
                "end_shift": end - cue["end"],
                "words": group,
            })

    matched_count = lcs_length(expected, observed)

    if not expected:
        status = "nonlexical"

    elif matches:
        status = "corroborated"

    elif not observed:
        status = "absent"

    elif matched_count:
        status = "partial"

    else:
        status = "competing"

    return {
        "cue": cue,
        "status": status,
        "short_circuit_eligible": (
            status == "corroborated"
            and len(matches) == 1
        ),
        "window_start": window_start,
        "window_end": window_end,
        "expected_word_count": len(expected),
        "nearby_word_count": len(observed),
        "partial_match_count": matched_count,
        "exact_match_count": len(matches),
        "exact_matches": matches,
        "nearby_recognition": nearby,
        "human_verified": False,
    }


# ------------------------------------------------------------
# Main.
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument("previous_srt", type=Path)
    parser.add_argument("recognition", type=Path)

    parser.add_argument(
        "--tolerance",
        type=float,
        default=TIMING_TOLERANCE
    )

    parser.add_argument(
        "--json",
        required=True,
        type=Path
    )

    args = parser.parse_args()

    if not 0 <= args.tolerance <= 5:
        parser.error("Tolerance must be between 0 and 5 seconds.")

    if args.json.exists():
        parser.error("Output already exists.")

    srt_raw, srt_hash = read_input(args.previous_srt)
    asr_raw, asr_hash = read_input(args.recognition)

    cues = parse_srt(srt_raw)
    evidence = json.loads(asr_raw)

    recognition = load_recognition(evidence)

    duration = (
        evidence["source_samples"]
        / evidence["sample_rate"]
    )

    for cue in cues:
        if cue["end"] > duration:
            raise ValueError(
                f"Cue {cue['id']} exceeds source duration."
            )

    rows = [
        compare_cue(
            cue,
            recognition,
            args.tolerance
        )
        for cue in cues
    ]

    counts = Counter(
        row["status"] for row in rows
    )

    eligible = sum(
        row["short_circuit_eligible"]
        for row in rows
    )

    ambiguous = sum(
        row["exact_match_count"] > 1
        for row in rows
    )

    print("MAGPIE INCREMENTAL COMPARISON")
    print("=" * 64)
    print(f"Previously acquired cues: {len(cues)}")
    print(f"New recognition words:    {len(recognition)}")
    print(f"Timing tolerance:         {args.tolerance:.3f}s")

    print()
    print("CLASSIFICATIONS")
    print("=" * 64)

    for status in (
        "corroborated",
        "partial",
        "competing",
        "absent",
        "nonlexical",
    ):
        print(f"{status:20s}: {counts[status]}")

    print()
    print(f"Ambiguous exact matches: {ambiguous}")
    print(f"Short-circuit eligible:  {eligible}")
    print(f"Further investigation:   {len(cues) - eligible}")

    if cues:
        print(
            f"Short-circuit rate:      "
            f"{100 * eligible / len(cues):.2f}%"
        )

    print()
    print("UNRESOLVED CANDIDATES (NO DIALOGUE)")
    print("=" * 64)

    for row in rows:

        if row["short_circuit_eligible"]:
            continue

        cue = row["cue"]

        print(
            f"Cue {cue['id']:3d}  "
            f"{timestamp(cue['start'])} - "
            f"{timestamp(cue['end'])}  "
            f"{row['status']:13s}  "
            f"matched={row['partial_match_count']}/"
            f"{row['expected_word_count']}  "
            f"nearby={row['nearby_word_count']}"
        )

    output = {
        "schema": "hehawk.magpie.incremental",
        "version": 1,
        "timestamp_basis": "episode",
        "source_sha256": evidence["source_sha256"],
        "inputs": {
            "previous_srt": {
                "path": str(args.previous_srt),
                "sha256": srt_hash,
            },
            "recognition": {
                "path": str(args.recognition),
                "sha256": asr_hash,
            },
        },
        "settings": {
            "timing_tolerance_seconds": args.tolerance,
            "exact_match_requires_contiguous_words": True,
            "ambiguous_matches_short_circuit": False,
            "srt_source_identity_verified": False,
            "human_verification_available": False,
        },
        "statistics": {
            "previous_cues": len(cues),
            "recognition_words": len(recognition),
            "classifications": dict(counts),
            "ambiguous_matches": ambiguous,
            "short_circuit_eligible": eligible,
            "further_investigation": len(cues) - eligible,
        },
        "candidates": rows,
    }

    for path, expected_hash in (
        (args.previous_srt, srt_hash),
        (args.recognition, asr_hash),
    ):

        _, current_hash = read_input(path)

        if current_hash != expected_hash:
            raise RuntimeError(f"Input changed: {path}")

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
    print(f"Saved: {args.json}")
    print("Comparison completed successfully.")


if __name__ == "__main__":
    main()
