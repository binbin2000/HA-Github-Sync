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


    def test_failed_directory_staging_preserves_live_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            backup = root / ".git-sync-backup.test"
            backup.mkdir()
            live = root / "automations"
            live.mkdir()
            (live / "a.yaml").write_text("original")
            with patch.object(snapshot, "CONFIG", root):
                snapshot.save(backup)
                (live / "a.yaml").write_text("newer")
                original_copytree = snapshot.shutil.copytree

                def fail_stage(src, dst, *args, **kwargs):
                    if pathlib.Path(src) == backup / "automations":
                        raise OSError("injected staging failure")
                    return original_copytree(src, dst, *args, **kwargs)

                with patch.object(snapshot.shutil, "copytree", side_effect=fail_stage):
                    with self.assertRaises(OSError):
                        snapshot.restore(backup)
            self.assertEqual((live / "a.yaml").read_text(), "newer")
            self.assertEqual((backup / "automations" / "a.yaml").read_text(), "original")
            self.assertFalse(list(root.glob(".automations.sync-stage.*")))

    def test_failed_directory_swap_restores_previous_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            backup = root / ".git-sync-backup.test"
            backup.mkdir()
            live = root / "automations"
            live.mkdir()
            (live / "a.yaml").write_text("original")
            with patch.object(snapshot, "CONFIG", root):
                snapshot.save(backup)
                (live / "a.yaml").write_text("newer")
                real_replace = snapshot.os.replace

                def fail_new_directory(src, dst):
                    if ".automations.sync-stage." in str(src):
                        raise OSError("injected swap failure")
                    return real_replace(src, dst)

                with patch.object(snapshot.os, "replace", side_effect=fail_new_directory):
                    with self.assertRaises(OSError):
                        snapshot.restore(backup)
            self.assertEqual((live / "a.yaml").read_text(), "newer")
            self.assertTrue((backup / ".complete").exists())


if __name__ == "__main__":
    unittest.main()
