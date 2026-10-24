"""Publication guard tests use synthetic secrets, never real credentials."""
import importlib.util
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

GUARD = Path(__file__).with_name('check_public_tree.py')


class GuardTests(unittest.TestCase):
    def check(self, name, body):
        self.assertTrue(GUARD.is_file(), 'publication guard implementation is missing')
        spec = importlib.util.spec_from_file_location('publication_guard', GUARD)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.check_file(name, body)

    def test_rejects_credentials_and_runtime_paths(self):
        self.assertTrue(self.check('books/.env', b'EXAMPLE=value'))
        self.assertTrue(self.check('games/host/cfg/settings.toml', b'example'))
        self.assertTrue(self.check('media/config/app.xml', b'example'))
        self.assertTrue(self.check('docs/readme.md', b'gh' + b'p_' + b'A' * 36))

    def test_allows_safe_template(self):
        self.assertEqual(self.check('books/.env.example', b'API_KEY=\nTZ=Etc/UTC\n'), [])
        self.assertEqual(self.check('media/compose.yml', b'image: example@sha256:' + b'a' * 64), [])

    def test_rejects_private_identity_and_unknown_binary(self):
        self.assertTrue(self.check('docs/setup.md', b'http://' + b'192.168.' + b'33.77:8096'))
        self.assertTrue(self.check('docs/setup.md', b'/home/' + b'personal-account/private'))
        self.assertTrue(self.check('docs/capture.png', b'\x89PNG\0'))

    def test_scans_staged_blob_instead_of_clean_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tools').mkdir()
            (root / 'tools/check_public_tree.py').write_bytes(GUARD.read_bytes())
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            target = root / 'README.md'
            target.write_bytes(b'gh' + b'p_' + b'Z' * 36)
            subprocess.run(['git', 'add', 'README.md'], cwd=root, check=True)
            target.write_text('clean worktree is not enough\n')
            result = subprocess.run(['python3', str(root / 'tools/check_public_tree.py')], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('GitHub token', result.stderr)
            self.assertNotIn('Z' * 36, result.stderr)

    def test_rejects_staged_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tools').mkdir()
            (root / 'tools/check_public_tree.py').write_bytes(GUARD.read_bytes())
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            os.symlink('/nonexistent/private', root / 'README.md')
            subprocess.run(['git', 'add', 'README.md'], cwd=root, check=True)
            result = subprocess.run(['python3', str(root / 'tools/check_public_tree.py')], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('symbolic link', result.stderr)


if __name__ == '__main__':
    unittest.main()
