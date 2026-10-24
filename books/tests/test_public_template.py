"""Public-template safety checks; no Docker daemon or live mount needed."""
import unittest
from unittest.mock import patch

from compose_fixture import PROJECT, FIXTURE_ENV
import ebookctl


class PublicMountTemplateTests(unittest.TestCase):
    def test_systemd_names_the_generic_mount_and_protected_controller(self):
        unit = (PROJECT / 'systemd/ebooks.service').read_text()
        for line in ('After=docker.service srv-media.mount',
                     'BindsTo=srv-media.mount', 'RequiresMountsFor=/srv/media/Books',
                     'WorkingDirectory=/srv/homelab/books',
                     'ExecStart=/usr/bin/python3 /etc/ebooks/ebookctl.py up'):
            self.assertIn(line + '\n', unit)

    def test_environment_example_contains_only_blanks_or_placeholders(self):
        for line in (PROJECT / '.env.example').read_text().splitlines():
            if not line or line.startswith('#'):
                continue
            key, value = line.split('=', 1)
            self.assertTrue(not value or value.startswith('REPLACE_WITH_'), key)

    def test_compose_rejects_each_missing_required_setting(self):
        import os
        import subprocess
        for missing in FIXTURE_ENV:
            with self.subTest(setting=missing):
                environment = os.environ.copy()
                environment.update(FIXTURE_ENV)
                environment.pop(missing, None)
                result = subprocess.run([
                    'docker', 'compose', '--env-file', '/dev/null', '--file',
                    str(PROJECT / 'compose.yml'), 'config', '--quiet',
                ], env=environment, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(missing, result.stderr)

    def test_unconfigured_uuid_fails_closed_even_on_matching_findmnt_row(self):
        placeholder = 'REPLACE_WITH_MEDIA_UUID'
        with patch.object(ebookctl, 'UUID', placeholder):
            data = {'filesystems': [{'target': str(ebookctl.MOUNT),
                                     'fstype': 'exfat', 'uuid': placeholder}]}
            self.assertFalse(ebookctl.valid_mount(data))

    def test_malformed_findmnt_response_is_rejected_without_writes(self):
        import subprocess
        for output in ('', 'invalid-json'):
            with self.subTest(output=output), patch('ebookctl.subprocess.run', return_value=
                    subprocess.CompletedProcess([], 0, output)), patch('pathlib.Path.mkdir') as mkdir:
                with self.assertRaises(RuntimeError):
                    ebookctl.prepare()
                mkdir.assert_not_called()


if __name__ == '__main__':
    unittest.main()
