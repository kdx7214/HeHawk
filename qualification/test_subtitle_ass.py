
"""Independent ASS native subtitle qualification."""

from qualification.subtitle_common import run


if __name__ == "__main__":
    raise SystemExit(
        run(
            codec="ass",

            count=415,

            packet_hash=(
                "5651582a44055266ad783ea3b477527a"
                "55ba1968f9ed6b167de194afb79e5923"
            ),

            initialization_size=489,

            initialization_hash=(
                "8af10976a956ccaa84e447c1f8b9dffb"
                "4f3d24b0ab14347d83736ae9e7583792"
            ),

            source_canvas=None,

            resource_canvas=None,

            canvas_status="not_reported",
        )
    )

