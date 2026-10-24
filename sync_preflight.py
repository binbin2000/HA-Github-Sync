#!/usr/bin/env python3
"""Fail-closed Git working-tree preflight for HA-Github-Sync.

Tracked split files are intentionally removed after successful sync runs.
Only their *unstaged* deletion is an expected working-tree change.
Everything else, including staged deletions and untracked files, blocks sync.
"""
import subprocess
import sys


def safe_status(raw: bytes) -> tuple[bool, str]:
    records = raw.split(b"\0")
    i = 0
    while i < len(records):
        record = records[i]
        i += 1
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            return False, "Malformed Git status entry"
        xy = record[:2].decode("ascii", errors="replace")
        path = record[3:].decode("utf-8", errors="replace")
        # Porcelain v1 rename/copy entries contain an additional NUL path.
        if "R" in xy or "C" in xy:
            i += 1
        is_split = path.startswith(("automations/", "scripts/"))
        if is_split and xy == " D":
            continue
        return False, f"Unsafe working-tree change ({xy}): {path}"
    return True, ""


def main() -> int:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        print("Cannot inspect Git working tree", file=sys.stderr)
        return 4
    safe, reason = safe_status(result.stdout)
    if not safe:
        print(reason, file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
