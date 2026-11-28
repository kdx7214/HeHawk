
import json
import os
import unittest

from unittest.mock import patch

import hehawk_register_verification as r
import hehawk_extract_audio as e
import test_hehawk_extract_audio as extraction_tests


class RegistrationTests(unittest.TestCase):

    def setUp(self):
        extraction_tests.ExtractionTests.setUp(self)

        for name, value in [
            (
                "preflight",
                lambda config: (
                    self.media,
                    self.workspace,
                    self.workspace.parent,
                ),
            ),
            (
                "safe_path",
                lambda root, rel, mount: root / rel,
            ),
        ]:
            p = patch.object(
                r,
                name,
                side_effect=value,
            )

            p.start()
            self.addCleanup(p.stop)

        e.extract(self.source, self.config, 0)

        self.manifest = (
            self.resources / "manifest.json"
        )

        self.target = (
            self.resources / "audio/stream-000.mka"
        )

        state = json.loads(
            self.manifest.read_text()
        )

        entry = state["resources"]["native_audio-000"]

        entry.pop("verification")

        entry["timeline_mapping"] = (
            "preserved-test-value"
        )

        self.manifest.write_text(
            json.dumps(state)
        )

    def run_registration(self):
        return r.register(
            self.source,
            self.config,
            0,
            True,
        )

    def test_success_and_repeat(self):
        before = r.signature(self.target)

        result = self.run_registration()

        self.assertEqual(
            result["status"],
            "registered",
        )

        self.assertTrue(
            result["resource"]["verification"][
                "decoded_match"
            ]
        )

        self.assertEqual(
            result["resource"]["timeline_mapping"],
            "preserved-test-value",
        )

        self.assertEqual(
            before,
            r.signature(self.target),
        )

        stamp = r.signature(self.manifest)

        self.assertEqual(
            self.run_registration()["status"],
            "unchanged",
        )

        self.assertEqual(
            stamp,
            r.signature(self.manifest),
        )

    def test_modified(self):
        with self.target.open("ab") as f:
            f.write(b"x")

        with self.assertRaises(ValueError):
            self.run_registration()

    def test_source_changed(self):
        s = self.source.stat()

        os.utime(
            self.source,
            ns=(
                s.st_atime_ns,
                s.st_mtime_ns + 1000000,
            ),
        )

        with self.assertRaises(ValueError):
            self.run_registration()

    def test_failed_packet(self):
        with patch.object(
            r,
            "verify",
            return_value={
                "passed": False,
                "packet_match": False,
            },
        ):
            with self.assertRaises(ValueError):
                self.run_registration()

    def test_failed_pcm(self):
        with patch.object(
            r,
            "verify",
            return_value={
                "passed": True,
                "packet_match": True,
                "decoded_match": False,
            },
        ):
            with self.assertRaises(ValueError):
                self.run_registration()

    def test_pending(self):
        (
            self.resources / ".publication.json"
        ).write_text("{}")

        with self.assertRaises(ValueError):
            self.run_registration()

    def test_missing_provenance(self):
        state = json.loads(
            self.manifest.read_text()
        )

        del state["resources"]["native_audio-000"][
            "provenance"
        ]

        self.manifest.write_text(
            json.dumps(state)
        )

        with self.assertRaises(KeyError):
            self.run_registration()

    def test_interrupted_update(self):
        before = self.manifest.read_bytes()

        with patch(
            "hehawk_publication.os.replace",
            side_effect=OSError(
                "simulated interruption"
            ),
        ):
            with self.assertRaises(OSError):
                self.run_registration()

        self.assertEqual(
            before,
            self.manifest.read_bytes(),
        )

    def test_no_downgrade(self):
        self.run_registration()

        with self.assertRaises(ValueError):
            r.register(
                self.source,
                self.config,
                0,
            )


if __name__ == "__main__":
    unittest.main()

