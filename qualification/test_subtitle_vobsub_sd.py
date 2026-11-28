
"""Independent SD VobSub native subtitle qualification."""

from qualification.subtitle_common import run


if __name__ == "__main__":
    raise SystemExit(
        run(
            codec="dvd_subtitle",

            count=290,

            packet_hash=(
                "9051e09052a7c2cf6133fc0c9c456985335c6bbd4294734a2bd72a839c3c37ae"
            ),

            initialization_size=349,

            initialization_hash=(
                "b2c0369c5618a831342dce9de77b9286afef4ada597e206f98c98068c151a4cc"
            ),

            source_canvas={
                "width": 720,
                "height": 480,
            },

            resource_canvas={
                "width": 720,
                "height": 480,
            },

            canvas_status="match",
        )
    )

