"""Git metadata and manual-recovery guard tests in disposable repositories."""
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import sync_git_metadata
import sync_recover
import sync_snapshot


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


class GitRecoveryMetadataTests(unittest.TestCase):
    def test_capture_records_pre_merge_commits_and_blocks_changed_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            git(root, "init", "-b", "main")
            git(root, "config", "user.name", "Test")
            git(root, "config", "user.email", "test@example.invalid")
            (root / "tracked").write_text("one")
            git(root, "add", "tracked")
            git(root, "commit", "-m", "first")
            head = git(root, "rev-parse", "HEAD")
            git(root, "update-ref", "refs/remotes/origin/main", head)
            snapshot = root / ".git-sync-backup.test"
            snapshot.mkdir()
            (root / "automations.yaml").write_text("old")
            with patch.object(sync_snapshot, "CONFIG", root):
                sync_snapshot.save(snapshot)
            data = sync_git_metadata.capture(snapshot, root)
            self.assertEqual(data["head_before_merge"], head)
            self.assertEqual(data["remote_before_merge"], head)
            self.assertEqual(json.loads((snapshot / "git-state.json").read_text())["schema"], 1)
            (root / "tracked").write_text("two")
            git(root, "add", "tracked")
            git(root, "commit", "-m", "second")
            (root / "automations.yaml").write_text("new")
            with self.assertRaisesRegex(RuntimeError, "Git HEAD changed"):
                sync_recover.recover(snapshot, root)
            self.assertEqual((root / "automations.yaml").read_text(), "new")
            self.assertTrue(snapshot.exists())
            self.assertIn("changed: True", sync_git_metadata.inspect(snapshot, root))

    def test_capture_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            git(root, "init", "-b", "main")
            git(root, "config", "user.name", "Test")
            git(root, "config", "user.email", "test@example.invalid")
            (root / "tracked").write_text("one")
            git(root, "add", "tracked")
            git(root, "commit", "-m", "first")
            head = git(root, "rev-parse", "HEAD")
            git(root, "update-ref", "refs/remotes/origin/main", head)
            snapshot = root / ".git-sync-backup.test"
            snapshot.mkdir()
            (snapshot / ".complete").write_text("complete")
            sync_git_metadata.capture(snapshot, root)
            with self.assertRaisesRegex(RuntimeError, "already recorded"):
                sync_git_metadata.capture(snapshot, root)


if __name__ == "__main__":
    unittest.main()
