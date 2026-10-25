"""Exercise atomic writes and replacement failures."""
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from sync_atomic import atomic_write_text


class AtomicWriteTests(unittest.TestCase):
    def test_create_and_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "automations.yaml"
            atomic_write_text(target, "first\n")
            self.assertEqual(target.read_text(), "first\n")
            atomic_write_text(target, "second\n")
            self.assertEqual(target.read_text(), "second\n")
            self.assertEqual(list(target.parent.glob(".automations.yaml.tmp-*")), [])

    def test_failed_replace_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "scripts.yaml"
            target.write_text("original\n")
            with patch("sync_atomic.os.replace", side_effect=OSError("simulated crash")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "replacement\n")
            self.assertEqual(target.read_text(), "original\n")
            self.assertEqual(list(target.parent.glob(".scripts.yaml.tmp-*")), [])


if __name__ == "__main__":
    unittest.main()
