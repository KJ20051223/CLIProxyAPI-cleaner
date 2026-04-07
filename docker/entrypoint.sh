#!/bin/sh
set -eu

DATA_DIR="${CLIPROXY_DATA_DIR:-/data}"
CONFIG_PATH="${CLIPROXY_CONFIG_PATH:-/data/web_config.json}"
STATE_PATH="${CLIPROXY_STATE_FILE:-/data/CLIProxyAPI-cleaner-state.json}"
BACKUP_ROOT="${CLIPROXY_BACKUP_ROOT:-/data/backups/cliproxyapi-auth-cleaner}"
REPORT_ROOT="${CLIPROXY_REPORT_ROOT:-/data/reports/cliproxyapi-auth-cleaner}"
WEB_LOG_PATH="${CLIPROXY_WEB_LOG_PATH:-/data/logs/web.log}"
CLEANER_LOG_PATH="${CLIPROXY_CLEANER_LOG_PATH:-/data/logs/CLIProxyAPI-cleaner.log}"
mkdir -p "$DATA_DIR" "$(dirname "$CONFIG_PATH")" "$(dirname "$STATE_PATH")" "$BACKUP_ROOT" "$REPORT_ROOT" "$(dirname "$WEB_LOG_PATH")" "$(dirname "$CLEANER_LOG_PATH")"

if [ ! -f "$CONFIG_PATH" ]; then
  python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

src = Path('/app/web_config.example.json')
dst = Path(os.environ.get('CLIPROXY_CONFIG_PATH', '/data/web_config.json'))
cfg = json.loads(src.read_text(encoding='utf-8'))
cfg['listen_host'] = os.environ.get('CLIPROXY_LISTEN_HOST', '0.0.0.0')
try:
    cfg['listen_port'] = int(str(os.environ.get('CLIPROXY_LISTEN_PORT', '28717')).strip() or '28717')
except Exception:
    cfg['listen_port'] = 28717
cfg['cleaner_path'] = os.environ.get('CLIPROXY_CLEANER_PATH', '/app/CLIProxyAPI-cleaner.py')
cfg['state_file'] = os.environ.get('CLIPROXY_STATE_FILE', '/data/CLIProxyAPI-cleaner-state.json')
raw_hosts = os.environ.get('CLIPROXY_ALLOWED_HOSTS', '*')
cfg['allowed_hosts'] = [x.strip() for x in raw_hosts.split(',') if x.strip()] or ['*']
base_url = str(os.environ.get('CLIPROXY_BASE_URL', '')).strip()
if base_url:
    cfg['base_url'] = base_url
management_key = str(os.environ.get('CLIPROXY_MANAGEMENT_KEY', '')).strip()
if management_key:
    cfg['management_key'] = management_key
console_password = str(os.environ.get('CLIPROXY_CONSOLE_PASSWORD', ''))
password_salt = str(os.environ.get('CLIPROXY_PASSWORD_SALT', '')).strip()
password_hash = str(os.environ.get('CLIPROXY_PASSWORD_HASH', '')).strip()
if console_password:
    password_salt = os.urandom(16).hex()
    password_hash = hashlib.pbkdf2_hmac('sha256', console_password.encode('utf-8'), bytes.fromhex(password_salt), 260000).hex()
if password_salt and password_hash:
    cfg['password_salt'] = password_salt
    cfg['password_hash'] = password_hash
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'[docker] created default config at {dst}')
if not base_url or not management_key:
    print('[docker] base_url / management_key still use placeholder values; update web_config.json before running real cleanup')
if not str(cfg.get('password_salt', '')).strip() or not str(cfg.get('password_hash', '')).strip():
    print('[docker] console password is not configured yet; edit web_config.json or provide CLIPROXY_CONSOLE_PASSWORD on first boot')
PY
fi

exec "$@"
