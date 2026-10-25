"""Regression tests for git_sync.sh safety guarantees.

Run with: python3 -m unittest discover -s tests -v
No Home Assistant instance or network access required.
"""
import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "git_sync.sh"


class ShellSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text()

    def test_shell_syntax(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_force_push_or_hard_reset(self):
        # Match executable commands, not comments/documentation.
        commands = "\n".join(
            line.strip() for line in self.source.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        self.assertNotRegex(commands, r"git\s+push\s+--force\b")
        self.assertNotRegex(commands, r"git\s+reset\s+--hard\b")

    def test_diverged_conflict_aborts(self):
        self.assertIn('echo "GIT_CONFLICT:', self.source)
        self.assertRegex(self.source, r'echo "GIT_CONFLICT:[^\n]*\n\s*exit [1-9]')

    def test_reconciliation_failures_abort_before_staging(self):
        check = self.source.index('if [ "$automations_exit" -ge 2 ] || [ "$scripts_exit" -ge 2 ]; then')
        staging = self.source.index("git add -A -- automations/ scripts/")
        self.assertLess(check, staging)
        self.assertRegex(self.source[check:staging], r"exit [1-9]")

    def test_git_failures_are_nonzero(self):
        for marker in ("GIT_FETCH_FAILED", "GIT_MERGE_FAILED", "GIT_COMMIT_FAILED", "GIT_ADD_FAILED"):
            with self.subTest(marker=marker):
                self.assertRegex(self.source, re.escape('echo "' + marker) + r'(?::[^\n"]*)?"\s*\n\s*exit [1-9]')
        # Push failures intentionally clean up the snapshot before exiting.
        # Both push branches must still report failure with a nonzero exit.
        push_branches = self.source.split('if ! git push origin HEAD:main; then')[1:]
        self.assertEqual(len(push_branches), 2)
        for branch in push_branches:
            with self.subTest(marker="GIT_PUSH_FAILED"):
                failure_branch = branch.split("\n    fi", 1)[0]
                self.assertIn("GIT_PUSH_FAILED", failure_branch)
                self.assertRegex(failure_branch, r"exit [1-9]")

    def test_changed_head_blocks_rollback_before_restore(self):
        start = self.source.index('if [ "$automations_exit" -ge 2 ]')
        end = self.source.index('git add -A -- automations/ scripts/', start)
        failure_path = self.source[start:end]
        guard = failure_path.index('if [ "$(git rev-parse HEAD)" != "$LOCAL_HASH" ]; then')
        restore = failure_path.index('python3 sync_snapshot.py restore "$SNAPSHOT_DIR"')
        self.assertLess(guard, restore)
        self.assertIn('RECOVERY_REQUIRED: Git HEAD changed', failure_path[guard:restore])
        self.assertRegex(failure_path[guard:restore], r'exit 5')

    def test_no_implicit_git_push_target(self):
        commands = [
            line.strip() for line in self.source.splitlines()
            if "git push " in line and not line.lstrip().startswith("#")
        ]
        self.assertTrue(commands)
        self.assertTrue(all("origin HEAD:main" in line for line in commands))

    def test_failed_push_keeps_local_commit_and_discards_snapshot(self):
        source = self.source
        self.assertEqual(source.count("discard_snapshot_after_git_failure || exit 5"), 2)
        self.assertEqual(source.count("GIT_PUSH_FAILED: local commit preserved"), 2)
        for part in source.split('if ! git push origin HEAD:main; then')[1:]:
            branch = part.split("fi", 1)[0]
            self.assertIn("discard_snapshot_after_git_failure || exit 5", branch)
            self.assertNotIn("git reset", branch)
            self.assertNotIn("sync_snapshot.py restore", branch)

    def test_interrupted_snapshot_blocks_before_checkout_and_reconciliation(self):
        guard = self.source.index('echo "RECOVERY_REQUIRED:')
        checkout = self.source.index('git checkout HEAD -- automations/')
        reconciliation = self.source.index('python3 sync_automations.py')
        self.assertLess(guard, checkout)
        self.assertLess(guard, reconciliation)
        self.assertIn('for previous_snapshot in /config/.git-sync-backup.*; do', self.source)
        self.assertRegex(self.source[guard:checkout], r'exit [1-9]')

    def test_lock_directory_has_exit_trap(self):
        self.assertIn("trap 'rmdir", self.source)


if __name__ == "__main__":
    unittest.main()
