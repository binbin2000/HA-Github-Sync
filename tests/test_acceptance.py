"""Acceptance tests: disposable config copies and local bare remotes only.

Run on Linux: python3 -m unittest discover -s tests -p test_acceptance.py -v
"""
import json
import os
import pathlib
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = ('automations.yaml', 'scripts.yaml', '.automations_sync_state.yaml',
         '.scripts_sync_state.yaml')


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ha-acceptance-')
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name)
        self.config = self.base / 'config'
        self.config.mkdir()
        self.remote = self.base / 'remote.git'
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1',
                        GIT_CONFIG_GLOBAL='/dev/null', GIT_ALLOW_PROTOCOL='file',
                        GIT_AUTHOR_NAME='Acceptance', GIT_AUTHOR_EMAIL='test@example.invalid',
                        GIT_COMMITTER_NAME='Acceptance', GIT_COMMITTER_EMAIL='test@example.invalid',
                        PYTHONDONTWRITEBYTECODE='1')
        self.run_cmd('git', 'init', '--bare', '-b', 'main', str(self.remote))
        self.git('init', '-b', 'main')
        self.git('remote', 'add', 'origin', str(self.remote))
        for source in [ROOT / 'git_sync.sh', *ROOT.glob('sync_*.py')]:
            (self.config / source.name).write_text(
                source.read_text().replace('/config', str(self.config)))
        (self.config / '.gitignore').write_text((ROOT / '.gitignore').read_text() +
            '\nautomations.yaml\nscripts.yaml\n.*_sync_state.yaml\n.automations_sync.lock/\n__pycache__/\n')
        (self.config / 'automations.yaml').write_text(
            "- id: '1'\n  alias: Kitchen\n  trigger: []\n  action: []\n")
        (self.config / 'scripts.yaml').write_text('hello:\n  alias: Hello\n  sequence: []\n')
        for domain in ('automations', 'scripts'):
            self.run_cmd('python3', f'sync_{domain}.py', '--bootstrap')
        self.git('add', '-A')
        self.git('commit', '-m', 'baseline')
        self.git('push', '-u', 'origin', 'main')
        self.initial = self.head()
        self.peer = self.base / 'peer'
        self.run_cmd('git', 'clone', str(self.remote), str(self.peer))
        self.cleanup_split()

    def run_cmd(self, *args, cwd=None, check=True, env=None):
        result = subprocess.run(args, cwd=cwd or self.config, env=env or self.env,
            text=True, capture_output=True, timeout=30)
        if check and result.returncode:
            self.fail(f'{args}: rc={result.returncode}\n{result.stdout}\n{result.stderr}')
        return result

    def git(self, *args, cwd=None):
        return self.run_cmd('git', *args, cwd=cwd).stdout.strip()

    def head(self):
        return self.git('rev-parse', 'HEAD')

    def remote_head(self):
        return self.git('--git-dir', str(self.remote), 'rev-parse', 'main')

    def cleanup_split(self):
        for name in ('automations', 'scripts'):
            if (self.config / name).exists():
                shutil.rmtree(self.config / name)

    def sync(self, code=0, marker=None):
        r = self.run_cmd('bash', 'git_sync.sh', check=False)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        if marker:
            self.assertIn(marker, r.stdout + r.stderr)
        return r

    def replace(self, root, name, before, after):
        p = root / name
        self.assertIn(before, p.read_text())
        p.write_text(p.read_text().replace(before, after))

    def commit(self, root, message):
        self.git('add', '-A', cwd=root)
        self.git('commit', '-m', message, cwd=root)

    def push_peer(self):
        self.commit(self.peer, 'remote edit')
        self.git('push', 'origin', 'main', cwd=self.peer)

    def live(self):
        return {name: (self.config / name).read_bytes() for name in FILES}

    def snapshots(self):
        return list(self.config.glob('.git-sync-backup.*'))

    def test_01_two_way_both_domains_and_idempotent_restart(self):
        self.replace(self.config, 'automations.yaml', 'Kitchen', 'Kitchen UI')
        self.replace(self.peer, 'scripts/hello.yaml', 'Hello', 'Hello Remote')
        self.push_peer()
        self.sync(marker='git_relation=remote_ahead')
        self.assertIn('Hello Remote', (self.config / 'scripts.yaml').read_text())
        self.assertIn('Kitchen UI', self.git('--git-dir', str(self.remote), 'show',
                                            'main:automations/kitchen_ui.yaml'))
        self.replace(self.config, 'scripts.yaml', 'Hello Remote', 'Hello UI')
        self.git('pull', '--ff-only', cwd=self.peer)
        self.replace(self.peer, 'automations/kitchen_ui.yaml', 'Kitchen UI', 'Kitchen Remote')
        self.push_peer()
        self.sync()
        self.assertIn('Kitchen Remote', (self.config / 'automations.yaml').read_text())
        self.assertIn('Hello UI', self.git('--git-dir', str(self.remote), 'show', 'main:scripts/hello.yaml'))
        before = self.live(), self.head(), self.remote_head()
        self.sync()
        self.assertEqual((self.live(), self.head(), self.remote_head()), before)
        self.assertFalse(self.snapshots())
        self.assertFalse((self.config / 'automations').exists())

    def test_02_clean_divergence_publishes_merge(self):
        self.git('checkout', 'HEAD', '--', 'automations/', 'scripts/')
        self.replace(self.config, 'automations/kitchen.yaml', 'Kitchen', 'Kitchen Local')
        self.commit(self.config, 'local independent change')
        self.cleanup_split()
        self.replace(self.peer, 'scripts/hello.yaml', 'Hello', 'Hello Remote')
        self.push_peer()
        local, remote = self.head(), self.remote_head()
        self.sync(marker='DIVERGED_MERGED_CLEAN')
        parents = self.git('rev-list', '--parents', '-n', '1', 'HEAD').split()[1:]
        self.assertEqual(set(parents), {local, remote})
        self.assertIn('Kitchen Local', (self.config / 'automations.yaml').read_text())
        self.assertIn('Hello Remote', (self.config / 'scripts.yaml').read_text())
        self.assertEqual(self.remote_head(), self.head(), 'Successful merge was not published')

    def test_03_git_conflict_preserves_heads_and_blocks_restart(self):
        self.git('checkout', 'HEAD', '--', 'automations/', 'scripts/')
        self.replace(self.config, 'automations/kitchen.yaml', 'Kitchen', 'Kitchen Local')
        self.commit(self.config, 'local conflict')
        self.cleanup_split()
        self.replace(self.peer, 'automations/kitchen.yaml', 'Kitchen', 'Kitchen Remote')
        self.push_peer()
        before = self.head(), self.remote_head(), self.live()
        self.sync(2, 'GIT_CONFLICT')
        self.assertEqual((self.head(), self.remote_head(), self.live()), before)
        self.assertFalse((self.config / '.git/MERGE_HEAD').exists())
        self.assertEqual(len(self.snapshots()), 1)
        self.sync(5, 'RECOVERY_REQUIRED')
        self.recover(self.snapshots()[0])
        self.assertFalse(self.snapshots())

    def test_04_unchanged_head_rolls_back_both_domains(self):
        self.replace(self.config, 'automations.yaml', 'Kitchen', 'Kitchen UI')
        (self.config / '.scripts_sync_state.yaml').write_text('{}\n')
        before = self.live()
        self.sync(3, 'SYNC_ABORTED')
        self.assertEqual(self.live(), before)
        self.assertEqual(self.head(), self.initial)
        self.assertEqual(self.remote_head(), self.initial)
        self.assertIn('Kitchen', (self.config / 'automations/kitchen.yaml').read_text())
        self.assertFalse((self.config / 'automations/kitchen_ui.yaml').exists())
        self.assertFalse(self.snapshots())

    def test_bundled_helpers_push_only_the_configured_branch(self):
        tools = self.base / 'bundled tools'
        tools.mkdir()
        self.git('switch', '-c', 'ha-sync/pilot')
        self.git('checkout', 'HEAD', '--', 'automations/', 'scripts/')
        for source in [self.config / 'git_sync.sh', *self.config.glob('sync_*.py')]:
            shutil.copy2(source, tools / source.name)
            self.git('rm', source.name)
        self.commit(self.config, 'Keep sync code outside the HA worktree')
        self.git('push', 'origin', 'HEAD:refs/heads/ha-sync/pilot')
        self.cleanup_split()
        self.replace(self.config, 'automations.yaml', 'Kitchen', 'Kitchen Pilot')
        wrong = self.run_cmd('bash', str(tools / 'git_sync.sh'), check=False)
        self.assertEqual(wrong.returncode, 4)
        self.assertIn('GIT_BRANCH_MISMATCH', wrong.stdout)
        self.run_cmd('bash', str(tools / 'git_sync.sh'),
                     env=dict(self.env, HA_SYNC_BRANCH='ha-sync/pilot'))
        self.assertEqual(self.remote_head(), self.initial)
        self.assertEqual(self.git('--git-dir', str(self.remote), 'rev-parse',
                                  'refs/heads/ha-sync/pilot'), self.head())
        self.assertIn('Kitchen Pilot', self.git('--git-dir', str(self.remote), 'show',
                      'ha-sync/pilot:automations/kitchen_pilot.yaml'))
        self.assertFalse(self.snapshots())

    def test_empty_scripts_can_bootstrap_and_remain_empty(self):
        self.git('checkout', 'HEAD', '--', 'automations/', 'scripts/')
        self.git('rm', 'scripts/hello.yaml')
        (self.config / 'scripts.yaml').write_text('{}\n')
        self.run_cmd('python3', 'sync_scripts.py', '--bootstrap')
        self.commit(self.config, 'Empty script domain')
        self.git('push', 'origin', 'main')
        self.cleanup_split()
        head = self.head()
        self.sync()
        self.assertEqual(self.head(), head)
        self.assertEqual(self.remote_head(), head)
        self.assertEqual((self.config / 'scripts.yaml').read_text(), '{}\n')

    def test_05_changed_head_refuses_automatic_and_explicit_restore(self):
        self.replace(self.config, 'automations.yaml', 'Kitchen', 'Kitchen UI')
        self.replace(self.peer, 'automations/kitchen.yaml', 'Kitchen', 'Kitchen Remote')
        self.replace(self.peer, 'scripts/hello.yaml', 'Hello', 'Hello Remote')
        self.push_peer()
        self.sync(5, 'Git HEAD changed')
        self.assertEqual(self.head(), self.remote_head())
        self.assertIn('Kitchen UI', (self.config / 'automations.yaml').read_text())
        self.assertIn('Hello Remote', (self.config / 'scripts.yaml').read_text())
        backup = self.snapshots()[0]
        self.assertIn('Hello', (backup / 'scripts.yaml').read_text())
        self.assertNotIn('Remote', (backup / 'scripts.yaml').read_text())
        before = self.live(), self.head(), self.remote_head()
        self.recover(backup, code=5)
        self.sync(5, 'RECOVERY_REQUIRED')
        self.assertEqual((self.live(), self.head(), self.remote_head()), before)
        self.assertTrue(backup.exists())

    def recover(self, backup, code=0):
        r = self.run_cmd('python3', 'sync_recover.py', 'restore', str(backup), '--confirm', check=False)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r

    def test_06_push_rejected_then_retry_same_commit(self):
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        self.replace(self.config, 'automations.yaml', 'Kitchen', 'Kitchen UI')
        self.sync(1, 'GIT_PUSH_FAILED')
        preserved = self.head()
        self.assertNotEqual(preserved, self.initial)
        self.assertEqual(self.remote_head(), self.initial)
        self.assertFalse(self.snapshots())
        hook.unlink()
        self.sync()
        self.assertEqual(self.head(), preserved)
        self.assertEqual(self.remote_head(), preserved)

    def test_07_incomplete_snapshot_blocks_without_mutation(self):
        backup = self.config / '.git-sync-backup.incomplete'
        backup.mkdir()
        before = self.live(), self.head(), self.remote_head()
        self.sync(5, 'RECOVERY_REQUIRED')
        self.recover(backup, code=5)
        self.assertEqual((self.live(), self.head(), self.remote_head()), before)

    def test_08_fresh_lock_blocks_sync_and_recovery(self):
        backup = self.config / '.git-sync-backup.locked'
        backup.mkdir()
        self.run_cmd('python3', 'sync_snapshot.py', 'save', str(backup))
        self.run_cmd('python3', 'sync_git_metadata.py', 'capture', str(backup))
        lock = self.config / '.automations_sync.lock'
        lock.mkdir()
        before = self.live(), self.head(), self.remote_head()
        self.sync(0, 'LOCK_BUSY')
        self.recover(backup, code=5)
        self.assertTrue(lock.exists())
        self.assertEqual((self.live(), self.head(), self.remote_head()), before)

    def start_paused(self, target):
        wrappers = self.base / 'bin'
        wrappers.mkdir()
        marker = self.base / 'paused'
        if target == 'reconcile':
            name, real = 'python3', shutil.which('python3')
            script = f'''#!/bin/bash
if [ "${{1##*/}}" = sync_automations.py ] && [ "$#" = 1 ]; then
  {real} "$@"
  result=$?
  touch "{marker}"
  while :; do sleep 0.1; done
  exit "$result"
fi
exec {real} "$@"
'''
        else:
            name, real = 'git', shutil.which('git')
            script = f'''#!/bin/bash
if [ "$1" = fetch ]; then
  touch "{marker}"
  while :; do sleep 0.1; done
fi
exec {real} "$@"
'''
        wrapper = wrappers / name
        wrapper.write_text(script)
        wrapper.chmod(0o755)
        env = dict(self.env, PATH=str(wrappers) + ':' + self.env['PATH'])
        log = (self.base / 'paused.log').open('w')
        self.addCleanup(log.close)
        p = subprocess.Popen(['bash', 'git_sync.sh'], cwd=self.config, env=env,
                             stdout=log, stderr=log, start_new_session=True)
        def stop():
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
            p.wait(timeout=5)
        self.addCleanup(stop)
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline and p.poll() is None:
            time.sleep(0.02)
        self.assertTrue(marker.exists(), (self.base / 'paused.log').read_text())
        return p, stop

    def test_09_sigkill_recovery_and_restart(self):
        self.replace(self.config, 'automations.yaml', 'Kitchen', 'Kitchen UI')
        before = self.live()
        p, stop = self.start_paused('reconcile')
        stop()
        self.assertEqual(p.returncode, -signal.SIGKILL)
        lock = self.config / '.automations_sync.lock'
        self.assertTrue(lock.exists())
        backup = self.snapshots()[0]
        self.assertTrue((backup / '.complete').exists())
        self.assertEqual(json.loads((backup / 'git-state.json').read_text())['head_before_merge'], self.initial)
        self.sync(0, 'LOCK_BUSY')
        self.recover(backup, code=5)
        # Operator has verified all processes in the group are dead.
        lock.rmdir()
        self.sync(5, 'RECOVERY_REQUIRED')
        self.replace(self.config, 'scripts.yaml', 'Hello', 'Hello After Crash')
        self.recover(backup)
        self.assertEqual(self.live(), before)
        rescues = list(self.config.glob('.git-sync-recovery.*'))
        self.assertEqual(len(rescues), 1)
        self.assertIn('Hello After Crash', (rescues[0] / 'scripts.yaml').read_text())
        self.sync()
        self.assertEqual(self.head(), self.remote_head())
        self.assertFalse(self.snapshots())
        self.sync()

    def test_10_old_but_active_lock_must_not_be_stolen(self):
        p, stop = self.start_paused('fetch')
        lock = self.config / '.automations_sync.lock'
        old = time.time() - 601
        os.utime(lock, (old, old))
        before = self.head(), self.remote_head(), self.live()
        self.sync(0, 'LOCK_BUSY')
        self.assertIsNone(p.poll())
        self.assertTrue(lock.exists())
        self.assertEqual((self.head(), self.remote_head(), self.live()), before)

    def test_11_missing_metadata_must_refuse_restore(self):
        backup = self.config / '.git-sync-backup.legacy'
        backup.mkdir()
        self.run_cmd('python3', 'sync_snapshot.py', 'save', str(backup))
        self.replace(self.config, 'scripts.yaml', 'Hello', 'Hello Newer')
        before = self.live(), self.head()
        self.recover(backup, code=5)
        self.assertEqual((self.live(), self.head()), before)
        self.assertTrue(backup.exists())

    def test_12_unhandled_reconciler_error_must_abort(self):
        # YAML scanner error exits Python with 1, also used for successful split->flat.
        (self.config / 'automations.yaml').write_text('[ invalid: yaml\n')
        self.replace(self.config, 'scripts.yaml', 'Hello', 'Hello UI')
        before = self.live(), self.head(), self.remote_head()
        r = self.run_cmd('bash', 'git_sync.sh', check=False)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.live(), self.head(), self.remote_head()), before)

    def test_13_scripts_parse_error_must_roll_back_first_domain(self):
        (self.config / 'scripts.yaml').write_text('[ invalid: yaml\n')
        self.replace(self.config, 'automations.yaml', 'Kitchen', 'Kitchen UI')
        before = self.live(), self.head(), self.remote_head()
        r = self.run_cmd('bash', 'git_sync.sh', check=False)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.live(), self.head(), self.remote_head()), before)
        self.assertFalse((self.config / 'automations/kitchen_ui.yaml').exists())

    def test_14_write_error_after_split_update_must_roll_back(self):
        self.git('checkout', 'HEAD', '--', 'automations/', 'scripts/')
        source = self.config / 'sync_atomic.py'
        source.write_text(source.read_text().replace(
            '        os.replace(temp_name, path)',
            '        if path.name == ".automations_sync_state.yaml":\n'
            '            raise OSError("injected state write failure")\n'
            '        os.replace(temp_name, path)'))
        self.commit(self.config, 'test-only fault injection')
        self.git('push', 'origin', 'main')
        self.cleanup_split()
        self.replace(self.config, 'automations.yaml', 'Kitchen', 'Kitchen UI')
        before = self.live(), self.head(), self.remote_head()
        self.sync(3, 'SYNC_ABORTED')
        self.assertEqual((self.live(), self.head(), self.remote_head()), before)
        self.assertFalse((self.config / 'automations/kitchen_ui.yaml').exists())


if __name__ == '__main__':
    unittest.main()
