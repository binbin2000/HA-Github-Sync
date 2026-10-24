#!/usr/bin/env python3
"""Record Git state for explicit recovery; never change Git history."""
import json
import pathlib
import subprocess
import sys

from sync_atomic import atomic_write_text


def git(*args, cwd=None):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                            text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def capture(snapshot, config=pathlib.Path("/config")):
    snapshot = pathlib.Path(snapshot)
    if not (snapshot / ".complete").is_file():
        raise RuntimeError("Cannot record Git state in incomplete snapshot")
    path = snapshot / "git-state.json"
    if path.exists():
        raise RuntimeError("Git state already recorded; refusing overwrite")
    data = {
        "schema": 1,
        "head_before_merge": git("rev-parse", "HEAD", cwd=config),
        "remote_before_merge": git("rev-parse", "refs/remotes/origin/main", cwd=config),
        "branch": git("symbolic-ref", "--short", "HEAD", cwd=config),
    }
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")
    return data


def inspect(snapshot, config=pathlib.Path("/config")):
    path = pathlib.Path(snapshot) / "git-state.json"
    if not path.is_file():
        return "GIT_METADATA_MISSING: manual investigation required"
    try:
        data = json.loads(path.read_text())
        if data.get("schema") != 1:
            raise ValueError("unsupported metadata version")
        before = data["head_before_merge"]
        remote = data["remote_before_merge"]
        branch = data["branch"]
        current = git("rev-parse", "HEAD", cwd=config)
        return (f"Git branch: {branch}; HEAD before merge: {before}; "
                f"origin/main before merge: {remote}; current HEAD: {current}; "
                f"changed: {current != before}. Git history is never reset automatically.")
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        return f"GIT_METADATA_UNAVAILABLE: {exc}; manual investigation required"


def main(args):
    if len(args) == 2 and args[0] == "capture":
        try:
            capture(pathlib.Path(args[1]))
            return 0
        except (OSError, RuntimeError) as exc:
            print(f"GIT_METADATA_ERROR: {exc}", file=sys.stderr)
            return 5
    if len(args) == 2 and args[0] == "inspect":
        print(inspect(pathlib.Path(args[1])))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
