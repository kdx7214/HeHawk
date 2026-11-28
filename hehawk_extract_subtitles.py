
#!/usr/bin/env python3
"""Extract and verify one native subtitle stream locally."""

import argparse
import json
import shutil
import subprocess
import sys

from pathlib import Path
from xml.etree.ElementTree import ParseError

from hehawk import inspect
from hehawk_resources import plan
from hehawk_workspace import preflight, safe_path
from hehawk_publication import publish
from hehawk_subtitle_policy import policy_for
from hehawk_verify_subtitles import verify as verify_subtitles


def extract(video, config, index):
    media, root, mount = preflight(config)

    if not media.is_mount():
        raise ValueError("Media mount unavailable")

    source = Path(video).resolve(strict=True)
    relative = source.relative_to(media)

    def signature():
        stat = source.stat()

        return (
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_dev,
            stat.st_ino,
        )

    original = signature()

    inventory = inspect(source)
    planned = plan(inventory, config)

    if signature() != original:
        raise ValueError(
            "Source changed during inspection"
        )

    resource = next(
        (
            r for r in planned["resources"]
            if r["kind"] == "native_subtitle"
            and r["source_stream"] == index
        ),
        None,
    )

    if resource is None:
        raise ValueError(
            "Requested stream is not a native "
            "subtitle resource"
        )

    stream = next(
        s for s in inventory["streams"]
        if s["index"] == index
    )

    codec = stream.get("codec_name")
    policy = policy_for(codec)

    if policy is None:
        raise ValueError(
            f"Unsupported native subtitle codec: {codec}"
        )

    if resource["status"] not in {
        "planned",
        "existing_unverified",
    }:
        raise ValueError(
            "Subtitle resource is not actionable"
        )

    expected_path = (
        f"resources/subtitles/stream-{index:03d}"
        f"{policy.extension}"
    )

    if (
        resource["path"] != expected_path
        or resource.get("container") != policy.container
        or resource.get("muxer_options")
        != list(policy.muxer_options)
    ):
        raise ValueError(
            "Subtitle resource policy mismatch"
        )

    project_rel = (
        Path("projects") / relative.with_suffix("")
    )

    resources = safe_path(
        root,
        project_rel / "resources",
        mount,
    )

    destination = Path(
        resource["path"]
    ).relative_to("resources")

    budget = (
        planned["storage"]["native_budget_bytes"]
        + planned["storage"]["overhead_allowance_bytes"]
    )

    reserve = planned["storage"]["reserve_bytes"]

    mount_stat = mount.stat()
    media_stat = media.stat()

    def check():
        if (
            preflight(config) != (media, root, mount)
            or not media.is_mount()
        ):
            raise ValueError(
                "Mount or configuration changed"
            )

        stat = mount.stat()

        if (
            stat.st_dev,
            stat.st_ino,
        ) != (
            mount_stat.st_dev,
            mount_stat.st_ino,
        ):
            raise ValueError(
                "Workspace mount changed"
            )

        stat = media.stat()

        if (
            stat.st_dev,
            stat.st_ino,
        ) != (
            media_stat.st_dev,
            media_stat.st_ino,
        ):
            raise ValueError(
                "Media mount changed"
            )

        if signature() != original:
            raise ValueError("Source changed")

        for path in (
            resources,
            resources / destination,
            resources / "manifest.json",
            resources / ".publication.json",
            resources / ".publication.lock",
        ):
            safe_path(
                root,
                path.relative_to(root),
                mount,
            )

        if shutil.disk_usage(mount).free < reserve + budget:
            raise ValueError(
                "Insufficient extraction budget"
            )

    args = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel", "error",
        "-xerror",
        "-n",
        "-copyts",
        "-i", str(source),
        "-map", f"0:{index}",
        "-c:s", "copy",
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        "-avoid_negative_ts", "disabled",
        *policy.muxer_options,
        "-f", policy.container,
    ]

    version = subprocess.check_output(
        ["ffmpeg", "-version"],
        text=True,
        timeout=30,
    ).splitlines()[0]

    provenance = {
        "project_id": planned["project_id"],
        "source": planned["source"],
        "source_stream": index,
        "source_codec": codec,
        "source_stream_metadata": stream,
        "resource_container": policy.container,
        "ffmpeg_version": version,
        "extraction_parameters": (
            args[1:] + ["<temporary-output>"]
        ),
    }

    def produce(path):
        check()

        subprocess.run(
            args + [str(path)],
            check=True,
        )

    def verify(path):
        check()

        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_streams",
                "-of", "json",
                "-i", str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.stderr.strip():
            raise ValueError(
                result.stderr.strip()
            )

        tracks = json.loads(
            result.stdout
        )["streams"]

        if (
            len(tracks) != 1
            or tracks[0]["codec_type"] != "subtitle"
            or tracks[0]["index"] != 0
        ):
            raise ValueError(
                "Expected exactly one subtitle stream"
            )

        if tracks[0].get("codec_name") != codec:
            raise ValueError(
                "Output subtitle codec mismatch"
            )

        report = verify_subtitles(
            source,
            path,
            index,
            0,
        )

        check()

        return report

    check()

    return publish(
        resources,
        destination,
        resource["id"],
        produce,
        verify,
        check,
        provenance=provenance,
        require_verification=True,
    )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "video",
        type=Path,
    )

    parser.add_argument(
        "--config",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--stream",
        type=int,
        required=True,
    )

    args = parser.parse_args()

    try:
        result = extract(
            args.video,
            json.loads(args.config.read_text()),
            args.stream,
        )

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        ArithmeticError,
        ParseError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            f"Subtitle extraction failed: {exc}",
            file=sys.stderr,
        )

        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

