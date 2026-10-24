"""Recovery inspection tests in temporary directories."""
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import sync_recover


class RecoveryInspectionTests(unittest.TestCase):
    def test_no_snapshots(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("builtins.print") as output:
                self.assertEqual(sync_recover.inspect(pathlib.Path(temp)), 0)
            output.assert_called_with("NO_RECOVERY_REQUIRED")

    def test_incomplete_snapshot_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / ".git-sync-backup.test").mkdir()
            with patch("builtins.print") as output:
                self.assertEqual(sync_recover.inspect(root), 5)
            self.assertIn("INCOMPLETE", str(output.call_args_list))


if __name__ == "__main__":
    unittest.main()
