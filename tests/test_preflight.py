"""Functional preflight tests using temporary Git repositories."""
import importlib.util
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sync_preflight", ROOT / "sync_preflight.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PreflightTests(unittest.TestCase):
    def run_git(self, directory, *args):
        return subprocess.run(["git", "-C", str(directory), *args],
                              capture_output=True, check=True)

    def test_clean_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            self.run_git(temp, "init")
            self.assertEqual(self.run_git(temp, "status", "--porcelain=v1", "-z").stdout, b"")

    def test_transient_split_deletions_are_allowed(self):
        self.assertEqual(module.safe_status(b" D automations/a.yaml\0 D scripts/b.yaml\0"), (True, ""))

    def test_real_modifications_are_blocked(self):
        for raw in (b" M configuration.yaml\0", b" M automations/a.yaml\0",
                    b"D  scripts/b.yaml\0", b"?? scripts/new.yaml\0",
                    b"?? secret.txt\0", b" M automations.yaml\0"):
            with self.subTest(raw=raw):
                self.assertFalse(module.safe_status(raw)[0])

    def test_git_failure_is_not_treated_as_clean(self):
        self.assertFalse(module.safe_status(b"invalid\0")[0])

    def test_actual_git_status(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp)
            self.run_git(temp, "init")
            self.run_git(temp, "config", "user.email", "test@example.invalid")
            self.run_git(temp, "config", "user.name", "Test")
            (path / "automations").mkdir()
            (path / "automations" / "one.yaml").write_text("test\n")
            self.run_git(temp, "add", ".")
            self.run_git(temp, "commit", "-m", "baseline")
            (path / "automations" / "one.yaml").unlink()
            raw = self.run_git(temp, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
            self.assertTrue(module.safe_status(raw)[0])
            (path / "automations" / "new.yaml").write_text("new\n")
            raw = self.run_git(temp, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
            self.assertFalse(module.safe_status(raw)[0])


if __name__ == "__main__":
    unittest.main()
