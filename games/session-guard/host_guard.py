"""UID-1000 launch boundary; both launch paths take the same per-game flock."""
from contextlib import contextmanager
import argparse
import fcntl
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

# Fixed reviewed deployment root; never accept a client/environment path override.
BASE = Path('/srv/homelab/games')
CONFIG = BASE / 'save-mapping.json'
HELPER = '/usr/local/lib/wolf-streaming/save_sync.py'
# Synthetic allowlist only. A root-trusted reviewer must supply exact prefixes,
# executable basenames, argv and cwd; do not load arbitrary client commands.
GAMES = {
    'example-game': {
        'prefix': '/srv/homelab/games/local-prefixes/example-game',
        'executables': ('example game.exe',),
        'command': ['/usr/bin/false'],  # Deliberately not a game launcher.
        'cwd': '/srv/homelab/games/local-games/example-game',
    },
    'second-game': {
        'prefix': '/srv/homelab/games/local-prefixes/second-game',
        'executables': ('second game.exe',),
        'command': ['/usr/bin/false'],
        'cwd': '/srv/homelab/games/local-games/second-game',
    },
}

class GuardError(Exception):
    pass


def check_game(game):
    if game not in GAMES:
        raise GuardError('unknown game')


@contextmanager
def game_lock(directory, game):
    check_game(game)
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    fd = None
    try:
        meta = os.fstat(dfd)
        if meta.st_uid != os.getuid() or meta.st_mode & 0o022:
            raise GuardError('unsafe lock directory')
        fd = os.open(game+'.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=dfd)
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_uid != os.getuid():
            raise GuardError('unsafe lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise GuardError('game already active or recovery lock held') from exc
        yield
    finally:
        if fd is not None: os.close(fd)
        os.close(dfd)


def blocked(directory, game, error=None):
    target = Path(directory)/(game+'.blocked')
    if error is None:
        target.unlink(missing_ok=True)
        return
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_uid != os.getuid():
            raise GuardError('unsafe sentinel')
        os.ftruncate(fd, 0)
        os.write(fd, (str(error)+'\n').encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def find_writers(game, proc=Path('/proc')):
    """Best effort bypass detection, not a defense against malicious same-UID code.

    Match both host prefixes, container /prefix, and known executable basenames.
    Refuse unreadable same-UID processes; unrelated users are not inspected.
    """
    check_game(game)
    prefixes = {GAMES[game]['prefix'], str(BASE/'prefixes'/game), '/prefix', '/wineprefix'}
    found = []
    for entry in Path(proc).iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid(): continue
        try:
            status = (entry/'status').read_text()
            uid_line = next((line for line in status.splitlines() if line.startswith('Uid:')), '')
            if not uid_line or int(uid_line.split()[1]) != os.getuid(): continue
            command = (entry/'cmdline').read_bytes().decode(errors='replace').split('\0')
            comm = (entry/'comm').read_text().strip().lower()
            # Zombies have no memory/environment and cannot write saves.
            if not any(command): continue
            names = [arg.replace('\\', '/').rsplit('/',1)[-1].lower() for arg in command]
            known = any(name in GAMES[game]['executables'] for name in names) or any(name.startswith(comm) for name in GAMES[game]['executables'] if len(comm) >= 8)
            if known:
                found.append(int(entry.name))
                continue
            wine_names = {'wine','wine64','wine-preloader','wine64-preloader','wineserver','wineserver64'}
            if not (set(names) & wine_names or comm in wine_names or comm.endswith('.exe')):
                continue
            environment = (entry/'environ').read_bytes().split(b'\0')
            prefix = next((x[11:].decode(errors='replace') for x in environment if x.startswith(b'WINEPREFIX=')), '')
            if prefix.rstrip('/') in prefixes:
                found.append(int(entry.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            raise GuardError('cannot inspect process '+entry.name) from exc
    return found


def stopped(writers):
    pids = writers()
    if pids:
        raise GuardError('unmanaged or surviving game/prefix writers: '+str(pids))


def run_sync(game, config=CONFIG, helper=HELPER):
    result = subprocess.run(['/usr/bin/python3', '-I', str(helper), '--config', str(config), '--game', game], stdout=sys.stderr, check=False)
    if result.returncode:
        raise GuardError('save sync failed with status '+str(result.returncode))


def boundary(directory, game, sync, writers):
    stopped(writers)
    sync()
    stopped(writers)
    blocked(directory, game)


def wait_idle(writers, settle=1.0, interval=0.2):
    quiet = None
    while True:
        if writers():
            quiet = None
        else:
            if quiet is None: quiet = time.monotonic()
            if time.monotonic()-quiet >= settle: return
        time.sleep(interval)


def local_session(game, directory, sync, writers, command, *, cwd=None, settle=1.0, interval=0.2):
    with game_lock(directory, game):
        try:
            boundary(directory, game, sync, writers)
            child = subprocess.Popen(command, cwd=cwd, close_fds=True)
            code = child.wait()
            wait_idle(writers, settle, interval)
            boundary(directory, game, sync, writers)
            return code
        except BaseException as exc:
            blocked(directory, game, exc)
            raise


def worker_session(game, directory, sync, writers, source=sys.stdin, output=sys.stdout):
    with game_lock(directory, game):
        try:
            boundary(directory, game, sync, writers)
            print('READY', file=output, flush=True)
            # EOF/invalid command cannot authorize post-sync; preserve lock forever.
            if source.readline(32) != 'FINISH\n':
                blocked(directory, game, 'broker lost; manual stopped-container recovery required')
                while True: time.sleep(3600)
            boundary(directory, game, sync, writers)
            print('DONE', file=output, flush=True)
            return 0
        except BaseException as exc:
            blocked(directory, game, exc)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('worker','local','retry'))
    parser.add_argument('game', choices=sorted(GAMES))
    args = parser.parse_args(argv)
    if os.getuid() != 1000 or os.geteuid() != 1000:
        parser.error('must run as uid 1000, never root')
    # Defer ordinary termination; never drop an active-session lock on a signal.
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: None)
    sync = lambda: run_sync(args.game)
    writers = lambda: find_writers(args.game)
    directory = BASE/'locks'
    try:
        if args.mode == 'worker': return worker_session(args.game, directory, sync, writers)
        if args.mode == 'local':
            game = GAMES[args.game]
            return local_session(args.game, directory, sync, writers, game['command'], cwd=game['cwd'])
        with game_lock(directory,args.game):
            try: boundary(directory,args.game,sync,writers)
            except BaseException as exc:
                blocked(directory,args.game,exc)
                raise
        return 0
    except (GuardError, OSError) as exc:
        print('BLOCKED: '+str(exc),file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
