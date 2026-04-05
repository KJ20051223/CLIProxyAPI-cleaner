#!/bin/sh
set -eu

WORK_DIR="${CLIPROXY_RETENTION_WORKDIR:-/opt/CLIProxyAPI-cleaner}"
CONFIG_PATH="${CLIPROXY_CONFIG_PATH:-$WORK_DIR/web_config.json}"
SCRIPT_PATH="${CLIPROXY_RETENTION_SCRIPT:-$WORK_DIR/cleanup_retention.py}"
LOCK_PATH="${CLIPROXY_RETENTION_LOCK:-/tmp/CLIProxyAPI-cleaner-retention.lock}"

KEEP_REPORTS="${CLIPROXY_KEEP_REPORTS:-}"
REPORT_MAX_AGE_DAYS="${CLIPROXY_REPORT_MAX_AGE_DAYS:-}"
BACKUP_MAX_AGE_DAYS="${CLIPROXY_BACKUP_MAX_AGE_DAYS:-}"
LOG_MAX_SIZE_MB="${CLIPROXY_LOG_MAX_SIZE_MB:-}"

if [ -f "$CONFIG_PATH" ]; then
  eval "$(python3 - "$CONFIG_PATH" <<'PY'
import json
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    raw = json.loads(path.read_text(encoding='utf-8'))
except Exception:
    raw = {}
if not isinstance(raw, dict):
    raw = {}
fields = {
    'KEEP_REPORTS': raw.get('retention_keep_reports', 200),
    'REPORT_MAX_AGE_DAYS': raw.get('retention_report_max_age_days', 7),
    'BACKUP_MAX_AGE_DAYS': raw.get('retention_backup_max_age_days', 14),
    'LOG_MAX_SIZE_MB': raw.get('retention_log_max_size_mb', 50),
}
for key, value in fields.items():
    print(f'{key}={shlex.quote(str(value))}')
PY
)"
fi

exec /usr/bin/flock -n "$LOCK_PATH" /usr/bin/python3 "$SCRIPT_PATH" \
  --keep-reports "${KEEP_REPORTS:-200}" \
  --report-max-age-days "${REPORT_MAX_AGE_DAYS:-7}" \
  --backup-max-age-days "${BACKUP_MAX_AGE_DAYS:-14}" \
  --log-max-size-mb "${LOG_MAX_SIZE_MB:-50}"
