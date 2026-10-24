"""Container entrypoint; no arbitrary command or path accepted from environment."""
import json
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import threading

# Root-reviewed synthetic IDs; keep aligned with host_guard and mappings.
GAMES = frozenset(('example-game', 'second-game'))


def stop_game(child):
    if child.poll() is not None: return
    try: os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError: pass
    try: child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try: os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        child.wait()


def run_client(game, socket_path='/run/wolf-session.sock', script='/opt/wolf/game.sh', *, expected_server_uid=0, stop=None):
    if game not in GAMES: return 125
    child = None
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(10)
            connection.connect(socket_path)
            _,uid,_ = struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))
            if uid != expected_server_uid: return 125
            connection.sendall(json.dumps({'game':game},separators=(',',':')).encode()+b'\n')
            connection.settimeout(None)
            response=bytearray()
            while len(response) <= 16:
                if stop is not None and stop.is_set(): return 125
                ready,_,_=select.select([connection],[],[],0.2)
                if not ready: continue
                chunk=connection.recv(1)
                if not chunk: return 125
                response += chunk
                if chunk == b'\n': break
            if response != b'READY\n': return 125
            child=subprocess.Popen([script],close_fds=True,start_new_session=True)
            while child.poll() is None:
                if stop is not None and stop.is_set():
                    stop_game(child)
                    return 125
                ready,_,_=select.select([connection],[],[],0.1)
                if ready:
                    # EOF or any unexpected broker data aborts this container app.
                    stop_game(child)
                    return 125
            status=child.returncode
            return status if status >= 0 else 128-status
    except (OSError, ValueError) as exc:
        print('session unavailable: '+str(exc),file=sys.stderr)
        if child is not None: stop_game(child)
        return 125


def main():
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):
        signal.signal(sig,lambda *_:stop.set())
    return run_client(os.environ.get('GAME_ID',''),stop=stop)

if __name__ == '__main__': raise SystemExit(main())
