"""Run the bundled sync without installing its code in the HA worktree."""
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter

SOURCE = Path(__file__).resolve().parent
CONFIG = Path('/config')
DATA = Path('/data')
AUTH = Path('/auth')
MODES = {'check', 'once', 'schedule', 'inspect'}
SSH_REMOTE = re.compile(
    r'(?:[\w.-]+@[A-Za-z0-9][\w.-]*:|ssh://(?:[\w.-]+@)?[A-Za-z0-9][\w.-]*(?::[0-9]+)?/)'
    r'[A-Za-z0-9_./~-]+', re.ASCII,
)
FLAT_AND_STATE = ('automations.yaml', 'scripts.yaml',
                  '.automations_sync_state.yaml', '.scripts_sync_state.yaml')


def git(*args):
    result = subprocess.run(['git', *args], cwd=CONFIG, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError(f'Git check failed: {args[0]}')
    return result.stdout.strip()


def read_options():
    options = json.loads((DATA / 'options.json').read_text())
    mode = options['mode']
    if mode not in MODES:
        raise ValueError('Unknown mode')
    if mode == 'inspect':
        return options
    if not SSH_REMOTE.fullmatch(options['repository']):
        raise ValueError('Set repository to a Git SSH URL without credentials')
    branch = options['branch']
    if not branch or branch.startswith('-'):
        raise ValueError('Set a valid Git branch')
    git('check-ref-format', f'refs/heads/{branch}')
    if mode == 'schedule':
        schedule = options['schedule']
        if len(schedule.split()) != 5 or not croniter.is_valid(schedule):
            raise ValueError('Set a valid five-field cron schedule')
        ZoneInfo(options['timezone'])
    return options


def check_checkout(options):
    if Path(git('rev-parse', '--show-toplevel')).resolve() != CONFIG.resolve():
        raise ValueError('/config must be the root of an existing Git checkout')
    if git('symbolic-ref', '--short', 'HEAD') != options['branch']:
        raise ValueError('The checked-out branch does not match branch')
    expected = [options['repository']]
    for flags in (('--all',), ('--push', '--all')):
        if git('remote', 'get-url', *flags, 'origin').splitlines() != expected:
            raise ValueError('The fetch and push URLs for origin must match repository')
    for name in FLAT_AND_STATE:
        path = CONFIG / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Missing or unsafe {name}; finish bootstrap first')
        if git('ls-files', '--', name):
            raise ValueError(f'{name} must be local, not tracked')
    for name in (*FLAT_AND_STATE, '.git-sync-backup.example/probe',
                 '.git-sync-recovery.example/probe'):
        git('check-ignore', '--quiet', '--', name)
    for name in ('automations', 'scripts'):
        path = CONFIG / name
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f'Unsafe split folder: {name}')
    if any(CONFIG.glob('.git-sync-backup.*')):
        raise ValueError('RECOVERY_REQUIRED: inspect the retained snapshot')


def environment(options):
    key, hosts = AUTH / 'id_ed25519', AUTH / 'known_hosts'
    if not key.is_file() or key.stat().st_mode & 0o077:
        raise ValueError('Install /auth/id_ed25519 with mode 600 or 400')
    if not hosts.is_file() or not hosts.stat().st_size:
        raise ValueError('Install /auth/known_hosts with a verified host key')
    ssh = ['ssh', '-F', '/dev/null', '-i', str(key), '-o', 'BatchMode=yes',
           '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', f'UserKnownHostsFile={hosts}', '-o', 'GlobalKnownHostsFile=/dev/null',
           '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=10',
           '-o', 'ServerAliveCountMax=3']
    return dict(os.environ, GIT_SSH_COMMAND=shlex.join(ssh), GIT_SSH_VARIANT='ssh',
                GIT_ALLOW_PROTOCOL='ssh', GIT_TERMINAL_PROMPT='0',
                HA_SYNC_BRANCH=options['branch'],
                GIT_AUTHOR_NAME=options['git_name'], GIT_AUTHOR_EMAIL=options['git_email'],
                GIT_COMMITTER_NAME=options['git_name'], GIT_COMMITTER_EMAIL=options['git_email'])


def write_result(code):
    status = DATA / 'last_result.json'
    temporary = status.with_suffix('.tmp')
    temporary.write_text(json.dumps({'exit': code, 'finished_at': time.time()}) + '\n')
    temporary.replace(status)
    print(f'HA GitHub Sync: exit={code}', flush=True)


def run_once(options, env):
    # Recheck each time: a manual Git operation may change the branch or origin.
    try:
        check_checkout(options)
    except ValueError as exc:
        print(exc, flush=True)
        code = 4
    else:
        code = subprocess.call(['bash', str(SOURCE / 'git_sync.sh')], cwd=CONFIG, env=env)
    write_result(code)
    return code


def main():
    options = read_options()
    mode = options['mode']
    if mode == 'inspect':
        return subprocess.call(['python3', str(SOURCE / 'sync_recover.py'), 'inspect'], cwd=CONFIG)
    check_checkout(options)
    env = environment(options)
    if mode == 'check':
        subprocess.run(['python3', str(SOURCE / 'sync_preflight.py')], cwd=CONFIG, check=True)
        subprocess.run(['git', 'ls-remote', '--exit-code', 'origin',
                        f"refs/heads/{options['branch']}"], cwd=CONFIG, env=env, check=True)
        print('Checkout, ignore rules and SSH read access verified. No sync ran.')
        return 0
    if mode == 'once':
        return run_once(options, env)

    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    timezone = ZoneInfo(options['timezone'])
    while not stopping:
        next_run = croniter(options['schedule'], datetime.now(timezone)).get_next(datetime)
        print(f'Next sync: {next_run.isoformat(timespec="minutes")} ({timezone.key})', flush=True)
        while not stopping and (remaining := next_run.timestamp() - time.time()) > 0:
            time.sleep(min(remaining, 5))
        if not stopping:
            run_once(options, env)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'HA GitHub Sync stopped: {error}') from None
