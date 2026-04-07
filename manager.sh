#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/CLIProxyAPI-cleaner"
STATE_FILE="/root/CLIProxyAPI-cleaner-state.json"
LOG_FILE="/root/CLIProxyAPI-cleaner.log"
DEFAULT_PORT="28717"

WEB_SERVICE="CLIProxyAPI-cleaner-web.service"
CLEANER_SERVICE="CLIProxyAPI-cleaner.service"
RETENTION_SERVICE="CLIProxyAPI-cleaner-retention.service"
RETENTION_TIMER="CLIProxyAPI-cleaner-retention.timer"
WEB_OVERRIDE_DIR="/etc/systemd/system/${WEB_SERVICE}.d"
WEB_OVERRIDE_PATH="${WEB_OVERRIDE_DIR}/override.conf"

say() {
  printf '%s\n' "$*"
}

die() {
  say "ERROR: $*" >&2
  exit 1
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    die "please run this script as root"
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

prompt_required() {
  local prompt="$1"
  local value=""
  while :; do
    read -r -p "${prompt}: " value || true
    if [ -n "${value// /}" ]; then
      printf '%s' "$value"
      return
    fi
    say "Value cannot be empty."
  done
}

prompt_default() {
  local prompt="$1"
  local default_value="$2"
  local value=""
  read -r -p "${prompt} [${default_value}]: " value || true
  printf '%s' "${value:-$default_value}"
}

prompt_yes_no() {
  local prompt="$1"
  local default_value="$2"
  local value=""
  read -r -p "${prompt} [${default_value}]: " value || true
  value="${value:-$default_value}"
  case "$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" in
    y|yes) return 0 ;;
    n|no) return 1 ;;
  esac
  say "Please answer yes or no."
  prompt_yes_no "$prompt" "$default_value"
}

prompt_password() {
  local first second
  while :; do
    read -r -s -p "Dashboard password (min 8 chars): " first || true
    printf '\n'
    read -r -s -p "Repeat dashboard password: " second || true
    printf '\n'
    if [ "$first" != "$second" ]; then
      say "Passwords do not match."
      continue
    fi
    if [ "${#first}" -lt 8 ]; then
      say "Password must be at least 8 characters."
      continue
    fi
    printf '%s' "$first"
    return
  done
}

choose_console_mode() {
  local value=""
  while :; do
    say "Dashboard exposure mode:"
    say "  1) Reverse proxy / HTTPS (listen on 127.0.0.1, secure cookie)"
    say "  2) LAN / direct HTTP (listen on 0.0.0.0, insecure cookie)"
    read -r -p "Choose [1/2] [1]: " value || true
    value="${value:-1}"
    case "$value" in
      1|2)
        printf '%s' "$value"
        return
        ;;
    esac
    say "Please choose 1 or 2."
  done
}

copy_workspace() {
  mkdir -p "$INSTALL_DIR"
  tar \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='web_config.json' \
    --exclude='docker-data' \
    --exclude='reports/cliproxyapi-auth-cleaner/report-*.json' \
    -C "$SCRIPT_DIR" -cf - . | tar -C "$INSTALL_DIR" -xf -
}

hash_password() {
  local password="$1"
  CONSOLE_PASSWORD="$password" python3 - <<'PY'
import hashlib
import os

password = os.environ['CONSOLE_PASSWORD']
salt = os.urandom(16).hex()
digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 260000).hex()
print(salt)
print(digest)
PY
}

write_config() {
  local base_url="$1"
  local management_key="$2"
  local listen_host="$3"
  local listen_port="$4"
  local allowed_hosts_csv="$5"
  local password_salt="$6"
  local password_hash="$7"

  SRC_CONFIG="${INSTALL_DIR}/web_config.example.json" \
  DST_CONFIG="${INSTALL_DIR}/web_config.json" \
  BASE_URL="$base_url" \
  MANAGEMENT_KEY="$management_key" \
  LISTEN_HOST="$listen_host" \
  LISTEN_PORT="$listen_port" \
  ALLOWED_HOSTS_CSV="$allowed_hosts_csv" \
  PASSWORD_SALT="$password_salt" \
  PASSWORD_HASH="$password_hash" \
  STATE_FILE="$STATE_FILE" \
  CLEANER_PATH="${INSTALL_DIR}/CLIProxyAPI-cleaner.py" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

src = Path(os.environ['SRC_CONFIG'])
dst = Path(os.environ['DST_CONFIG'])
cfg = json.loads(src.read_text(encoding='utf-8'))
hosts = []
for raw in os.environ['ALLOWED_HOSTS_CSV'].split(','):
    value = raw.strip()
    if value and value not in hosts:
        hosts.append(value)
cfg['listen_host'] = os.environ['LISTEN_HOST']
cfg['listen_port'] = int(os.environ['LISTEN_PORT'])
cfg['allowed_hosts'] = hosts or ['127.0.0.1', 'localhost']
cfg['cleaner_path'] = os.environ['CLEANER_PATH']
cfg['state_file'] = os.environ['STATE_FILE']
cfg['base_url'] = os.environ['BASE_URL']
cfg['management_key'] = os.environ['MANAGEMENT_KEY']
cfg['password_salt'] = os.environ['PASSWORD_SALT']
cfg['password_hash'] = os.environ['PASSWORD_HASH']
dst.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
PY
}

write_web_override() {
  local cookie_secure="$1"
  mkdir -p "$WEB_OVERRIDE_DIR"
  cat > "$WEB_OVERRIDE_PATH" <<EOF
[Service]
Environment=CLIPROXY_COOKIE_SECURE=${cookie_secure}
EOF
}

install_units() {
  install -m 0644 "${INSTALL_DIR}/${CLEANER_SERVICE}" "/etc/systemd/system/${CLEANER_SERVICE}"
  install -m 0644 "${INSTALL_DIR}/${WEB_SERVICE}" "/etc/systemd/system/${WEB_SERVICE}"
  install -m 0644 "${INSTALL_DIR}/${RETENTION_SERVICE}" "/etc/systemd/system/${RETENTION_SERVICE}"
  install -m 0644 "${INSTALL_DIR}/${RETENTION_TIMER}" "/etc/systemd/system/${RETENTION_TIMER}"
  systemctl daemon-reload
  systemctl enable "$CLEANER_SERVICE" "$WEB_SERVICE" "$RETENTION_TIMER" >/dev/null
  systemctl restart "$WEB_SERVICE" "$CLEANER_SERVICE"
  systemctl restart "$RETENTION_TIMER"
}

install_flow() {
  local reuse_existing=0
  local mode=""
  local base_url=""
  local management_key=""
  local listen_host="127.0.0.1"
  local listen_port="$DEFAULT_PORT"
  local allowed_hosts="127.0.0.1,localhost"
  local cookie_secure="true"
  local console_password=""
  local password_salt=""
  local password_hash=""
  local hash_lines=()

  say "Installing CLIProxyAPI-cleaner into ${INSTALL_DIR}"
  copy_workspace

  if [ -f "${INSTALL_DIR}/web_config.json" ] && prompt_yes_no "Reuse existing web_config.json and cookie override" "Y"; then
    reuse_existing=1
  fi

  if [ "$reuse_existing" -eq 0 ]; then
    base_url="$(prompt_required "Management base_url")"
    management_key="$(prompt_required "Management key")"
    mode="$(choose_console_mode)"
    listen_port="$(prompt_default "Dashboard listen port" "$DEFAULT_PORT")"
    if [ "$mode" = "1" ]; then
      listen_host="127.0.0.1"
      allowed_hosts="$(prompt_default "Dashboard allowed_hosts (comma separated)" "127.0.0.1,localhost")"
      cookie_secure="true"
    else
      listen_host="0.0.0.0"
      allowed_hosts="$(prompt_default "Dashboard allowed_hosts (comma separated)" "*,127.0.0.1,localhost")"
      cookie_secure="false"
    fi
    console_password="$(prompt_password)"
    mapfile -t hash_lines < <(hash_password "$console_password")
    password_salt="${hash_lines[0]}"
    password_hash="${hash_lines[1]}"
    write_config "$base_url" "$management_key" "$listen_host" "$listen_port" "$allowed_hosts" "$password_salt" "$password_hash"
    write_web_override "$cookie_secure"
  fi

  install_units

  say "Install complete."
  if [ "$reuse_existing" -eq 0 ]; then
    say "Dashboard listen: ${listen_host}:${listen_port}"
    say "Cookie secure: ${cookie_secure}"
    say "Allowed hosts: ${allowed_hosts}"
  else
    say "Existing dashboard config preserved."
  fi
  say "Cleaner log: ${LOG_FILE}"
}

uninstall_flow() {
  prompt_yes_no "This removes the installed files and generated runtime data. Continue" "N" || return 0

  systemctl disable --now "$CLEANER_SERVICE" "$WEB_SERVICE" "$RETENTION_TIMER" >/dev/null 2>&1 || true
  systemctl stop "$RETENTION_SERVICE" >/dev/null 2>&1 || true

  rm -f \
    "/etc/systemd/system/${CLEANER_SERVICE}" \
    "/etc/systemd/system/${WEB_SERVICE}" \
    "/etc/systemd/system/${RETENTION_SERVICE}" \
    "/etc/systemd/system/${RETENTION_TIMER}"
  rm -rf "$WEB_OVERRIDE_DIR"
  systemctl daemon-reload
  systemctl reset-failed >/dev/null 2>&1 || true

  rm -rf "$INSTALL_DIR"
  rm -f "$LOG_FILE" "$STATE_FILE"

  say "Uninstall complete."
}

main() {
  require_root
  require_cmd python3
  require_cmd systemctl
  require_cmd tar

  case "${1:-}" in
    install)
      install_flow
      ;;
    uninstall)
      uninstall_flow
      ;;
    *)
      say "Usage: $0 install|uninstall"
      exit 1
      ;;
  esac
}

main "$@"
