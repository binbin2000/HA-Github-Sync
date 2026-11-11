import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app_runner as app


class AppTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.options = {'mode': 'schedule', 'repository': 'ssh://git@example.net:2222/ha/config.git',
                        'branch': 'ha/pilot', 'schedule': '0 3 * * *',
                        'timezone': 'Europe/Stockholm'}

    def read(self):
        (self.root / 'options.json').write_text(json.dumps(self.options))
        with patch.object(app, 'DATA', self.root), patch.object(app, 'git'):
            return app.read_options()

    def test_portable_settings_are_accepted(self):
        self.assertEqual(self.read(), self.options)

    def test_rejects_non_ssh_and_credential_urls(self):
        for url in ('file:///tmp/repo', 'https://user:password@example.net/repo',
                    'ssh://user:password@example.net/repo', 'ext::sh -c command'):
            with self.subTest(url=url):
                self.options['repository'] = url
                with self.assertRaisesRegex(ValueError, 'Git SSH URL'):
                    self.read()

    def test_rejects_non_cron_or_seconds_schedule(self):
        for schedule in ('not cron', '* * * * * *', '61 * * * *'):
            self.options['schedule'] = schedule
            with self.assertRaisesRegex(ValueError, 'five-field'):
                self.read()

    def test_refuses_mismatched_push_url(self):
        with patch.object(app, 'CONFIG', self.root), patch.object(app, 'git', side_effect=[
            str(self.root), self.options['branch'], self.options['repository'], 'git@other.invalid:repo',
        ]):
            with self.assertRaisesRegex(ValueError, 'fetch and push URLs'):
                app.check_checkout(self.options)

    def test_inspect_does_not_require_configured_remote_or_cron(self):
        self.options = {'mode': 'inspect'}
        self.assertEqual(self.read(), self.options)
