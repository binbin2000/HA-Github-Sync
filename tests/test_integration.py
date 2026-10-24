"""End-to-end reconciliation and rollback in an isolated temporary HA config."""
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import sync_automations
import sync_scripts
import sync_snapshot


class ReconciliationIntegrationTests(unittest.TestCase):
    def test_both_domains_and_recovery_after_second_domain_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            backup = root / ".git-sync-backup.integration"
            backup.mkdir()
            (root / "automations.yaml").write_text("- id: '123'\n  alias: Kitchen\n  trigger: []\n  action: []\n")
            (root / "scripts.yaml").write_text("hello:\n  alias: Hello\n  sequence: []\n")
            with patch.multiple(sync_automations,
                                AUTOMATIONS_FILE=root / "automations.yaml",
                                SPLIT_DIR=root / "automations",
                                STATE_FILE=root / ".automations_sync_state.yaml"), \
                 patch.multiple(sync_scripts,
                                SCRIPTS_FILE=root / "scripts.yaml",
                                SPLIT_DIR=root / "scripts",
                                STATE_FILE=root / ".scripts_sync_state.yaml"), \
                 patch.object(sync_snapshot, "CONFIG", root):
                sync_automations.write_split(sync_automations.load_flat())
                sync_scripts.write_split(sync_scripts.load_flat())
                sync_automations.save_state(
                    sync_automations.canonical_hash(sync_automations.load_flat()),
                    sync_automations.canonical_hash(sync_automations.load_split()))
                sync_scripts.save_state(
                    sync_scripts.canonical_hash(sync_scripts.load_flat()),
                    sync_scripts.canonical_hash(sync_scripts.load_split()[0]))
                sync_snapshot.save(backup)

                # First reconciler completes, then the second fails.
                (root / "automations.yaml").write_text("- id: '123'\n  alias: Updated\n  trigger: []\n  action: []\n")
                sync_automations.write_split(sync_automations.load_flat())
                sync_automations.save_state(
                    sync_automations.canonical_hash(sync_automations.load_flat()),
                    sync_automations.canonical_hash(sync_automations.load_split()))
                with patch.object(sync_scripts, "write_split", side_effect=OSError("injected disk failure")):
                    with self.assertRaises(OSError):
                        sync_scripts.write_split(sync_scripts.load_flat())

                sync_snapshot.restore(backup)
                self.assertIn("Kitchen", (root / "automations.yaml").read_text())
                self.assertNotIn("Updated", (root / "automations.yaml").read_text())
                self.assertIn("Kitchen", (root / "automations" / "kitchen.yaml").read_text())
                self.assertIn("Hello", (root / "scripts.yaml").read_text())
                self.assertTrue((backup / ".complete").exists())


if __name__ == "__main__":
    unittest.main()
