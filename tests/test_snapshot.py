"""Snapshot/restore tests; never touch the actual /config directory."""
import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sync_snapshot", ROOT / "sync_snapshot.py")
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class SnapshotTests(unittest.TestCase):
    def test_round_trip_both_domains(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            backup = root / ".git-sync-backup.test"
            backup.mkdir()
            (root / "automations").mkdir()
            (root / "automations" / "a.yaml").write_text("original split")
            (root / "automations.yaml").write_text("original flat")
            (root / ".automations_sync_state.yaml").write_text("old state")
            with patch.object(snapshot, "CONFIG", root):
                snapshot.save(backup)
                (root / "automations.yaml").write_text("new flat")
                (root / "automations" / "a.yaml").write_text("new split")
                (root / "scripts.yaml").write_text("new file")
                snapshot.restore(backup)
                self.assertEqual((root / "automations.yaml").read_text(), "original flat")
                self.assertEqual((root / "automations" / "a.yaml").read_text(), "original split")
                self.assertEqual((root / ".automations_sync_state.yaml").read_text(), "old state")
                self.assertFalse((root / "scripts.yaml").exists())
                self.assertTrue((backup / ".complete").exists())

    def test_incomplete_snapshot_never_restores(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            backup = root / ".git-sync-backup.test"
            backup.mkdir()
            (root / "scripts.yaml").write_text("keep")
            with patch.object(snapshot, "CONFIG", root):
                with self.assertRaises(RuntimeError):
                    snapshot.restore(backup)
            self.assertEqual((root / "scripts.yaml").read_text(), "keep")

    def test_save_rejects_nonempty_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            backup = root / ".git-sync-backup.test"
            backup.mkdir()
            (backup / "existing").write_text("keep")
            with patch.object(snapshot, "CONFIG", root):
                with self.assertRaises(RuntimeError):
                    snapshot.save(backup)


if __name__ == "__main__":
    unittest.main()
