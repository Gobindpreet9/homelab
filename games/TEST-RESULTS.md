# Export verification results

Tests were actually run against this exported tree, as an ordinary UID-1000
user, with bytecode writes disabled. No games, input devices, live save roots,
Docker daemon, service operations, downloads or installation were exercised.

| Suite | Tests | Exit status | Result |
| --- | ---: | ---: | --- |
| `save-sync` | 41 | 0 | OK (0.490s) |
| `session-guard` | 21 | 0 | OK (0.884s) |

**Total: 62 tests passed.** Commands from the games source directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s save-sync -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s session-guard -p 'test_*.py' -v
```

The first root-directory discovery run exposed an existing test-only assumption:
a child imported `host_guard` from its current directory. The exported
`test_worker_eof_preserves_lock` now sets child cwd to its own suite directory;
the isolated regression and both full suites passed afterward. Production guard
logic was not changed by that fix. Bridge fixtures still assume UID 1000,
matching the production boundary; other CI users need an appropriate test user.

## Static review evidence

- All four current source/installed library pairs compared equal before export.
- Exported `save_sync.py` is byte-identical to the installed current library.
- AST comparison found all guard classes/functions unchanged apart from the
  explicitly sanitized fixed worker environment. Only module-level allowlists,
  prefix/command examples and runtime base were otherwise neutralized.
- All 6 Python files parsed successfully; all 5 shell files passed `bash -n`.
  Shell helpers were **not executed**.
- Compose YAML parsed; NVIDIA selection is generic `all` / `count: all`, with no
  GPU UUID. Public image digests were preserved, not fetched or updated.
- Synthetic mapping JSON parsed and passed the helper's schema/path validation
  without opening or creating any configured runtime save roots.
- Three systemd samples parsed as INI and retain the explicit operator-created
  REVIEWED condition. They were not installed or validated against live systemd.
- Full UTF-8 text scan covered every exported file, checking an explicit source
  file-type allowlist, personal home paths, UUID literals, personal inventory,
  nonpublic IPv4 literals, overlay hostnames, private-key markers, NUL/binary
  content, symlinks and forbidden runtime/config directories. No findings.
- Firewall uses only interface/CIDR placeholders and is intentionally invalid
  until reviewed and edited. It was not loaded or run through nft.

## Limits

This verifies synthetic unit behavior and static export hygiene, not deployment
correctness or complete absence of every possible secret. Parent repository
security review remains required. There is no supplied game inventory, game
launcher, Wolf app configuration, pairing state or complete runnable stack.
Root trust review, own game mappings, clone-only writable app mounts, correct
UID/GID/account/permissions, NVIDIA runtime, firewall choices and service
lifecycle review are all operator responsibilities. No HDR, streaming quality,
controller, GPU compatibility or image security claim is made.
