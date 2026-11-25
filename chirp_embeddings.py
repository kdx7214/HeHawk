import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from huggingface_hub import get_token
from pyannote.audio import Model, Inference


MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"
THREADS = 8

# Absolute episode timestamps in seconds.

SAMPLES = [
    ("J1", "Judge",       902.1, 906.8),
    ("J2", "Judge",       915.4, 917.6),
    ("J3", "Judge",       955.4, 957.0),

    ("D1", "Defense",     907.3, 910.6),
    ("D2", "Defense",     933.0, 936.5),
    ("D3", "Defense",     937.0, 939.9),

    ("P1", "Prosecutor",  919.0, 922.2),
    ("P2", "Prosecutor",  942.0, 945.0),
    ("P3", "Prosecutor",  949.0, 953.0),
]


def main():
    parser = argparse.ArgumentParser(
        description="CHIRP speaker embedding experiment"
    )

    parser.add_argument("input", type=Path)

    parser.add_argument(
        "--source-offset",
        type=float,
        default=900.0
    )

    parser.add_argument(
        "--json",
        type=Path,
        required=True
    )

    args = parser.parse_args()

    if args.json.exists():
        raise FileExistsError(args.json)

    torch.set_num_threads(THREADS)

    print("CHIRP - Voice discrimination experiment")
    print(f"Model: {MODEL}")
    print(f"CPU threads: {THREADS}")
    print()

    audio, rate = sf.read(
        args.input,
        dtype="float32",
        always_2d=True
    )

    duration = len(audio) / rate

    print(f"Sample rate: {rate}")
    print(f"Audio duration: {duration:.3f}s")
    print()

    print("Loading embedding model...")

    model = Model.from_pretrained(
        MODEL,
        token=get_token()
    )

    inference = Inference(
        model,
        window="whole",
        device=torch.device("cpu")
    )

    print("Model loaded.")
    print()

    embeddings = []
    observations = []

    for label, speaker, start, end in SAMPLES:

        a = round(
            (start - args.source_offset) * rate
        )

        b = round(
            (end - args.source_offset) * rate
        )

        if not 0 <= a < b <= len(audio):
            raise ValueError(
                f"Sample {label} outside audio bounds"
            )

        waveform = torch.from_numpy(
            audio[a:b].T.copy()
        )

        print(
            f"{label}: {speaker:12s} "
            f"{start:.3f} - {end:.3f} "
            f"({(b - a) / rate:.2f}s)"
        )

        embedding = inference({
            "waveform": waveform,
            "sample_rate": rate
        })

        vector = np.asarray(
            embedding,
            dtype=np.float64
        ).reshape(-1)

        magnitude = np.linalg.norm(vector)

        if (
            not np.all(np.isfinite(vector))
            or magnitude <= 0
        ):
            raise ValueError(
                f"Invalid embedding for {label}"
            )

        vector = vector / magnitude

        embeddings.append(vector)

        observations.append({
            "id": label,
            "speaker": speaker,
            "start_seconds": start,
            "end_seconds": end,
            "embedding": vector.tolist()
        })

    vectors = np.stack(embeddings)

    similarity = np.clip(
        vectors @ vectors.T,
        -1.0,
        1.0
    )

    labels = [s[0] for s in SAMPLES]

    print()
    print("=" * 76)
    print("COSINE SIMILARITY MATRIX")
    print("=" * 76)
    print()

    print(
        "     " +
        "".join(f"{label:>7s}" for label in labels)
    )

    for i, label in enumerate(labels):
        print(
            f"{label:>4s} " +
            "".join(
                f"{value:7.3f}"
                for value in similarity[i]
            )
        )

    same = []
    different = []

    for i in range(len(SAMPLES)):
        for j in range(i + 1, len(SAMPLES)):

            value = float(similarity[i, j])

            if SAMPLES[i][1] == SAMPLES[j][1]:
                same.append(value)
            else:
                different.append(value)

    print()
    print("=" * 76)
    print("DISCRIMINATION STATISTICS")
    print("=" * 76)
    print()

    print("Same speaker:")
    print(f"  Minimum: {min(same):.4f}")
    print(f"  Maximum: {max(same):.4f}")
    print(f"  Mean:    {np.mean(same):.4f}")

    print()
    print("Different speakers:")
    print(f"  Minimum: {min(different):.4f}")
    print(f"  Maximum: {max(different):.4f}")
    print(f"  Mean:    {np.mean(different):.4f}")

    margin = min(same) - max(different)

    print()
    print(f"Separation margin: {margin:.4f}")

    print()
    print("=" * 76)
    print("NEAREST NEIGHBOR TEST")
    print("=" * 76)
    print()

    correct = 0

    for i, sample in enumerate(SAMPLES):

        scores = similarity[i].copy()
        scores[i] = -np.inf

        j = int(np.argmax(scores))

        match = sample[1] == SAMPLES[j][1]

        if match:
            correct += 1

        status = "CORRECT" if match else "WRONG"

        print(
            f"{sample[0]} -> {SAMPLES[j][0]} "
            f"({scores[j]:.4f}) {status}"
        )

    print()
    print(
        f"Correct nearest neighbors: "
        f"{correct}/{len(SAMPLES)}"
    )

    result = {
        "schema": "hehawk.chirp.embeddings",
        "schema_version": 1,
        "model": MODEL,
        "source": str(args.input),
        "source_offset_seconds": args.source_offset,
        "timestamp_basis": "episode",
        "sample_rate": rate,
        "embedding_dimensions": vectors.shape[1],
        "samples": observations,
        "similarity_matrix": similarity.tolist(),
        "statistics": {
            "same_speaker_min": min(same),
            "same_speaker_max": max(same),
            "same_speaker_mean": float(np.mean(same)),
            "different_speaker_min": min(different),
            "different_speaker_max": max(different),
            "different_speaker_mean": float(
                np.mean(different)
            ),
            "separation_margin": margin,
            "nearest_neighbor_correct": correct,
            "nearest_neighbor_total": len(SAMPLES)
        }
    }

    with args.json.open("x", encoding="utf-8") as f:
        json.dump(
            result,
            f,
            indent=2,
            allow_nan=False
        )

    print()
    print(f"Results saved to {args.json}")


if __name__ == "__main__":
    main()
