#!/usr/bin/env python3
"""Snapshot and restore sync-managed files without touching other HA config.

Usage: python3 sync_snapshot.py save SNAPSHOT_DIR
       python3 sync_snapshot.py restore SNAPSHOT_DIR
       python3 sync_snapshot.py discard SNAPSHOT_DIR

The snapshot must be in /config and is created by the shell script using mktemp.
"""
import os
import pathlib
import shutil
import sys
import tempfile

CONFIG = pathlib.Path("/config")
FILES = ("automations.yaml", "scripts.yaml",
         ".automations_sync_state.yaml", ".scripts_sync_state.yaml")
DIRS = ("automations", "scripts")


def save(snapshot):
    if any(snapshot.iterdir()):
        raise RuntimeError("Snapshot destination is not empty")
    for name in FILES:
        source = CONFIG / name
        if source.is_file():
            shutil.copy2(source, snapshot / name)
    for name in DIRS:
        source = CONFIG / name
        if source.exists():
            shutil.copytree(source, snapshot / name)
    (snapshot / ".complete").write_text("complete\n")


def restore(snapshot):
    if not (snapshot / ".complete").is_file():
        raise RuntimeError("Incomplete snapshot; refusing restore")
    # Do not delete the backup until every restoration succeeds.
    for name in FILES:
        source, target = snapshot / name, CONFIG / name
        if source.is_file():
            temporary = target.with_name(target.name + ".sync-restore-tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        elif target.exists():
            target.unlink()
    for name in DIRS:
        source, target = snapshot / name, CONFIG / name
        # Stage the complete replacement before touching the live directory.
        staged = None
        previous = None
        try:
            if source.is_dir():
                staged = pathlib.Path(tempfile.mkdtemp(
                    prefix=f".{name}.sync-stage.", dir=CONFIG))
                shutil.rmtree(staged)
                shutil.copytree(source, staged)
            if target.exists():
                previous = pathlib.Path(tempfile.mkdtemp(
                    prefix=f".{name}.sync-previous.", dir=CONFIG))
                previous.rmdir()
                os.replace(target, previous)
            try:
                if staged is not None:
                    os.replace(staged, target)
                    staged = None
            except OSError:
                if previous is not None:
                    os.replace(previous, target)
                    previous = None
                raise
            if previous is not None:
                shutil.rmtree(previous)
                previous = None
        finally:
            if staged is not None and staged.exists():
                shutil.rmtree(staged)
            # On cleanup failure, preserve the previous directory for inspection.


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("save", "restore", "discard"):
        return 2
    action = sys.argv[1]
    snapshot = pathlib.Path(sys.argv[2]).resolve()
    if snapshot.parent != CONFIG or not snapshot.name.startswith(".git-sync-backup."):
        print("Invalid snapshot location", file=sys.stderr)
        return 2
    try:
        if action == "save":
            save(snapshot)
        elif action == "restore":
            restore(snapshot)
        else:
            if not (snapshot / ".complete").exists():
                raise RuntimeError("Refusing to discard incomplete snapshot")
            shutil.rmtree(snapshot)
    except (OSError, RuntimeError) as exc:
        print(f"SNAPSHOT_ERROR: {exc}", file=sys.stderr)
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
