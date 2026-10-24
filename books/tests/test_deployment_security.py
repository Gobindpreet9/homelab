from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from compose_fixture import resolve_compose
import bootstrap_admin

PROJECT = Path(__file__).resolve().parents[1]


class RealCwaBootstrapTests(unittest.TestCase):
    def test_fresh_cwa_guest_is_preserved_and_all_sends_disabled(self):
        with tempfile.TemporaryDirectory(dir=PROJECT / '.cache') as temp:
            database = Path(temp) / 'app.db'
            credentials = Path(temp) / 'credentials.json'
            hashed = lambda password: hashlib.sha256(password.encode()).hexdigest()
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute('CREATE TABLE user (id INTEGER PRIMARY KEY, name TEXT, password TEXT, auto_send_enabled INTEGER, role INTEGER)')
                connection.execute('INSERT INTO user VALUES (1, ?, ?, 1, 1)', ('admin', hashed('admin123')))
                connection.execute('INSERT INTO user VALUES (2, ?, ?, 1, ?)', ('Guest', '', 1 << 5))
            error = None
            try:
                bootstrap_admin.bootstrap(database, credentials, generate_hash=hashed,
                                          check_hash=lambda h, p: h == hashed(p))
            except Exception as exc:
                error = type(exc).__name__
            self.assertIsNone(error, 'Actual fresh CWA schema includes its anonymous Guest')
            with closing(sqlite3.connect(database)) as connection, connection:
                rows = connection.execute('SELECT name, auto_send_enabled FROM user ORDER BY id').fetchall()
                self.assertEqual(rows, [('admin', 0), ('Guest', 0)])
                self.assertEqual(connection.execute('SELECT password FROM user WHERE name=?', ('Guest',)).fetchone(), ('',))
            self.assertTrue(credentials.is_file())


class InstalledBundleTests(unittest.TestCase):
    def test_systemd_uses_root_owned_snapshot_without_changing_data_paths(self):
        import importlib.util
        with tempfile.TemporaryDirectory(dir=PROJECT / '.cache') as temp:
            installed = Path(temp) / 'ebookctl.py'
            installed.write_bytes((PROJECT / 'ebookctl.py').read_bytes())
            spec = importlib.util.spec_from_file_location('installed_ebookctl', installed)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.PROJECT, Path('/srv/homelab/books'))
            self.assertEqual(getattr(module, 'COMPOSE', None), Path(temp) / 'compose.yml')
        unit = (PROJECT / 'systemd/ebooks.service').read_text()
        self.assertIn('ExecStart=/usr/bin/python3 /etc/ebooks/ebookctl.py up', unit)
        self.assertIn('ExecStop=/usr/bin/python3 /etc/ebooks/ebookctl.py down', unit)
        self.assertNotIn('ExecStart=/usr/bin/python3 /home/', unit)


class AutomationPolicyTests(unittest.TestCase):
    def test_automation_key_is_private_reference_with_browser_auth_enabled(self):
        env = resolve_compose()['services']['shelfmark']['environment']
        self.assertEqual(env.get('AUTH_METHOD'), 'cwa')
        self.assertTrue(bool(env.get('SHELFMARK_API_KEY')), 'Private automation API key missing')
        self.assertIn('SHELFMARK_API_KEY: "${SHELFMARK_API_KEY:', (PROJECT / 'compose.yml').read_text())


class ReadOnlyAuthCompatibilityTests(unittest.TestCase):
    def test_cwa_conservative_mode_for_read_only_shared_auth_database(self):
        config = resolve_compose()
        self.assertEqual(config['services']['cwa']['environment'].get('NETWORK_SHARE_MODE'), 'true')
        auth = next(v for v in config['services']['shelfmark']['volumes'] if v['target'] == '/auth/app.db')
        self.assertTrue(auth['read_only'])
        self.assertEqual(auth['source'], str(PROJECT / 'config/cwa/app.db'))
