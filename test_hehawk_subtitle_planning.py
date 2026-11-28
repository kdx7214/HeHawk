
import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

import hehawk_resources as planner


class SubtitlePlanningTests(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(
            prefix="hehawk-subtitle-plan-"
        )

        self.addCleanup(temporary.cleanup)

        self.mount = Path(temporary.name)
        self.media = self.mount / "media"
        self.workspace = self.mount / "workspace"

        self.media.mkdir()
        self.workspace.mkdir()

        self.relative = Path(
            "Movies/Test Movie (2026).mkv"
        )

        self.source = self.media / self.relative

        self.source.parent.mkdir()
        self.source.write_bytes(b"synthetic media")

        self.project = (
            self.workspace
            / "projects"
            / self.relative.with_suffix("")
        )

        self.project.mkdir(parents=True)

        self.resources = self.project / "resources"
        self.resources.mkdir()

        self.manifest = self.project / "project.json"

        self.manifest.write_text(json.dumps({
            "schema_version": 1,
            "project_id": "subtitle-planning-test",
            "media_relative_path": (
                self.relative.as_posix()
            ),
            "source_size": (
                self.source.stat().st_size
            ),
        }))

        self.config = {
            "minimum_free_gib": 0,
        }

        self.inventory = {
            "source": str(self.source),
            "format": {
                "duration": "10.125",
            },
            "streams": [],
        }

        preflight = patch.object(
            planner,
            "preflight",
            return_value=(
                self.media,
                self.workspace,
                self.mount,
            ),
        )

        preflight.start()
        self.addCleanup(preflight.stop)

        safe_path = patch.object(
            planner,
            "safe_path",
            side_effect=lambda root, rel, mount: (
                root / rel
            ),
        )

        safe_path.start()
        self.addCleanup(safe_path.stop)

    def add_subtitle(self, index, codec):
        self.inventory["streams"].append({
            "index": index,
            "codec_type": "subtitle",
            "codec_name": codec,
            "tags": {
                "language": "eng",
            },
            "disposition": {
                "default": 0,
                "forced": 0,
            },
        })

    def add_audio(self, index=1):
        self.inventory["streams"].append({
            "index": index,
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
            "sample_rate": "48000",
            "tags": {
                "language": "eng",
            },
            "disposition": {
                "default": 1,
            },
        })

    def run_plan(self):
        return planner.plan(
            self.inventory,
            self.config,
        )

    def test_all_supported_codecs(self):
        cases = [
            (2, "ass", ".mks", "matroska", []),
            (3, "subrip", ".mks", "matroska", []),
            (
                4,
                "hdmv_pgs_subtitle",
                ".mks",
                "matroska",
                [],
            ),
            (
                5,
                "dvd_subtitle",
                ".mks",
                "matroska",
                [],
            ),
            (
                6,
                "mov_text",
                ".mp4",
                "mp4",
                ["-write_btrt", "0"],
            ),
        ]

        for index, codec, _, _, _ in cases:
            self.add_subtitle(index, codec)

        result = self.run_plan()

        resources = {
            r["source_stream"]: r
            for r in result["resources"]
        }

        self.assertEqual(len(resources), 5)

        for (
            index,
            codec,
            extension,
            container,
            options,
        ) in cases:
            with self.subTest(codec=codec):
                resource = resources[index]

                self.assertEqual(
                    resource["id"],
                    f"native_subtitle-{index:03d}",
                )

                self.assertEqual(
                    resource["kind"],
                    "native_subtitle",
                )

                self.assertEqual(
                    resource["source_codec"],
                    codec,
                )

                self.assertEqual(
                    resource["path"],
                    (
                        "resources/subtitles/"
                        f"stream-{index:03d}"
                        f"{extension}"
                    ),
                )

                self.assertEqual(
                    resource["container"],
                    container,
                )

                self.assertEqual(
                    resource["muxer_options"],
                    options,
                )

                self.assertEqual(
                    resource["status"],
                    "planned",
                )

                self.assertIsNone(
                    resource["dependency"]
                )

                self.assertEqual(
                    resource["timeline_mapping"],
                    "unverified",
                )

        self.assertEqual(
            result["deferred_resources"],
            [],
        )

    def test_unsupported_subtitle_deferred(self):
        self.add_subtitle(2, "webvtt")

        result = self.run_plan()

        self.assertEqual(
            len(result["resources"]),
            1,
        )

        resource = result["resources"][0]

        self.assertEqual(
            resource["id"],
            "native_subtitle-002",
        )

        self.assertEqual(
            resource["source_codec"],
            "webvtt",
        )

        self.assertEqual(
            resource["status"],
            "deferred_unsupported_codec",
        )

        self.assertIsNone(resource["path"])
        self.assertIsNone(resource["dependency"])

        self.assertTrue(resource["reason"])

        self.assertNotIn(
            "container",
            resource,
        )

        self.assertNotIn(
            "muxer_options",
            resource,
        )

        self.assertEqual(
            result["deferred_resources"],
            [{
                "id": resource["id"],
                "source_stream": 2,
                "source_codec": "webvtt",
                "reason": resource["reason"],
            }],
        )

        self.assertEqual(
            result["conflicts"],
            [],
        )

    def test_missing_codec_deferred(self):
        self.add_subtitle(2, None)

        result = self.run_plan()

        resource = result["resources"][0]

        self.assertEqual(
            resource["status"],
            "deferred_unsupported_codec",
        )

        self.assertIsNone(
            resource["source_codec"]
        )

        self.assertIsNone(resource["path"])

        self.assertEqual(
            len(result["deferred_resources"]),
            1,
        )

    def test_deferred_only_storage_budget(self):
        self.add_subtitle(2, "webvtt")

        storage = self.run_plan()["storage"]

        for key in (
            "native_budget_bytes",
            "pcm_payload_bytes",
            "overhead_allowance_bytes",
            "estimated_bytes",
        ):
            with self.subTest(key=key):
                self.assertEqual(
                    storage[key],
                    0,
                )

    def test_mixed_supported_and_deferred(self):
        self.add_subtitle(2, "ass")
        self.add_subtitle(3, "webvtt")
        self.add_subtitle(4, "mov_text")

        result = self.run_plan()

        resources = {
            r["source_stream"]: r
            for r in result["resources"]
        }

        self.assertEqual(len(resources), 3)

        self.assertEqual(
            resources[2]["status"],
            "planned",
        )

        self.assertEqual(
            resources[3]["status"],
            "deferred_unsupported_codec",
        )

        self.assertEqual(
            resources[4]["status"],
            "planned",
        )

        self.assertEqual(
            len(result["deferred_resources"]),
            1,
        )

        self.assertEqual(
            result["storage"]["native_budget_bytes"],
            self.source.stat().st_size,
        )

    def test_audio_planning_unaffected(self):
        self.add_audio()
        self.add_subtitle(2, "mov_text")
        self.add_subtitle(3, "webvtt")

        result = self.run_plan()

        resources = {
            r["id"]: r
            for r in result["resources"]
        }

        audio = resources["native_audio-001"]
        pcm = resources["recognition_pcm-001"]

        self.assertEqual(
            audio["path"],
            "resources/audio/stream-001.mka",
        )

        self.assertEqual(
            pcm["path"],
            "resources/audio/stream-001-16k-mono.wav",
        )

        self.assertEqual(
            pcm["dependency"],
            "native_audio-001",
        )

        self.assertNotIn("container", audio)
        self.assertNotIn("muxer_options", audio)

        self.assertEqual(
            result["storage"]["pcm_payload_bytes"],
            324000,
        )

        self.assertFalse(
            result["recognition_ready"]
        )

    def test_existing_mov_text_conflict(self):
        self.add_subtitle(2, "mov_text")

        target = (
            self.resources
            / "subtitles"
            / "stream-002.mp4"
        )

        target.parent.mkdir()
        target.write_bytes(b"existing resource")

        result = self.run_plan()

        resource = result["resources"][0]

        self.assertEqual(
            resource["status"],
            "existing_unverified",
        )

        self.assertEqual(
            result["conflicts"],
            ["resources/subtitles/stream-002.mp4"],
        )

        self.assertEqual(
            target.read_bytes(),
            b"existing resource",
        )

    def test_no_subtitles_not_deferred(self):
        result = self.run_plan()

        self.assertEqual(
            result["resources"],
            [],
        )

        self.assertEqual(
            result["deferred_resources"],
            [],
        )

        self.assertEqual(
            result["storage"]["estimated_bytes"],
            0,
        )

    def test_planning_is_read_only(self):
        self.add_audio()
        self.add_subtitle(2, "ass")
        self.add_subtitle(3, "mov_text")
        self.add_subtitle(4, "webvtt")

        before = sorted(
            str(p.relative_to(self.workspace))
            for p in self.workspace.rglob("*")
        )

        manifest_before = self.manifest.read_bytes()
        source_before = self.source.read_bytes()

        self.run_plan()

        after = sorted(
            str(p.relative_to(self.workspace))
            for p in self.workspace.rglob("*")
        )

        self.assertEqual(before, after)

        self.assertEqual(
            manifest_before,
            self.manifest.read_bytes(),
        )

        self.assertEqual(
            source_before,
            self.source.read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()

