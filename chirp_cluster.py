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

# Original baseline diarization.
# Times are relative to the extracted audio.
#
# The original speaker assignments are retained
# for comparison only.

SEGMENTS = [
    (0.031,   1.938,   "SPEAKER_02"),
    (2.039,   6.933,   "SPEAKER_02"),
    (7.203,   10.713,  "SPEAKER_02"),
    (11.270,  14.881,  "SPEAKER_02"),
    (15.303,  17.733,  "SPEAKER_02"),
    (18.678,  22.306,  "SPEAKER_00"),
    (22.424,  30.980,  "SPEAKER_00"),
    (30.980,  31.874,  "SPEAKER_01"),
    (32.836,  40.008,  "SPEAKER_01"),
    (40.700,  41.594,  "SPEAKER_00"),
    (41.847,  54.537,  "SPEAKER_00"),
    (55.297,  57.102,  "SPEAKER_02"),
    (57.946,  59.397,  "SPEAKER_02"),
    (80.204,  80.778,  "SPEAKER_00"),
    (81.098,  84.878,  "SPEAKER_00"),
    (85.385,  86.532,  "SPEAKER_00"),
    (119.455, 119.978, "SPEAKER_00"),
]


def format_time(seconds):

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:06.3f}"
    )


def cluster_embeddings(similarity, threshold):

    clusters = [
        [i] for i in range(len(similarity))
    ]

    history = []

    while len(clusters) > 1:

        best_score = -np.inf
        best_pair = None

        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):

                a = clusters[i]
                b = clusters[j]

                score = float(
                    similarity[np.ix_(a, b)].mean()
                )

                if score > best_score:
                    best_score = score
                    best_pair = (i, j)

        if best_pair is None:
            break

        if best_score < threshold:
            break

        i, j = best_pair

        a = clusters[i]
        b = clusters[j]

        merged = sorted(a + b)

        history.append({
            "left": list(a),
            "right": list(b),
            "similarity": best_score,
            "merged": merged
        })

        clusters[i] = merged
        del clusters[j]

    # Stable identifiers based on first appearance.

    clusters.sort(key=lambda c: min(c))

    assignments = {}

    for i, cluster in enumerate(clusters):

        label = f"VOICE_{i:02d}"

        for member in cluster:
            assignments[member] = label

    return clusters, assignments, history


def extract_embeddings(input_path, source_offset):

    torch.set_num_threads(THREADS)

    audio, rate = sf.read(
        input_path,
        dtype="float32",
        always_2d=True
    )

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

    observations = []

    for i, (start, end, original) in enumerate(
        SEGMENTS
    ):

        a = round(start * rate)
        b = round(end * rate)

        if not 0 <= a < b <= len(audio):
            raise ValueError(
                f"Segment {i} outside audio bounds"
            )

        waveform = torch.from_numpy(
            audio[a:b].T.copy()
        )

        print(
            f"S{i:02d}: "
            f"{format_time(start + source_offset)} - "
            f"{format_time(end + source_offset)} "
            f"({end - start:.3f}s)"
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
                f"Invalid embedding for segment {i}"
            )

        vector /= magnitude

        observations.append({
            "id": f"S{i:02d}",
            "start_seconds": start + source_offset,
            "end_seconds": end + source_offset,
            "duration_seconds": end - start,
            "original_speaker": original,
            "embedding": vector.tolist()
        })

    return {
        "schema": "hehawk.chirp.segment_embeddings",
        "schema_version": 1,
        "model": MODEL,
        "source": str(input_path),
        "source_offset_seconds": source_offset,
        "timestamp_basis": "episode",
        "sample_rate": rate,
        "segments": observations
    }


def main():

    parser = argparse.ArgumentParser(
        description="CHIRP independent clustering"
    )

    parser.add_argument(
        "input",
        type=Path
    )

    parser.add_argument(
        "--source-offset",
        type=float,
        default=900.0
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=0.34
    )

    parser.add_argument(
        "--json",
        type=Path,
        required=True
    )

    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Reuse saved segment embeddings"
    )

    args = parser.parse_args()

    if not -1.0 <= args.threshold <= 1.0:
        parser.error(
            "Threshold must be between -1 and 1"
        )

    print("CHIRP - Independent speaker clustering")
    print(f"Similarity threshold: {args.threshold}")
    print()

    if args.reuse:

        print("Loading saved embeddings...")

        with args.json.open(
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if (
            data.get("schema")
            != "hehawk.chirp.segment_embeddings"
            or data.get("schema_version") != 1
        ):
            raise ValueError(
                "Unsupported embedding schema"
            )

        if (
            Path(data["source"]).resolve()
            != args.input.resolve()
            or data["source_offset_seconds"]
            != args.source_offset
            or data["model"] != MODEL
        ):
            raise ValueError(
                "Saved embedding provenance mismatch"
            )

    else:

        if args.json.exists():
            raise FileExistsError(args.json)

        data = extract_embeddings(
            args.input,
            args.source_offset
        )

        with args.json.open(
            "x",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=2,
                allow_nan=False
            )

        print()
        print(f"Embeddings saved to {args.json}")

    segments = data["segments"]

    vectors = np.asarray(
        [s["embedding"] for s in segments],
        dtype=np.float64
    )

    if not np.all(np.isfinite(vectors)):
        raise ValueError("Invalid saved embeddings")

    similarity = np.clip(
        vectors @ vectors.T,
        -1.0,
        1.0
    )

    clusters, assignments, history = (
        cluster_embeddings(
            similarity,
            args.threshold
        )
    )

    print()
    print("=" * 76)
    print("CLUSTER MERGE HISTORY")
    print("=" * 76)
    print()

    for merge in history:

        left = ", ".join(
            segments[i]["id"]
            for i in merge["left"]
        )

        right = ", ".join(
            segments[i]["id"]
            for i in merge["right"]
        )

        print(
            f"[{left}] + [{right}] "
            f"= {merge['similarity']:.4f}"
        )

    print()
    print("=" * 76)
    print("INDEPENDENT DIARIZATION")
    print("=" * 76)
    print()

    for i, segment in enumerate(segments):

        start = format_time(
            segment["start_seconds"]
        )

        end = format_time(
            segment["end_seconds"]
        )

        print(
            f"{segment['id']}  "
            f"{start} - {end}  "
            f"{assignments[i]}  "
            f"(original: "
            f"{segment['original_speaker']})"
        )

    print()
    print(f"Speakers detected: {len(clusters)}")

    print()
    print("=" * 76)
    print("CLUSTER MEMBERSHIP")
    print("=" * 76)
    print()

    for i, cluster in enumerate(clusters):

        print(f"VOICE_{i:02d}")

        for member in cluster:

            segment = segments[member]

            print(
                f"  {segment['id']}  "
                f"{format_time(segment['start_seconds'])}"
                f" - "
                f"{format_time(segment['end_seconds'])}"
                f"  ({segment['duration_seconds']:.3f}s)"
            )

        print()

    print("=" * 76)
    print("NEAREST NEIGHBORS")
    print("=" * 76)
    print()

    for i, segment in enumerate(segments):

        scores = similarity[i].copy()
        scores[i] = -np.inf

        j = int(np.argmax(scores))

        print(
            f"{segment['id']} -> "
            f"{segments[j]['id']} "
            f"({scores[j]:.4f})"
        )


if __name__ == "__main__":
    main()
