
#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path


# ------------------------------------------------------------
# Command-line arguments
# ------------------------------------------------------------

parser = argparse.ArgumentParser(
    description="Convert Parakeet transcription JSON into SRT subtitles."
)

parser.add_argument(
    "input",
    help="Input JSON filename"
)

args = parser.parse_args()

INPUT_FILE = Path(args.input).expanduser()

if not INPUT_FILE.is_file():
    parser.error(f"Input file not found: {INPUT_FILE}")

OUTPUT_FILE = INPUT_FILE.with_suffix(".srt")


# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

MAX_LINE_LENGTH = 42
MAX_LINES = 2

# A pause this long normally starts a new caption.
PAUSE_BREAK = 0.65

# Minimum duration of a caption, in seconds.
MIN_CUE_DURATION = 0.60

# Small timing adjustment at the end of captions.
END_PADDING = 0.12


# ------------------------------------------------------------
# Load recognition data and reconstruct words
# ------------------------------------------------------------

with open(INPUT_FILE, encoding="utf-8") as f:
    data = json.load(f)

offset = data["source_offset_seconds"]
from word_timing import word_groups

words = [dict(text=w, start=s+offset, end=e+offset)
         for w, a, b, s, e in word_groups(data['tokens'], data['timestamps'],
                                         data['durations'], 0, len(data['tokens']))]


# ------------------------------------------------------------
# Text formatting helpers
# ------------------------------------------------------------

def wrap_text(text):
    """Wrap text into lines without splitting words."""

    lines = []
    current_line = ""

    for word in text.split():
        if not current_line:
            current_line = word
        elif len(current_line) + len(word) + 1 <= MAX_LINE_LENGTH:
            current_line += " " + word
        else:
            lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def is_sentence_end(word):
    """Recognize common sentence-ending punctuation."""

    return bool(re.search(r'[.!?]["\')\]]*$', word))


def group_text(group):
    return " ".join(word["text"] for word in group)


# ------------------------------------------------------------
# Build subtitle groups
# ------------------------------------------------------------

groups = []
current = []

for word in words:

    if not current:
        current.append(word)
        continue

    previous = current[-1]

    current_text = group_text(current)
    candidate_text = current_text + " " + word["text"]

    candidate_lines = wrap_text(candidate_text)

    pause = word["start"] - previous["end"]

    # A sentence ending is a strong boundary.
    sentence_break = is_sentence_end(previous["text"])

    # A substantial pause is also a natural boundary.
    pause_break = pause >= PAUSE_BREAK

    # Don't allow captions to exceed two lines.
    length_break = len(candidate_lines) > MAX_LINES

    if sentence_break or pause_break or length_break:
        groups.append(current)
        current = [word]
    else:
        current.append(word)

if current:
    groups.append(current)


# ------------------------------------------------------------
# Convert seconds to SRT timestamps
# ------------------------------------------------------------

def srt_timestamp(seconds):
    milliseconds = round(seconds * 1000)

    hours = milliseconds // 3600000
    milliseconds %= 3600000

    minutes = milliseconds // 60000
    milliseconds %= 60000

    seconds_part = milliseconds // 1000
    milliseconds %= 1000

    return (
        f"{hours:02}:"
        f"{minutes:02}:"
        f"{seconds_part:02},"
        f"{milliseconds:03}"
    )


# ------------------------------------------------------------
# Write subtitle file
# ------------------------------------------------------------

subtitles = []

for index, group in enumerate(groups):

    text = group_text(group)
    lines = wrap_text(text)

    start = group[0]["start"]
    end = group[-1]["end"] + END_PADDING

    # Avoid overlap with the next caption.
    if index + 1 < len(groups):
        next_start = groups[index + 1][0]["start"]
        end = min(end, next_start - 0.02)

    # Ensure a minimum display duration.
    end = max(end, start + MIN_CUE_DURATION)

    subtitles.append(
        f"{index + 1}\n"
        f"{srt_timestamp(start)} --> {srt_timestamp(end)}\n"
        f"{chr(10).join(lines)}"
    )

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n\n".join(subtitles))
    f.write("\n")

print(f"Created {OUTPUT_FILE}")
print(f"Words processed: {len(words)}")
print(f"Subtitle cues:   {len(subtitles)}")

