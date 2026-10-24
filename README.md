# Homelab

Source-only, sanitized exports for a Linux homelab: media playback and library management, ebook browsing and ingestion, and isolated game streaming. This repository is **not** a backup of a live machine, a complete disaster-recovery image, or a one-command deployment.

| Component | Includes | Start here |
| --- | --- | --- |
| Media | Jellyfin, Jellyseerr, Radarr, Sonarr, Prowlarr, Bazarr, qBittorrent Compose template | [media/README.md](media/README.md) |
| Books | Calibre-Web Automated + Shelfmark Lite; guarded controller, bootstrap and tests | [books/README.md](books/README.md) |
| Games | Wolf/Moonlight isolation templates, guarded save synchronization and tests | [games/README.md](games/README.md) |
| LG TV Home | Separate launcher, Moonfin deep-link patch and Omarchy theme bridge | `Gobindpreet9/lg-home-omarchy-sync` on GitHub |

## What was intentionally left out

No passwords, API tokens, SSH/private keys, certificates, TV/client pairing state, application databases, personal identities, viewing history, media/game/book files, save files, installed prefixes, private network names, GPU/disk UUIDs, runtime captures or private device-operation scripts. Each exported component has been reviewed; Git ignore patterns are an additional guard, not a substitute for reviewing staged content.

The Compose files preserve image pins from the source deployment. Pins enable repeatability but require ongoing vulnerability and upgrade review. Host GPU support, storage mounts, ownership, network ACLs, VPN protection and backups must be configured for your own environment. Sample paths and IDs are not a description of the original host.

## Safe starting order

1. Read [SECURITY.md](SECURITY.md) and each component's prerequisites.
2. Configure your storage and verify actual mounts. Do not let missing external storage silently fall back to the root filesystem.
3. Review the media template, set local `.env` values and deliberately deploy it. Administration UIs default to loopback; torrent privacy requires separate verified fail-closed routing.
4. Adapt the books paths, mount guard, local credentials and service unit. Its download handoff uses copies, not seeding-file moves. Email/automatic delivery stays disabled until separately configured and physically verified.
5. Treat game streaming as a separate privileged installation. Review Docker-socket/device access, root-owned trust configuration, UID and save mappings before enabling it. Never mount original games/prefixes writable in the remote session.

No installer is run by cloning, testing or validating this repository. No TV rooting or Home replacement is automated here.

## Local verification

Python 3.11+ is required. The publication checker and unit suites use the standard library; Compose template tests also require the Docker Compose CLI (no daemon or containers are used). The session-guard suite uses an actual Unix-socket UID-1000 trust fixture: run it as an ordinary UID-1000 user. CI runs a separate disposable copy under that UID rather than weakening production peer checks.

```sh
python3 -m unittest discover -s tools -p 'test_*.py'
python3 tools/check_public_tree.py
python3 -m unittest discover -s books/tests -p 'test_*.py'
python3 -m unittest discover -s games/save-sync -p 'test_*.py'
python3 -m unittest discover -s games/session-guard -p 'test_*.py'
```

See component docs for any additional tests. Test results cover exported source logic and template invariants, not a fresh installation, real playback, email arrival or physical controller input.

## Publication policy

This is an explicit allowlist export into fresh Git history, not a push of operational directories. Future updates must repeat the staged-blob checks and independently review content; unknown or binary files are blocked by the publication checker. Known live-secret comparisons are done locally without recording secret values in this repository. Use a GitHub noreply commit identity. See [NOTICE.md](NOTICE.md) for licensing boundaries.
