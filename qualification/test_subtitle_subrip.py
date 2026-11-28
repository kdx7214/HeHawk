
"""Independent SubRip native subtitle qualification."""

from qualification.subtitle_common import run


if __name__ == "__main__":
    raise SystemExit(
        run(
            codec="subrip",

            count=773,

            packet_hash=(
                "7a0839ce1a02c551df748c45c949453135487d30bec6b9f116441bcda7a77203"
            ),

            initialization_size=0,

            initialization_hash=None,

            source_canvas=None,

            resource_canvas=None,

            canvas_status="not_reported",
        )
    )

