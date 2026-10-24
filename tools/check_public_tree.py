#!/usr/bin/env python3
"""Conservative staged-blob guard. Never prints matched values.

This is not a comprehensive secret scanner; independent review is required.
"""
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIRS = {
    'config', 'private', 'backups', 'logs', 'cache', '.cache', 'runtime',
    'management', 'locks', 'save-state', 'prefixes', 'app-homes', 'host',
    'downloads', '__pycache__', '.venv', 'node_modules', 'dist', 'releases',
}
PRIVATE_NAMES = {'client.json', 'known_hosts', 'config.toml', '.env'}
ALLOWED_SUFFIXES = {'.md', '.py', '.sh', '.yml', '.yaml', '.json', '.service', '.nft', '.rules', '.toml', '.example', '.txt'}
PATTERNS = {
    'private key': re.compile(rb'-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----'),
    'GitHub token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'AWS access key': re.compile(rb'(?:AKIA|ASIA)[A-Z0-9]{16}'),
    'JWT': re.compile(rb'eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}'),
    'authenticated URL': re.compile(rb'https?://[^\s/\x22\x27]+:[^\s/\x22\x27]+@'),
    'home directory identity': re.compile(rb'/home/[a-z_][a-z0-9_-]*/'),
    'private IPv4 identity': re.compile(rb'(?<![\d.])(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\d.])'),
    'private overlay hostname': re.compile(rb'[a-zA-Z0-9.-]+\.ts\.net\b'),
}


def check_file(name, body):
    path = PurePosixPath(name)
    reasons = []
    if (set(path.parts) & PRIVATE_DIRS or path.name in PRIVATE_NAMES
            or path.name.startswith('.env.') and path.name != '.env.example'
            or path.name.startswith(('id_rsa', 'id_ed25519'))
            or 'credentials' in path.name.lower()):
        reasons.append('private/runtime artifact path')
    if path.suffix not in ALLOWED_SUFFIXES and path.name not in {'.gitignore', 'LICENSE', 'Makefile'}:
        reasons.append('unknown file type requires review')
    if b'\0' in body:
        reasons.append('binary content requires review')
    reasons.extend(label for label, pattern in PATTERNS.items() if pattern.search(body))
    return reasons


def main():
    entries = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT).split(b'\0')
    checked = 0
    findings = []
    for entry in filter(None, entries):
        metadata, raw_name = entry.split(b'\t', 1)
        mode, oid, stage = metadata.split()
        name = raw_name.decode('utf-8')
        checked += 1
        if mode not in (b'100644', b'100755') or stage != b'0':
            findings.append((name, ['symbolic link/submodule/unmerged entry is forbidden']))
            continue
        body = subprocess.check_output(['git', 'cat-file', 'blob', oid.decode('ascii')], cwd=ROOT)
        reasons = check_file(name, body)
        if reasons:
            findings.append((name, reasons))
    for name, reasons in findings:
        print(name + ': ' + ', '.join(reasons), file=sys.stderr)
    print(f'Publication guard: {checked} staged files; {len(findings)} flagged files.')
    return 1 if findings or not checked else 0


if __name__ == '__main__':
    sys.exit(main())
