# Export-only verification

**Result: public source template prepared; no deployment acceptance is claimed.** The allowlist in `EXPORT.md` contains 15 text files. There are no exported runtime settings, working secrets, databases, logs, backups, binaries or personal deployment reports.

## Checks actually executed

| Check | Result |
|---|---|
| Original regression behavior | All 24 inherited tests retained and passing after generic paths and fixture-based Compose rendering |
| Public-template safety regressions | Five additional tests pass: refusing placeholder UUID, controlled malformed mount-response rejection, generic/protected systemd paths, placeholder-only environment example, and rejection of every missing required Compose setting |
| Repository-root discovery | `PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s books/tests -v`: **29 tests passed**, no skips |
| Compose rendering | Actual template rendered by existing Docker Compose using explicit synthetic environment values and `--env-file /dev/null`; no real `.env`, Docker daemon, pull or container startup used |
| Python syntax | All eight Python source/test files parsed in memory, without bytecode artifacts |
| Image references | Both exported version-and-digest pins compared with the original source: unchanged |
| Original input integrity | Nine original allowlisted source/test/unit/Compose/ignore files matched their pre-copy SHA-256 fingerprints after export |
| Privacy/secret review | Pattern and in-memory exact-credential comparisons produced no findings; final allowlist review excludes runtime/data artifacts. No credential values printed |
| Systemd dependency preflight | `systemd-analyze verify` could not complete against this host: the generic prerequisite `srv-media.mount` is not installed. Static unit regression checks pass; this is **not** a passed runtime dependency test |

The inherited controller lifecycle tests mock subprocesses, including partial startup, project-scoped cleanup and preservation of the original startup failure. Bootstrap tests use synthetic SQLite databases and injected hash functions; real image hashing and schema behavior are not re-proven by these unit fixtures. The EPUB test creates and validates an authored temporary archive, then removes it; it does not import or deliver a book.

## Not executed / not established

- No image pull, install/download, container start/stop, mount change, systemd install or service enablement.
- No modifications to the original deployment or Git state; no commit, push or publication.
- No live mount UUID/permission/locking test at the generic paths.
- No actual CWA/Shelfmark health, shared-auth, journal, import/cleanup or restart test of the template.
- No Prowlarr/qBittorrent connectivity or authorized acquisition test using the public placeholders.
- No email configuration, SMTP submission, automatic send or physical-device receipt test.
- No backup/restore, reboot, physical disk-loss or multi-user routing acceptance test.

Private installation must configure the filesystem identity, protected project/environment, authorized API/indexer settings, generic external `homelab_media` dependency, and mount unit. Follow `README.md` for first-run bootstrap, read-only SQLite compatibility checks, mount/lifecycle safeguards, no-auto-email policy and operator acceptance. Historical successful tests on a different private installation are deliberately not copied into this report.
