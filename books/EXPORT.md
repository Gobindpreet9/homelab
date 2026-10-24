# Public export boundary

This directory is a **source-only, sanitized template**. The following 15 relative paths are the complete public allowlist; copying the original project recursively is not an acceptable way to refresh it.

```text
.env.example
.gitignore
EXPORT.md
README.md
VERIFICATION.md
bootstrap_admin.py
compose.yml
ebookctl.py
smoke_epub.py
systemd/ebooks.service
tests/compose_fixture.py
tests/test_deployment_security.py
tests/test_ebooks.py
tests/test_public_template.py
tests/test_startup_cleanup.py
```

The Python source, original regression tests, image-pinned Compose and service unit were exported selectively. README/verification/export documentation and the environment schema were authored for this public template; historical private plans, deployment reports, research caches and agent logs were not copied. Names such as `admin`, `Guest`, the publicly known factory-password check and the authored EPUB's generic test author are upstream/test fixtures, not personal accounts or working credentials.

## Excluded without exception

- Real `.env` files; app `config/`; private runtime settings and credentials.
- SQLite/databases, WAL/SHM/journal files, user lists and authentication tokens.
- Generated EPUBs, acquired books, download files and other binary assets.
- Logs, caches, backups, credential snapshots, personal reports and screenshots.
- Deployment state, Git metadata, image layers, installed service copies and host mount configuration.

`.gitignore` is a secondary accident-prevention measure, not an export policy or a secret scanner. Review the actual allowlist again before publication. Test-created ephemeral fixtures remain ignored and are not exported.

## Replacements and retained behavior

| Original deployment-specific value | Public representation |
|---|---|
| Personal home/workspace paths | `/srv/homelab/books` |
| Private disk mount and label in operational messages | `/srv/media` and generic media wording |
| Disk mount unit | `srv-media.mount` |
| Actual filesystem UUID | Refusing `REPLACE_WITH_MEDIA_UUID` controller placeholder; `TEST-MEDIA-UUID` only in synthetic tests |
| Machine timezone | Generic `Etc/UTC` default |
| Original shared media network | Explicit external `homelab_media`, matching the sibling media template |
| Selected deployment indexer IDs | Required `${PROWLARR_INDEXERS:?...}` reference and an explicit example placeholder |
| Working API keys | Required environment references; only blank example values |
| Live verification claims and user decisions | Export-only evidence and generic operator acceptance checklist |

Image tags **and** SHA-256 digests are unchanged. Loopback publishing, separate Compose project, read-only download/auth binds, copy-based handoff, disabled optional sources, folder-only Shelfmark delivery, conservative shared-auth mode, no restart policy, failed-start cleanup and secure first-run/no-auto-send bootstrap remain intact.

The controller intentionally uses fixed generic project/mount paths rather than accepting arbitrary runtime paths in a privileged service. The UUID must be configured only in a protected private installation. In addition to sanitization, this export adds refusal of an unconfigured UUID and converts malformed `findmnt` JSON into a controlled mount rejection; regression tests cover both. Existing tests were made portable to root-level discovery and to synthetic Compose values without consulting a real `.env`.

## Security review method and limits

Export review scans all allowlisted text for personal paths/identifiers, private IPv4 addresses, email identities, real filesystem identity, deployment indexer selections, token/private-key patterns and exact matches against private credential inputs **in memory**, without printing values. SHA-256 image references and the authored EPUB's non-filesystem UUID are expected non-secret literals. The default `admin123` string is only the public factory-password recognition/test case; bootstrap replaces it and never emits the generated password.

A clean scan is not a mathematical guarantee of no sensitive information. The allowlist, readable source review, placeholder-only environment and absence of runtime data are independent safeguards. This export performed no image pull, install/download, container lifecycle change, deployment edit, Git mutation or publication. Runtime acceptance, secure operator configuration and any future publication review remain separate tasks.
