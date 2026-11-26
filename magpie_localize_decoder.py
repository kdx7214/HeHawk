"""Experimental decoder-aware MAGPIE localization."""

import magpie_localize

from magpie_decoder_reconstruct import reconstruct

from test_magpie_decoder_reconstruct import (
    classify_boundary_agreement,
    verify_ownership,
)


# ------------------------------------------------------------
# Experimental reconstruction adapter
# ------------------------------------------------------------

def observation_words(observation, offset):

    text = observation["text"]
    tokens = observation["tokens"]
    timestamps = observation["timestamps"]
    durations = observation["durations"]

    classification = classify_boundary_agreement(
        text,
        tokens
    )

    if classification not in {

        "lexical_agreement",
        "punctuation_boundary_agreement",

    }:

        raise ValueError(
            "Decoder reconstruction requires investigation: "
            + classification
        )

    result = reconstruct(
        text,
        tokens,
        timestamps,
        durations
    )

    try:

        verify_ownership(
            text,
            tokens,
            timestamps,
            durations,
            result
        )

    except AssertionError as exc:

        raise ValueError(
            "Decoder ownership verification failed: "
            + str(exc)
        ) from exc

    words = result["words"]

    expected = observation["normalized_words"]

    actual = [
        word["normalized"]
        for word in words
    ]

    if actual != expected:

        raise ValueError(
            "Reconstructed lexical sequence differs "
            "from accumulated recognition evidence."
        )

    output = []

    for word in words:

        output.append({
            **word,
            "start": offset + word["start"],
            "end": offset + word["end"],
            "reconstruction_method": "decoder_aware",
            "boundary_classification": classification,
            "ownership_verified": True,
        })

    return output


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    print("=" * 72)
    print("MAGPIE DECODER-AWARE LOCALIZATION")
    print("=" * 72)
    print("Reconstruction: decoder-aware")
    print("Character ownership verification: enabled")
    print("Boundary classification: enabled")
    print("Lexical comparison: unchanged")
    print("Localization algorithm: unchanged")
    print("Production files modified: NO")
    print()

    # Substitute the reconstruction function for this
    # process only. No source files are modified.

    magpie_localize.observation_words = observation_words

    return magpie_localize.main()


if __name__ == "__main__":

    raise SystemExit(main())
