
#!/usr/bin/env python3
"""Regression tests for native subtitle verification."""

import subprocess
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from hehawk_verify_subtitles import (
    SUPPORTED_CODECS,
    initialization,
    canvas,
    compare_canvas,
    metadata_observations,
    signature,
    verify,
)


# ------------------------------------------------------------
# Initialization data tests
# ------------------------------------------------------------

class InitializationTests(unittest.TestCase):

    def test_supported_codecs(self):
        self.assertEqual(
            SUPPORTED_CODECS,
            {
                "ass",
                "mov_text",
                "hdmv_pgs_subtitle",
                "dvd_subtitle",
                "subrip",
            },
        )

    def test_required_initialization_missing(self):
        for codec in ("ass", "mov_text", "dvd_subtitle"):
            with self.subTest(codec=codec):
                with self.assertRaises(ValueError):
                    initialization({
                        "codec_name": codec,
                    })

    def test_optional_initialization_absent(self):
        for codec in ("subrip", "hdmv_pgs_subtitle"):
            with self.subTest(codec=codec):
                self.assertEqual(
                    initialization({
                        "codec_name": codec,
                    }),
                    {
                        "size": 0,
                        "sha256": None,
                    },
                )

    def test_valid_initialization(self):
        result = initialization({
            "codec_name": "ass",
            "extradata_size": 100,
            "extradata_hash": "SHA256:" + "A" * 64,
        })

        self.assertEqual(result["size"], 100)
        self.assertEqual(
            result["sha256"],
            "sha256:" + "a" * 64,
        )

    def test_missing_hash(self):
        with self.assertRaises(ValueError):
            initialization({
                "codec_name": "ass",
                "extradata_size": 100,
            })

    def test_malformed_hash(self):
        with self.assertRaises(ValueError):
            initialization({
                "codec_name": "ass",
                "extradata_size": 100,
                "extradata_hash": "SHA256:invalid",
            })

    def test_hash_without_data(self):
        with self.assertRaises(ValueError):
            initialization({
                "codec_name": "subrip",
                "extradata_size": 0,
                "extradata_hash": "SHA256:" + "a" * 64,
            })

    def test_negative_size(self):
        with self.assertRaises(ValueError):
            initialization({
                "codec_name": "ass",
                "extradata_size": -1,
            })

    def test_optional_initialization_present(self):
        for codec in ("subrip", "hdmv_pgs_subtitle"):
            with self.subTest(codec=codec):
                result = initialization({
                    "codec_name": codec,
                    "extradata_size": 10,
                    "extradata_hash": "SHA256:" + "a" * 64,
                })

                self.assertEqual(result["size"], 10)
                self.assertEqual(
                    result["sha256"],
                    "sha256:" + "a" * 64,
                )


# ------------------------------------------------------------
# Canvas verification tests
# ------------------------------------------------------------

class CanvasTests(unittest.TestCase):

    SD = {"width": 720, "height": 480}
    HD = {"width": 1920, "height": 1080}

    def test_absent_canvas(self):
        self.assertIsNone(canvas({}))

    def test_zero_canvas(self):
        self.assertIsNone(canvas({
            "width": 0,
            "height": 0,
        }))

    def test_incomplete_canvas(self):
        with self.assertRaises(ValueError):
            canvas({"width": 720})

    def test_negative_canvas(self):
        with self.assertRaises(ValueError):
            canvas({
                "width": -720,
                "height": 480,
            })

    def test_vobsub_sd_match(self):
        self.assertEqual(
            compare_canvas(
                "dvd_subtitle", self.SD, self.SD
            ),
            "match",
        )

    def test_vobsub_hd_match(self):
        self.assertEqual(
            compare_canvas(
                "dvd_subtitle", self.HD, self.HD
            ),
            "match",
        )

    def test_vobsub_dimension_mismatch(self):
        self.assertEqual(
            compare_canvas(
                "dvd_subtitle", self.SD, self.HD
            ),
            "mismatch",
        )

    def test_vobsub_missing_dimensions(self):
        for a, b in (
            ({}, self.SD),
            (self.SD, {}),
            ({}, {}),
        ):
            with self.subTest(source=a, resource=b):
                self.assertEqual(
                    compare_canvas("dvd_subtitle", a, b),
                    "required_dimensions_missing",
                )

    def test_pgs_discovered_dimensions(self):
        self.assertEqual(
            compare_canvas(
                "hdmv_pgs_subtitle", {}, self.HD
            ),
            "resource_dimensions_discovered",
        )

    def test_pgs_lost_dimensions(self):
        self.assertEqual(
            compare_canvas(
                "hdmv_pgs_subtitle", self.HD, {}
            ),
            "mismatch",
        )

    def test_pgs_dimension_mismatch(self):
        self.assertEqual(
            compare_canvas(
                "hdmv_pgs_subtitle", self.HD, self.SD
            ),
            "mismatch",
        )

    def test_text_canvas_absent(self):
        for codec in ("ass", "mov_text", "subrip"):
            with self.subTest(codec=codec):
                self.assertEqual(
                    compare_canvas(codec, {}, {}),
                    "not_reported",
                )


# ------------------------------------------------------------
# Metadata observation tests
# ------------------------------------------------------------

class MetadataObservationTests(unittest.TestCase):

    def test_identical_metadata(self):
        stream = {
            "time_base": "1/1000",
            "start_pts": 0,
            "duration": "10.000000",
            "tags": {"language": "eng"},
        }

        self.assertEqual(
            metadata_observations(stream, stream),
            {},
        )

    def test_duration_difference(self):
        self.assertEqual(
            metadata_observations(
                {"duration": "10.000000"},
                {"duration": "9.000000"},
            ),
            {
                "duration": {
                    "source": "10.000000",
                    "resource": "9.000000",
                },
            },
        )

    def test_missing_language_tag(self):
        self.assertEqual(
            metadata_observations(
                {"tags": {"language": "eng"}},
                {"tags": {}},
            ),
            {
                "tags": {
                    "source": {"language": "eng"},
                    "resource": {},
                },
            },
        )

    def test_disposition_difference(self):
        self.assertEqual(
            metadata_observations(
                {"disposition": {"forced": 1}},
                {"disposition": {"forced": 0}},
            ),
            {
                "disposition": {
                    "source": {"forced": 1},
                    "resource": {"forced": 0},
                },
            },
        )


# ------------------------------------------------------------
# End-to-end native conservation tests
# ------------------------------------------------------------

class ConservationTests(unittest.TestCase):

    ORIGINAL = """1
00:00:01,000 --> 00:00:03,000
The owl is watching.

2
00:00:04,000 --> 00:00:06,000
The crow stole the seed.

3
00:00:07,000 --> 00:00:09,000
The mynah wants out.

"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="hehawk-subtitle-test-"
        )

        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)

        self.source = self.make_resource(
            "source",
            self.ORIGINAL,
        )

    def ffmpeg(self, *args):
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel", "error",
                "-xerror",
                "-n",
                *map(str, args),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def make_resource(self, name, content):
        srt = self.root / f"{name}.srt"
        mks = self.root / f"{name}.mks"

        srt.write_text(
            content,
            encoding="utf-8",
        )

        self.ffmpeg(
            "-copyts",
            "-i", srt,
            "-map", "0:0",
            "-c:s", "copy",
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-avoid_negative_ts", "disabled",
            "-f", "matroska",
            mks,
        )

        return mks

    def test_lossless_remux(self):
        resource = self.root / "remux.mks"

        self.ffmpeg(
            "-copyts",
            "-i", self.source,
            "-map", "0:0",
            "-c:s", "copy",
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-avoid_negative_ts", "disabled",
            "-f", "matroska",
            resource,
        )

        report = verify(
            self.source, resource, 0, 0
        )

        self.assertTrue(report["passed"])
        self.assertTrue(report["packet_match"])
        self.assertTrue(report["initialization_match"])
        self.assertEqual(
            report["source_packets"]["count"], 3
        )
        self.assertEqual(
            report["timeline_mapping"], "unverified"
        )
        self.assertEqual(
            report["rendering_equivalence"], "unverified"
        )

    def test_changed_text(self):
        resource = self.make_resource(
            "changed",
            self.ORIGINAL.replace(
                "stole the seed",
                "sold the seed",
            ),
        )

        report = verify(
            self.source, resource, 0, 0
        )

        self.assertFalse(report["passed"])
        self.assertFalse(report["packet_match"])
        self.assertTrue(report["initialization_match"])

        self.assertEqual(
            report["source_packets"]["count"],
            report["resource_packets"]["count"],
        )

    def test_shifted_timestamp(self):
        resource = self.make_resource(
            "shifted",
            self.ORIGINAL.replace(
                "00:00:04,000",
                "00:00:04,500",
            ),
        )

        report = verify(
            self.source, resource, 0, 0
        )

        self.assertFalse(report["passed"])
        self.assertFalse(report["packet_match"])

    def test_changed_duration(self):
        resource = self.make_resource(
            "duration",
            self.ORIGINAL.replace(
                "00:00:06,000",
                "00:00:06,500",
            ),
        )

        report = verify(
            self.source, resource, 0, 0
        )

        self.assertFalse(report["passed"])
        self.assertFalse(report["packet_match"])

    def test_truncated_stream(self):
        resource = self.make_resource(
            "truncated",
            self.ORIGINAL.split("\n3\n", 1)[0]
            + "\n",
        )

        report = verify(
            self.source, resource, 0, 0
        )

        self.assertFalse(report["passed"])
        self.assertFalse(report["packet_match"])

        self.assertEqual(
            report["source_packets"]["count"], 3
        )
        self.assertEqual(
            report["resource_packets"]["count"], 2
        )

    def test_changed_codec(self):
        resource = self.root / "converted-ass.mks"

        self.ffmpeg(
            "-i", self.source,
            "-map", "0:0",
            "-c:s", "ass",
            "-f", "matroska",
            resource,
        )

        report = verify(
            self.source, resource, 0, 0
        )

        self.assertFalse(report["passed"])
        self.assertIn(
            "codec_name",
            report["metadata_differences"],
        )

    def test_invalid_stream_index(self):
        with self.assertRaises(ValueError):
            verify(
                self.source,
                self.source,
                99,
                0,
            )

    def test_missing_resource(self):
        with self.assertRaises(FileNotFoundError):
            verify(
                self.source,
                self.root / "missing.mks",
                0,
                0,
            )

    def test_corrupt_resource(self):
        resource = self.root / "corrupt.mks"

        resource.write_bytes(
            b"This is not a Matroska container."
        )

        with self.assertRaises(
            subprocess.CalledProcessError
        ):
            verify(
                self.source,
                resource,
                0,
                0,
            )

    def test_input_changed_during_verification(self):
        resource = self.make_resource(
            "modified",
            self.ORIGINAL,
        )

        source_signature = signature(self.source)
        resource_signature = signature(resource)

        changed_signature = (
            resource_signature[0],
            resource_signature[1],
            resource_signature[2],
            resource_signature[3] + 1,
        )

        with patch(
            "hehawk_verify_subtitles.signature",
            side_effect=[
                source_signature,
                resource_signature,
                source_signature,
                changed_signature,
            ],
        ):
            with self.assertRaisesRegex(
                ValueError,
                "Input changed during verification",
            ):
                verify(
                    self.source,
                    resource,
                    0,
                    0,
                )


# ------------------------------------------------------------
# Entry point
# ------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()

