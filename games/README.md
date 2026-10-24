# Isolated Wolf game streaming — source-only export

**Review material, not an installer or a ready-to-run deployment. Do not start,
enable, install or apply these templates automatically.** No game is configured.
The two allowlist IDs (`example-game`, `second-game`) and all save mappings are
synthetic. Local commands deliberately use `/usr/bin/false`; `game.example.sh`
always refuses with status 125.

## Included

- `save-sync/`: current stdlib-only offline save synchronizer, synthetic mapping,
  caller contract and unit tests.
- `session-guard/`: current local launcher/worker, root Unix-socket broker,
  container client and synthetic boundary tests; reviewed constants replace
  private game inventories and identities.
- `launchers/`: current-derived local wrapper, nested-compositor startup/client
  helpers and optional NVIDIA 32-bit library helper. The client wrapper retains
  static touchpad/window rules and failure-only compositor shutdown; exported
  diagnostics and personal desktop references were removed. No game-specific
  launcher or user-sourced per-game environment hook is included.
- `templates/`: sanitized Compose, LAN firewall and systemd examples. They are
  intentionally not installed and do not include Wolf app/session configuration.
- `TEST-RESULTS.md`: results of safe tests run against this export.

This is an allowlisted export of selected current files, not a recursive copy.
The source and installed copies of `save_sync.py`, `host_guard.py`,
`session_guard.py` and `app_client.py` were compared byte-for-byte and matched.
Installed library copies were used; deployment helper scripts and service
samples were inspected separately. Historical backups, audit reports, bootstrap,
add-game, artwork-refresh and live-management tools were not exported. No Git
history was inspected or exported.

Excluded: live `config.toml`, host/cfg directories, certificates/keys, pairing
state, client identities, game/account identifiers, GPU UUIDs, personal game
inventory, game binaries, Wine prefixes, saves, covers, logs and runtime data.
Image SHA-256 digests are public container references, not account identifiers.
`.gitignore` helps exclude future runtime material but is not a substitute for
an explicit publishing review.

## Security model that must remain intact

1. Both local launches and remote session workers take the **same host-local
   per-game flock**, then verify idle writers and complete a real pre-sync.
   They hold the lock throughout the game and all writers, then post-sync.
   Any failure blocks launch; never bypass wrappers or delete active lockfiles.
2. The root broker exposes only a Unix socket. `SO_PEERCRED`, host UID, stable
   process identity, host cgroup, exact Docker container ID, pinned app image,
   label and running state are checked. Requests contain only an allowlisted
   game ID, never a command, path, UID or client-supplied container ID.
3. Only the unprivileged worker touches saves/config/state. It is spawned with
   fixed argv, Python isolated mode, empty supplementary groups, a minimal
   environment, and UID/GID **1000**. This is an explicit deployment constraint,
   not an inferred account identity. The sample environment calls that account
   `gameworker` and uses `/srv/homelab/games` as HOME.
4. Client disconnect is **not** proof the game stopped. The broker withholds
   FINISH until Docker confirms that the previously verified container exited,
   died or was removed. Inspection failure holds the boundary. Worker EOF
   retains its lock indefinitely for manual recovery.
5. Original game directories and original prefixes are **never mounted into
   app containers**, and never bound read-write. Use independent clones/copies
   with narrow save-only synchronization. Never substitute hardlinks or a
   shared live prefix. Read-only runner/library mounts must be separate.

Same-UID writer detection is best-effort, not a sandbox against malicious code.
Docker socket access is root-equivalent. Wolf's orchestrator needs substantial
host access in the sample; do not expose that access to game app containers.

## Manual integration checklist — root trust review required

No commands below install or activate anything. Before a separate, explicitly
approved deployment, the operator must review all code, images, volumes,
capabilities, game launch commands, firewall behavior and service dependencies.

- Use Linux, Python 3.11+ and a local filesystem supporting flock, no-follow
  directory descriptor operations, rename and fsync. The streaming examples
  target NVIDIA with the NVIDIA container runtime, appropriate device access
  and an already available GoW/Wolf installation. These are prerequisites, not
  components installed or downloaded by this export.
- Install reviewed Python/helpers only into root-owned, non-user-writable code
  paths such as `/usr/local/lib/wolf-streaming`; keep every ancestor trusted.
  Do not run the root broker directly from a user-writable checkout. Install
  the synchronizer next to `host_guard.py`, despite their separate source dirs.
- Supply **your own game mappings**. Edit all three fixed `GAMES` allowlists,
  exact host executable basenames, local prefix paths, fixed command argv and
  cwd, app labels/`GAME_ID`, foreground container `game.sh`, and narrow save
  mappings together. Do not accept arbitrary launch commands or privileged
  paths from environment variables or socket clients. A user-owned save mapping
  may only be read by the UID-1000 helper, never root Python.
- `/srv/homelab/games` is the neutral runtime root, **not this source checkout**.
  Review `BASE`, mapping paths, unit write exceptions and Compose mounts as one
  set if changing it. Replace `gameworker` with the reviewed UID-1000 account
  name/environment. A different UID/GID requires coordinated changes to broker
  peer verification, worker spawn, host guard checks, socket group ownership,
  container user and tests; user-namespace remapping is not supported as-is.
- Create real, canonical, non-symlink save roots, private state/lock directories
  and appropriate UID-1000 ownership. Keep config outside all save/state roots.
  Include only save data, not cloud caches, crash dumps, account metadata,
  device graphics/HDR settings or whole prefixes. Keep backups outside the
  publication tree. Review first sync offline with independent backups.
- Provide a new private Wolf config yourself; this export deliberately omits
  `config.toml` and app definitions. Configure an isolated virtual compositor,
  matching pinned app image and label, read-only `/opt/wolf` helpers, and the
  root-owned session socket mounted read-only at `/run/wolf-session.sock`.
  Mount only clone game/prefix data writable. App UID/GID must be 1000, its
  supervisor must stop the entire app container on client exit, and app restart
  policy must be disabled. Never expose Docker socket, host proc or lock files
  to the game app. Only the trusted Wolf orchestrator uses the Docker socket.
- `container-startup.sh` expects GoW's `/opt/gow` helpers; place reviewed
  `launch-client.sh`, `app_client.py` and your fixed `game.sh` at `/opt/wolf`.
  The launcher uses `SWAYSOCK` for the nested Sway only. Static untitled-window,
  fullscreen and touchpad-pointer rules are optional and title-dependent.
  `game.sh` must wait for Wine and its writers, not launch in the background.
- `25-host-nvidia32.sh` is optional, container-root startup code: it expects
  host `/usr/lib32` read-only at `/opt/host-lib32` and a compatible Debian-style
  target. It symlinks selected NVIDIA libraries and calls `ldconfig` **inside
  the app container only**. Never run it on the host or put host libc/the whole
  lib32 directory on the container loader path. Review driver ABI compatibility.
- `local-launch.sh` is a desktop wrapper for the reviewed installed guard;
  route all local launchers through it. Create its runtime log directory with
  private ownership/mode before use; the wrapper may write logs and
  send a refusal notification. Do not publish those logs or run the wrapper as
  a test: after a remote session ends it may launch your configured local game.
- Compose uses generic `NVIDIA_VISIBLE_DEVICES: all` / GPU `count: all`; select
  your own GPU and render node if necessary. Image digests were retained from
  the compared deployment, **not** checked for updates or vulnerability status.
  Review NVIDIA runtime and broad host device/udev mounts before reuse.
- Replace the firewall's interface and `REPLACE_WITH_LAN_CIDR` placeholders; the
  firewall template is intentionally invalid until edited.
  It permits the listed streaming ports only on loopback or the chosen IPv4
  LAN, dropping other sources including IPv6 for those ports. It changes only
  its named table; existing firewall chains may still reject allowed traffic.
  Review nft syntax/version (`destroy table` support), port requirements,
  VPN/routing, and interaction with the host firewall. Never forward to WAN.
- Service templates live under `templates/systemd/` and require an operator-created
  `/etc/wolf-streaming/REVIEWED` marker; none is supplied. Review that condition,
  then manually provision paths/config if deployment is later authorized.
  Streaming expects reviewed `compose.yml`, firewall `lan-filter.nft`, and the
  installed broker. Compose start forbids builds and pulls. No service is
  enabled, started, reloaded or changed by this export.

**No HDR support or performance claim is made.** This export was not tested
with a real stream, display, controller, game or NVIDIA runtime. Reassess upstream
capabilities before promising HDR; keep per-device settings out of save sync.

## Safe tests only

From this directory, as an ordinary UID-1000 user (the bridge fixtures mirror
that explicit deployment constraint):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s save-sync -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s session-guard -p 'test_*.py' -v
```

Tests create and clean disposable synthetic fixtures inside the export. They
exercise real local locks, temporary Unix sockets, synthetic processes and
save-sync CLI subprocesses, **not** a Docker daemon, live saves, games, input,
services or a deployed launcher. Do not replace them with a live smoke test.
For detailed contracts and failure recovery see the two library READMEs.
