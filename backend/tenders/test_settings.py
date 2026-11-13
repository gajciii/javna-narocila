import os
import runpy
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase


class NumericEnvironmentSettingsTests(SimpleTestCase):
    defaults = {
        'PIPELINE_MAX_DOWNLOAD': 8 * 1024**3,
        'PIPELINE_MAX_EXPANDED': 32 * 1024**3,
        'PIPELINE_MAX_DOCUMENT': 512 * 1024**2,
        'PIPELINE_MAX_PAGES': 10000,
        'EMAIL_PORT': 587,
    }

    def load_settings(self, environment):
        with patch.dict(os.environ, environment, clear=True), patch('dotenv.load_dotenv'):
            return runpy.run_path(
                str(Path(__file__).resolve().parent.parent / 'radar' / 'settings.py'),
                run_name='radar.settings_environment_test',
            )

    def test_missing_and_blank_values_allow_startup_with_defaults(self):
        for value in (None, '', '  '):
            with self.subTest(value=value):
                environment = {} if value is None else dict.fromkeys(self.defaults, value)
                settings = self.load_settings(environment)
                for name, default in self.defaults.items():
                    self.assertEqual(settings[name], default)

    def test_explicit_values_are_preserved(self):
        settings = self.load_settings(dict.fromkeys(self.defaults, ' 123 '))
        for name in self.defaults:
            self.assertEqual(settings[name], 123)

    def test_invalid_nonempty_values_still_fail(self):
        for name in self.defaults:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.load_settings({name: 'invalid'})
