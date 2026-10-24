"""Exercise the actual shell sync against an isolated local Git remote.

The production script hardcodes /config. Rewrite that path only in copies
inside a temporary directory; never run the production script against /config.
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = ("git_sync.sh", "sync_preflight.py", "sync_snapshot.py",
           "sync_atomic.py", "sync_automations.py", "sync_scripts.py")


def run(*args, cwd=None, check=True, env=None):
    return subprocess.run(args, cwd=cwd, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=check)


class PushFailureIntegrationTests(unittest.TestCase):
    def test_rejected_push_preserves_commit_and_retry_publishes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = pathlib.Path(temp)
            config = base / "config"
            remote = base / "remote.git"
            config.mkdir()
            run("git", "init", "--bare", str(remote))
            run("git", "init", "-b", "main", str(config))
            run("git", "config", "user.name", "Sync Test", cwd=config)
            run("git", "config", "user.email", "sync-test@example.invalid", cwd=config)
            run("git", "remote", "add", "origin", str(remote), cwd=config)
            for name in SOURCES:
                source = (ROOT / name).read_text()
                # The replacement is restricted to a disposable copy.
                (config / name).write_text(source.replace("/config", str(config)))
            (config / ".gitignore").write_text((ROOT / ".gitignore").read_text() + "\nautomations.yaml\nscripts.yaml\n.*_sync_state.yaml\n")
            (config / "automations.yaml").write_text(
                "- id: '1'\n  alias: Kitchen\n  trigger: []\n  action: []\n")
            (config / "scripts.yaml").write_text(
                "hello:\n  alias: Hello\n  sequence: []\n")
            env = dict(os.environ, GIT_AUTHOR_NAME="Sync Test",
                       GIT_AUTHOR_EMAIL="sync-test@example.invalid",
                       GIT_COMMITTER_NAME="Sync Test",
                       GIT_COMMITTER_EMAIL="sync-test@example.invalid")
            run("python3", "sync_automations.py", "--bootstrap",
                cwd=config, check=False, env=env)
            run("python3", "sync_scripts.py", "--bootstrap",
                cwd=config, check=False, env=env)
            # Bootstrap must have succeeded and produced both baselines.
            self.assertTrue((config / ".automations_sync_state.yaml").exists())
            self.assertTrue((config / ".scripts_sync_state.yaml").exists())
            run("git", "add", "-A", cwd=config)
            run("git", "commit", "-m", "baseline", cwd=config, env=env)
            run("git", "push", "-u", "origin", "main", cwd=config)
            shutil.rmtree(config / "automations")
            shutil.rmtree(config / "scripts")
            # A Home Assistant UI edit to the flat automation file.
            (config / "automations.yaml").write_text(
                "- id: '1'\n  alias: Kitchen Updated\n  trigger: []\n  action: []\n")
            hook = remote / "hooks" / "pre-receive"
            hook.write_text("#!/bin/sh\\nexit 1\\n".replace("\\n", "\n"))
            hook.chmod(0o755)
            before = run("git", "rev-parse", "HEAD", cwd=config).stdout.strip()
            first = run("bash", "git_sync.sh", cwd=config, check=False, env=env)
            self.assertNotEqual(first.returncode, 0)
            self.assertIn("GIT_PUSH_FAILED", first.stdout)
            local_commit = run("git", "rev-parse", "HEAD", cwd=config).stdout.strip()
            self.assertNotEqual(local_commit, before)
            remote_commit = run("git", "--git-dir", str(remote), "rev-parse", "main").stdout.strip()
            self.assertEqual(remote_commit, before)
            self.assertFalse(list(config.glob(".git-sync-backup.*")))
            hook.unlink()
            second = run("bash", "git_sync.sh", cwd=config, check=False, env=env)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            published = run("git", "--git-dir", str(remote), "rev-parse", "main").stdout.strip()
            self.assertEqual(published, local_commit)
            self.assertFalse(list(config.glob(".git-sync-backup.*")))



if __name__ == "__main__":
    unittest.main()
