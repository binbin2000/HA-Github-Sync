#!/usr/bin/env python3
"""Inspect or explicitly recover an interrupted Home Assistant sync.

Usage:
  python3 sync_recover.py inspect
  python3 sync_recover.py restore /config/.git-sync-backup.NAME --confirm

Restore first preserves the current state under /config/.git-sync-recovery.*.
Never use restore while a sync process is running.
"""
import pathlib
import shutil
import sys
import tempfile

import sync_snapshot

CONFIG = pathlib.Path("/config")


def candidates(config=CONFIG):
    return sorted(p for p in config.glob(".git-sync-backup.*") if p.is_dir())


def inspect(config=CONFIG):
    found = candidates(config)
    if not found:
        print("NO_RECOVERY_REQUIRED")
        return 0
    for snapshot in found:
        complete = (snapshot / ".complete").is_file()
        print(f"{snapshot}: {'COMPLETE' if complete else 'INCOMPLETE'}")
        for name in (*sync_snapshot.FILES, *sync_snapshot.DIRS):
            if (snapshot / name).exists():
                print(f"  {name}")
    return 5


def recover(snapshot, config=CONFIG):
    snapshot = pathlib.Path(snapshot)
    if not snapshot.is_absolute() or snapshot.parent != config or snapshot not in candidates(config):
        raise RuntimeError("Snapshot must be an existing /config/.git-sync-backup.* directory")
    if not (snapshot / ".complete").is_file():
        raise RuntimeError("Incomplete snapshot: manual investigation required")
    if len(candidates(config)) != 1:
        raise RuntimeError("Multiple snapshots: manual investigation required")
    if (config / ".automations_sync.lock").exists():
        raise RuntimeError("Sync lock exists: stop sync and investigate before recovery")

    rescue = pathlib.Path(tempfile.mkdtemp(prefix=".git-sync-recovery.", dir=config))
    # The rescue copy is intentionally retained even after successful recovery.
    try:
        with _config_override(config):
            sync_snapshot.save(rescue)
            sync_snapshot.restore(snapshot)
    except Exception:
        print(f"RECOVERY_FAILED: current-state backup at {rescue}", file=sys.stderr)
        raise
    shutil.rmtree(snapshot)
    print(f"RECOVERED: prior state restored; overwritten state saved at {rescue}")


class _config_override:
    def __init__(self, config):
        self.config = config

    def __enter__(self):
        self.previous = sync_snapshot.CONFIG
        sync_snapshot.CONFIG = self.config

    def __exit__(self, *args):
        sync_snapshot.CONFIG = self.previous


def main(args):
    if args == ["inspect"]:
        return inspect()
    if len(args) == 3 and args[0] == "restore" and args[2] == "--confirm":
        try:
            recover(pathlib.Path(args[1]))
        except (OSError, RuntimeError) as exc:
            print(f"RECOVERY_ERROR: {exc}", file=sys.stderr)
            return 5
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
