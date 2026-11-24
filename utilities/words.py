
import json

# Load the recognition results.
with open("Angel_test.json", encoding="utf-8") as f:
    data = json.load(f)

# The audio sample starts 10 seconds into the episode.
offset = data["source_offset_seconds"]

words = []

# Reassemble model tokens into complete words.
for token, start, duration in zip(
    data["tokens"],
    data["timestamps"],
    data["durations"]
):
    absolute_start = start + offset
    absolute_end = start + duration + offset

    # A leading space indicates the beginning of a new word.
    if token.startswith(" ") or not words:
        words.append({
            "text": token.strip(),
            "start": absolute_start,
            "end": absolute_end
        })
    else:
        # Append this token to the current word.
        words[-1]["text"] += token

        # Extend the word's ending time if necessary.
        words[-1]["end"] = max(
            words[-1]["end"],
            absolute_end
        )

# Display the reconstructed words and their episode timestamps.
for word in words:
    print(
        f'{word["start"]:7.2f} - {word["end"]:7.2f}  '
        f'{word["text"]}'
    )

print(f"\nReconstructed {len(words)} words.")

