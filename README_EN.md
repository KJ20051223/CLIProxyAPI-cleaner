# CLIProxyAPI-cleaner

[中文](README.md) | English

`CLIProxyAPI-cleaner` is an all-in-one project that includes both a **cleanup script** and a **web dashboard** for managing CLIProxyAPI / auth-file account states.

The repository homepage defaults to Chinese. If you prefer Chinese, use the link above to switch back.

## What is included

- `CLIProxyAPI-cleaner.py`: the main cleanup script for detection, disable, delete, refresh, and revival probing
- `app.py`: lightweight web backend for login, status, config save, systemd control, and report viewing
- `common.py`: shared config loading, validation, and command building
- `run_cleaner.py`: launches the cleaner using the current `web_config.json`
- `CLIProxyAPI-cleaner.service`: background cleaner service
- `CLIProxyAPI-cleaner-web.service`: web console service
- `static/`: frontend files
- `web_config.example.json`: public example config

## Features

- Config editing and saving
- Start / stop / restart cleaner
- Restart web backend
- One-click dry-run
- Cleaner / web log viewing
- Recent report summaries
- Rate-limited login, host allowlist, secure cookie settings

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

### 5. Install systemd units

```bash
cp CLIProxyAPI-cleaner.service /etc/systemd/system/CLIProxyAPI-cleaner.service
cp CLIProxyAPI-cleaner-web.service /etc/systemd/system/CLIProxyAPI-cleaner-web.service
systemctl daemon-reload
systemctl enable CLIProxyAPI-cleaner.service CLIProxyAPI-cleaner-web.service
```

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
```

If unit files changed, also run:

```bash
systemctl daemon-reload
```

## Security notes

- Do not expose the dashboard openly without extra protection
- Replace example password values before production use
- Keep `allowed_hosts` strict
- Prefer binding to `127.0.0.1` and exposing only via Nginx

## Acknowledgements

Special thanks to LinuxDo contributor [@jingtai123](https://linux.do/t/topic/1810923). This project is a further derivative / secondary development based on that script direction.

## License

This project is licensed under the **MIT License**. See `LICENSE` for details.
