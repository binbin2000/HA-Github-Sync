# HA GitHub Sync app

This app bundles Bash, Git, Python, OpenSSH and the two-way sync engine. It is for
Home Assistant OS (or a Supervisor installation that supports local app builds).
It does not need the Terminal & SSH app at runtime, and opens no ports.

## Prepare your Home Assistant Git checkout

1. Back up Home Assistant. Prepare `/config` as the root of a Git checkout of
   **your configuration repository**, with `origin` pointing to the SSH URL
   you intend to use. The selected local branch must already exist on the remote.
   This app does not clone over `/config`, change your remote, or reset history.
2. HA must read `automations.yaml` and `scripts.yaml` from `/config` (directly or
   through includes). Leave unrelated YAML includes alone. The app owns only
   the top-level `automations/` and `scripts/` split directories; do not use
   these directories for other files or direct HA includes.
3. Ignore the flat files, the two state files and the local lock/recovery files.
   These ignore rules are required:

   ```gitignore
   /automations.yaml
   /scripts.yaml
   /.automations_sync_state.yaml
   /.scripts_sync_state.yaml
   /.automations_sync.lock/
   /.git-sync-backup.*/
   /.git-sync-recovery.*/
   ```

   If flat files were already tracked, remove them from the index only, after
   checking the paths: `git rm --cached -- automations.yaml scripts.yaml`.
   Keep secrets and HA runtime files out of Git. Review remaining edits before
   committing; the existing preflight blocks unrelated dirty files.
4. For a fresh checkout, use the [one-time bootstrap](README.md#7-do-the-one-time-split)
   from a temporary checkout of this tool's source. Run `python3 /path/to/tool/sync_automations.py --bootstrap`
   and `python3 /path/to/tool/sync_scripts.py --bootstrap` in an environment with
   `/config` mounted and PyYAML installed. This creates the split files and
   baseline hashes. Keep the original flat files in HA; use `[]` and `{}` for
   intentionally empty automation and script domains. Review and commit the
   split files that were created and the ignore rules before starting the app.
   Skip bootstrap if already migrating an initialized sync. If split files
   exist but their matching baseline state is absent, investigate before choosing
   a source of truth; do not bootstrap over them.

## Install and authorize

Add the tool repository URL to the HA App store's repositories, then install
**HA GitHub Sync**. For local testing, put an exported copy of the tool repository
in the `local_apps`/`addons` share and reload the store; install the local entry.
Supervisor builds the image from the included Dockerfile.

The app's public configuration directory is under the `addon_configs` (or
`app_configs`) share. Use the directory matching the installed app's full slug
(e.g. `local_ha_github_sync` for a local installation). The app reads two files
from that directory:

- `id_ed25519`: a private deploy key for **the configuration repo**, with mode
  `600` or `400`. Put only its public counterpart in your Git provider. For push,
  enable write access to the target repo. The key must work noninteractively.
- `known_hosts`: the server host key obtained from your Git provider or verified
  with its administrator. For a custom port, use OpenSSH's `[host]:port` entry.
  Host key checking is always required. Neither file belongs in either Git repo.

The key directory is mounted read-only to the app. Other apps with access to
all app configuration directories can read it if they run as a privileged user;
keep access to those apps and backups restricted.

## App settings and first run

| Field | Example | Purpose |
|---|---|---|
| `repository` | `git@example.net:team/ha-config.git` or `ssh://git@example.net:2222/team/ha-config.git` | Exact effective SSH fetch and push URL of `origin`. |
| `branch` | `main` or `ha/pilot` | Must match the local checkout and an existing remote branch. |
| `schedule` | `17 * * * *` or `0 3 * * *` | Five cron fields; hourly at :17, or daily at 03:00. |
| `timezone` | `Europe/Stockholm` | IANA timezone for the schedule; default `UTC`. |
| `git_name`, `git_email` | `HA GitHub Sync`, `ha-github-sync@localhost` | Author and committer for new sync commits. |
| `mode` | `check` | Verify checkout, state files, ignore rules and SSH read access; no merge or push. |

Start in `check`. Read the log, then use `once` for a supervised real sync. A
successful real sync may push local commits to the selected remote branch.
When ready, use `schedule` and enable **Start on boot**. Stop/start the app to
apply setting changes. It runs one sync at a time and logs the next scheduled
time and each run's result. If HA or the app was down at the scheduled time, it
waits for the next one. The app does not reload or restart Home Assistant.

Use `inspect` to list retained snapshots without a Git connection. For recovery,
stop the scheduler and follow the [recovery guide](README.md#safe-recovery-after-interrupted-synchronization-v02).
Failures appear in the app log; this version does not send HA notifications.

## Migrate from a one-shot or scheduled runner

1. Stop the old runner and turn off its start-on-boot and any old HA schedule.
2. Install this app. Copy the existing deploy key and verified `known_hosts` into
   this app's configuration directory under the filenames above. Set permissions
   before starting. Keep the original key in place for rollback.
3. Enter the current config repo's SSH URL, branch and desired schedule. Use
   `check`, then `once`, before enabling `schedule`.
4. After verifying the new scheduler, you can remove the old runner. The shell
   and Python files previously installed in `/config` may remain tracked; the
   app runs the copies built into its image. Remove those files only as a
   separately reviewed config commit if no manual jobs use them.

To roll back, stop this app and restart the previous runner. Do not run both
schedulers at once.
