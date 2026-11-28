
"""Independent MOV_TEXT native subtitle qualification."""

from qualification.subtitle_common import run


if __name__ == "__main__":
    raise SystemExit(
        run(
            codec="mov_text",

            count=3637,

            packet_hash=(
                "398249f6d9685559e2a7d116b5ad8ae30"
                "73d716a2cc443c968c9115224b9ff42"
            ),

            initialization_size=48,

            initialization_hash=(
                "dfd140fa284a572c37291ebac3280dc7"
                "3be19be485e7586d641aaae3ee6f8e26"
            ),

            source_canvas=None,

            resource_canvas=None,

            canvas_status="not_reported",
        )
    )

