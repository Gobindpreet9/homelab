# Media streaming and library stack

Sanitized Compose export of a Jellyfin-based stack: Jellyfin playback, Jellyseerr requests, Radarr/Sonarr organization, Prowlarr indexer integration, qBittorrent downloads, and Bazarr subtitles. Image digests are carried over from the source deployment; they are reproducibility pins, not a promise of current security support. Review upgrades before deployment.

## Boundaries

- All published host ports default to loopback, including torrent incoming ports. Do not expose administration interfaces or create router forwards as a shortcut.
- `LISTEN_ADDRESS` controls only Jellyfin (8096) and Jellyseerr (5055). Set it to a chosen LAN interface if desired; firewall and application authentication remain necessary.
- `TORRENT_BIND_ADDRESS` controls the incoming torrent port, **not** outbound routing. This template does not include the original host's VPN, firewall, or kill-switch policy. Do not start downloads until your own routing/fail-closed controls have been verified. A loopback WebUI is not a VPN boundary.
- NVIDIA device reservation is retained for Jellyfin. Configure NVIDIA Container Toolkit beforehand, or remove that reservation for a software-only host and verify playback.
- No application databases, users, API keys, indexer credentials, watch history, downloads, or media are included.

## Configuration layout and existing deployments

This public export intentionally differs from the original deployment's Jellyfin config root: Jellyfin mounts `./config/jellyfin` at `/config`, not the shared `./config` parent. The other six applications keep their own sibling directories, so Jellyfin cannot access their configuration through its config mount.

For a fresh deployment, create separate owner-writable directories `config/jellyfin`, `config/qbittorrent`, `config/radarr`, `config/sonarr`, `config/prowlarr`, `config/jellyseerr`, and `config/bazarr`, plus Jellyfin's separate `cache/` directory.

Existing operators must stop the affected services and take verified private backups before changing paths. Plan and perform the migration privately: migrate only Jellyfin's own files and directories from the old config root into `config/jellyfin`, preserving their relative layout and required ownership. Do not copy the entire old `config/` tree or any sibling application directories into Jellyfin's new directory; leave those applications' configuration separate. Verify the migrated Jellyfin state and each service's bind source before restarting. This export does not migrate or modify any live setup.

## Prepare and validate

Use only content you are authorized to obtain and redistribute. Set up Docker Engine and Compose separately. Review the template first; running it downloads pinned container images.

1. Copy `.env.example` to `.env`, set your UID/GID, storage paths and intended bindings.
2. Create `Movies` and `Series` under `MEDIA_ROOT`, and `incomplete`, `movies`, `tv`, and `books` under `DOWNLOAD_ROOT`. Confirm the actual disk is mounted and writable before startup. Compose short-form binds can otherwise create directories on the wrong disk; this media template does not ship a mount-guard controller.
3. Create owner-writable service config directories under `config/` and Jellyfin `cache/`. Back these up privately, never into Git.
4. Validate configuration without starting services:

   ```sh
   docker compose --env-file .env config --quiet
   ```

5. After reviewing VPN/firewall and storage safety, deploy deliberately:

   ```sh
   docker compose --env-file .env up -d
   docker compose ps
   ```

## First-run service wiring

Create unique credentials in every application. qBittorrent may log a temporary initial password; replace it immediately and never post those logs publicly.

| Connection | Internal endpoint |
| --- | --- |
| Radarr/Sonarr → qBittorrent | `http://qbittorrent:18080` |
| Prowlarr → Radarr | `http://radarr:7878` |
| Prowlarr → Sonarr | `http://sonarr:8989` |
| Jellyseerr → Jellyfin | `http://jellyfin:8096` |
| Jellyseerr/Bazarr → Radarr/Sonarr | `http://radarr:7878`, `http://sonarr:8989` |

Use application settings to transfer your own API keys locally. Use `/media/movies` and `/media/shows` for media roots, `/downloads` for completed downloads, and `/downloads/incomplete` for unfinished files. Categories `movies`, `tv`, and `books` should target the corresponding `/downloads/<category>` directory. The books stack joins the explicitly named `homelab_media` network; start this project first. The supplied examples share `/srv/media/Downloads` between qBittorrent and Shelfmark: if changing `DOWNLOAD_ROOT`, also adapt the books Compose bind and mount/controller checks so both applications see the same completed files.

On filesystems without hardlinks, configure copy-based imports and budget disk space accordingly. Do not mix partial downloads with libraries. Restrict non-admin users and request permissions deliberately.

## Verify your deployment

Check intended listeners, authentication, actual mounts, and GPU transcoding with your own licensed sample. Verify a request/import/playback/subtitle flow. Configuration validation and unit tests do not prove playback or network isolation. No remote access proxy or router configuration is shipped. If using a private overlay network, scope its ACLs to required service ports; do not grant all ports by default.

For shutdown use `docker compose down` without `--volumes`; keep config and media backups. Never publish diagnostic logs without reviewing them for credentials and media/user metadata.
