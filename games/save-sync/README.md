# Offline two-way save synchronization

`save_sync.py` is the current Linux/Python 3.11+ stdlib-only implementation.
It works on two existing, offline directories. It is not a live-prefix sharing
system, game supervisor or cloud-sync client. The example mapping is synthetic.

## Mandatory caller contract

1. Hold the same host-local **per-game active-session flock** used by every
   local/remote launch path. Never unlink/recreate lock files while in use.
2. Verify both games, Wine descendants, background/cloud save writers and other
   editors have stopped. No untrusted concurrent writers may access either tree.
3. Perform a real sync and abort launch on **every nonzero result**. Dry-run is
   never permission to launch or a substitute for establishing a baseline.
4. Keep the active-session lock throughout the game and all surviving writers.
5. Verify all writers stopped, then perform a real post-sync while still locked.
6. If post-sync fails, preserve recovery evidence and block subsequent launch
   until a real retry succeeds. Do not hide failure or bypass the guard.

The helper independently takes exclusive nonblocking `state_dir/sync.lock` for
its transaction. That serializes **all games using that state directory**, not
sessions. Lock order is active-session lock → sync lock; the caller must not
already hold the sync lock. Use one config/state directory for all entry points.
Local-filesystem flock/rename/fsync semantics are required, not assumed on NFS.
Mutation checks are defense in depth, not a hostile-same-UID sandbox.

## Configuration and paths

Edit `mapping.example.json` for your own games only after trust review. All roots
must already exist, be absolute and canonical, and have no symlink components.
Save/state roots cannot overlap or nest, even across games; config must be outside
all roots. State must belong to the helper's effective UID and not be group/other
writable; private mode 0700 is recommended. No paths are inferred from HOME.
Game IDs match `[a-z0-9][a-z0-9_-]{0,63}`. Duplicate JSON keys, unknown schema fields,
invalid versions/IDs/paths and unknown games fail closed.

Optional `include` / `exclude` are case-sensitive `fnmatchcase` patterns against
whole POSIX relative filenames: `*` also matches `/`. Defaults are `include:
["*"]`, `exclude: []`; an empty include selects nothing. Directories are still
traversed and safety-checked even when files are excluded. Symlinks, multiply
linked regular files and special files anywhere in either tree are rejected.
Empty directories, permissions/timestamps, ACLs and xattrs are not synchronized.
The `.wolf-sync-` prefix is reserved. Use narrow real save roots; exclude logs,
per-device display settings, account/cloud metadata and caches.

Created files/backups/baselines are 0600, new subdirectories 0700, owned by the
helper's effective UID. The helper does not chown or widen permissions.

## API and CLI

The public API is `sync(config_path, game, *, dry_run=False) -> dict`.
`SyncError` is launch-blocking; `ConflictError` and `LockError` subclass it.
Other functions/classes are implementation details.

After holding the active-session lock and proving both trees offline, an operator
can use this command form with **their own reviewed absolute paths**:

```sh
python3 /absolute/path/save_sync.py --config /absolute/path/mapping.json --game example-game --dry-run
```

Omitting `--dry-run` performs real writes; never run it on live roots. Success
prints JSON: `copies` contains `{"from":"local"|"remote","path":"relative"}`,
`backups` lists preserved versions, and optional `resolution` describes an
opt-in newest-policy winner. CLI adds `game` and `dry_run`. Dry-run may create
`sync.lock` and update read atimes, but does not change saves, create save
subdirectories, archive conflicts or update baselines.

Exit codes: 0 success; 2 conflict (also argparse usage error); 3 unsafe path,
changed/lost data, invalid config/state or I/O failure; 4 sync lock busy.
Operational errors use JSON on stderr with `error`, `message`, and for conflicts
`paths` and `archive`. Dry-run conflicts have null archive; usage errors are text.

## Decisions and preservation

The baseline records the last common SHA-256 for each selected relative file.

| Situation | Action |
| --- | --- |
| Both sides byte-identical | Accept, record common hash; do not rewrite save |
| One side absent, even after one-sided deletion | Copy survivor; never propagate deletion |
| Both present, one differs from baseline | Copy changed side; back up destination first |
| Both differ from each other and from baseline | Default: archive both, abort before replacements |
| File/directory shape collision | Archive available conflicting files, abort |
| A baselined file is missing from both sides | Abort and retain baseline; recover manually |

New unrelated files merge; there is no game-format-aware merge. Renames may
resurrect old names because deletions do not propagate. No backups are pruned.

`conflict_policy` defaults to `abort`. Opt-in `newest` resolves content conflicts
by comparing the latest changed-file mtime on each side and choosing a **whole
save-set side**, not per-file winners. Existing differing files follow that side,
including loser-only edits; missing files are still resurrected rather than
deleted. Overwritten versions are backed up. A time difference below two seconds,
a changed-file timestamp over 120 seconds in the future, or a file/directory
collision still aborts. Incorrect clocks/mtimes can make this policy choose the
wrong progress; keep `abort` unless you deliberately accept that risk. A dry-run
can report a proposed winner but cannot authorize launch. Policy itself is not
bound into the baseline, so switching policy need not migrate state.

State layout:

```text
sync.lock
<game>.json
backups/<game>/<unique-run>/<local|remote>/<relative-file>
conflicts/<game>/<unique-run>/<local|remote>/<relative-file>
```

Baselines are bound to mapping/filter values and root identities. Current code
records `[filesystem_id, inode]`, using `statvfs().f_fsid` instead of Btrfs's
reboot-unstable device number. Compatibility matching accepts the same inode
even if the first identity field differs, including older device-number
baselines; it is **not a strict filesystem-ID comparison**. Avoid moving roots
between filesystems or reusing state for another tree. Inode reuse is not a
cryptographic identity guarantee. Replaced roots and changed mappings/filters
require deliberate offline migration with original state/saves retained.
An ordinary no-op does not replace canonical baseline/save inodes.

To resolve a conflict, preserve and inspect archives offline, deliberately make
both selected trees agree, then retry real sync. Do not casually delete/edit a
baseline to suppress an error. If consciously reinitializing, retain old state
and saves and use a new private state directory. First-sync conflicts still
require review.

## Atomicity and failure limits

All replacements are staged in exclusive 0600 destination-filesystem temporary
files before any save replacement. Descriptor metadata/path identity and SHA-256
are checked around reads, staging, rescans and commits; old destinations are
backed up durably first. No-follow descriptor-relative traversal rejects escaped
components, symlinks, hardlinks and special files. Roots are rechecked; files and
affected parent directories are fsynced; baseline advances only after convergence.

**Per-file replacement is atomic; a whole multi-file sync is not one transaction.**
Power loss, SIGKILL or an I/O error can leave a partially applied batch, old
baseline, completed backups, empty directories and/or orphan `.wolf-sync-*`
entries. Orphans cause fail-closed refusal: preserve them outside save roots and
inspect manually, never assume complete saves. Do not launch after failure.
Review backups, verify all writers idle and retry under the active-session lock.

## Safe tests

From the export root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s save-sync -p 'test_*.py' -v
```

All save roots in tests are disposable synthetic fixtures beneath the suite.
Coverage includes baselines, both directions, resurrection/lost-both detection,
conflicts, newest policy, Btrfs identity compatibility, atomic readers, archives,
unsafe links/FIFOs, root/source/destination mutation, failed rename, locks and
actual helper CLI exit statuses. No live saves or games are opened.
