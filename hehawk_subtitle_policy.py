
#!/usr/bin/env python3
"""Shared native subtitle resource container policy."""

from dataclasses import dataclass

from hehawk_verify_subtitles import SUPPORTED_CODECS


@dataclass(frozen=True)
class SubtitlePolicy:
    extension: str
    container: str
    muxer_options: tuple = ()


POLICIES = {
    "ass": SubtitlePolicy(
        ".mks", "matroska"
    ),

    "subrip": SubtitlePolicy(
        ".mks", "matroska"
    ),

    "hdmv_pgs_subtitle": SubtitlePolicy(
        ".mks", "matroska"
    ),

    "dvd_subtitle": SubtitlePolicy(
        ".mks", "matroska"
    ),

    "mov_text": SubtitlePolicy(
        ".mp4",
        "mp4",
        ("-write_btrt", "0"),
    ),
}


if frozenset(POLICIES) != SUPPORTED_CODECS:
    raise RuntimeError(
        "Subtitle extraction and verification "
        "codec policies disagree"
    )


def policy_for(codec):
    """Return a qualified policy or None."""
    return POLICIES.get(codec)

