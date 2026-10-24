from contextlib import closing
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from compose_fixture import resolve_compose
import ebookctl

PROJECT = Path(__file__).resolve().parents[1]

class ControllerTests(unittest.TestCase):
    @patch.object(ebookctl, 'UUID', 'TEST-MEDIA-UUID')
    def test_actual_mount(self):
        good = {'filesystems': [{'target': '/srv/media', 'fstype': 'exfat', 'uuid': 'TEST-MEDIA-UUID'}]}
        self.assertTrue(ebookctl.valid_mount(good))
        for data in ({}, {'filesystems': []}, {'filesystems': [{'target': '/srv/media', 'fstype': 'autofs', 'uuid': 'TEST-MEDIA-UUID'}]}, {'filesystems': [{'target': '/srv/media', 'fstype': 'exfat', 'uuid': 'WRONG'}]}, {'filesystems': [{'target': '/other', 'fstype': 'exfat', 'uuid': 'TEST-MEDIA-UUID'}]}):
            self.assertFalse(ebookctl.valid_mount(data))

    def test_guard_before_writes(self):
        with tempfile.TemporaryDirectory(dir=PROJECT / '.cache') as temp:
            root = Path(temp)
            with patch.object(ebookctl, 'PROJECT', root / 'project'), patch.object(ebookctl, 'MOUNT', root / 'media'), patch('ebookctl.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '{"filesystems": []}')) as run:
                with self.assertRaises(RuntimeError):
                    ebookctl.prepare()
                self.assertEqual(list(root.iterdir()), [])
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0][0], 'findmnt')

    def test_prepare_exact_dirs(self):
        with tempfile.TemporaryDirectory(dir=PROJECT / '.cache') as temp:
            root = Path(temp)
            with patch.object(ebookctl, 'PROJECT', root / 'project'), patch.object(ebookctl, 'MOUNT', root / 'media'), patch.object(ebookctl, 'guard'), patch('os.geteuid', return_value=1000):
                ebookctl.prepare()
                actual = {str(p.relative_to(root)) for p in root.rglob('*')}
                self.assertEqual(actual, {'project', 'project/config', 'project/config/cwa', 'project/config/shelfmark', 'media', 'media/Books', 'media/Books/Ingest', 'media/Books/Library'})

    def test_symlinks_rejected_before_any_creation(self):
        for location in ('project/config', 'media/Books', 'media'):
            with self.subTest(location=location), tempfile.TemporaryDirectory(dir=PROJECT / '.cache') as temp:
                root = Path(temp)
                target = root / 'target'
                target.mkdir()
                link = root / location
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(target, target_is_directory=True)
                before = set(root.rglob('*'))
                with patch.object(ebookctl, 'PROJECT', root / 'project'), patch.object(ebookctl, 'MOUNT', root / 'media'), patch.object(ebookctl, 'guard'):
                    with self.assertRaises(RuntimeError):
                        ebookctl.prepare()
                self.assertEqual(set(root.rglob('*')), before)

    def test_lifecycle_commands(self):
        with patch.object(ebookctl, 'guard', side_effect=RuntimeError('no mount')) as guard, patch.object(ebookctl, 'safe_paths'), patch('ebookctl.subprocess.run') as run:
            for action in ('check', 'up', 'pull'):
                with self.assertRaises(RuntimeError):
                    ebookctl.control(action)
            run.assert_not_called()
            guard.reset_mock()
            ebookctl.control('down')
            ebookctl.control('status')
            guard.assert_not_called()
            base = ['docker', 'compose', '--project-name', 'ebooks', '--project-directory', str(ebookctl.PROJECT), '--file', str(ebookctl.COMPOSE)]
            self.assertEqual([c.args[0] for c in run.call_args_list], [base + ['down'], base + ['ps', '--all']])
            self.assertTrue(all(c.kwargs['check'] for c in run.call_args_list))
        with patch.object(ebookctl, 'guard') as guard, patch.object(ebookctl, 'safe_paths'), patch.object(ebookctl, 'require_dirs'), patch('ebookctl.subprocess.run') as run:
            ebookctl.control('up', ('cwa',))
            self.assertEqual(run.call_args.args[0][-3:], ['--pull', 'never', 'cwa'])
            guard.assert_called_once()
        with patch('ebookctl.subprocess.run') as run:
            for action, services in [('rm', ()), ('up', ('jellyfin',)), ('down', ('cwa',))]:
                with self.assertRaises(ValueError):
                    ebookctl.control(action, services)
            run.assert_not_called()

    def test_missing_dirs_fail_without_docker(self):
        with tempfile.TemporaryDirectory(dir=PROJECT / '.cache') as temp:
            with patch.object(ebookctl, 'PROJECT', Path(temp) / 'project'), patch.object(ebookctl, 'MOUNT', Path(temp) / 'media'), patch.object(ebookctl, 'guard'), patch('ebookctl.subprocess.run') as run:
                with self.assertRaises(RuntimeError):
                    ebookctl.control('up')
                run.assert_not_called()

class ComposeTests(unittest.TestCase):
    def test_auth_copy_sources_and_no_email_policy(self):
        service = resolve_compose()['services']['shelfmark']
        expected = {
            'AUTH_METHOD': 'cwa', 'CWA_DB_PATH': '/auth/app.db',
            'BOOKS_OUTPUT_MODE': 'folder', 'INGEST_DIR': '/books',
            'HARDLINK_TORRENTS': 'false', 'HARDLINK_TORRENTS_AUDIOBOOK': 'false',
            'PROWLARR_TORRENT_ACTION': 'keep',
            'CALIBRE_WEB_URL': 'http://127.0.0.1:8083', 'SEARCH_MODE': 'universal',
            'METADATA_PROVIDER': 'openlibrary', 'OPENLIBRARY_ENABLED': 'true',
            'BOOK_LANGUAGE': 'en', 'SUPPORTED_FORMATS': 'epub',
            'PROWLARR_ENABLED': 'true', 'PROWLARR_URL': 'http://prowlarr:9696',
            'PROWLARR_INDEXERS': 'TEST_INDEXERS', 'PROWLARR_AUTO_EXPAND': 'false',
            'PROWLARR_TORRENT_CLIENT': 'qbittorrent',
            'QBITTORRENT_URL': 'http://qbittorrent:18080',
            'QBITTORRENT_CATEGORY': 'books', 'QBITTORRENT_DOWNLOAD_DIR': '/downloads/books',
            'DIRECT_DOWNLOAD_ENABLED': 'false', 'LIBGEN_SEARCH_ENABLED': 'false',
            'NEWZNAB_ENABLED': 'false', 'ABB_ENABLED': 'false',
        }
        env = service['environment']
        for key, value in expected.items():
            self.assertEqual(env.get(key), value)
        for key in ('PROWLARR_API_KEY', 'QBITTORRENT_API_KEY', 'SHELFMARK_API_KEY'):
            self.assertTrue(bool(env.get(key)), 'Required API key is missing')
        self.assertEqual(set(env), set(expected) | {'PUID', 'PGID', 'TZ', 'PROWLARR_API_KEY', 'QBITTORRENT_API_KEY', 'SHELFMARK_API_KEY'})
        auth = [v for v in service['volumes'] if v['target'] == '/auth/app.db']
        self.assertEqual(len(auth), 1)
        self.assertEqual(auth[0]['source'], str(PROJECT / 'config/cwa/app.db'))
        self.assertTrue(auth[0]['read_only'])
        self.assertFalse(auth[0]['bind']['create_host_path'])
        authored = (PROJECT / 'compose.yml').read_text()
        for key in ('PROWLARR_API_KEY', 'QBITTORRENT_API_KEY'):
            self.assertIn('${' + key, authored)

    def test_resolved_deployment(self):
        config = resolve_compose()
        self.assertEqual(config['name'], 'ebooks')
        services = config['services']
        self.assertEqual(set(services), {'cwa', 'shelfmark'})
        images = {'shelfmark': 'ghcr.io/calibrain/shelfmark-lite:v1.4.0@sha256:edc889c12c4e54076432e5377b674fed4a1aaa934890f8a678bc5b38e5088a75', 'cwa': 'crocodilestick/calibre-web-automated:v4.0.8@sha256:5e00373854247750cc3e4479b492ae09293ff5e06ed10177f226634d97888679'}
        mounts = {'cwa': {str(PROJECT / 'config/cwa'): '/config', '/srv/media/Books/Ingest': '/cwa-book-ingest', '/srv/media/Books/Library': '/calibre-library'}, 'shelfmark': {str(PROJECT / 'config/shelfmark'): '/config', '/srv/media/Books/Ingest': '/books', '/srv/media/Downloads': '/downloads', str(PROJECT / 'config/cwa/app.db'): '/auth/app.db'}}
        for name, service in services.items():
            self.assertEqual(service['image'], images[name])
            self.assertEqual(service['restart'], 'no')
            self.assertFalse(service.get('privileged', False))
            self.assertNotIn('cap_add', service)
            self.assertEqual({key: service['environment'][key] for key in ('PUID', 'PGID', 'TZ')}, {'PUID': '1000', 'PGID': '1000', 'TZ': 'Etc/UTC'})
            if name == 'cwa':
                self.assertEqual(set(service['environment']), {'PUID', 'PGID', 'TZ', 'NETWORK_SHARE_MODE'})
                self.assertEqual(service['environment']['NETWORK_SHARE_MODE'], 'true')
            port = service['ports'][0]
            self.assertEqual(port['host_ip'], '127.0.0.1')
            self.assertEqual(str(port['published']), '8083' if name == 'cwa' else '8084')
            self.assertEqual(port['target'], 8083 if name == 'cwa' else 8084)
            self.assertEqual({v['source']: v['target'] for v in service['volumes']}, mounts[name])
            for volume in service['volumes']:
                self.assertEqual(volume['type'], 'bind')
                self.assertFalse(volume['bind']['create_host_path'])
                self.assertEqual(volume.get('read_only', False), volume['target'] in ('/downloads', '/auth/app.db'))
        self.assertEqual(set(services['cwa']['networks']), {'default'})
        self.assertEqual(set(services['shelfmark']['networks']), {'default', 'media'})
        self.assertEqual(config['networks']['media']['name'], 'homelab_media')
        self.assertTrue(config['networks']['media']['external'])
        self.assertIn('/api/health', ' '.join(services['shelfmark']['healthcheck']['test']))
        self.assertNotIn('healthcheck', services['cwa'])

class FixtureTests(unittest.TestCase):
    def test_valid_authored_epub(self):
        import smoke_epub
        import zipfile
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory(dir=PROJECT / '.cache') as temp:
            path = smoke_epub.generate(Path(temp))
            self.assertIsInstance(path, Path)
            with zipfile.ZipFile(path) as archive:
                first = archive.infolist()[0]
                self.assertEqual(first.filename, 'mimetype')
                self.assertEqual(first.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(archive.read('mimetype'), b'application/epub+zip')
                for name in ('META-INF/container.xml', 'EPUB/package.opf', 'EPUB/nav.xhtml', 'EPUB/chapter.xhtml'):
                    ET.fromstring(archive.read(name))
                opf = ET.fromstring(archive.read('EPUB/package.opf'))
                self.assertEqual(opf.find('{http://www.idpf.org/2007/opf}metadata/{http://purl.org/dc/elements/1.1/}title').text, 'Ebook Pipeline Smoke Test')
                self.assertIn(b'Authored locally', archive.read('EPUB/chapter.xhtml'))
            with self.assertRaises(FileExistsError):
                smoke_epub.generate(Path(temp))

    def test_fixture_rejects_parent_escape_before_writes(self):
        import smoke_epub
        # Mock every writer so the RED test itself cannot escape the workspace.
        with patch('pathlib.Path.mkdir') as mkdir, patch('smoke_epub.zipfile.ZipFile') as archive:
            with self.assertRaises(ValueError):
                smoke_epub.generate(PROJECT / '..' / 'outside-fixture')
            mkdir.assert_not_called()
            archive.assert_not_called()


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        import sqlite3
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT / '.cache')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'app.db'
        self.credentials = self.root / 'admin-credentials.json'
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute('CREATE TABLE user (id INTEGER PRIMARY KEY, name TEXT, password TEXT, auto_send_enabled INTEGER)')
            connection.execute('INSERT INTO user VALUES (1, ?, ?, 1)', ('admin', self.hash_password('admin123')))

    @staticmethod
    def hash_password(password):
        import hashlib
        return hashlib.sha256(password.encode()).hexdigest()

    def run_bootstrap(self):
        import bootstrap_admin
        bootstrap_admin.bootstrap(self.db, self.credentials,
                                  generate_hash=self.hash_password,
                                  check_hash=lambda hashed, password: hashed == self.hash_password(password))

    def rows(self):
        import sqlite3
        with closing(sqlite3.connect(self.db)) as connection, connection:
            return connection.execute('SELECT name, password, auto_send_enabled FROM user').fetchall()

    def test_fresh_admin_secure_credential_and_no_email(self):
        import os
        import stat
        self.run_bootstrap()
        self.assertTrue(self.credentials.is_file())
        login = json.loads(self.credentials.read_text())
        self.assertEqual(set(login), {'username', 'password'})
        self.assertEqual(login['username'], 'admin')
        self.assertTrue(len(login['password']) >= 43)
        self.assertTrue(login['password'] != 'admin123')
        rows = self.rows()
        self.assertTrue(rows[0][1] == self.hash_password(login['password']))
        self.assertTrue(rows[0][1] != self.hash_password('admin123'))
        self.assertTrue(all(row[2] == 0 for row in rows))
        metadata = self.credentials.stat()
        self.assertTrue(stat.S_ISREG(metadata.st_mode))
        self.assertEqual(stat.S_IMODE(metadata.st_mode), 0o600)
        self.assertEqual(metadata.st_uid, os.geteuid())
        self.assertEqual(metadata.st_gid, os.getegid())

    def test_repeat_preserves_identity_and_disables_sending(self):
        import sqlite3
        self.run_bootstrap()
        before = self.credentials.read_bytes()
        inode = self.credentials.stat().st_ino
        original_hash = self.rows()[0][1]
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute('UPDATE user SET auto_send_enabled = 1')
        error = None
        try:
            self.run_bootstrap()
        except Exception as exc:
            error = type(exc).__name__
        self.assertIsNone(error)
        self.assertTrue(self.credentials.read_bytes() == before)
        self.assertEqual(self.credentials.stat().st_ino, inode)
        self.assertTrue(self.rows()[0][1] == original_hash)
        self.assertTrue(all(row[2] == 0 for row in self.rows()))

    def test_unexpected_users_schema_and_nondefault_admin_refused(self):
        import sqlite3
        for change in (
            "INSERT INTO user VALUES (2, 'other', 'unrelated', 1)",
            "UPDATE user SET name = 'other'",
            "UPDATE user SET password = 'already-changed'",
            "ALTER TABLE user RENAME COLUMN auto_send_enabled TO old_send",
        ):
            with self.subTest(change=change):
                with closing(sqlite3.connect(self.db)) as connection, connection:
                    connection.execute(change)
                before = self.db.read_bytes()
                refused = False
                try:
                    self.run_bootstrap()
                except (ValueError, sqlite3.Error):
                    refused = True
                self.assertTrue(refused)
                self.assertFalse(self.credentials.exists())
                self.assertTrue(self.db.read_bytes() == before)
                self.db.unlink()
                with closing(sqlite3.connect(self.db)) as connection, connection:
                    connection.execute('CREATE TABLE user (id INTEGER PRIMARY KEY, name TEXT, password TEXT, auto_send_enabled INTEGER)')
                    connection.execute('INSERT INTO user VALUES (1, ?, ?, 1)', ('admin', self.hash_password('admin123')))

    def test_mismatched_existing_credentials_refused(self):
        import sqlite3
        self.run_bootstrap()
        before = self.credentials.read_bytes()
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE user SET password = 'changed', auto_send_enabled = 1")
        with self.assertRaises(ValueError):
            self.run_bootstrap()
        self.assertTrue(self.credentials.read_bytes() == before)
        self.assertEqual(self.rows()[0][2], 1)

    def test_symlinks_and_unsafe_credentials_refused(self):
        import os
        self.run_bootstrap()
        original = self.credentials.read_bytes()
        target = self.root / 'saved-login.json'
        self.credentials.rename(target)
        self.credentials.symlink_to(target)
        with self.assertRaises(ValueError):
            self.run_bootstrap()
        self.assertTrue(target.read_bytes() == original)
        self.credentials.unlink()
        target.rename(self.credentials)
        os.chmod(self.credentials, 0o644)
        with self.assertRaises(ValueError):
            self.run_bootstrap()
        os.chmod(self.credentials, 0o600)
        saved_db = self.root / 'saved.db'
        self.db.rename(saved_db)
        self.db.symlink_to(saved_db)
        before = saved_db.read_bytes()
        with self.assertRaises(ValueError):
            self.run_bootstrap()
        self.assertTrue(saved_db.read_bytes() == before)

    def test_symlinked_parent_and_missing_database_refused(self):
        link = self.root / 'linked'
        link.symlink_to(self.root, target_is_directory=True)
        import bootstrap_admin
        with self.assertRaises(ValueError):
            bootstrap_admin.bootstrap(link / 'app.db', link / 'admin-credentials.json',
                                      generate_hash=self.hash_password, check_hash=lambda *_: True)
        self.assertFalse(self.credentials.exists())
        self.db.unlink()
        with self.assertRaises(ValueError):
            self.run_bootstrap()
        self.assertFalse(self.db.exists())

    def test_commit_failure_rolls_back_and_removes_only_new_credential(self):
        import sqlite3
        untouched = self.root / 'untouched.json'
        untouched.write_text('preserve')
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.executescript("""
                CREATE TABLE parent (id INTEGER PRIMARY KEY);
                CREATE TABLE audit (id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED);
                CREATE TRIGGER fail_commit AFTER UPDATE OF password ON user
                BEGIN INSERT INTO audit VALUES (99); END;
            """)
        before = self.rows()
        refused = False
        try:
            self.run_bootstrap()
        except sqlite3.IntegrityError:
            refused = True
        self.assertTrue(refused)
        self.assertFalse(self.credentials.exists())
        self.assertTrue(self.rows() == before)
        self.assertEqual(untouched.read_text(), 'preserve')

    def test_cli_uses_only_cwa_paths_and_container_werkzeug(self):
        import bootstrap_admin
        import io
        import types
        from contextlib import redirect_stdout, redirect_stderr
        self.assertTrue(callable(getattr(bootstrap_admin, 'main', None)))
        security = types.ModuleType('werkzeug.security')
        security.generate_password_hash = self.hash_password
        security.check_password_hash = lambda *_: True
        package = types.ModuleType('werkzeug')
        package.security = security
        output = io.StringIO()
        with patch.dict('sys.modules', {'werkzeug': package, 'werkzeug.security': security}), patch.object(bootstrap_admin, 'bootstrap') as run, redirect_stdout(output), redirect_stderr(output):
            bootstrap_admin.main()
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(run.call_args.args, (Path('/config/app.db'), Path('/config/admin-credentials.json')))
        self.assertIs(run.call_args.kwargs['generate_hash'], security.generate_password_hash)
        self.assertIs(run.call_args.kwargs['check_hash'], security.check_password_hash)
