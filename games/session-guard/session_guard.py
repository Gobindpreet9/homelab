"""Root-only Unix boundary broker. No user file access or Docker writes."""
import json
import re
from contextlib import contextmanager
import http.client
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import time

# Root-reviewed synthetic IDs; keep aligned with host_guard and mappings.
GAMES = frozenset(('example-game', 'second-game'))
IMAGE = 'ghcr.io/games-on-whales/lutris@sha256:ced81076359daf2684b5a64e908cb116af7bb22541bfeaf7ab2feb6f2154121b'
MAX_REQUEST = 256

class Rejected(Exception):
    pass


def validate_request(raw):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise Rejected('duplicate key')
            result[k] = v
        return result
    try:
        if len(raw) > MAX_REQUEST:
            raise Rejected('request too long')
        obj = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(obj, dict) or set(obj) != {'game'} or not isinstance(obj['game'], str) or obj['game'] not in GAMES:
            raise Rejected('only an allowlisted game is accepted')
        return obj['game']
    except (ValueError, UnicodeError, TypeError) as exc:
        raise Rejected('invalid JSON') from exc


def require_uid(credentials):
    pid, uid, gid = credentials
    if uid != 1000 or pid <= 0:
        raise Rejected('unauthorized peer')
    return pid


def container_from_cgroup(text):
    ids = set()
    for line in text.splitlines():
        path = line.split(':', 2)[-1]
        match = re.fullmatch(r'/(?:system\.slice/docker-([a-f0-9]{64})\.scope|docker/([a-f0-9]{64}))(?:/.*)?', path)
        if match: ids.add(match.groups())
    flattened = {a or b for a, b in ids}
    if len(flattened) != 1:
        raise Rejected('peer is not in one Docker cgroup')
    return flattened.pop()


def verify_container(doc, cid, game):
    if (not isinstance(doc, dict) or doc.get('Id') != cid or
        doc.get('Config', {}).get('Image') != IMAGE or
        doc.get('Config', {}).get('Labels', {}).get('org.hermes.wolf-game') != game):
        raise Rejected('container identity, label or pinned image mismatch')


def peer_container(pid, proc=Path('/proc')):
    """Bind cgroup lookup to a stable process identity (PID reuse fails closed)."""
    entry = Path(proc)/str(pid)
    before = (entry/'stat').read_text()
    cid = container_from_cgroup((entry/'cgroup').read_text())
    after = (entry/'stat').read_text()
    # Field 22 is starttime; comm may contain spaces and parentheses.
    if before.rsplit(') ',1)[1].split()[19] != after.rsplit(') ',1)[1].split()[19]:
        raise Rejected('peer PID was reused')
    return cid


class DockerHTTP(http.client.HTTPConnection):
    def __init__(self, path='/var/run/docker.sock'):
        super().__init__('localhost', timeout=5)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def inspect_container(cid, socket_path='/var/run/docker.sock'):
    if not re.fullmatch('[a-f0-9]{64}', cid):
        raise Rejected('invalid container ID')
    connection = DockerHTTP(socket_path)
    try:
        # Intentionally the only Docker API operation: GET one exact ID.
        connection.request('GET', '/containers/'+cid+'/json')
        response = connection.getresponse()
        if response.status == 404: return None
        if response.status != 200: raise Rejected('Docker inspection unavailable')
        raw = response.read(1024*1024+1)
        if len(raw) > 1024*1024: raise Rejected('Docker response too large')
        return json.loads(raw)
    finally:
        connection.close()


def spawn_worker(game):
    if game not in GAMES: raise Rejected('unknown game')
    return subprocess.Popen(
        ['/usr/bin/python3', '-I', '/usr/local/lib/wolf-streaming/host_guard.py', 'worker', game],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, text=True,
        user=1000, group=1000, extra_groups=[], umask=0o077, cwd='/',
        env={'HOME':'/srv/homelab/games','USER':'gameworker','LOGNAME':'gameworker','PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},
        close_fds=True, start_new_session=True,
    )


def request_line(connection):
    data = bytearray()
    while len(data) <= MAX_REQUEST:
        chunk = connection.recv(1)
        if not chunk: raise Rejected('incomplete request')
        data += chunk
        if chunk == b'\n': return bytes(data)
    raise Rejected('request too long')


class Broker:
    def __init__(self, *, inspect=inspect_container, spawn=spawn_worker, identity=peer_container, sleep=time.sleep):
        self.inspect, self.spawn, self.identity, self.sleep = inspect, spawn, identity, sleep
        self.active = set()
        self.mutex = threading.Lock()

    @contextmanager
    def reserve(self, game):
        with self.mutex:
            if game in self.active: raise Rejected('game already reserved')
            self.active.add(game)
        try: yield
        finally:
            with self.mutex: self.active.remove(game)

    def wait_stopped(self, cid, game):
        while True:
            try:
                doc = self.inspect(cid)
                if doc is None: return  # 404 only, after successful initial verification.
                verify_container(doc, cid, game)
                state = doc.get('State', {})
                if state.get('Running') is False and state.get('Status') in ('exited','dead'):
                    return
            except (OSError, Rejected, ValueError, http.client.HTTPException, TypeError, AttributeError):
                # Daemon unavailable, malformed state, changed identity: never infer stop.
                pass
            self.sleep(1)

    def handle(self, connection):
        worker = None
        try:
            credentials = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
            pid = require_uid(credentials)
            connection.settimeout(10)
            game = validate_request(request_line(connection))
            cid = self.identity(pid)
            doc = self.inspect(cid)
            verify_container(doc, cid, game)
            if doc.get('State',{}).get('Running') is not True:
                raise Rejected('container not running')
            if self.identity(pid) != cid:
                raise Rejected('peer container changed')
            with self.reserve(game):
                worker = self.spawn(game)
                try:
                    if worker.stdout.readline(64) != 'READY\n':
                        raise Rejected('worker refused launch')
                    connection.sendall(b'READY\n')
                    connection.settimeout(None)
                    # No further client commands exist; EOF is the normal boundary.
                    if connection.recv(1): raise Rejected('unexpected client data')
                finally:
                    connection.close()
                    self.wait_stopped(cid, game)
                    try:
                        worker.stdin.write('FINISH\n')
                        worker.stdin.flush()
                    except (BrokenPipeError, OSError): pass
                    finally:
                        worker.stdin.close()
                    status = worker.wait()
                    worker.stdout.close()
                    if status: print('worker failed for '+game, file=sys.stderr, flush=True)
        except (Rejected, OSError, ValueError, KeyError, TypeError, AttributeError, http.client.HTTPException) as exc:
            try: connection.sendall(b'ERROR\n')
            except OSError: pass
            print('session refused: '+str(exc), file=sys.stderr, flush=True)
        finally:
            connection.close()


def main():
    if os.getuid() != 0: raise SystemExit('root service only')
    path = '/run/wolf-streaming/session.sock'
    # RuntimeDirectory is created by systemd, never mkdir/chown user-supplied paths.
    parent = os.stat('/run/wolf-streaming', follow_symlinks=False)
    import stat
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022:
        raise SystemExit('unsafe RuntimeDirectory')
    try:
        old = os.lstat(path)
        if not stat.S_ISSOCK(old.st_mode) or old.st_uid != 0:
            raise SystemExit('unsafe stale socket')
        os.unlink(path)
    except FileNotFoundError: pass
    broker = Broker()
    slots = threading.BoundedSemaphore(16)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(path)
        os.chown(path,0,1000)
        os.chmod(path,0o660)
        server.listen(8)
        def serve(connection):
            try: broker.handle(connection)
            finally: slots.release()
        while True:
            connection, _ = server.accept()
            if not slots.acquire(blocking=False):
                connection.close()
                continue
            threading.Thread(target=serve,args=(connection,),daemon=True).start()


if __name__ == '__main__': main()
