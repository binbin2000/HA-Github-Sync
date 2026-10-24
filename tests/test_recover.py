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


    def test_restore_requires_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            backup = root / ".git-sync-backup.test"
            backup.mkdir()
            with self.assertRaises(RuntimeError):
                sync_recover.recover(backup, root)

    def test_restore_rejects_multiple_snapshots(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            for suffix in ("one", "two"):
                backup = root / (".git-sync-backup." + suffix)
                backup.mkdir()
                (backup / ".complete").write_text("complete")
            with self.assertRaises(RuntimeError):
                sync_recover.recover(root / ".git-sync-backup.one", root)


    def test_active_sync_lock_blocks_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            backup = root / ".git-sync-backup.test"
            backup.mkdir()
            (backup / ".complete").write_text("complete")
            (root / ".automations_sync.lock").mkdir()
            with self.assertRaises(RuntimeError):
                sync_recover.recover(backup, root)
            self.assertTrue(backup.exists())


if __name__ == "__main__":
    unittest.main()
