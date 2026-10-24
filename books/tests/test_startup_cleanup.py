from contextlib import redirect_stderr
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import call, patch

from compose_fixture import PROJECT
import ebookctl


class StartupCleanupTests(unittest.TestCase):
    def test_systemd_cleans_up_after_failed_start(self):
        unit = (Path(__file__).resolve().parents[1] / 'systemd/ebooks.service').read_text()
        self.assertIn('ExecStopPost=/usr/bin/python3 /etc/ebooks/ebookctl.py down\n', unit)

    def test_partial_start_is_cleaned_up_and_original_error_preserved(self):
        base = ['docker', 'compose', '--project-name', 'ebooks',
                '--project-directory', str(ebookctl.PROJECT), '--file',
                str(ebookctl.COMPOSE)]
        up = base + ['up', '-d', '--pull', 'never']
        down = base + ['down']
        for startup_error in (subprocess.CalledProcessError(1, up), OSError('startup failed')):
            for cleanup_error in (None, subprocess.CalledProcessError(2, down), OSError('cleanup failed')):
                with self.subTest(startup=type(startup_error).__name__, cleanup=type(cleanup_error).__name__):
                    running = set()

                    def simulate(args, **kwargs):
                        if args == up:
                            running.add('cwa')
                            raise startup_error
                        self.assertEqual(args, down)
                        if cleanup_error is not None:
                            raise cleanup_error
                        running.clear()
                        return subprocess.CompletedProcess(args, 0)

                    errors = io.StringIO()
                    with patch.object(ebookctl, 'guard') as guard, patch.object(ebookctl, 'safe_paths'), patch.object(ebookctl, 'require_dirs'), patch('ebookctl.subprocess.run', side_effect=simulate) as run, redirect_stderr(errors):
                        with self.assertRaises(type(startup_error)) as raised:
                            ebookctl.control('up')
                        self.assertIs(raised.exception, startup_error)
                        self.assertEqual(run.call_args_list, [call(up, check=True), call(down, check=True)])
                        guard.assert_called_once_with()
                        self.assertEqual(running, {'cwa'} if cleanup_error else set())
                        self.assertEqual(bool(errors.getvalue()), cleanup_error is not None)
