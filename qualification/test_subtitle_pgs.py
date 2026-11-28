
"""Independent PGS native subtitle qualification."""

from qualification.subtitle_common import run


if __name__ == "__main__":
    raise SystemExit(
        run(
            codec="hdmv_pgs_subtitle",

            count=1062,

            packet_hash=(
                "19c505ab726d1bb5607b5b1a356070e0110839de4f51467acbb7fd6065eacb08"
            ),

            initialization_size=0,

            initialization_hash=None,

            source_canvas=None,

            resource_canvas={
                "width": 1920,
                "height": 1080,
            },

            canvas_status=(
                "resource_dimensions_discovered"
            ),
        )
    )

