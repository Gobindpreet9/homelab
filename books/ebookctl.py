"""Mount-aware controller for the fixed ebook Compose project."""
import os
import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path('/srv/homelab/books')
COMPOSE = Path(__file__).resolve().with_name('compose.yml')
MOUNT = Path('/srv/media')
UUID = 'REPLACE_WITH_MEDIA_UUID'  # Configure from the real filesystem; never commit it.
SERVICES = ('cwa', 'shelfmark')


def valid_mount(data):
    if not UUID or UUID.startswith('REPLACE_'):
        return False
    def rows(items):
        for row in items:
            yield row
            yield from rows(row.get('children', []))
    return any(row.get('target') == str(MOUNT)
               and row.get('fstype') == 'exfat'
               and row.get('uuid') == UUID
               for row in rows(data.get('filesystems', [])))


def guard():
    result = subprocess.run(['findmnt', '--json', '--mountpoint', str(MOUNT),
                             '--output', 'TARGET,FSTYPE,UUID'],
                            check=False, capture_output=True, text=True)
    try:
        matched = result.returncode == 0 and valid_mount(json.loads(result.stdout))
    except (ValueError, TypeError, AttributeError):
        matched = False
    if not matched:
        raise RuntimeError('Required media exFAT mount is absent or incorrect')


def directories():
    return (PROJECT / 'config' / 'cwa', PROJECT / 'config' / 'shelfmark',
            MOUNT / 'Books' / 'Ingest', MOUNT / 'Books' / 'Library')


def safe_paths():
    for path in (*directories(), MOUNT / 'Downloads', COMPOSE):
        for part in (path, *path.parents):
            if part.is_symlink():
                raise RuntimeError('Symlinked deployment path rejected')
            if part != COMPOSE and part.exists() and not part.is_dir():
                raise RuntimeError('Deployment directory is not a directory')


def prepare():
    guard()
    safe_paths()
    for path in directories():
        path.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        for path in (PROJECT / 'config', *directories()[:2]):
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fchown(fd, 1000, 1000)
            finally:
                os.close(fd)


def control(action, services=()):
    if action not in ('check', 'up', 'pull', 'down', 'status'):
        raise ValueError('Unsupported action')
    if any(service not in SERVICES for service in services):
        raise ValueError('Unsupported service')
    if services and action not in ('up', 'pull'):
        raise ValueError('Service selection is only allowed for up/pull')
    if action in ('check', 'up', 'pull'):
        guard()
        safe_paths()
        require_dirs()
    args = {'check': ['config', '--quiet'], 'up': ['up', '-d', '--pull', 'never'],
            'pull': ['pull'], 'down': ['down'], 'status': ['ps', '--all']}[action]
    try:
        subprocess.run(['docker', 'compose', '--project-name', 'ebooks',
                        '--project-directory', str(PROJECT), '--file',
                        str(COMPOSE), *args, *services], check=True)
    except (subprocess.CalledProcessError, OSError):
        if action == 'up':
            try:
                control('down')
            except (subprocess.CalledProcessError, OSError):
                print('ebookctl: startup cleanup failed; verify project state.', file=sys.stderr)
        raise


def require_dirs():
    if not all(path.is_dir() for path in (*directories(), MOUNT / 'Downloads')):
        raise RuntimeError('Required directories are absent; run prepare and verify Downloads')


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'check', 'up', 'pull', 'down', 'status'))
    parser.add_argument('services', nargs='*', help='cwa/shelfmark; up or pull only')
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            if args.services:
                raise ValueError('prepare does not accept services')
            prepare()
        else:
            control(args.action, args.services)
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError):
        parser.exit(1, 'ebookctl: operation failed; verify mount, paths and operator access.\n')


if __name__ == '__main__':
    main()
