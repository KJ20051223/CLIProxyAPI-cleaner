# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLIPROXY_APP_DIR=/app \
    CLIPROXY_SCRIPT_DIR=/app \
    CLIPROXY_CONFIG_PATH=/data/web_config.json \
    CLIPROXY_STATE_FILE=/data/CLIProxyAPI-cleaner-state.json \
    CLIPROXY_WEB_LOG_PATH=/data/logs/web.log \
    CLIPROXY_CLEANER_LOG_PATH=/data/logs/CLIProxyAPI-cleaner.log \
    CLIPROXY_REPORT_DIR=/data/reports/cliproxyapi-auth-cleaner \
    CLIPROXY_REPORT_ROOT=/data/reports/cliproxyapi-auth-cleaner \
    CLIPROXY_BACKUP_ROOT=/data/backups/cliproxyapi-auth-cleaner \
    CLIPROXY_CONTROL_MODE=supervisor \
    CLIPROXY_SUPERVISORCTL_BIN=/usr/bin/supervisorctl \
    CLIPROXY_SUPERVISORCTL_CONFIG=/app/docker/supervisord.conf \
    CLIPROXY_SUPERVISOR_CLEANER_NAME=cleaner \
    CLIPROXY_SUPERVISOR_WEB_NAME=web \
    CLIPROXY_COOKIE_SECURE=false

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends supervisor ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
RUN chmod +x /app/docker/entrypoint.sh /app/docker/run_cleaner.sh \
    && mkdir -p /data/logs /data/reports /data/backups

EXPOSE 28717
VOLUME ["/data"]

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["/usr/bin/supervisord", "-c", "/app/docker/supervisord.conf"]
