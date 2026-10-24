# Unix-socket session boundary bridge

Source-only, root-trust-reviewed integration required; no configured game is
supplied. The synthetic allowlists contain `example-game` and `second-game`.
`host_guard.py` deliberately uses `/usr/bin/false` as both local commands.

## Components and trusted configuration

- `host_guard.py`: UID-1000 local wrapper / remote worker; both modes use the
  same per-game active-session flock, idle-writer check and real pre/post sync.
- `session_guard.py`: root broker, Unix socket only. Fixed paths, UID/GID, image,
  Docker endpoint and worker argv are not controlled by environment or clients.
  Root reads host proc, Docker inspections and worker pipes; only the dropped
  worker reads save mappings and touches user save/state/lock paths.
- `app_client.py`: fixed container entrypoint; environment selects only `GAME_ID`.
  Requires a root peer, waits for READY, runs `/opt/wolf/game.sh` in a new process
  group, monitors broker EOF and returns game status or 125 on boundary failure.

Install reviewed code with trusted root ownership under
`/usr/local/lib/wolf-streaming`; install `../save-sync/save_sync.py` there too.
Never run privileged code from a user-writable checkout or allow writable code
ancestors. Runtime root is `/srv/homelab/games`, with `save-mapping.json`, private
`locks/`, private `sync-state/`, original `local-prefixes/` and isolated `prefixes/`.
Mapping roots and unit write exceptions must be narrow save directories, not
whole prefixes. Originals must never be app container mounts, especially rw.

Edit all three root-trusted GAMES constants, exact host prefixes/executable
basenames/local command argv/cwd, matching label and GAME_ID, own foreground
game script and save mappings together. Do not replace constants with arbitrary
client/env commands or load user config into root Python. Review the fixed
`gameworker` account name/HOME in the sanitized worker environment.

UID/GID **1000** is intentionally still an enforced invariant. Root worker spawn
uses user=1000, group=1000, no supplementary groups, umask 0077, Python `-I`,
fixed argv, no shell, cwd `/`, and a minimal environment. A different identity
requires coordinated review of host checks, broker peer checks, spawn, socket
group, app user and tests. Do not enable user-namespace remapping as-is.

## Container verification and integration

The broker verifies SO_PEERCRED UID=1000 and a positive PID, then derives one
full 64-hex Docker ID from host `/proc/<pid>/cgroup`. It accepts system Docker
`/system.slice/docker-<id>.scope` and `/docker/<id>` layouts (and descendants),
not user-delegated lookalikes, abbreviated IDs or a client-supplied ID. Process
starttime checks and a second cgroup lookup detect PID reuse / changing identity.
Docker inspection must match the exact full ID, label `org.hermes.wolf-game`,
running state and exact `Config.Image` reference in the broker's `IMAGE` constant.
That public pinned app reference was retained from the compared current source;
it has not been updated or vulnerability-assessed as part of this export.

Bind the root-owned host socket `/run/wolf-streaming/session.sock` read-only to
app `/run/wolf-session.sock`. Do not expose Docker socket, host proc or host
locks to app containers. Mount reviewed app code read-only at `/opt/wolf`; supply
your own fixed, foreground `/opt/wolf/game.sh`. App user must be 1000:1000. Its
supervisor must stop the **entire app container** after the client exits, with no
restart policy. `game.sh` must not return while Wine writers survive. The client
terminates its game process group on broker EOF, but the broker still requires
Docker-confirmed complete stop before post-sync.

Root has Docker socket access and is therefore root-equivalent if compromised;
the small inspect-only code path is not a Docker authorization sandbox. Its only
Docker operation is a bounded HTTP GET of one exact container ID. It does not
start/stop containers or send Docker mutations. The separate Wolf orchestrator
in the Compose template does need Docker control; do not confuse those roles.

Route every local desktop launch through the reviewed installed local guard or
`../launchers/local-launch.sh`; no direct Bottles bypass. Local mode waits for its
fixed CLI and all known executable/prefix writers, including wineserver, plus
one second idle before post-sync. A parent CLI exiting is insufficient. Ordinary
TERM/INT/HUP are deferred while the guard owns a boundary.

## Protocol and lock semantics

Client sends one newline-terminated JSON object, for example
`{"game":"example-game"}`. Request deadline 10 seconds, maximum 256 bytes,
only one allowlisted game key, no duplicate/extra fields. Broker replies READY
only after the worker completed pre-sync; otherwise ERROR or EOF. No subsequent
client commands exist. Duplicate game reservations are refused. Independent games
still share a sync-state lock and conservative writer detection can block both.

Both host modes hold `/srv/homelab/games/locks/<game>.lock` throughout the session.
Failures create `<game>.blocked` and refuse launch; successful real retry
boundaries with idle writers clear it. Contention never modifies another
session's sentinel. Sentinels are evidence, not permission to bypass pre-sync.

Known executable basenames and Wine processes whose WINEPREFIX matches original
or cloned prefix, `/prefix` or `/wineprefix` count as writers. Unreadable relevant
same-UID processes fail closed; unrelated non-Wine processes need not expose
their environments. These checks are conservative, best-effort bypass detection,
not protection against hostile same-UID code, deliberate unguarded launches,
renamed processes, custom runners, hidden namespaces or SIGKILL.

Client EOF alone never authorizes FINISH. After successful initial verification,
only Docker-confirmed exited/dead state or exact-ID removal (404) does. Docker
errors, malformed state or changed identity hold the worker/reservation
indefinitely. Worker EOF/invalid input retains its lock indefinitely and records
a sentinel. This intentionally favors blocking over risking concurrent saves.

## Service review and manual recovery

`../templates/systemd/wolf-session-guard.service` is uninstalled and
requires a separately created REVIEWED marker. systemd creates a root-owned
runtime directory; broker creates root:1000 socket mode 0660. Root service is
intentional (no explicit User=); broker asserts root and drops workers. Preserve
host proc visibility: do not add PrivateUsers, hide host `/proc`, or use
ProtectProc=invisible. Sandbox uses strict read-only system/home, narrow reviewed
ReadWritePaths, no-new-privileges, AF_UNIX and setuid/setgid/chown capabilities.
All writable save/state/lock paths must exist with correct ownership before use.
Adding a mapping requires updating unit write exceptions for **every** save root.

KillMode=process / SendSIGKILL=no intentionally preserve worker locks if the
broker dies. Restarting does not reconnect orphan workers. Never restart a live
stack casually: streaming's Requires= dependency on the guard can stop Wolf when
the guard is stopped/restarted. Review lifecycle/dependencies at an idle boundary.

Manual failure recovery, only with explicit operator approval:

1. Independently prove the specific container stopped/was removed and every
   relevant local/Wine writer is idle. A disconnected client is not proof.
2. Preserve logs, sentinel, saves, state and conflict/backups for inspection;
   resolve conflicts offline. Never publish that runtime material.
3. If an orphan worker still owns the boundary, explicitly terminate only that
   reviewed worker after proving writers idle. Do not delete lockfiles.
4. Run the installed guard's `retry <own-game-id>` as the configured UID, never
   root. It takes the shared lock, verifies idle writers, and performs real sync.
   Resume launches only after success; do not simply remove `.blocked` files.
5. If the broker socket inode changed, recreate app containers at the approved
   idle boundary: existing file bind mounts can retain the old socket inode.

## Safe unit tests

From the export root, as ordinary UID 1000 (matching fixture assumptions):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s session-guard -p 'test_*.py' -v
```

Tests use disposable files beneath this directory, real flock and Unix sockets,
synthetic proc trees, harmless temporary scripts/processes, a temporary Unix HTTP
Docker fixture and actual exported save-sync subprocesses. Worker privilege-drop
argv/flags are inspected with a mock; no privileged worker is spawned, Docker
daemon is contacted, game launched or input injected. A test child uses explicit
suite cwd so discovery from the export root also imports the exported guard.
