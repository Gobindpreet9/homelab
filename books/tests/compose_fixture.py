"""Render the public template with explicit synthetic values, never a real .env.

Only `docker compose config` is called: no daemon, pull, network or container use.
All API strings here are test placeholders, not working credentials.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
# Discovery works from either the books directory or the repository root.
sys.path.insert(0, str(PROJECT))
(PROJECT / '.cache').mkdir(exist_ok=True)
FIXTURE_ENV = {
    'SHELFMARK_API_KEY': 'TEST_ONLY_NOT_A_SECRET',
    'PROWLARR_API_KEY': 'TEST_ONLY_NOT_A_SECRET',
    'QBITTORRENT_API_KEY': 'TEST_ONLY_NOT_A_SECRET',
    'PROWLARR_INDEXERS': 'TEST_INDEXERS',
}


def resolve_compose():
    environment = os.environ.copy()
    environment.update(FIXTURE_ENV)
    result = subprocess.run([
        'docker', 'compose', '--env-file', '/dev/null',
        '--project-directory', str(PROJECT), '--file', str(PROJECT / 'compose.yml'),
        'config', '--format', 'json',
    ], env=environment, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)
