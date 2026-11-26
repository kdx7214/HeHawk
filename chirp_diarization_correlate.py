#!/usr/bin/env python3
"""Correlate CHIRP acoustic candidates with diarization, Parakeet words, and GULP captions.

Evidence only: this script never edits subtitles or assigns character identities.
All timestamps in the inputs must be episode-relative.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from word_timing import word_groups


SCHEMA = "hehawk.chirp.diarization_correlation"
SCHEMA_VERSION = 1

# Conservative association limits. These are review heuristics, not probabilities.
MAX_SIDE_DISTANCE = 1.50
MAX_SPEECH_GAP = 2.50
MIN_SEGMENT_DURATION = 0.60
SHORT_SEGMENT_DURATION = 0.90
CAPTION_EDGE_TOLERANCE = 0.35
WORD_EDGE_TOLERANCE = 0.12


def load_json(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def finite_number(value, label):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Non-finite {label}")
    return value


def words_from(data):
    if data.get("source_offset_seconds", 0) != 0:
        raise ValueError("Expected full-episode recognition with zero offset")
    tokens = data["tokens"]
    timestamps = data["timestamps"]
    durations = data["durations"]
    if not (len(tokens) == len(timestamps) == len(durations)):
        raise ValueError("Recognition token/timestamp/duration counts differ")

    words = []
    for raw, token_start, token_end, start, end in word_groups(
        tokens, timestamps, durations, 0, len(tokens)
    ):
        if not any(ch.isalnum() for ch in raw):
            continue
        start = finite_number(start, "word start")
        end = finite_number(end, "word end")
        if start < 0 or end < start:
            raise ValueError("Invalid recognition word timing")
        words.append({
            "word": raw,
            "token_start": token_start,
            "token_end": token_end,
            "start_seconds": round(start, 6),
            "end_seconds": round(end, 6),
            "sentence_end": raw.rstrip("\"'”’)]} ").endswith((".", "?", "!")),
        })
    return sorted(words, key=lambda item: (item["start_seconds"], item["end_seconds"]))


def diarization_segments(data, mode):
    if (data.get("schema"), data.get("schema_version"), data.get("timestamp_basis")) != (
        "hehawk.chirp.diarization", 1, "episode"
    ):
        raise ValueError("Unsupported diarization schema; expected episode-relative v1")
    if mode not in data:
        raise ValueError(f"Diarization has no {mode!r} result")
    rows = data[mode]["segments"]
    segments = []
    for row in rows:
        start = finite_number(row["start_seconds"], "diarization start")
        end = finite_number(row["end_seconds"], "diarization end")
        speaker = row.get("original_speaker")
        if not speaker:
            raise ValueError("Diarization segment has no original_speaker")
        if start < 0 or end <= start:
            raise ValueError("Invalid diarization segment")
        segments.append({
            "id": row.get("id"),
            "start_seconds": start,
            "end_seconds": end,
            "duration_seconds": end - start,
            "speaker": speaker,
        })
    return sorted(segments, key=lambda item: (item["start_seconds"], item["end_seconds"]))


def lexical_position(t, words):
    containing = [
        w for w in words
        if w["start_seconds"] <= t <= w["end_seconds"]
    ]
    if containing:
        return {
            "position": "inside_word",
            "containing_words": containing,
            "nearest_gap": None,
            "distance_to_gap_seconds": None,
        }

    gaps = []
    for left, right in zip(words, words[1:]):
        # Avoid treating overlapping recognition words as a gap.
        if right["start_seconds"] >= left["end_seconds"]:
            gaps.append({
                "start_seconds": left["end_seconds"],
                "end_seconds": right["start_seconds"],
                "duration_seconds": right["start_seconds"] - left["end_seconds"],
                "left": left,
                "right": right,
            })

    if not gaps:
        return {
            "position": "outside_recognized_span",
            "containing_words": [],
            "nearest_gap": None,
            "distance_to_gap_seconds": None,
        }

    def distance(gap):
        return max(gap["start_seconds"] - t, t - gap["end_seconds"], 0.0)

    nearest = min(gaps, key=lambda g: (distance(g), -g["duration_seconds"]))
    dist = distance(nearest)
    at_edge = any(
        abs(t - edge) <= WORD_EDGE_TOLERANCE
        for w in words for edge in (w["start_seconds"], w["end_seconds"])
    )
    position = "interword_gap" if dist == 0 else "word_edge" if at_edge else "outside_recognized_span"
    return {
        "position": position,
        "containing_words": [],
        "nearest_gap": nearest,
        "distance_to_gap_seconds": round(dist, 6),
        "seconds_from_left_word_end": round(t - nearest["start_seconds"], 6),
        "seconds_to_right_word_start": round(nearest["end_seconds"] - t, 6),
        "distance_to_gap_edge_seconds": round(
            min(abs(t - nearest["start_seconds"]), abs(nearest["end_seconds"] - t)), 6
        ),
    }


def speaker_evidence(t, segments):
    # Find the closest segment ending at/before t and starting at/after t.
    # Segments that contain t are retained separately; they are not evidence
    # of a transition at t.
    containing = [
        s for s in segments
        if s["start_seconds"] <= t <= s["end_seconds"]
    ]
    left = [s for s in segments if s["end_seconds"] <= t]
    right = [s for s in segments if s["start_seconds"] >= t]

    before = max(left, key=lambda s: s["end_seconds"]) if left else None
    after = min(right, key=lambda s: s["start_seconds"]) if right else None

    left_distance = t - before["end_seconds"] if before else None
    right_distance = after["start_seconds"] - t if after else None
    combined_gap = (
        after["start_seconds"] - before["end_seconds"]
        if before and after else None
    )

    result = {
        "segments_containing_time": containing,
        "segment_before": before,
        "segment_after": after,
        "distance_to_before_seconds": round(left_distance, 6) if left_distance is not None else None,
        "distance_to_after_seconds": round(right_distance, 6) if right_distance is not None else None,
        "gap_between_speech_segments_seconds": round(combined_gap, 6) if combined_gap is not None else None,
        "speaker_relation": "UNKNOWN",
        "usable_for_comparison": False,
        "review_flags": [],
    }

    if containing:
        result["review_flags"].append("CANDIDATE_FALLS_WITHIN_DIARIZED_SPEECH")
        return result

    if before is None or after is None:
        result["review_flags"].append("MISSING_SPEECH_ON_ONE_SIDE")
        return result

    if left_distance > MAX_SIDE_DISTANCE or right_distance > MAX_SIDE_DISTANCE:
        result["review_flags"].append("NEAREST_SPEECH_TOO_FAR_FROM_CANDIDATE")
        return result

    if combined_gap is not None and combined_gap > MAX_SPEECH_GAP:
        result["review_flags"].append("LARGE_SILENCE_BETWEEN_SPEECH_SEGMENTS")
        return result

    result["usable_for_comparison"] = True
    if before["speaker"] == after["speaker"]:
        result["speaker_relation"] = "SAME"
    else:
        result["speaker_relation"] = "DIFFERENT"

    if min(before["duration_seconds"], after["duration_seconds"]) < MIN_SEGMENT_DURATION:
        result["review_flags"].append("VERY_SHORT_ADJACENT_SPEECH_SEGMENT")
    elif min(before["duration_seconds"], after["duration_seconds"]) < SHORT_SEGMENT_DURATION:
        result["review_flags"].append("SHORT_ADJACENT_SPEECH_SEGMENT")

    return result


def caption_evidence(t, cues):
    active = [
        c for c in cues
        if c["start_ms"] / 1000 <= t <= c["end_ms"] / 1000
    ]
    nearest = None
    nearest_distance = None
    for cue in cues:
        for edge_name, edge_ms in (("start", cue["start_ms"]), ("end", cue["end_ms"])):
            distance = abs(t - edge_ms / 1000)
            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
                nearest = {"cue_id": cue.get("id"), "edge": edge_name, "time_seconds": edge_ms / 1000}
    return {
        "active_cues": [
            {"id": c.get("id"), "start_ms": c["start_ms"], "end_ms": c["end_ms"],
             "display_text": c.get("display_text", "")}
            for c in active
        ],
        "inside_existing_caption": bool(active),
        "nearest_caption_edge": nearest,
        "distance_to_caption_edge_seconds": round(nearest_distance, 6) if nearest_distance is not None else None,
        "near_caption_edge": nearest_distance is not None and nearest_distance <= CAPTION_EDGE_TOLERANCE,
    }


def classify(acoustic, lexical, speaker):
    flags = list(speaker["review_flags"])
    if lexical["position"] in ("inside_word", "outside_recognized_span"):
        flags.append("LINGUISTIC_BOUNDARY_NOT_ESTABLISHED")
    if lexical["position"] == "word_edge":
        flags.append("NEAR_WORD_EDGE_NOT_CLEAR_INTERWORD_GAP")

    # Acoustic confidence is a descriptive evidence tier, not a calibrated probability.
    primary = acoustic.get("primary", {})
    contrast = primary.get("contrast")
    prominence = primary.get("prominence")
    acoustic_tier = "UNKNOWN"
    if contrast is not None and prominence is not None:
        if contrast >= 0.35 and prominence >= 0.25:
            acoustic_tier = "STRONG"
        elif contrast >= 0.15 and prominence >= 0.10:
            acoustic_tier = "MODERATE"
        else:
            acoustic_tier = "WEAK"

    lexical_tier = {
        "interword_gap": "BOUNDARY_ALIGNED",
        "word_edge": "EDGE_ADJACENT",
        "inside_word": "CONFLICTS_WITH_WORD_BOUNDARY",
        "outside_recognized_span": "UNALIGNED",
    }.get(lexical["position"], "UNKNOWN")

    if speaker["speaker_relation"] == "DIFFERENT" and speaker["usable_for_comparison"]:
        classification = "SPEAKER_CHANGE_SUPPORTED"
        flags.append("HUMAN_REVIEW_REQUIRED_FOR_SPEAKER_CHANGE")
    elif speaker["speaker_relation"] == "SAME" and speaker["usable_for_comparison"]:
        classification = "SAME_SPEAKER_SUPPORTED"
    elif lexical["position"] == "interword_gap":
        classification = "SPEECH_BOUNDARY_ONLY"
    else:
        classification = "INSUFFICIENT_EVIDENCE"

    if acoustic_tier == "WEAK":
        flags.append("WEAK_ACOUSTIC_EVIDENCE")
    if lexical_tier in ("CONFLICTS_WITH_WORD_BOUNDARY", "UNALIGNED"):
        flags.append("ACOUSTIC_AND_LINGUISTIC_EVIDENCE_DISAGREE")
    # Noise cannot be inferred reliably from these inputs; always expose this limitation.
    # Background noise is an explicit limitation, not proof that every
    # observation is unusable. It is recorded globally and in each observation.
    review_required = (
        classification == "SPEAKER_CHANGE_SUPPORTED"
        or bool(flags)
        or classification == "INSUFFICIENT_EVIDENCE"
    )

    return {
        "classification": classification,
        "acoustic_confidence": acoustic_tier,
        "speaker_confidence": (
            "COMPARABLE_DIFFERENT_LABELS" if speaker["speaker_relation"] == "DIFFERENT"
            else "COMPARABLE_SAME_LABEL" if speaker["speaker_relation"] == "SAME"
            else "UNRESOLVED"
        ),
        "linguistic_confidence": lexical_tier,
        "human_review_required": review_required,
        "background_noise_assessment": "NOT_INDEPENDENTLY_ASSESSED",
        "review_flags": sorted(set(flags)),
    }


def read_captions(path):
    if path is None:
        return [], None
    data, digest = load_json(path)
    if (data.get("schema"), data.get("schema_version")) != ("hehawk.gulp", 1):
        raise ValueError("Unsupported caption schema; expected GULP hehawk.gulp v1")
    if data.get("timestamp_basis") != "source":
        raise ValueError("Expected GULP source-relative timestamps")
    cues = data["cues"]
    for cue in cues:
        start, end = int(cue["start_ms"]), int(cue["end_ms"])
        if start < 0 or end <= start:
            raise ValueError("Invalid GULP cue timing")
    return cues, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("consensus", type=Path)
    parser.add_argument("diarization", type=Path)
    parser.add_argument("recognition", type=Path)
    parser.add_argument("--captions", type=Path, help="Optional GULP hehawk.gulp v1 JSON")
    parser.add_argument("--mode", choices=("regular", "exclusive"), default="regular")
    parser.add_argument("--caption-offset", type=float, default=0.0,
                        help="Seconds to add to source-relative GULP cue times (default: 0)")
    parser.add_argument("--json", required=True, type=Path)
    args = parser.parse_args()

    try:
        if args.json.exists():
            raise ValueError(f"Output already exists: {args.json}")

        consensus, consensus_hash = load_json(args.consensus)
        diarization, diarization_hash = load_json(args.diarization)
        recognition, recognition_hash = load_json(args.recognition)

        if (consensus.get("schema"), consensus.get("schema_version"),
            consensus.get("timestamp_basis")) != ("hehawk.chirp.consensus", 1, "episode"):
            raise ValueError("Unsupported consensus schema; expected episode-relative v1")

        segments = diarization_segments(diarization, args.mode)
        words = words_from(recognition)
        if not words:
            raise ValueError("No lexical recognition words found")

        captions, captions_hash = read_captions(args.captions)
        offset = finite_number(args.caption_offset, "caption offset")
        if offset < 0:
            raise ValueError("Caption offset cannot be negative")

        candidates = consensus.get("proposed_transitions")
        if candidates is None:
            candidates = [c for c in consensus.get("candidates", []) if c.get("status") == "PROPOSED"]

        observations = []
        for candidate in candidates:
            t = finite_number(candidate["primary"]["time_seconds"], "acoustic candidate time")
            lexical = lexical_position(t, words)
            speaker = speaker_evidence(t, segments)
            captions_at_t = caption_evidence(t - offset, captions) if captions else {
                "active_cues": [], "inside_existing_caption": None,
                "nearest_caption_edge": None, "distance_to_caption_edge_seconds": None,
                "near_caption_edge": None,
            }
            decision = classify(candidate, lexical, speaker)
            observations.append({
                "time_seconds": t,
                "acoustic": candidate,
                "speaker_evidence": speaker,
                "lexical_evidence": lexical,
                "caption_evidence": captions_at_t,
                "assessment": decision,
            })

        result = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "timestamp_basis": "episode",
            "purpose": "evidence_only_no_caption_edits_no_character_identity",
            "settings": {
                "diarization_mode": args.mode,
                "max_side_distance_seconds": MAX_SIDE_DISTANCE,
                "max_speech_gap_seconds": MAX_SPEECH_GAP,
                "minimum_segment_duration_seconds": MIN_SEGMENT_DURATION,
                "short_segment_duration_seconds": SHORT_SEGMENT_DURATION,
                "caption_edge_tolerance_seconds": CAPTION_EDGE_TOLERANCE,
                "word_edge_tolerance_seconds": WORD_EDGE_TOLERANCE,
                "confidence_tiers_are_calibrated_probabilities": False,
                "background_noise_independently_assessed": False,
            },
            "sources": {
                "consensus": {"path": str(args.consensus), "sha256": consensus_hash},
                "diarization": {"path": str(args.diarization), "sha256": diarization_hash},
                "recognition": {"path": str(args.recognition), "sha256": recognition_hash},
                "captions": (
                    {"path": str(args.captions), "sha256": captions_hash,
                     "offset_seconds": offset} if args.captions else None
                ),
            },
            "observations": observations,
            "review_policy": {
                "automatic_caption_changes": False,
                "speaker_change_claims_require_human_review": True,
                "uncertain_or_conflicting_evidence_requires_human_review": True,
                "review_decisions_stored_separately": True,
            },
        }

        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        with args.json.open("x", encoding="utf-8") as output:
            output.write(payload)

    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    counts = {}
    for row in observations:
        label = row["assessment"]["classification"]
        counts[label] = counts.get(label, 0) + 1

    print("CHIRP DIARIZATION CORRELATION V1 — evidence only")
    print(f"Candidates: {len(observations)} | Diarization mode: {args.mode}")
    print("Episode    Classification             Acoustic  Speaker       Linguistic")
    for row in observations:
        t = row["time_seconds"]
        a = row["assessment"]
        print(f"{t:9.3f}  {a['classification']:27s} "
              f"{a['acoustic_confidence']:9s} "
              f"{a['speaker_confidence']:13s} "
              f"{a['linguistic_confidence']}")
        if a["human_review_required"]:
            print("           REVIEW: " + ", ".join(a["review_flags"]))
    print("\nSUMMARY")
    for label in (
        "SPEAKER_CHANGE_SUPPORTED", "SAME_SPEAKER_SUPPORTED",
        "SPEECH_BOUNDARY_ONLY", "INSUFFICIENT_EVIDENCE"
    ):
        print(f"{label}: {counts.get(label, 0)}")
    print(f"Saved evidence report: {args.json}")
    print("No captions changed; all speaker-change claims require human review.")


if __name__ == "__main__":
    main()
