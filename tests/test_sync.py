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
        for marker in ("GIT_FETCH_FAILED", "GIT_MERGE_FAILED", "GIT_PUSH_FAILED", "GIT_COMMIT_FAILED", "GIT_ADD_FAILED"):
            with self.subTest(marker=marker):
                self.assertRegex(self.source, re.escape('echo "' + marker + '"') + r'\s*\n\s*exit [1-9]')

    def test_no_implicit_git_push_target(self):
        commands = [
            line.strip() for line in self.source.splitlines()
            if line.lstrip().startswith("git push ")
        ]
        self.assertTrue(commands)
        self.assertTrue(all("origin HEAD:main" in line for line in commands))

    def test_lock_directory_has_exit_trap(self):
        self.assertIn("trap 'rmdir", self.source)


if __name__ == "__main__":
    unittest.main()
