
#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path


# ------------------------------------------------------------
# Time and text utilities
# ------------------------------------------------------------

def ass_time_to_seconds(value):
    hours, minutes, seconds = value.split(":")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + float(seconds)
    )


def format_time(seconds):
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes:02d}:{secs:05.2f}"


def clean_ass_text(text):
    text = re.sub(r"\{[^}]*\}", "", text)
    text = text.replace(r"\N", " ")
    text = text.replace(r"\n", " ")
    text = text.replace(r"\h", " ")
    return text.strip()


# ------------------------------------------------------------
# Read ASS cues
# ------------------------------------------------------------

def read_ass(filename):
    cues = []

    with open(filename, "r", encoding="utf-8-sig") as file:
        for line in file:

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

            cues.append({
                "start": start,
                "end": end,
                "text": clean_ass_text(fields[9]),
                "raw": fields[9],
            })

    return cues


# ------------------------------------------------------------
# Read and reconstruct Parakeet words
# ------------------------------------------------------------

def read_parakeet(filename):
    with open(filename, "r", encoding="utf-8") as file:
        data = json.load(file)

    words = []

    current_text = ""
    current_start = None
    current_end = None

    def save_word():
        nonlocal current_text, current_start, current_end

        if current_text:
            found = re.findall(
                r"[^\W_]+(?:['’][^\W_]+)*",
                current_text,
                re.UNICODE
            )

            for word in found:
                words.append({
                    "word": word,
                    "start": current_start,
                    "end": current_end,
                })

        current_text = ""
        current_start = None
        current_end = None

    for token, timestamp, duration in zip(
        data["tokens"],
        data["timestamps"],
        data["durations"]
    ):

        start = float(timestamp)
        end = start + float(duration)

        if token and token[0].isspace():
            save_word()

            current_text = token.strip()
            current_start = start
            current_end = end

        else:
            if not current_text:
                current_text = token.strip()
                current_start = start
                current_end = end
            else:
                current_text += token
                current_end = end

    save_word()

    return words


# ------------------------------------------------------------
# Display diagnostics
# ------------------------------------------------------------

def inspect_window(start, end, cues, words):

    print()
    print("=" * 78)
    print(f"WINDOW: {format_time(start)} - {format_time(end)}")
    print("=" * 78)

    print()
    print("ORIGINAL ASS CUES")
    print("-" * 78)

    for cue in cues:
        if cue["end"] < start or cue["start"] > end:
            continue

        print(
            f"{format_time(cue['start'])} - "
            f"{format_time(cue['end'])}  "
            f"{cue['text']}"
        )

    print()
    print("PARAKEET WORDS")
    print("-" * 78)

    for word in words:
        midpoint = (word["start"] + word["end"]) / 2

        if start <= midpoint <= end:
            print(
                f"{word['start']:8.2f} - "
                f"{word['end']:8.2f}  "
                f"{word['word']}"
            )


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description="Inspect ASS and Parakeet timing around selected passages."
    )

    parser.add_argument("json_file")
    parser.add_argument("ass_file")

    args = parser.parse_args()

    json_path = Path(args.json_file)
    ass_path = Path(args.ass_file)

    if not json_path.exists():
        parser.error(f"JSON file not found: {json_path}")

    if not ass_path.exists():
        parser.error(f"ASS file not found: {ass_path}")

    print("Reading ASS subtitles...")
    cues = read_ass(ass_path)

    print("Reading Parakeet transcription...")
    words = read_parakeet(json_path)

    print(f"ASS cues: {len(cues)}")
    print(f"Parakeet words: {len(words)}")

    inspect_window(50, 65, cues, words)
    inspect_window(295, 322, cues, words)

    print()
    print("Inspection complete.")


if __name__ == "__main__":
    main()

