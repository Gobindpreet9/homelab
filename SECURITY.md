# Security and publication boundaries

## Credentials and privacy

Keep credentials in local owner-readable configuration or a secret manager. `.env.example` contains only non-secret examples or empty fields. Real `.env`, databases, keys, certificates, pairings, client IDs, reports, captures, saves, game prefixes and libraries do not belong in Git, even in a private repository. Private operational workspaces remain separate.

Before every commit run `python3 tools/check_public_tree.py` against the staged index. It rejects disallowed paths/types, symlinks, common credential formats and private network identities. It is a deliberately limited additional check, **not** a comprehensive secret scanner or guarantee. Review the staged diff and do not use broad copies or `git add -f` on runtime directories. Never upload private scanner reports containing matched values.

If a secret is ever committed, revoke/rotate it before history cleanup; deleting the latest file is insufficient. Do not put the exposed value in a public issue.

## Deployment trust

- Default service bindings are local-only where practical. LAN bindings, firewall rules, private-overlay ACLs and authentication are independent controls.
- Wolf intentionally needs device and Docker-socket access. Treat it and its per-session broker as privileged; never make the management socket reachable over the network. Root-owned code/configuration and peer/cgroup verification are part of its trust boundary.
- Separate local and remote game copies. Both launch paths must use the same save lock; retain conflict backups. Tests do not prove real game shutdown or controller input.
- Pinning images does not make them secure indefinitely. Review upstream advisories and upgrades; templates are not an attestation of current CVE status.
- Do not disconnect a VPN or weaken its kill switch as a routine connectivity workaround. The original host's private routing is intentionally not published.
- Do not enable automatic book email/delivery until authorized-recipient settings and a real licensed sample have been verified. SMTP success alone is not proof of arrival.
- Logs can contain passwords, URL query tokens, user identities and titles. Sanitize before sharing.

These templates are not hardened turnkey products. Review permissions, routes, mounts and backups for your own host before deployment. For reports, share a minimal reproduction with synthetic identities, never credentials.
