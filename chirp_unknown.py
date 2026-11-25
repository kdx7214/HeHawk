import argparse
import hashlib
import json
from pathlib import Path


def format_time(seconds):

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds %= 60

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:06.3f}"
    )


def classify(scores, min_similarity, min_margin):

    ranked = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True
    )

    winner, best = ranked[0]
    runner_up, second = ranked[1]

    margin = best - second

    if best < min_similarity:
        status = "UNKNOWN"

    elif margin < min_margin:
        status = "AMBIGUOUS"

    else:
        status = "MATCH"

    return {
        "candidate": winner,
        "similarity": best,
        "runner_up": runner_up,
        "margin": margin,
        "status": status,
        "identity": winner if status == "MATCH" else None
    }


def evaluate(
    controls,
    speakers,
    withheld,
    min_similarity,
    min_margin
):

    known = [
        s for s in speakers
        if s != withheld
    ]

    counts = {
        "unknown_correctly_rejected": 0,
        "unknown_ambiguous": 0,
        "unknown_falsely_accepted": 0,
        "known_correctly_accepted": 0,
        "known_rejected": 0,
        "known_ambiguous": 0,
        "known_misidentified": 0
    }

    observations = []

    for region in controls:

        actual = region["expected_speaker"]

        for window in region["windows"]:

            scores = {
                speaker: window["scores"][speaker]["mean"]
                for speaker in known
            }

            result = classify(
                scores,
                min_similarity,
                min_margin
            )

            status = result["status"]
            identity = result["identity"]

            if actual == withheld:

                if status == "UNKNOWN":
                    outcome = "unknown_correctly_rejected"

                elif status == "AMBIGUOUS":
                    outcome = "unknown_ambiguous"

                else:
                    outcome = "unknown_falsely_accepted"

            else:

                if status == "UNKNOWN":
                    outcome = "known_rejected"

                elif status == "AMBIGUOUS":
                    outcome = "known_ambiguous"

                elif identity == actual:
                    outcome = "known_correctly_accepted"

                else:
                    outcome = "known_misidentified"

            counts[outcome] += 1

            observations.append({
                "region_id": region["id"],
                "window_id": window["id"],
                "center_seconds": window["center_seconds"],
                "actual_speaker": actual,
                "available_scores": scores,
                "outcome": outcome,
                **result
            })

    return {
        "withheld_speaker": withheld,
        "known_speakers": known,
        "min_similarity": min_similarity,
        "min_margin": min_margin,
        "counts": counts,
        "observations": observations
    }


def percentage(numerator, denominator):

    if denominator == 0:
        return "N/A"

    return f"{100 * numerator / denominator:.1f}%"


def print_result(result):

    counts = result["counts"]

    unknown_total = (
        counts["unknown_correctly_rejected"]
        + counts["unknown_ambiguous"]
        + counts["unknown_falsely_accepted"]
    )

    known_total = (
        counts["known_correctly_accepted"]
        + counts["known_rejected"]
        + counts["known_ambiguous"]
        + counts["known_misidentified"]
    )

    print()
    print("=" * 76)

    print(
        f"WITHHELD SPEAKER: "
        f"{result['withheld_speaker']}"
    )

    print(
        f"Known speakers: "
        f"{', '.join(result['known_speakers'])}"
    )

    print("=" * 76)

    print()
    print("UNKNOWN SPEAKER")
    print(f"  Windows:              {unknown_total}")

    print(
        "  Correctly rejected:   "
        f"{counts['unknown_correctly_rejected']}"
    )

    print(
        "  Ambiguous:            "
        f"{counts['unknown_ambiguous']}"
    )

    print(
        "  Falsely accepted:     "
        f"{counts['unknown_falsely_accepted']}"
    )

    print(
        "  False acceptance:     "
        + percentage(
            counts["unknown_falsely_accepted"],
            unknown_total
        )
    )

    print()
    print("KNOWN SPEAKERS")
    print(f"  Windows:              {known_total}")

    print(
        "  Correctly accepted:   "
        f"{counts['known_correctly_accepted']}"
    )

    print(
        "  Rejected:             "
        f"{counts['known_rejected']}"
    )

    print(
        "  Ambiguous:            "
        f"{counts['known_ambiguous']}"
    )

    print(
        "  Misidentified:        "
        f"{counts['known_misidentified']}"
    )

    print(
        "  Correct acceptance:   "
        + percentage(
            counts["known_correctly_accepted"],
            known_total
        )
    )

    unknown = [
        observation
        for observation in result["observations"]
        if observation["actual_speaker"]
        == result["withheld_speaker"]
    ]

    similarities = [
        observation["similarity"]
        for observation in unknown
    ]

    if similarities:

        print()
        print("UNKNOWN SPEAKER SIMILARITY RANGE")

        print(f"  Minimum: {min(similarities):.4f}")
        print(f"  Maximum: {max(similarities):.4f}")

        print(
            f"  Mean:    "
            f"{sum(similarities) / len(similarities):.4f}"
        )

    errors = [
        observation
        for observation in result["observations"]
        if observation["outcome"] in (
            "unknown_falsely_accepted",
            "known_misidentified"
        )
    ]

    print()
    print("INCORRECT IDENTITY ASSIGNMENTS")

    if not errors:
        print("  None")

    for observation in errors:

        print(
            f"  {format_time(observation['center_seconds'])}"
            f"  Actual: {observation['actual_speaker']}"
            f"  Assigned: {observation['identity']}"
            f"  Similarity: {observation['similarity']:.3f}"
            f"  Margin: {observation['margin']:.3f}"
        )


def main():

    parser = argparse.ArgumentParser(
        description="CHIRP unknown speaker experiment"
    )

    parser.add_argument(
        "input",
        type=Path
    )

    parser.add_argument(
        "--min-similarity",
        type=float,
        default=0.30
    )

    parser.add_argument(
        "--min-margin",
        type=float,
        default=0.10
    )

    parser.add_argument(
        "--json",
        type=Path,
        required=True
    )

    args = parser.parse_args()

    if args.json.exists():
        raise FileExistsError(args.json)

    if not -1 <= args.min_similarity <= 1:
        parser.error("Invalid similarity threshold")

    if not 0 <= args.min_margin <= 2:
        parser.error("Invalid margin threshold")

    raw = args.input.read_bytes()
    data = json.loads(raw)

    if (
        data.get("schema")
        != "hehawk.chirp.transitions"
        or data.get("schema_version") != 1
    ):
        raise ValueError(
            "Unsupported transition evidence schema"
        )

    controls = [
        region
        for region in data["regions"]
        if region["kind"] == "CONTROL"
        and region.get("expected_speaker")
    ]

    speakers = sorted({
        region["expected_speaker"]
        for region in controls
    })

    if len(speakers) < 3:
        raise ValueError(
            "At least three speakers required"
        )

    print("CHIRP - Unknown speaker experiment")
    print(f"Similarity threshold: {args.min_similarity}")
    print(f"Margin threshold:     {args.min_margin}")
    print(f"Speakers:             {len(speakers)}")

    print(
        "Control windows:      "
        f"{sum(len(r['windows']) for r in controls)}"
    )

    results = []

    for withheld in speakers:

        result = evaluate(
            controls,
            speakers,
            withheld,
            args.min_similarity,
            args.min_margin
        )

        print_result(result)
        results.append(result)

    print()
    print("=" * 76)
    print("THRESHOLD SENSITIVITY")
    print("=" * 76)
    print()

    print(
        f"{'Similarity':>10s}"
        f"{'Margin':>10s}"
        f"{'Unknown':>10s}"
        f"{'False ID':>10s}"
        f"{'Known':>10s}"
        f"{'Correct':>10s}"
        f"{'Wrong ID':>10s}"
    )

    sweep = []

    for threshold in (
        0.15, 0.20, 0.25, 0.30,
        0.35, 0.40, 0.45, 0.50
    ):

        for margin in (
            0.05, 0.10, 0.15, 0.20
        ):

            totals = {}

            for withheld in speakers:

                result = evaluate(
                    controls,
                    speakers,
                    withheld,
                    threshold,
                    margin
                )

                for key, value in result["counts"].items():

                    totals[key] = (
                        totals.get(key, 0) + value
                    )

            unknown_total = (
                totals["unknown_correctly_rejected"]
                + totals["unknown_ambiguous"]
                + totals["unknown_falsely_accepted"]
            )

            known_total = (
                totals["known_correctly_accepted"]
                + totals["known_rejected"]
                + totals["known_ambiguous"]
                + totals["known_misidentified"]
            )

            print(
                f"{threshold:10.2f}"
                f"{margin:10.2f}"
                f"{unknown_total:10d}"
                f"{totals['unknown_falsely_accepted']:10d}"
                f"{known_total:10d}"
                f"{totals['known_correctly_accepted']:10d}"
                f"{totals['known_misidentified']:10d}"
            )

            sweep.append({
                "min_similarity": threshold,
                "min_margin": margin,
                "counts": totals
            })

    output = {
        "schema": "hehawk.chirp.unknown",
        "schema_version": 1,
        "timestamp_basis": "episode",
        "source": str(args.input),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "settings": {
            "min_similarity": args.min_similarity,
            "min_margin": args.min_margin
        },
        "experiments": results,
        "threshold_sweep": sweep
    }

    with args.json.open("x", encoding="utf-8") as f:

        json.dump(
            output,
            f,
            indent=2,
            allow_nan=False
        )

    print()
    print(f"Results saved to {args.json}")


if __name__ == "__main__":
    main()
