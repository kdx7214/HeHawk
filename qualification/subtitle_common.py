
"""Independent, read-only native subtitle qualification."""

import argparse
import json
import shutil
import subprocess
import tempfile

from pathlib import Path

from hehawk_subtitle_policy import policy_for
from hehawk_verify_subtitles import verify
from hehawk_workspace import preflight, safe_path


def run(
    codec,
    count,
    packet_hash,
    initialization_size,
    initialization_hash,
    source_canvas,
    resource_canvas,
    canvas_status,
):
    parser = argparse.ArgumentParser(
        description=(
            f"Qualify {codec} against "
            "a known subtitle specimen"
        )
    )

    parser.add_argument(
        "source",
        type=Path,
    )

    parser.add_argument(
        "--stream",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--temp-dir",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--media-root",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--config",
        type=Path,
        required=True,
    )

    args = parser.parse_args()

    config = json.loads(
        args.config.read_text()
    )

    configured_media, root, mount = (
        preflight(config)
    )

    def identity(path):
        stat = path.stat()

        return (
            stat.st_dev,
            stat.st_ino,
        )

    mount_identity = identity(mount)

    source = args.source.resolve(
        strict=True
    )

    media = args.media_root.resolve(
        strict=True
    )

    temp = args.temp_dir.resolve(
        strict=True
    )

    if (
        not media.is_mount()
        or not source.is_relative_to(media)
    ):
        parser.error(
            "Source must be on the "
            "mounted media root"
        )

    if (
        temp.is_relative_to(media)
        or media.is_relative_to(temp)
    ):
        parser.error(
            "Temporary directory must be "
            "separate from media root"
        )

    if (
        media != configured_media
        or temp != root / "temp"
    ):
        parser.error(
            "Use configured media root "
            "and workspace temp directory"
        )

    media_identity = identity(media)

    def signature():
        stat = source.stat()

        return (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
        )

    before = signature()

    def check(budget=0):
        if (
            preflight(config)
            != (media, root, mount)
            or not media.is_mount()
        ):
            raise ValueError(
                "Storage configuration "
                "or mount changed"
            )

        if identity(mount) != mount_identity:
            raise ValueError(
                "Workspace mount changed"
            )

        if identity(media) != media_identity:
            raise ValueError(
                "Media mount changed"
            )

        if signature() != before:
            raise ValueError(
                "Source changed"
            )

        safe_path(
            root,
            Path("temp"),
            mount,
        )

        reserve = (
            config["minimum_free_gib"]
            * 1024**3
        )

        if (
            not temp.is_dir()
            or shutil.disk_usage(temp).free
            < budget + reserve
        ):
            raise ValueError(
                "Insufficient temporary storage "
                "or invalid directory"
            )

    policy = policy_for(codec)

    if policy is None:
        parser.error(
            "Unsupported subtitle codec"
        )

    check(source.stat().st_size)

    tempfile.tempdir = str(temp)

    expected_packets = {
        "count": count,
        "sha256": packet_hash,
    }

    expected_initialization = {
        "size": initialization_size,
        "sha256": (
            f"sha256:{initialization_hash}"
            if initialization_hash is not None
            else None
        ),
    }

    with tempfile.TemporaryDirectory(
        prefix=f"qualify-subtitle-{codec}-",
        dir=temp,
    ) as directory:

        resource = (
            Path(directory)
            / f"native{policy.extension}"
        )

        check(source.stat().st_size)

        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel", "error",
                "-xerror",
                "-n",
                "-copyts",
                "-i", str(source),
                "-map", f"0:{args.stream}",
                "-c:s", "copy",
                "-map_metadata", "-1",
                "-map_chapters", "-1",
                "-avoid_negative_ts", "disabled",
                *policy.muxer_options,
                "-f", policy.container,
                str(resource),
            ],
            check=True,
        )

        check()

        report = verify(
            source,
            resource,
            args.stream,
            0,
        )

        check()

        print(
            json.dumps(
                report,
                indent=2,
            )
        )

        checks = {
            "source unchanged": (
                signature() == before
            ),

            "schema": (
                report["schema_version"] == 1
            ),

            "verification type": (
                report["verification_type"]
                == "native_subtitle"
            ),

            "source stream": (
                report["source_stream"]
                == args.stream
            ),

            "resource stream": (
                report["resource_stream"] == 0
            ),

            "source codec": (
                report["source_codec"] == codec
            ),

            "resource codec": (
                report["resource_codec"] == codec
            ),

            "source packets": (
                report["source_packets"]
                == expected_packets
            ),

            "resource packets": (
                report["resource_packets"]
                == expected_packets
            ),

            "packet conservation": (
                report["packet_match"] is True
            ),

            "source initialization": (
                report["source_initialization"]
                == expected_initialization
            ),

            "resource initialization": (
                report["resource_initialization"]
                == expected_initialization
            ),

            "initialization conservation": (
                report["initialization_match"]
                is True
            ),

            "source canvas": (
                report["source_canvas"]
                == source_canvas
            ),

            "resource canvas": (
                report["resource_canvas"]
                == resource_canvas
            ),

            "canvas status": (
                report["canvas_status"]
                == canvas_status
            ),

            "metadata differences": (
                report["metadata_differences"]
                == []
            ),

            "native preservation": (
                report["native_preservation_passed"]
                is True
            ),

            "rendering remains unverified": (
                report["rendering_equivalence"]
                == "unverified"
            ),

            "external dependencies remain unverified": (
                report["external_dependencies"]
                == "unverified"
            ),

            "timeline remains unverified": (
                report["timeline_mapping"]
                == "unverified"
            ),

            "strict result": (
                report["passed"] is True
            ),
        }

        for name, passed in checks.items():
            status = "PASS" if passed else "FAIL"

            print(f"{status}: {name}")

        passed = all(checks.values())

    status = "PASS" if passed else "FAIL"

    print(
        f"Qualification {status}: {codec}"
    )

    return 0 if passed else 1

