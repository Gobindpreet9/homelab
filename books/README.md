# Books: source-only ebook stack template

Calibre-Web Automated (CWA) provides the library/import workflow; Shelfmark Lite provides search/request and completed-file delivery through an existing Prowlarr/qBittorrent integration. Only use sources and DRM-free books you are authorized to access. Search/request is not future-title monitoring.

**This is a sanitized template, not an installed or verified deployment.** No runtime data, accounts, working keys, mount identity, personal reports or historical live acceptance results are included. See `EXPORT.md` for the explicit allowlist and replacements and `VERIFICATION.md` for export-only evidence. No image is asserted to be the latest; the original version-and-digest pins are preserved unchanged.

## Layout and defaults

| Host location | Purpose |
|---|---|
| `/srv/homelab/books` | Protected deployment project and private `.env` |
| `/srv/homelab/books/config/cwa` | CWA settings, users and application databases; private |
| `/srv/homelab/books/config/shelfmark` | Shelfmark settings and databases; private |
| `/srv/media/Books/Library` | Persistent Calibre library, including `metadata.db` |
| `/srv/media/Books/Ingest` | Disposable completed-file copies, consumed by CWA |
| `/srv/media/Downloads` | Existing client originals; read-only to Shelfmark |
| `/etc/ebooks` | Reviewed, root-owned controller and Compose snapshots |

CWA is bound to `127.0.0.1:8083`; Shelfmark to `127.0.0.1:8084`. Loopback is a host publishing default, not proof of firewall, reverse-proxy, container-network or household access restrictions. No public exposure is configured. Use a separately reviewed authenticated private access path if needed.

UID/GID **1000:1000** are generic defaults, not an exported identity. Timezone defaults to `Etc/UTC`. Review them before deployment: if changing UID/GID, update BOTH Compose services, `prepare()`'s ownership values in the private controller and the bootstrap command below. Only application config subdirectories should be writable by the containers; the project root, `.env`, service and privileged code must not be writable by them or ordinary users. Library/mount permissions require separate operator review.

Shelfmark's `CALIBRE_WEB_URL` is a browser-facing library shortcut to the local CWA UI, not a container-local CWA API address. Change it only to the separately secured browser-visible URL appropriate for your access scope.

## Offline export checks

Existing Python 3.9+ and Docker Compose with JSON config output are needed. Do not install anything merely to inspect this export. Run from the exported directory:

```sh
mkdir -p .cache
TMPDIR="$PWD/.cache" PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -v
```

Repository-root CI can instead run `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s books/tests -v`; the test support initializes its ignored cache and import path automatically.

The tests render the actual Compose template with **synthetic placeholders**, using `--env-file /dev/null`; they never read an operator's `.env`, connect to the Docker daemon, start services, pull images, query sources or send email. Temporary SQLite/credential/EPUB fixtures are confined to `.cache` and cleaned up. Bootstrap hashing is injected in tests; real operation uses the pinned image's Werkzeug implementation. Mock lifecycle tests do not prove runtime or mount behavior. Do not interpret a fixture API string as an actual credential or a fixture indexer label as a selectable indexer.

Never print full resolved Compose JSON or container environments in a configured deployment: those expose API values. `ebookctl.py check` uses quiet validation but first requires the real mount and prepared paths. It is intentionally **not** an export validation command.

## Private preparation (operator action, not performed by this export)

1. Review the images, ports, storage, UID/GID, authorized sources and current upstream behavior. Arrange a separate authorized Docker operator. Do not broaden socket permissions or add a Docker-group grant as a shortcut.
2. Provision a real **exFAT** filesystem at `/srv/media` using your normal reviewed mount configuration. Do not format or change an existing disk as part of these instructions. Determine its real UUID privately; an autofs placeholder is insufficient. Arrange a genuine systemd mount unit `srv-media.mount` for boot/loss binding. If using a different mount or filesystem, review controller and unit changes together and retest rather than weakening the guard.
3. Install reviewed copies of `ebookctl.py`, `compose.yml`, `bootstrap_admin.py` and `smoke_epub.py` under `/srv/homelab/books`, with a root-owned non-writable project root. Keep deployment edits outside the public checkout. Create a root-owned mode-0600 `/srv/homelab/books/.env` using `.env.example` as a schema. Enter credentials locally through a secure prompt/editor; never pass real keys as shell command arguments or paste them into reports.
4. Supply all three required API values: a dedicated Shelfmark automation key, a Prowlarr API key and a qBittorrent API key supported by your existing client. No username/password is exported. The external integration network is explicitly named `homelab_media`, matching the sibling media template; it must already exist and provide DNS names `prowlarr` and `qbittorrent` on the documented ports. Review attached containers and access permissions. The books template does not deploy, configure or create this external network or either dependency.
5. Fill `PROWLARR_INDEXERS` with an explicit selection of authorized ebook-capable source IDs from your own instance. Verify the pinned application's expected list syntax. There are deliberately no exported IDs or all-indexer fallback. Confirm the existing qBittorrent `books` category, `/downloads/books` path mapping and completed-file access. No unrelated categories are managed here.
6. Create protected root-owned snapshots and a private controller configuration:

```sh
sudo install -d -o root -g root -m 0755 /etc/ebooks
sudo install -o root -g root -m 0644 /srv/homelab/books/ebookctl.py /etc/ebooks/ebookctl.py
sudo install -o root -g root -m 0644 /srv/homelab/books/compose.yml /etc/ebooks/compose.yml
sudoedit /etc/ebooks/ebookctl.py
# Replace UUID = 'REPLACE_WITH_MEDIA_UUID' with the real UUID only here.
# Review UID/GID and paths; do not commit the privately configured file.
```

The installed controller reads its adjacent `/etc/ebooks/compose.yml`, but explicitly retains `/srv/homelab/books` as the Compose project directory. Thus relative config binds and private `.env` resolve under that protected project, not `/etc/ebooks`. Keep `.env` and both parent directories protected: root-owned code alone is not enough if root consumes attacker-writable interpolation settings. The public controller refuses the UUID placeholder even if a synthetic mount row matches it.

7. With the real disk mounted, prepare and validate:

```sh
sudo python3 /etc/ebooks/ebookctl.py prepare
# Downloads must already exist as the reviewed download-client directory.
sudo python3 /etc/ebooks/ebookctl.py check
```

`prepare` checks the actual mount **before** creating directories. It only creates the config subdirectories and book library/intake directories. It does not create `Downloads`, format/mount disks or change media mount permissions. The controller rejects symlinked paths and missing required bind directories. Every bind has `create_host_path: false`; this is additional protection, not a replacement for the mount guard.

## First run: CWA alone, then secure shared authentication

These commands are examples for an operator's privately configured deployment. They were not executed against this export. Image pulls and service startup require separate authorization.

```sh
sudo python3 /etc/ebooks/ebookctl.py pull cwa
sudo python3 /etc/ebooks/ebookctl.py up cwa
# Wait for CWA's real /config/app.db initialization.
sudo docker compose --project-name ebooks --project-directory /srv/homelab/books \
  --file /etc/ebooks/compose.yml exec -T --user 1000:1000 cwa \
  /lsiopy/bin/python - < /srv/homelab/books/bootstrap_admin.py
```

Keep CWA local and do not create additional users or change the factory password before this first-run bootstrap. The bootstrap recognizes the fresh `admin` plus the expected anonymous `Guest`, refuses unexpected users/schemas and unsafe/symlinked credentials, replaces the publicly known factory password with a random one, and disables **all** user auto-send flags. It stores the generated login only in `config/cwa/admin-credentials.json` with mode 0600 and container UID/GID ownership. Read it privately through a secure local interface, not chat, terminal logs, screenshots or version control.

A rerun verifies the same saved password and disables auto-send again; it does not rotate an already secured account or accept arbitrary user state. Do not delete the credential file to bypass a refusal. This is not a scheduled boot action and must not run after deliberate email activation without operator review.

Sign in locally to CWA, choose `/calibre-library` as the library, and verify guest/anonymous permissions are appropriate. No personal user, Kindle address, SMTP account or delivery settings are preconfigured.

### Single-file read-only authentication and SQLite journals

Shelfmark receives **only** `config/cwa/app.db` at `/auth/app.db`, read-only; it must not receive the entire CWA config directory or a writable auth mount. Shelfmark browser authentication stays `cwa`, with a separate required automation API key. Verify anonymous APIs are denied and legitimate user/API authentication succeeds on your actual deployment.

`NETWORK_SHARE_MODE=true` is retained as a conservative compatibility/polling setting for this single-file read-only arrangement. A WAL database may depend on sidecar files that this bind intentionally does not expose. This template does not claim that a fresh or migrated database already has compatible journaling. Before starting Shelfmark, stop **all ebook writers** and verify/checkpoint the actual CWA application and library databases, using the following isolated maintenance example. Stop the systemd unit first if already enabled; ensure no other ebook or Calibre process writes these files.

```sh
sudo python3 /etc/ebooks/ebookctl.py down
sudo docker compose --project-name ebooks --project-directory /srv/homelab/books \
  --file /etc/ebooks/compose.yml run --rm --no-deps --pull never \
  --user 1000:1000 --entrypoint /lsiopy/bin/python cwa - <<'PY'
from contextlib import closing
from pathlib import Path
import sqlite3
for name in ('/config/app.db', '/calibre-library/metadata.db'):
    path = Path(name)
    if not path.is_file():
        raise SystemExit('Expected initialized database is missing; stop and inspect.')
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as db:
        checkpoint = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if checkpoint[0] != 0:
            raise SystemExit('Busy database; do not proceed.')
        if db.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower() != 'delete':
            raise SystemExit('Journal policy not applied; do not proceed.')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise SystemExit('Integrity check failed; do not proceed.')
print('Offline database checks passed; runtime shared-auth still needs testing.')
PY
sudo python3 /etc/ebooks/ebookctl.py pull shelfmark
sudo python3 /etc/ebooks/ebookctl.py up
```

This maintenance command reuses the pinned CWA image, not a downloaded utility, and is NOT proof of runtime compatibility. Verify a real read-only SELECT from Shelfmark, login, import/cleanup, journal behavior and restart recovery before calling shared auth accepted. If these fail, stop; do not delete sidecars, widen the bind or reformat/move storage as an unreviewed workaround.

## Mount lifecycle and boot

The guard requires matching target `/srv/media`, type `exfat` and the privately configured UUID, not just directory existence. `check`, `pull` and `up` require it and required paths; `down`/`status` remain available when the disk is absent. Startup uses `--pull never`. Docker restart policies are `no`; the reviewed systemd unit owns boot startup. A partial `up` triggers project-scoped `down` while preserving the original failure, and `ExecStopPost` adds a failed-start cleanup path. Cleanup can itself fail: inspect ebook project state, never global-prune Docker.

After first-run security and import/shared-auth acceptance, install the reviewed unit:

```sh
sudo install -o root -g root -m 0644 systemd/ebooks.service /etc/systemd/system/ebooks.service
sudo systemctl daemon-reload
# Inspect root ownership, modes, installed code and srv-media.mount dependencies first.
sudo systemctl enable --now ebooks.service
```

The unit requires Docker, `RequiresMountsFor=/srv/media/Books`, `After=srv-media.mount`, and `BindsTo=srv-media.mount`. Mount setup is an operator prerequisite, not included disk provisioning. Reinstall root-owned snapshots deliberately after reviewing code changes. Do not run root directly from a user-writable checkout. Test wrong UUID, absent mount and autofs states synthetically and inspect actual dependencies; do not unplug a shared disk as a casual acceptance test. Systemd lifecycle binding cannot guarantee transactional safety against sudden removal.

## Import and no-auto-email policy

- Shelfmark is **folder-only** delivery; CWA is the only potential email sender. Direct-download/Libgen/Newznab/AudiobookBay options remain disabled. Hardlinks are disabled and torrent completion action is `keep`.
- Use a **completed-file copy** into intake; CWA consumes/deletes intake files. Never point intake at a seeding source, incomplete download or persistent library. Copies are required on the exFAT layout; do not assume native-Linux permissions, hardlinks or symlinks.
- From the source checkout, `python3 smoke_epub.py` generates an authored EPUB in `.cache/fixtures` and never enqueues it. Only with explicit integration-test approval, copy that fixture into intake, retaining the original separately. Verify a readable persistent EPUB, metadata/SQLite integrity, intake cleanup, original preservation and restart persistence. Generation alone is not an import test.
- **Auto-email stays disabled.** Bootstrap enforces database flags, but no Compose environment variable guarantees that an operator will never re-enable them. Recheck actual settings and all users after import/restart; do not restore preconfigured sending accounts blindly.
- Later email setup requires a separately chosen provider, secure local credential entry, a private device address and approved sender. Manually send one authorized DRM-free EPUB and confirm it opens on the physical device before enabling auto-send for the intended user. SMTP acceptance is not device-delivery proof. Verify current size limits and failure/manual-resend behavior at that time.
- Keep sends off for bulk imports unless deliberately desired. Before household expansion, test username-specific ingest routing: root-level imports may target every auto-send-enabled user. This export claims no multi-user delivery test.

## Backup, restore, rollback and acceptance

Stop `ebooks.service` (if enabled), stop this Compose project, and confirm all ebook/database writers are gone. Back up both private config directories, private environment/configuration and the **complete** persistent library including databases/sidecars to a protected independent disk. Backups contain authentication material; restrict access and never export them. A copy on the same media disk does not protect against disk failure. Test an isolated restore, SQLite integrity and compatible image versions before calling recovery tested.

Acceptance remains operator work: actual mount and permissions; exact installed pins; container health; real bind addresses; shared authentication and anonymous denial; authorized indexer/client connectivity; completed-copy import and original preservation; no-auto-send flags; stop/start persistence; service dependencies and failure cleanup; and consistent backup/restore. External acquisition and physical-device email delivery, if desired, need separate explicit checks. No historical private-deployment results are inherited by this template.

Rollback stops/disables **only** `ebooks.service` and the `ebooks` Compose project. Retain configs, credentials, library, intake and download originals. Never use `down -v`, delete databases or perform global Docker cleanup. Downgrades require compatible stopped-writer backups; image digest pins do not ensure schema rollback safety.
