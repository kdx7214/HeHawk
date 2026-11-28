
#!/usr/bin/env python3
"""Native subtitle initialization conservation tests."""

import subprocess
import tempfile
import unittest

from pathlib import Path

from hehawk_verify_subtitles import verify


ASS_TEMPLATE = """[Script Info]
ScriptType: v4.00+
PlayResX: 384
PlayResY: 288
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,CROW reads the fine print.
Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,OWL checks the fine print.
Dialogue: 0,0:00:07.00,0:00:09.00,Default,,0,0,0,,MYNAH demands a refund.
"""


class ASSInitializationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="hehawk-ass-init-test-"
        )

        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)

        self.source = self.make_resource(
            "source", 20
        )

    def make_resource(self, name, font_size):
        ass = self.root / f"{name}.ass"
        mks = self.root / f"{name}.mks"

        ass.write_text(
            ASS_TEMPLATE.format(size=font_size),
            encoding="utf-8",
        )

        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel", "error",
                "-xerror",
                "-n",
                "-copyts",
                "-i", str(ass),
                "-map", "0:0",
                "-c:s", "copy",
                "-map_metadata", "-1",
                "-map_chapters", "-1",
                "-avoid_negative_ts", "disabled",
                "-f", "matroska",
                str(mks),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

        return mks

    def test_identical_initialization(self):
        resource = self.make_resource(
            "control", 20
        )

        report = verify(
            self.source, resource, 0, 0
        )

        self.assertEqual(
            report["source_codec"], "ass"
        )

        self.assertEqual(
            report["resource_codec"], "ass"
        )

        self.assertEqual(
            report["source_packets"]["count"], 3
        )

        self.assertEqual(
            report["resource_packets"]["count"], 3
        )

        self.assertGreater(
            report["source_initialization"]["size"], 0
        )

        self.assertEqual(
            report["source_initialization"],
            report["resource_initialization"],
        )

        self.assertTrue(
            report["initialization_match"]
        )

        self.assertTrue(report["packet_match"])

        self.assertEqual(
            report["metadata_differences"], []
        )

        self.assertTrue(
            report["native_preservation_passed"]
        )

        self.assertTrue(report["passed"])

    def test_changed_initialization(self):
        resource = self.make_resource(
            "modified", 30
        )

        report = verify(
            self.source, resource, 0, 0
        )

        self.assertEqual(
            report["source_codec"], "ass"
        )

        self.assertEqual(
            report["resource_codec"], "ass"
        )

        self.assertEqual(
            report["source_packets"]["count"], 3
        )

        self.assertEqual(
            report["resource_packets"]["count"], 3
        )

        self.assertEqual(
            report["source_packets"],
            report["resource_packets"],
        )

        self.assertTrue(report["packet_match"])

        self.assertGreater(
            report["source_initialization"]["size"], 0
        )

        self.assertEqual(
            report["source_initialization"]["size"],
            report["resource_initialization"]["size"],
        )

        self.assertNotEqual(
            report["source_initialization"]["sha256"],
            report["resource_initialization"]["sha256"],
        )

        self.assertFalse(
            report["initialization_match"]
        )

        self.assertEqual(
            report["metadata_differences"],
            ["initialization"],
        )

        self.assertFalse(
            report["native_preservation_passed"]
        )

        self.assertFalse(report["passed"])

        self.assertEqual(
            report["rendering_equivalence"],
            "unverified",
        )

        self.assertEqual(
            report["external_dependencies"],
            "unverified",
        )

        self.assertEqual(
            report["timeline_mapping"],
            "unverified",
        )


if __name__ == "__main__":
    unittest.main()

