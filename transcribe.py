
#!/usr/bin/env python3

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

import sherpa_onnx
import soundfile as sf


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

MODEL = Path(
    "models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
)

CHUNK_SECONDS = 300
SAMPLE_RATE = 16000
NUM_THREADS = 8


# ------------------------------------------------------------
# Command-line arguments
# ------------------------------------------------------------

parser = argparse.ArgumentParser(
    description="Transcribe an audio or video file using Parakeet."
)

parser.add_argument(
    "input",
    help="Input audio or video filename"
)

parser.add_argument(
    "--limit-seconds",
    type=float,
    default=None,
    help="Only process this many seconds (for testing)"
)

args = parser.parse_args()

input_file = Path(args.input).expanduser()

if not input_file.is_file():
    parser.error(f"Input file not found: {input_file}")

if args.limit_seconds is not None and args.limit_seconds <= 0:
    parser.error("--limit-seconds must be greater than zero")

output_file = input_file.with_suffix(".json")


# ------------------------------------------------------------
# Load the Parakeet model
# ------------------------------------------------------------

print("Loading Parakeet model...")

recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
    encoder=str(MODEL / "encoder.int8.onnx"),
    decoder=str(MODEL / "decoder.int8.onnx"),
    joiner=str(MODEL / "joiner.int8.onnx"),
    tokens=str(MODEL / "tokens.txt"),
    num_threads=NUM_THREADS,
    provider="cpu",
    model_type="nemo_transducer",
)


print("Model loaded.")


# ------------------------------------------------------------
# Extract audio and recognize it
# ------------------------------------------------------------

with tempfile.TemporaryDirectory() as temp_dir:

    wav_file = Path(temp_dir) / "audio.wav"

    print("Extracting audio...")

    command = [
        "ffmpeg",
        "-y",
        "-i", str(input_file),
        "-map", "0:a:0",
        "-vn",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_s16le",
    ]

    if args.limit_seconds is not None:
        command.extend([
            "-t", str(args.limit_seconds)
        ])

    command.append(str(wav_file))

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    print("Reading audio...")

    audio, sample_rate = sf.read(
        wav_file,
        dtype="float32"
    )

    total_samples = len(audio)
    duration = total_samples / sample_rate

    print(f"Audio duration: {duration:.1f} seconds")

    # --------------------------------------------------------
    # Calculate chunk positions
    # --------------------------------------------------------

    chunk_samples = CHUNK_SECONDS * SAMPLE_RATE

    chunk_starts = list(
        range(0, total_samples, chunk_samples)
    )

    # Discard a tiny trailing fragment.
    # Parakeet cannot reliably process extremely short chunks.

    if len(chunk_starts) > 1:
        remaining = total_samples - chunk_starts[-1]

        if remaining < SAMPLE_RATE:
            chunk_starts.pop()

    total_chunks = len(chunk_starts)

    print(f"Processing {total_chunks} chunks...")

    # --------------------------------------------------------
    # Recognize audio chunks
    # --------------------------------------------------------

    all_tokens = []
    all_timestamps = []
    all_durations = []
    all_text = []

    start_time = time.perf_counter()

    for chunk_number, start_sample in enumerate(
        chunk_starts,
        start=1
    ):

        end_sample = min(
            start_sample + chunk_samples,
            total_samples
        )

        chunk = audio[start_sample:end_sample]
        chunk_offset = start_sample / SAMPLE_RATE

        print(
            f"Chunk {chunk_number}/{total_chunks} "
            f"({chunk_offset:.1f} seconds)..."
        )

        stream = recognizer.create_stream()

        stream.accept_waveform(
            sample_rate,
            chunk
        )

        recognizer.decode_stream(stream)

        result = stream.result

        all_text.append(result.text)
        all_tokens.extend(result.tokens)

        all_timestamps.extend(
            timestamp + chunk_offset
            for timestamp in result.timestamps
        )

        all_durations.extend(result.durations)

    recognition_time = time.perf_counter() - start_time


# ------------------------------------------------------------
# Save results
# ------------------------------------------------------------

print("Saving transcription...")

output = {
    "text": " ".join(all_text),
    "tokens": all_tokens,
    "timestamps": all_timestamps,
    "durations": all_durations,
    "source_offset_seconds": 0.0,
}

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(
        output,
        f,
        ensure_ascii=False,
        indent=2
    )

print()
print("Transcription complete.")
print(f"Output: {output_file}")
print(f"Audio duration: {duration:.1f} seconds")
print(f"Recognition time: {recognition_time:.2f} seconds")
print(
    f"Processing speed: "
    f"{duration / recognition_time:.1f}x real time"
)

