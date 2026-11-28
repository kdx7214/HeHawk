
import unittest

from dataclasses import FrozenInstanceError

from hehawk_subtitle_policy import (
    POLICIES,
    SubtitlePolicy,
    policy_for,
)

from hehawk_verify_subtitles import (
    SUPPORTED_CODECS,
)


class SubtitlePolicyTests(unittest.TestCase):

    def assert_policy(
        self,
        codec,
        extension,
        container,
        options=(),
    ):
        policy = policy_for(codec)

        self.assertIsInstance(
            policy,
            SubtitlePolicy,
        )

        self.assertEqual(
            policy.extension,
            extension,
        )

        self.assertEqual(
            policy.container,
            container,
        )

        self.assertEqual(
            policy.muxer_options,
            options,
        )

    def test_codec_coverage(self):
        self.assertEqual(
            frozenset(POLICIES),
            SUPPORTED_CODECS,
        )

        self.assertEqual(
            frozenset(POLICIES),
            frozenset({
                "ass",
                "subrip",
                "hdmv_pgs_subtitle",
                "dvd_subtitle",
                "mov_text",
            }),
        )

    def test_ass(self):
        self.assert_policy(
            "ass",
            ".mks",
            "matroska",
        )

    def test_subrip(self):
        self.assert_policy(
            "subrip",
            ".mks",
            "matroska",
        )

    def test_pgs(self):
        self.assert_policy(
            "hdmv_pgs_subtitle",
            ".mks",
            "matroska",
        )

    def test_vobsub(self):
        self.assert_policy(
            "dvd_subtitle",
            ".mks",
            "matroska",
        )

    def test_mov_text(self):
        self.assert_policy(
            "mov_text",
            ".mp4",
            "mp4",
            ("-write_btrt", "0"),
        )

    def test_unsupported_codecs(self):
        for codec in (
            "webvtt",
            "dvb_subtitle",
            "eia_608",
            "dvb_teletext",
            "unknown",
            "aac",
            "h264",
        ):
            with self.subTest(codec=codec):
                self.assertIsNone(
                    policy_for(codec)
                )

    def test_missing_codec(self):
        self.assertIsNone(
            policy_for(None)
        )

        self.assertIsNone(
            policy_for("")
        )

    def test_policy_immutable(self):
        policy = policy_for("mov_text")

        for attribute, value in (
            ("extension", ".mks"),
            ("container", "matroska"),
            ("muxer_options", ()),
        ):
            with self.subTest(attribute=attribute):
                with self.assertRaises(
                    FrozenInstanceError
                ):
                    setattr(
                        policy,
                        attribute,
                        value,
                    )

        self.assert_policy(
            "mov_text",
            ".mp4",
            "mp4",
            ("-write_btrt", "0"),
        )


if __name__ == "__main__":
    unittest.main()

