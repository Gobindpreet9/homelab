import importlib
import json
from pathlib import Path
import socket
import tempfile
import unittest

ROOT = Path(__file__).parent

class ProtocolTests(unittest.TestCase):
    def guard(self):
        return importlib.import_module('session_guard')

    def test_only_game_field_and_allowlist(self):
        g = self.guard()
        self.assertEqual(g.validate_request(b'{"game":"example-game"}\n'), 'example-game')
        for value in [b'{}', b'[]', b'{"game":"../x"}', b'{"game":"example-game","containerID":"fake"}', b'{"game":"example-game","game":"second-game"}', b'x'*257]:
            with self.subTest(value=value), self.assertRaises(g.Rejected):
                g.validate_request(value)

    def test_cgroup_and_inspect_identity(self):
        g = self.guard()
        cid = 'a'*64
        self.assertEqual(g.container_from_cgroup('0::/system.slice/docker-'+cid+'.scope\n'), cid)
        self.assertEqual(g.container_from_cgroup('0::/docker/'+cid+'\n'), cid)
        for bad in ['0::/user.slice/session.scope', '0::/user.slice/user-1000.slice/docker-'+cid+'.scope', '0::/docker/'+cid[:12], '0::/docker/'+cid+'\n0::/docker/'+'b'*64]:
            with self.assertRaises(g.Rejected): g.container_from_cgroup(bad)
        doc = {'Id':cid, 'Config':{'Image':g.IMAGE, 'Labels':{'org.hermes.wolf-game':'example-game'}}, 'State':{'Running':True, 'Status':'running'}}
        g.verify_container(doc, cid, 'example-game')
        for field, value in [('Image', 'forged'), ('Labels', {'org.hermes.wolf-game':'second-game'})]:
            changed = json.loads(json.dumps(doc)); changed['Config'][field] = value
            with self.assertRaises(g.Rejected): g.verify_container(changed,cid,'example-game')

    def test_uid_is_from_socket_not_request(self):
        g = self.guard()
        with self.assertRaises(g.Rejected): g.require_uid((123,0,1000))
        with self.assertRaises(g.Rejected): g.require_uid((123,1001,1000))
        self.assertEqual(g.require_uid((123,1000,1000)), 123)

class HostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_lock_exclusion(self):
        import host_guard as h
        with h.game_lock(self.base, 'example-game'):
            with self.assertRaises(h.GuardError):
                with h.game_lock(self.base, 'example-game'): pass
        with h.game_lock(self.base, 'example-game'): pass

    def test_nonzero_presync_blocks_launch_and_successful_retry_clears(self):
        import host_guard as h
        marker = self.base/'started'
        failed = lambda: (_ for _ in ()).throw(h.GuardError('sync failed'))
        with self.assertRaises(h.GuardError):
            h.local_session('example-game', self.base, failed, lambda: [], ['touch', str(marker)], settle=0)
        self.assertFalse(marker.exists())
        self.assertTrue((self.base/'example-game.blocked').exists())
        calls = []
        result = h.local_session('example-game', self.base, lambda: calls.append('sync'), lambda: [], ['touch', str(marker)], settle=0)
        self.assertEqual(result, 0)
        self.assertEqual(calls, ['sync', 'sync'])
        self.assertFalse((self.base/'example-game.blocked').exists())

    def test_waits_for_detached_writer_after_launcher_exit(self):
        import host_guard as h
        import os, sys, time
        child_file = self.base/'pid'
        code = 'import subprocess,sys; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(0.35)"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); open(sys.argv[1],"w").write(str(p.pid))'
        def writers():
            if not child_file.exists(): return []
            pid = child_file.read_text()
            try:
                stat = Path('/proc')/pid/'stat'
                alive = stat.read_text().split(') ',1)[1].split()[0] != 'Z'
                return [pid] if alive else []
            except FileNotFoundError: return []
        start = time.monotonic()
        h.local_session('example-game', self.base, lambda: None, writers, [sys.executable,'-c',code,str(child_file)], settle=0, interval=0.02)
        self.assertGreater(time.monotonic()-start, 0.3)

    def test_known_writers_in_synthetic_proc(self):
        import host_guard as h
        proc = self.base/'proc'; p = proc/'123'; p.mkdir(parents=True)
        (p/'status').write_text('Uid:\t1000\t1000\t1000\t1000\n')
        (p/'environ').write_bytes(b'WINEPREFIX=/srv/homelab/games/local-prefixes/example-game\0')
        (p/'cmdline').write_bytes(b'/runner/bin/wineserver\0-p0\0')
        (p/'comm').write_text('wineserver\n')
        self.assertEqual(h.find_writers('example-game', proc), [123])
        (p/'environ').write_bytes(b'')
        (p/'cmdline').write_bytes(b'Z:\\game\\Example Game.exe\0')
        self.assertEqual(h.find_writers('example-game', proc), [123])
        self.assertEqual(h.find_writers('second-game', proc), [])

    def test_real_helper_round_trip_local_and_remote(self):
        import host_guard as h
        import contextlib, io
        local=self.base/'local'; remote=self.base/'remote'; state=self.base/'state'
        for path in (local,remote,state): path.mkdir(mode=0o700)
        (local/'save.dat').write_text('initial')
        config=self.base/'config.json'
        config.write_text(json.dumps({'version':1,'state_dir':str(state),'games':{'example-game':{'local':str(local),'remote':str(remote)}}}))
        helper=ROOT.parent/'save-sync'/'save_sync.py'
        def sync(): h.run_sync('example-game',config,helper)
        with (self.base/'sync.log').open('w') as log, contextlib.redirect_stderr(log):
            h.local_session('example-game',self.base,sync,lambda:[],['/usr/bin/python3','-c','import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("local-play")',str(local/'save.dat')],settle=0)
            self.assertEqual((remote/'save.dat').read_text(),'local-play')
            class Output(io.StringIO):
                def write(self, text):
                    if text == 'READY': (remote/'save.dat').write_text('remote-play')
                    return super().write(text)
            h.worker_session('example-game',self.base,sync,lambda:[],io.StringIO('FINISH\n'),Output())
        self.assertEqual((local/'save.dat').read_text(),'remote-play')

    def test_actual_nonzero_helper_aborts_launch(self):
        import host_guard as h
        helper=self.base/'bad_sync.py'; helper.write_text('raise SystemExit(3)\n')
        with self.assertRaises(h.GuardError):
            h.local_session('example-game',self.base,lambda:h.run_sync('example-game',self.base/'unused',helper),lambda:[],['/usr/bin/touch',str(self.base/'launched')],settle=0)
        self.assertFalse((self.base/'launched').exists())
        self.assertTrue((self.base/'example-game.blocked').exists())

    def test_unmanaged_writer_blocks_before_sync(self):
        import host_guard as h
        calls=[]
        with self.assertRaises(h.GuardError):
            h.local_session('example-game',self.base,lambda:calls.append('sync'),lambda:[123],['false'],settle=0)
        self.assertEqual(calls,[])

    def test_worker_eof_preserves_lock(self):
        import host_guard as h
        import subprocess, sys, time
        code='import host_guard as h,sys; h.worker_session("example-game",sys.argv[1],lambda:None,lambda:[])'
        # The disposable child imports the exported module, even when discovery
        # is invoked from the export root rather than this suite directory.
        child=subprocess.Popen([sys.executable,'-c',code,str(self.base)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,cwd=ROOT)
        try:
            self.assertEqual(child.stdout.readline(),'READY\n')
            child.stdin.close(); time.sleep(0.05)
            self.assertIsNone(child.poll())
            with self.assertRaises(h.GuardError):
                with h.game_lock(self.base,'example-game'): pass
        finally:
            child.kill(); child.wait(); child.stdout.close()

    def test_unrelated_process_does_not_require_environment_access(self):
        import host_guard as h
        proc=self.base/'proc'; p=proc/'987'; p.mkdir(parents=True)
        (p/'status').write_text('Uid:\t1000\t1000\t1000\t1000\n')
        (p/'cmdline').write_bytes(b'/usr/bin/unrelated-service\0')
        (p/'comm').write_text('unrelated-service\n')
        from unittest.mock import patch
        read_bytes=Path.read_bytes
        def read(path):
            if path.name == 'environ': raise PermissionError('denied')
            return read_bytes(path)
        with patch.object(Path,'read_bytes',read):
            self.assertEqual(h.find_writers('example-game',proc),[])

    def test_known_wine_with_unreadable_environment_fails_closed(self):
        import host_guard as h
        from unittest.mock import patch
        proc=self.base/'proc'; p=proc/'987'; p.mkdir(parents=True)
        (p/'status').write_text('Uid:\t1000\t1000\t1000\t1000\n')
        (p/'cmdline').write_bytes(b'/runner/wineserver\0')
        (p/'comm').write_text('wineserver\n')
        read_bytes=Path.read_bytes
        def read(path):
            if path.name == 'environ': raise PermissionError('denied')
            return read_bytes(path)
        with patch.object(Path,'read_bytes',read), self.assertRaises(h.GuardError):
            h.find_writers('example-game',proc)

class BrokerTests(unittest.TestCase):
    cid = 'a'*64
    def doc(self, running=True):
        import session_guard as g
        return {'Id':self.cid,'Config':{'Image':g.IMAGE,'Labels':{'org.hermes.wolf-game':'example-game'}}, 'State':{'Running':running,'Status':'running' if running else 'exited'}}

    def test_docker_api_is_one_bounded_unix_get(self):
        import session_guard as g
        import threading
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path=str(Path(tmp)/'docker.sock'); requests=[]
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
                server.bind(path); server.listen()
                def respond():
                    conn,_=server.accept()
                    with conn:
                        request=b''
                        while b'\r\n\r\n' not in request: request+=conn.recv(4096)
                        requests.append(request.split(b'\r\n',1)[0])
                        body=json.dumps(self.doc()).encode()
                        conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
                t=threading.Thread(target=respond); t.start()
                self.assertEqual(g.inspect_container(self.cid,path)['Id'],self.cid)
                t.join(2)
            self.assertEqual(requests,[('GET /containers/'+self.cid+'/json HTTP/1.1').encode()])

    def test_inspection_error_does_not_release_worker(self):
        import session_guard as g
        seen = []
        states = iter([OSError('docker down'), self.doc(), self.doc(False)])
        def inspect(cid):
            value = next(states)
            if isinstance(value, Exception): raise value
            return value
        broker = g.Broker(inspect=inspect, sleep=lambda n:seen.append('held'))
        broker.wait_stopped(self.cid,'example-game')
        self.assertEqual(seen,['held','held'])

    def test_duplicate_reservation(self):
        import session_guard as g
        broker = g.Broker()
        with broker.reserve('example-game'):
            with self.assertRaises(g.Rejected):
                with broker.reserve('example-game'): pass
        with broker.reserve('example-game'): pass

    def test_worker_spawn_is_unprivileged_fixed_and_sanitized(self):
        import session_guard as g
        from unittest.mock import patch
        with patch.object(g.subprocess,'Popen') as popen:
            g.spawn_worker('example-game')
        args, kw = popen.call_args
        self.assertEqual(args[0],['/usr/bin/python3','-I','/usr/local/lib/wolf-streaming/host_guard.py','worker','example-game'])
        self.assertEqual((kw['user'],kw['group'],kw['extra_groups']),(1000,1000,[]))
        self.assertNotIn('PYTHONPATH',kw['env'])
        self.assertFalse(kw.get('shell',False))

    def test_full_handshake_finishes_only_after_container_stops(self):
        import session_guard as g
        import io, threading, time
        class Worker:
            stdout = io.StringIO('READY\nDONE\n')
            stdin = io.StringIO()
            def wait(self): return 0
        worker = Worker()
        # Keep test pipe buffers inspectable after broker cleanup.
        worker.stdin.close = lambda: None
        worker.stdout.close = lambda: None
        stopped = threading.Event()
        broker = g.Broker(inspect=lambda cid:self.doc(not stopped.is_set()), spawn=lambda game:worker, identity=lambda pid:self.cid, sleep=lambda n:time.sleep(0.01))
        a,b=socket.socketpair(); self.addCleanup(b.close)
        thread=threading.Thread(target=broker.handle,args=(a,)); thread.start()
        b.sendall(b'{"game":"example-game"}\n')
        self.assertEqual(b.recv(64),b'READY\n')
        b.close(); time.sleep(0.04)
        self.assertEqual(worker.stdin.getvalue(),'')
        stopped.set(); thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(worker.stdin.getvalue(),'FINISH\n')

class ClientTests(unittest.TestCase):
    def test_stop_before_ready_aborts_without_game(self):
        import app_client as a
        import os, threading
        stop=threading.Event(); stop.set()
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path=str(Path(tmp)/'sock')
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
                server.bind(path); server.listen()
                def accept():
                    conn,_=server.accept()
                    with conn:
                        conn.recv(256)
                        self.assertEqual(conn.recv(1),b'')
                t=threading.Thread(target=accept); t.start()
                self.assertEqual(a.run_client('example-game',path,'/does-not-exist',expected_server_uid=os.getuid(),stop=stop),125)
                t.join(2)

    def test_refusal_does_not_launch_game(self):
        import app_client as a
        import os, threading
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = str(Path(tmp)/'sock'); marker=Path(tmp)/'started'
            script=Path(tmp)/'game.sh'; script.write_text('#!/bin/sh\ntouch '+str(marker)+'\n'); script.chmod(0o700)
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
                server.bind(path); server.listen()
                def refuse():
                    conn,_=server.accept()
                    with conn:
                        conn.recv(256); conn.sendall(b'ERROR\n')
                t=threading.Thread(target=refuse); t.start()
                self.assertEqual(a.run_client('example-game',path,str(script),expected_server_uid=os.getuid()),125)
                t.join(2)
            self.assertFalse(marker.exists())

    def test_keeps_socket_open_and_returns_game_status(self):
        import app_client as a
        import os, threading, time
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path=str(Path(tmp)/'sock'); script=Path(tmp)/'game.sh'
            script.write_text('#!/bin/sh\nsleep 0.15\nexit 7\n'); script.chmod(0o700)
            elapsed=[]
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
                server.bind(path); server.listen()
                def accept():
                    conn,_=server.accept()
                    with conn:
                        request=conn.recv(256)
                        self.assertEqual(json.loads(request),{'game':'example-game'})
                        conn.sendall(b'READY\n'); start=time.monotonic()
                        self.assertEqual(conn.recv(1),b''); elapsed.append(time.monotonic()-start)
                t=threading.Thread(target=accept); t.start()
                self.assertEqual(a.run_client('example-game',path,str(script),expected_server_uid=os.getuid()),7)
                t.join(2)
            self.assertGreater(elapsed[0],0.1)

if __name__ == '__main__': unittest.main()
