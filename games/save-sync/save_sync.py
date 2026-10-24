"""Two-way save synchronization. See README.md for the caller contract."""

from contextlib import contextmanager, ExitStack
import fcntl
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

# Newest-wins refuses to guess when the two sides' latest save times are this
# close together, or when a timestamp lies in the future (clock problems).
TIE_WINDOW_NS = 2_000_000_000
FUTURE_SLACK_NS = 120_000_000_000
POLICIES = ('abort', 'newest')


class SyncError(Exception):
    """Launch-blocking synchronization error."""


class LockError(SyncError):
    """Another synchronization owns this state directory."""


class ConflictError(SyncError):
    def __init__(self, paths, archive=None):
        self.paths = paths
        self.archive = str(archive) if archive else None
        super().__init__('conflicting saves: ' + ', '.join(paths))


def parts(name):
    if not isinstance(name, str) or not name or '\x00' in name or name.startswith('/'):
        raise SyncError('invalid relative path')
    result = name.split('/')
    if any(p in ('', '.', '..') for p in result):
        raise SyncError('escaped or non-canonical path: ' + name)
    return result


def _json_loads(raw):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SyncError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique_pairs)


def _signature(meta):
    return (meta.st_dev, meta.st_ino, meta.st_mode, meta.st_nlink,
            meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns)


def _root_identity(fd):
    """[filesystem id, inode]. st_dev is not stable on Btrfs across reboots
    (anonymous device numbers), so use statvfs f_fsid, which is."""
    return [os.fstatvfs(fd).f_fsid, os.fstat(fd).st_ino]


def _same_root(stored, current):
    # Accept older baselines that recorded st_dev: the inode must still match.
    return (isinstance(stored, list) and len(stored) == 2
            and stored[1] == current[1])


def _transfer(source, output):
    while chunk := source.read(1024 * 1024):
        output.write(chunk)


class Staged:
    def __init__(self, tree, name, parent, temp, digest):
        self.tree, self.name, self.parent, self.temp, self.digest = tree, name, parent, temp, digest
        prefix = name.rpartition('/')[0]
        self.relative = prefix + '/' + temp if prefix else temp

    def commit(self, expected):
        self.tree.verify_anchor()
        if self.tree.digest(self.name) != expected:
            raise SyncError('destination changed before replacement: ' + self.name)
        with self.tree.parent(self.name) as (current, leaf):
            old, new = os.fstat(self.parent), os.fstat(current)
            if (old.st_dev, old.st_ino) != (new.st_dev, new.st_ino):
                raise SyncError('destination directory moved: ' + self.name)
            if self.tree.digest(self.relative) != self.digest:
                raise SyncError('staged file changed: ' + self.name)
            os.replace(self.temp, leaf, src_dir_fd=self.parent, dst_dir_fd=self.parent)
            os.fsync(self.parent)

    def close(self):
        try:
            os.unlink(self.temp, dir_fd=self.parent)
        except FileNotFoundError:
            pass
        finally:
            os.close(self.parent)


class Tree:
    """Pinned directory descriptors; never follows symlinks at any component."""
    def __init__(self, path):
        self.path = os.fspath(path)
        if not self.path.startswith('/'):
            raise SyncError('root must be absolute: ' + self.path)
        components = parts(self.path[1:])
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for name in components:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                os.close(fd)
                fd = child
            self.fd = fd
        except BaseException:
            os.close(fd)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        os.close(self.fd)

    def verify_anchor(self):
        with Tree(self.path) as current:
            old, new = os.fstat(self.fd), os.fstat(current.fd)
            if (old.st_dev, old.st_ino) != (new.st_dev, new.st_ino):
                raise SyncError('root directory moved or replaced: ' + self.path)

    @contextmanager
    def parent(self, name, create=False):
        components = parts(name)
        fd = os.dup(self.fd)
        try:
            for component in components[:-1]:
                if create:
                    try:
                        os.mkdir(component, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd, components[-1]
        finally:
            os.close(fd)

    @contextmanager
    def reader(self, name):
        with self.parent(name) as (parent, leaf):
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
            try:
                metadata = os.fstat(fd)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise SyncError('not a private regular file: ' + name)
                before = _signature(metadata)
                with os.fdopen(fd, 'rb', closefd=False) as stream:
                    yield stream
                after = os.fstat(fd)
                current = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                if before != _signature(after) or before != _signature(current):
                    raise SyncError('file changed while reading: ' + name)
            finally:
                os.close(fd)

    def read(self, name):
        try:
            with self.reader(name) as source:
                return source.read()
        except FileNotFoundError:
            return None

    def digest(self, name):
        try:
            with self.reader(name) as source:
                return hashlib.file_digest(source, 'sha256').hexdigest()
        except FileNotFoundError:
            return None

    def mtime_ns(self, name):
        with self.parent(name) as (parent, leaf):
            metadata = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            raise SyncError('not a regular file: ' + name)
        return metadata.st_mtime_ns

    def scan(self, ignore=(), include=('*',), exclude=()):
        result = {}
        self.directories = set()
        def visit(fd, prefix):
            # Rewind explicitly: some filesystems retain a stale directory cookie
            # after rename when a duplicated directory description is reused.
            os.lseek(fd, 0, os.SEEK_SET)
            for name in sorted(os.listdir(fd)):
                relative = prefix + name
                if relative in ignore:
                    continue
                if name.startswith('.wolf-sync-'):
                    raise SyncError('orphan staging entry requires manual recovery: ' + relative)
                metadata = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(metadata.st_mode):
                    self.directories.add(relative)
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                    try:
                        visit(child, relative + '/')
                    finally:
                        os.close(child)
                elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                    if any(fnmatchcase(relative, p) for p in include) and not any(fnmatchcase(relative, p) for p in exclude):
                        result[relative] = self.digest(relative)
                else:
                    raise SyncError('symlink, hardlink or special file: ' + relative)
        visit(self.fd, '')
        return result

    @contextmanager
    def stage_from(self, name, source_tree, source_name, expected):
        with self.parent(name, create=True) as (parent, leaf):
            parent = os.dup(parent)
        temp = '.wolf-sync-' + uuid.uuid4().hex
        staged = Staged(self, name, parent, temp, expected)
        try:
            fd = os.open(temp, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
            with os.fdopen(fd, 'w+b') as output:
                with source_tree.reader(source_name) as source:
                    _transfer(source, output)
                output.flush()
                os.fsync(output.fileno())
                output.seek(0)
                if hashlib.file_digest(output, 'sha256').hexdigest() != expected:
                    raise SyncError('source hash changed: ' + source_name)
            yield staged
        finally:
            staged.close()

    def copy_from(self, name, source_tree, source_name, expected):
        with self.stage_from(name, source_tree, source_name, expected) as staged:
            staged.commit(None)

    def write(self, name, data):
        with self.parent(name, create=True) as (parent, leaf):
            # Refuse an existing symlink rather than replacing even its directory entry.
            self.digest(name)
            temp = '.wolf-sync-' + uuid.uuid4().hex
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temp, leaf, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                try:
                    os.unlink(temp, dir_fd=parent)
                except FileNotFoundError:
                    pass


@contextmanager
def sync_lock(state):
    fd = os.open('sync.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=state.fd)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1:
            raise SyncError('unsafe sync lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockError('synchronization already running') from exc
        yield
    finally:
        os.close(fd)


def validate_config(config, game, config_path):
    if not isinstance(config, dict) or set(config) != {'version', 'state_dir', 'games'} or type(config['version']) is not int or config['version'] != 1:
        raise SyncError('config requires version=1, state_dir and games')
    games = config['games']
    if not isinstance(games, dict) or not games or game not in games:
        raise SyncError('unknown game or empty games mapping')
    paths = [config['state_dir']]
    for key, mapping in games.items():
        if not isinstance(key, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', key):
            raise SyncError('invalid game identifier')
        if not isinstance(mapping, dict) or not {'local', 'remote'} <= mapping.keys() or mapping.keys() - {'local', 'remote', 'include', 'exclude', 'conflict_policy'}:
            raise SyncError('game requires local/remote and optional include/exclude/conflict_policy')
        if mapping.get('conflict_policy', 'abort') not in POLICIES:
            raise SyncError('conflict_policy must be one of: ' + ', '.join(POLICIES))
        paths.extend([mapping['local'], mapping['remote']])
        for field, default in [('include', ['*']), ('exclude', [])]:
            patterns = mapping.get(field, default)
            if not isinstance(patterns, list) or any(not isinstance(p, str) or not p for p in patterns):
                raise SyncError('filters must be lists of nonempty relative glob patterns')
            for pattern in patterns:
                parts(pattern)
    for path in paths:
        if not isinstance(path, str) or not path.startswith('/'):
            raise SyncError('all roots must be absolute paths')
        parts(path[1:])
    for index, first in enumerate(paths):
        for second in paths[index + 1:]:
            if os.path.commonpath([first, second]) in (first, second):
                raise SyncError('save/state roots must not overlap, including across games')
    for path in paths:
        if os.path.commonpath([path, str(config_path)]) == path:
            raise SyncError('config cannot live inside a save or state root')


def _newest_side(roots, files, baseline):
    """Return (winner, details) or (None, reason) when the choice is unsafe."""
    now = time.time_ns()
    latest = {}
    for side, root in roots.items():
        changed = [name for name, digest in files[side].items() if digest != baseline.get(name)]
        if not changed:
            return None, 'no changed files on ' + side
        stamps = [root.mtime_ns(name) for name in changed]
        if max(stamps) > now + FUTURE_SLACK_NS:
            return None, 'future timestamp on ' + side
        latest[side] = max(stamps)
    gap = latest['local'] - latest['remote']
    if abs(gap) < TIE_WINDOW_NS:
        return None, 'save times too close to decide'
    winner = 'local' if gap > 0 else 'remote'
    return winner, {'policy': 'newest', 'winner': winner,
                    'local_mtime_ns': latest['local'], 'remote_mtime_ns': latest['remote']}


def _sync(config, game, dry_run, stack):
    mapping = config['games'][game]
    roots = {side: stack.enter_context(Tree(mapping[side])) for side in ('local', 'remote')}
    state = stack.enter_context(Tree(config['state_dir']))
    state_meta = os.fstat(state.fd)
    if state_meta.st_uid != os.geteuid() or state_meta.st_mode & 0o022:
        raise SyncError('state directory must be owned by this user and not writable by group/others')
    stack.enter_context(sync_lock(state))
    filters = {'include': mapping.get('include', ['*']), 'exclude': mapping.get('exclude', [])}
    files = {side: root.scan(**filters) for side, root in roots.items()}
    state_name = game + '.json'
    raw = state.read(state_name)
    identity = {side: _root_identity(root.fd) for side, root in roots.items()}
    binding = {key: mapping[key] for key in ('local', 'remote')}
    binding.update(filters)
    if raw is None:
        baseline = {}
    else:
        document = _json_loads(raw)
        if not isinstance(document, dict) or set(document) != {'version', 'mapping', 'roots', 'files'} or document['version'] != 1:
            raise SyncError('invalid baseline schema/version')
        stored = document['roots']
        if (document['mapping'] != binding or not isinstance(stored, dict) or set(stored) != set(identity)
                or not all(_same_root(stored[side], identity[side]) for side in identity)):
            raise SyncError('baseline mapping/root identity changed; manual migration required')
        baseline = document['files']
        if not isinstance(baseline, dict):
            raise SyncError('baseline files must be a hash mapping')
        for name, digest in baseline.items():
            parts(name)
            if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise SyncError('invalid baseline SHA-256')
    lost = baseline.keys() - (files['local'].keys() | files['remote'].keys())
    if lost:
        raise SyncError('both sides missing baseline files: ' + ', '.join(sorted(lost)))
    conflicts = [name for name in sorted(files['local'].keys() | files['remote'].keys())
                 if files['local'].get(name) is not None and files['remote'].get(name) is not None
                 and files['local'][name] != files['remote'][name]
                 and files['local'][name] != baseline.get(name)
                 and files['remote'][name] != baseline.get(name)]
    all_names = files['local'].keys() | files['remote'].keys()
    blocked = (files['local'].keys() & roots['remote'].directories) | (files['remote'].keys() & roots['local'].directories)
    conflicts = sorted(set(conflicts) | blocked | {name for name in all_names if any(name.startswith(parent + '/') for parent in blocked)})
    winner, resolution = None, None
    if conflicts and not blocked and mapping.get('conflict_policy', 'abort') == 'newest':
        winner, resolution = _newest_side(roots, files, baseline)
        if winner is None:
            resolution = None
    if conflicts and winner is None:
        if dry_run:
            raise ConflictError(conflicts)
        archive = 'conflicts/' + game + '/' + uuid.uuid4().hex
        for side in roots:
            for name in conflicts:
                if name in files[side]:
                    state.copy_from(archive + '/' + side + '/' + name, roots[side], name, files[side][name])
        raise ConflictError(conflicts, Path(state.path) / archive)
    copies = []
    backups = []
    stages = []
    ignored = {'local': set(), 'remote': set()}
    run_id = uuid.uuid4().hex
    for name in sorted(files['local'].keys() | files['remote'].keys()):
        left, right = files['local'].get(name), files['remote'].get(name)
        if left == right:
            continue
        if left is None:
            source, dest = 'remote', 'local'
        elif right is None:
            source, dest = 'local', 'remote'
        elif winner is not None:
            # Whole save set follows the newer side; overwritten files are backed up.
            source, dest = winner, ('remote' if winner == 'local' else 'local')
        elif right == baseline.get(name):
            source, dest = 'local', 'remote'
        else:
            source, dest = 'remote', 'local'
        if not dry_run:
            if files[dest].get(name) is not None:
                backup = 'backups/' + game + '/' + run_id + '/' + dest + '/' + name
                state.copy_from(backup, roots[dest], name, files[dest][name])
                backups.append(str(Path(state.path) / backup))
            staged = stack.enter_context(roots[dest].stage_from(name, roots[source], name, files[source][name]))
            stages.append((source, dest, name, staged))
            ignored[dest].add(staged.relative)
        copies.append({'from': source, 'path': name})
    if not dry_run:
        for side, root in roots.items():
            root.verify_anchor()
            if root.scan(ignore=ignored[side], **filters) != files[side]:
                raise SyncError('save tree changed while staging: ' + side)
        for source, dest, name, staged in stages:
            if roots[source].digest(name) != files[source][name]:
                raise SyncError('source changed before commit: ' + name)
            staged.commit(files[dest].get(name))
            files[dest][name] = files[source][name]
        final = {side: root.scan(**filters) for side, root in roots.items()}
        if final != files or final['local'] != final['remote']:
            raise SyncError('save tree changed during commit; baseline not advanced')
        for root in [*roots.values(), state]:
            root.verify_anchor()
        encoded = json.dumps({'version': 1, 'mapping': binding, 'roots': identity, 'files': files['local']}, sort_keys=True).encode()
        if encoded != raw:
            state.write(state_name, encoded)
    result = {'copies': copies, 'backups': backups}
    if resolution:
        result['resolution'] = resolution
    return result


def sync(config_path, game, *, dry_run=False):
    try:
        with ExitStack() as stack:
            config_path = Path(config_path)
            source = stack.enter_context(Tree(str(config_path.parent)))
            config = _json_loads(source.read(config_path.name))
            validate_config(config, game, config_path)
            return _sync(config, game, dry_run, stack)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SyncError(str(exc)) from exc


def main(argv=None):
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='Offline two-way save sync; requires caller-held active-game lock and stopped writers.')
    parser.add_argument('--config', required=True, help='absolute path to version-1 JSON mapping')
    parser.add_argument('--game', required=True, help='configured game identifier')
    parser.add_argument('--dry-run', action='store_true', help='plan only; acquires/creates sync.lock but changes no saves or baseline')
    args = parser.parse_args(argv)
    try:
        result = sync(args.config, args.game, dry_run=args.dry_run)
    except ConflictError as exc:
        print(json.dumps({'error': 'conflict', 'message': str(exc), 'paths': exc.paths, 'archive': exc.archive}), file=sys.stderr)
        return 2
    except LockError as exc:
        print(json.dumps({'error': 'locked', 'message': str(exc)}), file=sys.stderr)
        return 4
    except SyncError as exc:
        print(json.dumps({'error': 'unsafe', 'message': str(exc)}), file=sys.stderr)
        return 3
    result.update({'game': args.game, 'dry_run': args.dry_run})
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
