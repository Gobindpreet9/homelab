"""Template-only checks; never start services or contact application APIs."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('docker'), 'Docker Compose CLI is needed for template validation')
class MediaTemplateTests(unittest.TestCase):
    def setUp(self):
        result = subprocess.run(
            ['docker', 'compose', '--project-directory', str(ROOT / 'media'),
             '--env-file', str(ROOT / 'media/.env.example'), 'config', '--format', 'json'],
            capture_output=True, text=True, check=True)
        self.config = json.loads(result.stdout)

    def test_all_ports_default_to_loopback(self):
        for name, service in self.config['services'].items():
            for port in service.get('ports', []):
                with self.subTest(service=name, target=port['target']):
                    self.assertEqual(port['host_ip'], '127.0.0.1')

    def test_images_are_digest_pinned_and_network_is_explicit(self):
        self.assertEqual(len(self.config['services']), 7)
        for service in self.config['services'].values():
            self.assertRegex(service['image'], r'@sha256:[a-f0-9]{64}$')
        self.assertEqual(self.config['networks']['media']['name'], 'homelab_media')

    def test_service_configuration_roots_do_not_overlap(self):
        roots = []
        for name, service in self.config['services'].items():
            for volume in service.get('volumes', []):
                if volume['target'] in ('/config', '/app/config'):
                    roots.append((name, Path(volume['source'])))
        self.assertEqual(len(roots), 7)
        for index, (name, root) in enumerate(roots):
            for other_name, other_root in roots[index + 1:]:
                with self.subTest(services=(name, other_name)):
                    self.assertFalse(root == other_root or root in other_root.parents or other_root in root.parents,
                                     'service config roots must be disjoint')

    def test_books_and_media_share_download_storage(self):
        import os
        environment = os.environ.copy()
        environment.update({key: 'synthetic-test-value' for key in
                            ('SHELFMARK_API_KEY', 'PROWLARR_API_KEY', 'QBITTORRENT_API_KEY', 'PROWLARR_INDEXERS')})
        result = subprocess.run(
            ['docker', 'compose', '--env-file', '/dev/null',
             '--file', str(ROOT / 'books/compose.yml'), 'config', '--format', 'json'],
            env=environment, capture_output=True, text=True, check=True)
        books = json.loads(result.stdout)
        def downloads(service):
            return next(volume['source'] for volume in service['volumes'] if volume['target'] == '/downloads')
        self.assertEqual(downloads(self.config['services']['qbittorrent']),
                         downloads(books['services']['shelfmark']))

    def test_download_client_port_matches_documentation(self):
        service = self.config['services']['qbittorrent']
        self.assertEqual(str(service['environment']['WEBUI_PORT']), '18080')
        self.assertTrue(any(port['target'] == 18080 for port in service['ports']))


if __name__ == '__main__':
    unittest.main()
