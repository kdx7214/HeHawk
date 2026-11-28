
"""Synthetic native subtitle extraction integration tests."""

import json
import os
import subprocess
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

import hehawk_extract_subtitles as e

from hehawk_publication import digest


SUBTITLES = """1
00:00:01,000 --> 00:00:03,000
The owl is watching.

2
00:00:04,000 --> 00:00:06,000
The crow stole the seed.

3
00:00:07,000 --> 00:00:09,000
The mynah wants out.

"""


class SubtitleExtractionTests(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(
            prefix="hehawk-subtitle-extract-"
        )

        self.addCleanup(temporary.cleanup)

        self.root = Path(
            temporary.name
        ).resolve()

        self.media = self.root / "media"
        self.workspace = self.root / "workspace"

        self.media.mkdir()
        self.workspace.mkdir()

        self.subtitle_input = (
            self.root / "synthetic.srt"
        )

        self.subtitle_input.write_text(
            SUBTITLES,
            encoding="utf-8",
        )

        self.config = {
            "minimum_free_gib": 0,
        }

        for target in (
            "hehawk_extract_subtitles.preflight",
            "hehawk_resources.preflight",
        ):
            p = patch(
                target,
                return_value=(
                    self.media,
                    self.workspace,
                    self.root,
                ),
            )

            p.start()
            self.addCleanup(p.stop)

        p = patch.object(
            Path,
            "is_mount",
            return_value=True,
        )

        p.start()
        self.addCleanup(p.stop)

        for target in (
            "hehawk_extract_subtitles.safe_path",
            "hehawk_resources.safe_path",
        ):
            p = patch(
                target,
                side_effect=lambda root, rel, mount: (
                    root / rel
                ),
            )

            p.start()
            self.addCleanup(p.stop)

    def create_source(
        self,
        codec="subrip",
        extension=".mkv",
    ):
        relative = Path(
            "Movies/Synthetic (2026)"
            + extension
        )

        self.source = self.media / relative

        self.source.parent.mkdir(
            exist_ok=True
        )

        args = [
            "ffmpeg",
            "-nostdin",
            "-v", "error",
            "-n",
            "-f", "lavfi",
            "-i",
            (
                "sine=frequency=440:"
                "sample_rate=48000:duration=10"
            ),
            "-i", str(self.subtitle_input),
            "-map", "0:a:0",
            "-map", "1:s:0",
            "-c:a", "aac",
            "-c:s", codec,
            "-metadata:s:s:0", "language=eng",
        ]

        if codec == "mov_text":
            args.extend([
                "-write_btrt", "0",
            ])

        subprocess.run(
            args + [str(self.source)],
            check=True,
            timeout=60,
        )

        self.resources = (
            self.workspace
            / "projects"
            / relative.with_suffix("")
            / "resources"
        )

        self.resources.mkdir(parents=True)

        self.project_manifest = (
            self.resources.parent
            / "project.json"
        )

        self.project_manifest.write_text(
            json.dumps({
                "schema_version": 1,
                "project_id": "synthetic-subtitles",
                "media_relative_path": (
                    relative.as_posix()
                ),
                "source_size": (
                    self.source.stat().st_size
                ),
            })
        )

        self.manifest = (
            self.resources / "manifest.json"
        )

        self.journal = (
            self.resources / ".publication.json"
        )

    def extract(self, index=1):
        return e.extract(
            self.source,
            self.config,
            index,
        )

    def assert_published(
        self,
        result,
        extension,
        codec,
    ):
        expected = (
            f"subtitles/stream-001{extension}"
        )

        self.assertEqual(
            result["path"],
            expected,
        )

        target = self.resources / expected

        self.assertTrue(target.is_file())

        self.assertEqual(
            target.stat().st_mode & 0o777,
            0o600,
        )

        self.assertEqual(
            result["size"],
            target.stat().st_size,
        )

        self.assertEqual(
            result["sha256"],
            digest(target),
        )

        report = result["verification"]

        self.assertTrue(report["passed"])

        self.assertTrue(
            report["native_preservation_passed"]
        )

        self.assertTrue(
            report["packet_match"]
        )

        self.assertTrue(
            report["initialization_match"]
        )

        self.assertEqual(
            report["source_codec"],
            codec,
        )

        self.assertEqual(
            report["resource_codec"],
            codec,
        )

        self.assertEqual(
            report["source_stream"],
            1,
        )

        self.assertEqual(
            report["resource_stream"],
            0,
        )

        self.assertEqual(
            report["source_packets"],
            report["resource_packets"],
        )

        self.assertGreaterEqual(
            report["source_packets"]["count"],
            3,
        )

        for field in (
            "rendering_equivalence",
            "external_dependencies",
            "timeline_mapping",
        ):
            self.assertEqual(
                report[field],
                "unverified",
            )

        self.assertEqual(
            result["timeline_mapping"],
            "unverified",
        )

        state = json.loads(
            self.manifest.read_text()
        )

        self.assertEqual(
            state["resources"][
                "native_subtitle-001"
            ],
            result,
        )

        self.assertFalse(
            self.journal.exists()
        )

        self.assertEqual(
            list(
                target.parent.glob(".pending-*")
            ),
            [],
        )

        return target

    def assert_not_published(self):
        self.assertFalse(
            self.manifest.exists()
        )

        for extension in (".mks", ".mp4"):
            self.assertFalse(
                (
                    self.resources
                    / "subtitles"
                    / f"stream-001{extension}"
                ).exists()
            )

    def test_subrip_success(self):
        self.create_source()

        before = digest(self.source)
        project_before = (
            self.project_manifest.read_bytes()
        )

        result = self.extract()

        self.assert_published(
            result,
            ".mks",
            "subrip",
        )

        self.assertEqual(
            result["verification"][
                "source_packets"
            ]["count"],
            3,
        )

        self.assertEqual(
            result["provenance"][
                "source_stream_metadata"
            ]["tags"]["language"],
            "eng",
        )

        self.assertEqual(
            digest(self.source),
            before,
        )

        self.assertEqual(
            self.project_manifest.read_bytes(),
            project_before,
        )

    def test_ass_success(self):
        self.create_source(codec="ass")

        result = self.extract()

        self.assert_published(
            result,
            ".mks",
            "ass",
        )

        self.assertGreater(
            result["verification"][
                "source_initialization"
            ]["size"],
            0,
        )

    def test_mov_text_success(self):
        self.create_source(
            codec="mov_text",
            extension=".mp4",
        )

        result = self.extract()

        self.assert_published(
            result,
            ".mp4",
            "mov_text",
        )

        provenance = result["provenance"]

        self.assertEqual(
            provenance["resource_container"],
            "mp4",
        )

        args = provenance[
            "extraction_parameters"
        ]

        index = args.index("-write_btrt")

        self.assertEqual(
            args[index + 1],
            "0",
        )

        self.assertGreater(
            result["verification"][
                "source_initialization"
            ]["size"],
            0,
        )

    def test_rejected_verification(self):
        self.create_source()

        with patch.object(
            e,
            "verify_subtitles",
            return_value={
                "passed": False,
                "packet_match": False,
            },
        ):
            with self.assertRaises(ValueError):
                self.extract()

        self.assert_not_published()

        record = json.loads(
            self.journal.read_text()
        )

        self.assertEqual(
            record["state"],
            "pending",
        )

        self.assertTrue(
            record["verification_required"]
        )

    def test_missing_verification(self):
        self.create_source()

        with patch.object(
            e,
            "verify_subtitles",
            return_value=None,
        ):
            with self.assertRaises(ValueError):
                self.extract()

        self.assert_not_published()

        self.assertTrue(
            self.journal.exists()
        )

    def test_no_overwrite(self):
        self.create_source()

        result = self.extract()

        target = self.assert_published(
            result,
            ".mks",
            "subrip",
        )

        before = digest(target)
        manifest_before = self.manifest.read_bytes()

        with self.assertRaises(FileExistsError):
            self.extract()

        self.assertEqual(
            digest(target),
            before,
        )

        self.assertEqual(
            self.manifest.read_bytes(),
            manifest_before,
        )

    def test_audio_stream_rejected(self):
        self.create_source()

        with self.assertRaisesRegex(
            ValueError,
            "not a native subtitle resource",
        ):
            self.extract(index=0)

        self.assert_not_published()

        self.assertFalse(
            self.journal.exists()
        )

    def test_nonexistent_stream_rejected(self):
        self.create_source()

        with self.assertRaises(ValueError):
            self.extract(index=99)

        self.assert_not_published()

        self.assertFalse(
            self.journal.exists()
        )

    def test_unsupported_codec_rejected(self):
        self.create_source()

        inventory = e.inspect(self.source)

        inventory["streams"][1][
            "codec_name"
        ] = "webvtt"

        with patch.object(
            e,
            "inspect",
            return_value=inventory,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "Unsupported native subtitle codec",
            ):
                self.extract()

        self.assert_not_published()

        self.assertFalse(
            self.journal.exists()
        )

    def test_pending_transaction_blocks(self):
        self.create_source()

        self.journal.write_text("{}")

        with self.assertRaisesRegex(
            RuntimeError,
            "Pending publication",
        ):
            self.extract()

        self.assert_not_published()

        self.assertEqual(
            self.journal.read_text(),
            "{}",
        )

    def test_source_change_during_verification(self):
        self.create_source()

        original_verify = e.verify_subtitles

        def verify_and_change(*args, **kwargs):
            report = original_verify(
                *args,
                **kwargs,
            )

            stat = self.source.stat()

            os.utime(
                self.source,
                ns=(
                    stat.st_atime_ns,
                    stat.st_mtime_ns + 1000000000,
                ),
            )

            return report

        with patch.object(
            e,
            "verify_subtitles",
            side_effect=verify_and_change,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "Source changed",
            ):
                self.extract()

        self.assert_not_published()

        self.assertTrue(
            self.journal.exists()
        )


if __name__ == "__main__":
    unittest.main()

