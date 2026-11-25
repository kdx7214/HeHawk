
import argparse
import time
from pathlib import Path

import soundfile as sf
import torch

from huggingface_hub import get_token
from pyannote.audio import Pipeline


MODEL = "pyannote/speaker-diarization-community-1"
THREADS = 8


def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60

    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


def main():
    parser = argparse.ArgumentParser(
        description="CHIRP V1 - Speaker diarization experiment"
    )

    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--source-offset",
        type=float,
        default=0.0
    )

    args = parser.parse_args()

    torch.set_num_threads(THREADS)

    token = get_token()

    if not token:
        raise RuntimeError(
            "No Hugging Face token found. Run hf auth login."
        )

    print("CHIRP V1 - Speaker diarization")
    print(f"Model: {MODEL}")
    print(f"CPU threads: {THREADS}")
    print()

    print("Loading diarization pipeline...")

    pipeline = Pipeline.from_pretrained(
        MODEL,
        token=token
    )

    pipeline.to(torch.device("cpu"))

    print("Pipeline loaded.")
    print("Reading audio...")

    audio, sample_rate = sf.read(
        args.input,
        dtype="float32",
        always_2d=True
    )

    waveform = torch.from_numpy(audio.T.copy())

    duration = waveform.shape[1] / sample_rate

    print(f"Sample rate: {sample_rate}")
    print(f"Channels: {waveform.shape[0]}")
    print(f"Duration: {duration:.3f} seconds")
    print("Running speaker diarization...")
    print()

    started = time.perf_counter()

    result = pipeline({
        "waveform": waveform,
        "sample_rate": sample_rate
    }, num_speakers=3)


    elapsed = time.perf_counter() - started

    for title, annotation in (
        ("REGULAR DIARIZATION", result.speaker_diarization),
        ("EXCLUSIVE DIARIZATION",
         result.exclusive_speaker_diarization)
    ):
        print("=" * 72)
        print(title)
        print("=" * 72)

        for segment, _, speaker in annotation.itertracks(
            yield_label=True
        ):
            start = segment.start + args.source_offset
            end = segment.end + args.source_offset

            print(
                f"{format_time(start)} - "
                f"{format_time(end)}  "
                f"{speaker}"
            )

        print()
        print(f"Speakers detected: {len(annotation.labels())}")
        print()

    print(f"Processing time: {elapsed:.2f} seconds")
    print(f"Real-time factor: {elapsed / duration:.3f}")


if __name__ == "__main__":
    main()

