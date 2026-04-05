from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


APP_DIR = Path(os.environ.get('CLIPROXY_APP_DIR', str(Path(__file__).resolve().parent))).expanduser().resolve()
DEFAULT_REPORT_DIR = Path(
    os.environ.get('CLIPROXY_REPORT_ROOT')
    or os.environ.get('CLIPROXY_REPORT_DIR')
    or str(APP_DIR / 'reports' / 'cliproxyapi-auth-cleaner')
).expanduser().resolve()
DEFAULT_BACKUP_ROOT = Path(
    os.environ.get('CLIPROXY_BACKUP_ROOT')
    or str(APP_DIR / 'backups' / 'cliproxyapi-auth-cleaner')
).expanduser().resolve()
DEFAULT_CLEANER_LOG_PATH = Path(
    os.environ.get('CLIPROXY_CLEANER_LOG_PATH')
    or '/root/CLIProxyAPI-cleaner.log'
).expanduser().resolve()
DEFAULT_WEB_LOG_PATH = Path(
    os.environ.get('CLIPROXY_WEB_LOG_PATH')
    or str(APP_DIR / 'web.log')
).expanduser().resolve()


def env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, '')).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def default_log_paths() -> list[Path]:
    paths = [DEFAULT_CLEANER_LOG_PATH, DEFAULT_WEB_LOG_PATH]
    extra = str(os.environ.get('CLIPROXY_EXTRA_LOG_PATHS', '')).strip()
    if extra:
        for raw in extra.split(','):
            text = raw.strip()
            if text:
                paths.append(Path(text).expanduser().resolve())
    deduped = []
    seen = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description='CLIProxyAPI-cleaner retention cleanup tool')
    ap.add_argument('--report-dir', default=str(DEFAULT_REPORT_DIR), help='Report directory')
    ap.add_argument('--backup-root', default=str(DEFAULT_BACKUP_ROOT), help='Backup root directory')
    ap.add_argument('--log-path', dest='log_paths', action='append', default=[], help='Additional log path to trim; can be repeated')
    ap.add_argument('--keep-reports', type=int, default=max(0, env_int('CLIPROXY_KEEP_REPORTS', 200)), help='Keep at most this many latest report files')
    ap.add_argument('--report-max-age-days', type=int, default=max(0, env_int('CLIPROXY_REPORT_MAX_AGE_DAYS', 7)), help='Delete reports older than this many days; 0 disables age-based pruning')
    ap.add_argument('--backup-max-age-days', type=int, default=max(0, env_int('CLIPROXY_BACKUP_MAX_AGE_DAYS', 14)), help='Delete backups older than this many days; 0 disables age-based pruning')
    ap.add_argument('--log-max-size-mb', type=int, default=max(1, env_int('CLIPROXY_LOG_MAX_SIZE_MB', 50)), help='Trim logs back to this size when they grow too large')
    ap.add_argument('--loop', action='store_true', help='Run in a loop instead of once')
    ap.add_argument('--interval', type=int, default=max(60, env_int('CLIPROXY_CLEANUP_INTERVAL_SECONDS', 21600)), help='Loop interval in seconds; default 21600 (6h)')
    return ap


def file_age_exceeded(path: Path, *, now_ts: float, max_age_days: int) -> bool:
    if max_age_days <= 0:
        return False
    cutoff = now_ts - max_age_days * 86400
    try:
        return path.stat().st_mtime < cutoff
    except FileNotFoundError:
        return False


def prune_reports(report_dir: Path, *, keep_reports: int, max_age_days: int, now_ts: float) -> tuple[int, int]:
    if not report_dir.exists():
        return 0, 0
    removed = 0
    freed_bytes = 0
    files = sorted(report_dir.glob('report-*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    for index, path in enumerate(files):
        delete_for_count = index >= keep_reports
        delete_for_age = file_age_exceeded(path, now_ts=now_ts, max_age_days=max_age_days)
        if not delete_for_count and not delete_for_age:
            continue
        try:
            size = path.stat().st_size
            path.unlink()
            removed += 1
            freed_bytes += size
        except FileNotFoundError:
            continue
    return removed, freed_bytes


def prune_backups(backup_root: Path, *, max_age_days: int, now_ts: float) -> tuple[int, int, int]:
    if not backup_root.exists() or max_age_days <= 0:
        return 0, 0, 0
    removed_files = 0
    removed_dirs = 0
    freed_bytes = 0
    for path in sorted((p for p in backup_root.rglob('*') if p.is_file()), key=lambda p: len(p.parts), reverse=True):
        if not file_age_exceeded(path, now_ts=now_ts, max_age_days=max_age_days):
            continue
        try:
            size = path.stat().st_size
            path.unlink()
            removed_files += 1
            freed_bytes += size
        except FileNotFoundError:
            continue
    for path in sorted((p for p in backup_root.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            path.rmdir()
            removed_dirs += 1
        except OSError:
            continue
    return removed_files, removed_dirs, freed_bytes


def shrink_log(path: Path, *, max_bytes: int) -> int:
    if not path.exists() or max_bytes <= 0:
        return 0
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return 0
    if size <= max_bytes:
        return 0
    keep_from = max(0, size - max_bytes)
    with path.open('rb+') as f:
        f.seek(keep_from)
        data = f.read()
        if keep_from > 0:
            newline = data.find(b'\n')
            if newline != -1 and newline + 1 < len(data):
                data = data[newline + 1:]
        f.seek(0)
        f.write(data)
        f.truncate()
    return size - len(data)


def format_bytes(num: int) -> str:
    value = float(num)
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f'{value:.1f}{unit}'
        value /= 1024.0
    return f'{num}B'


def collect_log_paths(args: argparse.Namespace) -> list[Path]:
    paths = default_log_paths()
    for raw in args.log_paths:
        text = str(raw or '').strip()
        if text:
            paths.append(Path(text).expanduser().resolve())
    deduped = []
    seen = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def run_once(args: argparse.Namespace) -> int:
    now_ts = time.time()
    report_dir = Path(args.report_dir).expanduser().resolve()
    backup_root = Path(args.backup_root).expanduser().resolve()
    max_bytes = int(args.log_max_size_mb) * 1024 * 1024

    reports_removed, report_bytes = prune_reports(
        report_dir,
        keep_reports=max(0, int(args.keep_reports)),
        max_age_days=max(0, int(args.report_max_age_days)),
        now_ts=now_ts,
    )
    backup_files_removed, backup_dirs_removed, backup_bytes = prune_backups(
        backup_root,
        max_age_days=max(0, int(args.backup_max_age_days)),
        now_ts=now_ts,
    )

    log_bytes = 0
    logs_trimmed = 0
    for path in collect_log_paths(args):
        removed = shrink_log(path, max_bytes=max_bytes)
        if removed > 0:
            logs_trimmed += 1
            log_bytes += removed

    total_bytes = report_bytes + backup_bytes + log_bytes
    print('[cleanup] reports_removed=%d backups_removed=%d backup_dirs_removed=%d logs_trimmed=%d freed=%s' % (
        reports_removed,
        backup_files_removed,
        backup_dirs_removed,
        logs_trimmed,
        format_bytes(total_bytes),
    ))
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if not args.loop:
        return run_once(args)

    try:
        while True:
            run_once(args)
            time.sleep(max(60, int(args.interval)))
    except KeyboardInterrupt:
        print('[cleanup] interrupted by user', file=sys.stderr)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
