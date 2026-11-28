
"""Independent HD VobSub native subtitle qualification."""

from qualification.subtitle_common import run


if __name__ == "__main__":
    raise SystemExit(
        run(
            codec="dvd_subtitle",

            count=1709,

            packet_hash=(
                "eb01c80e61d6d7d5a7664180ad8152cebf91c7eec785590811fb090208d3f142"
            ),

            initialization_size=348,

            initialization_hash=(
                "98567c263bd5b64552faf7557df780b6511c6cbdafd153d45fcbd1e06007c3bb"
            ),

            source_canvas={
                "width": 1920,
                "height": 1080,
            },

            resource_canvas={
                "width": 1920,
                "height": 1080,
            },

            canvas_status="match",
        )
    )

