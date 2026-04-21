from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

APP_DIR = Path(os.environ.get('CLIPROXY_APP_DIR', str(Path(__file__).resolve().parent))).expanduser().resolve()
STATIC_DIR = APP_DIR / 'static'
CONFIG_PATH = Path(os.environ.get('CLIPROXY_CONFIG_PATH', str(APP_DIR / 'web_config.json'))).expanduser()
CLEANER_LOG_PATH = Path(os.environ.get('CLIPROXY_CLEANER_LOG_PATH', '/root/CLIProxyAPI-cleaner.log')).expanduser()
WEB_LOG_PATH = Path(os.environ.get('CLIPROXY_WEB_LOG_PATH', str(APP_DIR / 'web.log'))).expanduser()
REPORT_DIR = Path(
    os.environ.get('CLIPROXY_REPORT_ROOT')
    or os.environ.get('CLIPROXY_REPORT_DIR')
    or str(APP_DIR / 'reports' / 'cliproxyapi-auth-cleaner')
).expanduser()
CLEANER_SERVICE = 'CLIProxyAPI-cleaner.service'
WEB_SERVICE = 'CLIProxyAPI-cleaner-web.service'
CONTROL_MODE = os.environ.get('CLIPROXY_CONTROL_MODE', 'systemctl').strip().lower() or 'systemctl'
SUPERVISORCTL_BIN = os.environ.get('CLIPROXY_SUPERVISORCTL_BIN', 'supervisorctl').strip() or 'supervisorctl'
SUPERVISORCTL_CONFIG = os.environ.get('CLIPROXY_SUPERVISORCTL_CONFIG', '').strip()
SUPERVISOR_CLEANER_NAME = os.environ.get('CLIPROXY_SUPERVISOR_CLEANER_NAME', 'cleaner').strip() or 'cleaner'
SUPERVISOR_WEB_NAME = os.environ.get('CLIPROXY_SUPERVISOR_WEB_NAME', 'web').strip() or 'web'
COOKIE_NAME = 'pcw_session'
COOKIE_PATH = '/CLIProxyAPI-cleaner/'

PASSWORD_PBKDF2_ITERATIONS = 260000

DEFAULT_CONFIG = {
    'listen_host': '127.0.0.1',
    'listen_port': 28717,
    'allowed_hosts': ['example.com', '127.0.0.1', 'localhost'],
    'cleaner_path': '/root/CLIProxyAPI-cleaner.py',
    'state_file': '/root/CLIProxyAPI-cleaner-state.json',
    'base_url': 'https://example.com/management.html',
    'management_key': 'replace-me',
    'interval': 60,
    'enable_api_call_check': True,
    'api_call_url': 'https://chatgpt.com/backend-api/wham/usage',
    'api_call_method': 'GET',
    'api_call_account_id': '',
    'api_call_user_agent': 'Mozilla/5.0 CLIProxyAPI-cleaner/1.0',
    'api_call_body': '',
    'api_call_providers': 'codex,openai,chatgpt',
    'api_call_max_per_run': 50,
    'api_call_sleep_min': 5.0,
    'api_call_sleep_max': 10.0,
    'revival_wait_days': 7,
    'revival_probe_interval_hours': 12,
    'retention_keep_reports': 200,
    'retention_report_max_age_days': 7,
    'retention_backup_max_age_days': 14,
    'retention_log_max_size_mb': 50,
    'password_salt': '',
    'password_hash': '',
}

BOOL_FIELDS = {'enable_api_call_check'}
INT_FIELDS = {
    'interval': (10, 604800),
    'api_call_max_per_run': (1, 50),
    'revival_wait_days': (0, 365),
    'revival_probe_interval_hours': (1, 168),
    'retention_keep_reports': (1, 5000),
    'retention_report_max_age_days': (0, 3650),
    'retention_backup_max_age_days': (0, 3650),
    'retention_log_max_size_mb': (1, 1024),
}
FLOAT_FIELDS = {
    'api_call_sleep_min': (0.0, 3600.0),
    'api_call_sleep_max': (0.0, 3600.0),
}
ALLOWED_METHODS = {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'}
_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_HEX_RE = re.compile(r'^[0-9a-f]+$', re.I)


def ensure_app_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEB_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    CLEANER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def deep_copy_default_config() -> dict:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def load_config() -> dict:
    ensure_app_dirs()
    config = deep_copy_default_config()
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        except Exception:
            raw = {}
        if isinstance(raw, dict):
            config.update(raw)
    if 'cleaner_path' not in config:
        if config.get('cpa_cleaner_path'):
            config['cleaner_path'] = config.get('cpa_cleaner_path')
        elif config.get('proxy_cleaner_path'):
            config['cleaner_path'] = config.get('proxy_cleaner_path')
    config.pop('cpa_cleaner_path', None)
    config.pop('proxy_cleaner_path', None)
    config['allowed_hosts'] = normalize_allowed_hosts(config.get('allowed_hosts'))
    return config


def save_config(config: dict) -> None:
    ensure_app_dirs()
    config = dict(config)
    config.pop('cpa_cleaner_path', None)
    config.pop('proxy_cleaner_path', None)
    config['allowed_hosts'] = normalize_allowed_hosts(config.get('allowed_hosts'))
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(CONFIG_PATH)


def normalize_allowed_hosts(value) -> list[str]:
    hosts = []
    raw_values = value if isinstance(value, list) else DEFAULT_CONFIG['allowed_hosts']
    for item in raw_values:
        host = str(item or '').strip().lower()
        if host and host not in hosts:
            hosts.append(host)
    return hosts or list(DEFAULT_CONFIG['allowed_hosts'])


def mask_secret(value: str, keep: int = 4) -> str:
    text = str(value or '')
    if len(text) <= keep * 2:
        return '*' * len(text)
    return text[:keep] + '*' * (len(text) - keep * 2) + text[-keep:]


def hash_console_password(password: str) -> tuple[str, str]:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), PASSWORD_PBKDF2_ITERATIONS)
    return salt, digest.hex()


def is_console_password_configured(config: dict) -> bool:
    salt = str(config.get('password_salt', '') or '').strip()
    digest = str(config.get('password_hash', '') or '').strip()
    return len(salt) == 32 and len(digest) == 64 and bool(_HEX_RE.fullmatch(salt)) and bool(_HEX_RE.fullmatch(digest))


def build_supervisorctl_command(*args: str) -> list[str]:
    cmd = [SUPERVISORCTL_BIN]
    config_path = SUPERVISORCTL_CONFIG
    if not config_path and CONTROL_MODE == 'supervisor':
        bundled_config = APP_DIR / 'docker' / 'supervisord.conf'
        if bundled_config.exists():
            config_path = str(bundled_config)
    if config_path:
        cmd.extend(['-c', config_path])
    cmd.extend(args)
    return cmd


def sanitize_config_for_ui(config: dict) -> dict:
    return {
        'base_url': config.get('base_url', ''),
        'interval': config.get('interval', 60),
        'enable_api_call_check': bool(config.get('enable_api_call_check', True)),
        'api_call_url': config.get('api_call_url', ''),
        'api_call_method': config.get('api_call_method', 'GET'),
        'api_call_account_id': config.get('api_call_account_id', ''),
        'api_call_user_agent': config.get('api_call_user_agent', ''),
        'api_call_body': config.get('api_call_body', ''),
        'api_call_providers': config.get('api_call_providers', ''),
        'api_call_max_per_run': config.get('api_call_max_per_run', 50),
        'api_call_sleep_min': config.get('api_call_sleep_min', 5.0),
        'api_call_sleep_max': config.get('api_call_sleep_max', 10.0),
        'revival_wait_days': config.get('revival_wait_days', 7),
        'revival_probe_interval_hours': config.get('revival_probe_interval_hours', 12),
        'retention_keep_reports': config.get('retention_keep_reports', 200),
        'retention_report_max_age_days': config.get('retention_report_max_age_days', 7),
        'retention_backup_max_age_days': config.get('retention_backup_max_age_days', 14),
        'retention_log_max_size_mb': config.get('retention_log_max_size_mb', 50),
        'management_key_masked': mask_secret(config.get('management_key', '')),
        'management_key_configured': bool(str(config.get('management_key', '')).strip()),
        'console_password_configured': is_console_password_configured(config),
    }


def normalize_base_url(url: str) -> str:
    text = str(url or '').strip()
    if not text:
        raise ValueError('地址不能为空')
    parsed = urlparse(text)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('地址必须是合法的 http/https URL')
    return text.rstrip('/')


def sanitize_plain_text(name: str, value: str, max_len: int, *, allow_newlines: bool = False) -> str:
    text = str(value or '')
    if not allow_newlines:
        text = text.strip()
    if len(text) > max_len:
        raise ValueError(f'{name} 过长')
    if _CONTROL_CHARS.search(text):
        raise ValueError(f'{name} 含有非法控制字符')
    return text


def validate_and_merge_config(existing: dict, incoming: dict) -> dict:
    if not isinstance(incoming, dict):
        raise ValueError('请求体必须是 JSON 对象')
    cfg = dict(existing)

    for key in BOOL_FIELDS:
        if key in incoming:
            cfg[key] = bool(incoming[key])

    for key, (min_value, max_value) in INT_FIELDS.items():
        if key in incoming:
            try:
                value = int(incoming[key])
            except Exception:
                raise ValueError(f'{key} 必须是整数')
            if value < min_value or value > max_value:
                raise ValueError(f'{key} 超出允许范围')
            cfg[key] = value

    for key, (min_value, max_value) in FLOAT_FIELDS.items():
        if key in incoming:
            try:
                value = float(incoming[key])
            except Exception:
                raise ValueError(f'{key} 必须是数字')
            if value < min_value or value > max_value:
                raise ValueError(f'{key} 超出允许范围')
            cfg[key] = value

    if cfg.get('api_call_sleep_max', 0.0) < cfg.get('api_call_sleep_min', 0.0):
        raise ValueError('api_call_sleep_max 不能小于 api_call_sleep_min')

    if 'base_url' in incoming:
        cfg['base_url'] = normalize_base_url(incoming.get('base_url'))
    if 'api_call_url' in incoming:
        cfg['api_call_url'] = normalize_base_url(incoming.get('api_call_url'))

    if 'management_key' in incoming:
        value = sanitize_plain_text('management_key', incoming.get('management_key'), 512)
        if value.strip():
            cfg['management_key'] = value.strip()

    if 'console_password' in incoming:
        value = sanitize_plain_text('console_password', incoming.get('console_password'), 256)
        if value.strip():
            if len(value.strip()) < 8:
                raise ValueError('console_password 至少 8 位')
            salt, digest = hash_console_password(value.strip())
            cfg['password_salt'] = salt
            cfg['password_hash'] = digest

    if 'api_call_method' in incoming:
        method = sanitize_plain_text('api_call_method', incoming.get('api_call_method'), 16).upper()
        if method not in ALLOWED_METHODS:
            raise ValueError('api_call_method 不支持')
        cfg['api_call_method'] = method

    if 'api_call_account_id' in incoming:
        cfg['api_call_account_id'] = sanitize_plain_text('api_call_account_id', incoming.get('api_call_account_id'), 256)
    if 'api_call_user_agent' in incoming:
        cfg['api_call_user_agent'] = sanitize_plain_text('api_call_user_agent', incoming.get('api_call_user_agent'), 512)
    if 'api_call_providers' in incoming:
        cfg['api_call_providers'] = sanitize_plain_text('api_call_providers', incoming.get('api_call_providers'), 256)
    if 'api_call_body' in incoming:
        cfg['api_call_body'] = sanitize_plain_text('api_call_body', incoming.get('api_call_body'), 10000, allow_newlines=True)

    return cfg


def build_cleaner_command(config: dict, *, once: bool = False, dry_run: bool = False) -> list[str]:
    cmd = [
        sys.executable,
        str(config['cleaner_path']),
        '--base-url', str(config['base_url']),
        '--management-key', str(config['management_key']),
        '--interval', str(int(config['interval'])),
        '--state-file', str(config['state_file']),
        '--api-call-url', str(config['api_call_url']),
        '--api-call-method', str(config['api_call_method']).upper(),
        '--api-call-account-id', str(config.get('api_call_account_id', '')),
        '--api-call-user-agent', str(config.get('api_call_user_agent', '')),
        '--api-call-providers', str(config.get('api_call_providers', '')),
        '--api-call-max-per-run', str(int(config['api_call_max_per_run'])),
        '--api-call-sleep-min', str(float(config['api_call_sleep_min'])),
        '--api-call-sleep-max', str(float(config['api_call_sleep_max'])),
        '--revival-wait-days', str(int(config['revival_wait_days'])),
        '--revival-probe-interval-hours', str(int(config['revival_probe_interval_hours'])),
    ]
    cmd.append('--enable-api-call-check' if config.get('enable_api_call_check', True) else '--disable-api-call-check')
    if str(config.get('api_call_body', '')).strip():
        cmd.extend(['--api-call-body', str(config.get('api_call_body', ''))])
    if once:
        cmd.append('--once')
    if dry_run:
        cmd.append('--dry-run')
    return cmd
