# CLIProxyAPI-cleaner

[中文](README.md) | English

`CLIProxyAPI-cleaner` is an all-in-one project that includes both a **cleanup script** and a **web dashboard** for managing CLIProxyAPI / auth-file account states.

The repository homepage defaults to Chinese. If you prefer Chinese, use the link above to switch back.

## What is included

- `CLIProxyAPI-cleaner.py`: the main cleanup script for detection, disable, delete, refresh, and revival probing
- `app.py`: lightweight web backend for login, status, config save, systemd control, and report viewing
- `common.py`: shared config loading, validation, and command building
- `run_cleaner.py`: launches the cleaner using the current `web_config.json`
- `cleanup_retention.py`: standalone retention cleanup for old reports/backups and oversized logs
- `run_retention.sh`: reads retention settings from `web_config.json` and launches retention cleanup
- `manager.sh`: interactive install / uninstall helper for systemd + bare-metal deployments
- `CLIProxyAPI-cleaner.service`: background cleaner service
- `CLIProxyAPI-cleaner-web.service`: web console service
- `CLIProxyAPI-cleaner-retention.service` / `.timer`: periodic artifact cleanup service and timer
- `static/`: frontend files
- `web_config.example.json`: public example config

## Features

- Config editing and saving
- Start / stop / restart cleaner
- Restart web backend
- One-click dry-run
- Cleaner / web log viewing
- Recent report summaries
- Periodic cleanup for old reports/backups plus automatic log trimming
- Rate-limited login, host allowlist, secure cookie settings
- Docker / Docker Compose deployment support

## Notes on examples

In this repository, account-related examples and detection descriptions are written with **codex** as the default example. The overall handling idea is similar for other compatible providers.

## Requirements

- Linux
- Python 3.10+
- systemd
- Nginx (recommended)
- Network access to your upstream API and management endpoint

## Deployment (Detailed)

### 1. Get the code

```bash
git clone https://github.com/KJ20051223/CLIProxyAPI-cleaner.git
cd CLIProxyAPI-cleaner
```

### 2. Prepare the install directory

```bash
mkdir -p /opt/CLIProxyAPI-cleaner
cp -r ./* /opt/CLIProxyAPI-cleaner/
cd /opt/CLIProxyAPI-cleaner
```

### 3. Generate a console password hash

```bash
python3 - <<'PY'
import os, hashlib
password = 'change-me-now'
salt = os.urandom(16).hex()
digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000).hex()
print('password_salt =', salt)
print('password_hash =', digest)
PY
```

### 4. Create `web_config.json`

```bash
cp web_config.example.json web_config.json
```

Edit it for your environment, especially:

- `cleaner_path`
- `state_file`
- `base_url`
- `management_key`
- `allowed_hosts`
- `password_salt` / `password_hash`

### 5. Install systemd services and the retention timer

```bash
cp CLIProxyAPI-cleaner.service /etc/systemd/system/CLIProxyAPI-cleaner.service
cp CLIProxyAPI-cleaner-web.service /etc/systemd/system/CLIProxyAPI-cleaner-web.service
cp CLIProxyAPI-cleaner-retention.service /etc/systemd/system/CLIProxyAPI-cleaner-retention.service
cp CLIProxyAPI-cleaner-retention.timer /etc/systemd/system/CLIProxyAPI-cleaner-retention.timer
systemctl daemon-reload
systemctl enable CLIProxyAPI-cleaner.service CLIProxyAPI-cleaner-web.service
systemctl enable --now CLIProxyAPI-cleaner-retention.timer
```

Default retention policy:

- Reports: keep the latest `200`, and also delete anything older than `7` days
- Backups: delete anything older than `14` days and remove empty directories
- Logs: trim `/root/CLIProxyAPI-cleaner.log` and `web.log` back to the latest `50MB` when they grow too large

These values can now be changed directly in the **Web console**. After saving, the next retention timer run automatically uses the new settings.

If you want to edit the config file manually, the fields are:

- `retention_keep_reports`
- `retention_report_max_age_days`
- `retention_backup_max_age_days`
- `retention_log_max_size_mb`

### 6. Configure Nginx

Example for `https://your-domain.com/CLIProxyAPI-cleaner/`:

```nginx
location ^~ /CLIProxyAPI-cleaner/ {
    proxy_pass http://127.0.0.1:28717;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;

    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy same-origin always;
    add_header Content-Security-Policy "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
}
```

Then reload Nginx:

```bash
nginx -t && systemctl reload nginx
```

### 7. Start services

```bash
systemctl restart CLIProxyAPI-cleaner-web.service
systemctl restart CLIProxyAPI-cleaner.service
```

### 8. Verify status

```bash
systemctl status CLIProxyAPI-cleaner-web.service --no-pager
systemctl status CLIProxyAPI-cleaner.service --no-pager
systemctl status CLIProxyAPI-cleaner-retention.timer --no-pager
```

Logs:

```bash
tail -f /opt/CLIProxyAPI-cleaner/web.log
tail -f /root/CLIProxyAPI-cleaner.log
```

### 9. Open the dashboard

```text
https://your-domain.com/CLIProxyAPI-cleaner/
```

### 10. Upgrade later

```bash
cd /opt/CLIProxyAPI-cleaner
git pull
systemctl restart CLIProxyAPI-cleaner-web.service
systemctl restart CLIProxyAPI-cleaner.service
systemctl restart CLIProxyAPI-cleaner-retention.timer
```

If unit files changed, also run:

```bash
systemctl daemon-reload
```

## Docker / Docker Compose deployment

If you do not want to manage systemd manually, the repository now includes a ready-to-run Docker setup:

- `Dockerfile`
- `docker-compose.yml`
- `docker/supervisord.conf`
- `docker/entrypoint.sh`
- `docker/run_cleaner.sh`
- `.github/workflows/docker-publish.yml` (auto-publishes Docker Hub images after GitHub pushes)

In Docker mode:

- **web and cleaner run in the same container**
- **supervisor** manages both processes
- dashboard start / stop / restart actions automatically use `supervisorctl` instead of `systemctl`
- config, logs, reports, and backups are persisted under `./docker-data`

### Quick start (Docker Hub image)

```bash
git clone https://github.com/KJ20051223/CLIProxyAPI-cleaner.git
cd CLIProxyAPI-cleaner
docker compose pull && docker compose up -d
```

Default image:

```text
docker.io/kxmjj/cliproxyapi-cleaner:latest
```

If you want to use your own image instead:

```bash
export CLIPROXY_IMAGE=docker.io/your-dockerhub-user/cliproxyapi-cleaner:latest
```

On first boot, `./docker-data/web_config.json` will be created automatically. Update these values:

- `base_url`
- `management_key`
- `allowed_hosts`
- `password_salt`
- `password_hash`

If you want to prefill them on the **first boot**, uncomment these optional environment variables in `docker-compose.yml`:

- `CLIPROXY_BASE_URL`
- `CLIPROXY_MANAGEMENT_KEY`
- `CLIPROXY_CONSOLE_PASSWORD`

Access URL:

```text
http://your-server-ip:28717/CLIProxyAPI-cleaner/
```

Common commands:

```bash
docker compose pull && docker compose up -d
docker compose logs -f
docker compose down
```

### Default data directory

Compose persists these files into `./docker-data`:

- `web_config.json`
- `logs/`
- `reports/`
- `backups/`
- `CLIProxyAPI-cleaner-state.json`

### Notes for Docker mode

1. For plain local HTTP access, `docker-compose.yml` defaults to `CLIPROXY_COOKIE_SECURE=false`, otherwise the login cookie would not work on non-HTTPS connections.
2. If you put it behind HTTPS, you should change it back to:

```yaml
CLIPROXY_COOKIE_SECURE: "true"
```

3. `CLIPROXY_ALLOWED_HOSTS` defaults to `*` for easier first boot; for real deployment, tighten it to your own hostnames or IPs.
4. The cleaner process checks whether `web_config.json` already contains real `base_url / management_key` values. If the config is still placeholder-only, it waits instead of running cleanup logic.
5. In Docker mode, the dashboard now calls `supervisorctl` with `/app/docker/supervisord.conf` explicitly, so it will not fall back to `/var/run/supervisor.sock`.
6. If `password_salt / password_hash` are still unset, the login API now returns a clear configuration error instead of crashing with HTTP 500.
7. `cleanup_retention.py` is also included in the image. For Docker deployments, add a host cron/timer or run it manually if you also want periodic report/backup/log retention cleanup.
8. `run_retention.sh` reads retention settings from `web_config.json`, so changes saved from the Web console will be picked up automatically on the next scheduled retention run.
9. `./docker-data/reports` and `./docker-data/backups` are runtime artifacts; do not commit them back into the repository.

## manager.sh (interactive installer)

If you want a faster **systemd + bare-metal** install path, the repository now includes a safer `manager.sh`:

```bash
chmod +x manager.sh
sudo ./manager.sh install
```

It will:

- copy the current workspace into `/opt/CLIProxyAPI-cleaner`
- ask for `base_url`, `management_key`, and dashboard password
- let you choose between **reverse-proxy / HTTPS** mode and **LAN / direct HTTP** mode
- generate `web_config.json`
- write `CLIPROXY_COOKIE_SECURE=true/false` via a systemd override instead of patching source code
- install and start cleaner / web / retention timer

So unlike PR #2, it does **not** `sed`-patch `app.py`, which keeps upgrades and diffs clean.

Uninstall:

```bash
sudo ./manager.sh uninstall
```

## Security notes

- Do not expose the dashboard openly without extra protection
- Replace example password values before production use
- Keep `allowed_hosts` strict
- Prefer binding to `127.0.0.1` and exposing only via Nginx

## How to adapt other auth file formats / providers

The current repository provides its most complete implementation **with codex auth files as the main example**, especially for the “quota exhausted -> refresh -> revival probe” flow. That flow currently assumes:

- the local auth file is a JSON object
- a `refresh_token` is available
- refresh logic is compatible with the OpenAI-family token endpoint
- a new `access_token` can be written back after refresh
- a follow-up probe can be executed through the configured `api_call_url`

If you want to support **other auth file formats** or providers, the main adaptation points are:

### 1. Classification rules

Check `classify()` and `classify_api_call_response()`.
You need to decide:

- which errors mean 401 / invalid auth
- which errors mean quota exhaustion / rate limit / billing issue
- which states should stay recoverable instead of being deleted

### 2. Account ID and request header extraction

Check `choose_account_id()` and `direct_probe_auth()`.
If your provider does not use `Chatgpt-Account-Id`, you should adapt the required headers and account identity extraction here.

### 3. Auth file read / write format

Check `load_auth_payload_from_path()` and `write_auth_payload()`.
If your auth file is not the current JSON structure, this layer must be adapted first.

### 4. Refresh logic

Check `refresh_openai_family_tokens()`.
This is not a universal refresh layer; it is the current provider-specific implementation.
For another provider, you will usually need to replace:

- token endpoint
- request parameters
- response parsing
- token write-back format

### 5. Revival support scope

Check `run_revival_cycle()`.
Right now revival is only enabled for `codex`, `openai`, and `chatgpt`.
To support another provider, you need to:

- add that provider to the supported list
- ensure a valid local auth file path exists
- make sure refresh / probe logic is already adapted

### 6. Partial support is also fine

For some providers, you may only be able to support:

- availability detection
- 401 detection
- quota detection

and not token refresh. That is still fine. In that case, you can keep revival in a reduced mode, such as:

- disable first
- probe later
- skip refresh entirely
- or disable revival for that provider

### 7. Practical adaptation order

A stable way to adapt a new provider is:

1. make `classify()` correct
2. make `/api-call` probing work
3. adapt auth-file reading
4. then add refresh + revival

In short:

> this repository is not limited to codex only, but the most complete built-in implementation is currently written with codex auth files as the main example.
> For other auth file formats, the main adaptation layers are **classification, headers, file structure, refresh, and revival**.

## Acknowledgements

Thanks to the **LinuxDo community** for the discussion space, and special thanks to LinuxDo contributor [@jingtai123](https://linux.do/t/topic/1810923). This project is a further derivative / secondary development based on that script direction.

## License

This project is licensed under the **MIT License**. See `LICENSE` for details.
