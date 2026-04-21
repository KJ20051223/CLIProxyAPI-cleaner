import os
import sys
import re
import json
import base64
import argparse
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib import request, parse, error
from datetime import datetime, timezone, timedelta

P401 = re.compile(r'(^|\D)401(\D|$)|unauthorized|unauthenticated|token\s+expired|login\s+required|authentication\s+failed|invalid_grant|refresh_token_reused|invalid\s+refresh', re.I)
PQUOTA = re.compile(r'(^|\D)(402|403|429)(\D|$)|quota|insufficient\s*quota|resource\s*exhausted|rate\s*limit|too\s+many\s+requests|payment\s+required|billing|credit|额度|用完|超限|上限|usage_limit_reached', re.I)
PREMOVE = re.compile(r'invalid_grant|refresh_token_reused|account.*deactivated|account.*disabled|missing\s+refresh\s+token|invalid\s+token', re.I)

DEFAULT_BASE_URL = 'https://example.com/management.html'
DEFAULT_MANAGEMENT_KEY = 'replace-me'
DEFAULT_API_CALL_PROVIDERS = 'codex,openai,chatgpt'
DEFAULT_API_CALL_URL = 'https://chatgpt.com/backend-api/wham/usage'
DEFAULT_API_CALL_USER_AGENT = 'Mozilla/5.0 CLIProxyAPI-cleaner/1.0'
DEFAULT_API_CALL_ACCOUNT_ID = ''
DEFAULT_API_CALL_MAX_PER_RUN = 50
DEFAULT_API_CALL_SLEEP_MIN = 5.0
DEFAULT_API_CALL_SLEEP_MAX = 10.0
DEFAULT_REVIVAL_WAIT_DAYS = 7
DEFAULT_REVIVAL_INTERVAL_HOURS = 12
DEFAULT_STATE_FILE = 'CLIProxyAPI-cleaner-state.json'
OPENAI_TOKEN_URL = 'https://auth.openai.com/oauth/token'
OPENAI_CLIENT_ID = 'app_EMoamEEZ73f0CkXaXp7hrann'
OPENAI_SCOPE = 'openid profile email'
AUTH_FILE_STATUS_METHODS = ('PATCH', 'PUT', 'POST')


def get_current_time():
    return datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %z')


def iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def run_id():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def script_dir():
    override = os.environ.get('CLIPROXY_SCRIPT_DIR')
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent


def normalize_base_url(base):
    text = str(base or '').strip()
    if not text:
        return text
    text = text.rstrip('/')
    if text.endswith('/management.html'):
        text = text[:-len('/management.html')]
    return text.rstrip('/')


def parse_csv_set(value):
    if not value:
        return set()
    return {x.strip().lower() for x in str(value).split(',') if x.strip()}


def env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in ('0', 'false', 'no', 'off', '')


def parse_time(value):
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00'))
    except Exception:
        return None


def to_iso(dt):
    if not dt:
        return ''
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def api(base, key, method, path, timeout=20, query=None, expect_json=True, body=None, extra_headers=None):
    base = normalize_base_url(base)
    url = base.rstrip('/') + '/v0/management' + path
    if query:
        url += '?' + parse.urlencode(query, doseq=True)

    headers = {
        'Authorization': 'Bearer ' + key,
        'Accept': 'application/json',
        'User-Agent': 'cliproxyapi-cleaner/2.0',
    }
    if extra_headers:
        headers.update(extra_headers)

    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers.setdefault('Content-Type', 'application/json')
        elif isinstance(body, bytes):
            data = body
        else:
            data = str(body).encode('utf-8')
            headers.setdefault('Content-Type', 'application/json')

    req = request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.getcode()
            resp_headers = dict(resp.headers.items())
    except error.HTTPError as e:
        raw = e.read()
        code = e.code
        resp_headers = dict(e.headers.items()) if e.headers else {}
    except error.URLError as e:
        raise RuntimeError('请求管理 API 失败: %s' % e)

    if expect_json:
        try:
            payload = json.loads(raw.decode('utf-8')) if raw else {}
        except Exception:
            payload = {'raw': raw.decode('utf-8', errors='replace')}
        return code, payload, resp_headers
    return code, raw, resp_headers


def request_json_or_text(url, method='GET', timeout=20, body=None, headers=None):
    method = (method or 'GET').upper()
    req_headers = {
        'Accept': 'application/json',
        'User-Agent': 'cliproxyapi-cleaner/2.0',
    }
    if headers:
        req_headers.update(headers)

    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            req_headers.setdefault('Content-Type', 'application/json')
        elif isinstance(body, bytes):
            data = body
        else:
            data = str(body).encode('utf-8')
            req_headers.setdefault('Content-Type', 'application/json')

    req = request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.getcode()
            resp_headers = dict(resp.headers.items())
    except error.HTTPError as e:
        raw = e.read()
        code = e.code
        resp_headers = dict(e.headers.items()) if e.headers else {}
    except error.URLError as e:
        raise RuntimeError('请求上游失败: %s' % e)

    text = raw.decode('utf-8', errors='replace') if raw else ''
    try:
        parsed = json.loads(text) if text else {}
    except Exception:
        parsed = text
    return {
        'status_code': code,
        'header': resp_headers,
        'body': parsed,
    }


def extract_error_message(msg):
    try:
        if isinstance(msg, str) and msg.strip().startswith('{'):
            error_data = json.loads(msg)
            if 'error' in error_data:
                error_obj = error_data['error']
                if isinstance(error_obj, dict):
                    error_type = error_obj.get('type', '')
                    error_message = error_obj.get('message', '')
                    return error_type, error_message
                if isinstance(error_obj, str):
                    return 'error', error_obj
            return None, msg
    except Exception:
        pass
    return None, msg


def simplify_reason(reason):
    text = str(reason or '').strip()
    if not text:
        return ''
    if not text.startswith('{'):
        return text[:160]
    try:
        error_data = json.loads(text)
    except Exception:
        return text[:160]
    if 'error' not in error_data:
        return text[:160]
    error_obj = error_data['error']
    if isinstance(error_obj, dict):
        error_type = str(error_obj.get('type') or '').strip()
        error_message = str(error_obj.get('message') or '').strip()
        if error_type == 'usage_limit_reached':
            return ('usage_limit_reached: ' + error_message)[:160]
        return (error_type or error_message or text)[:160]
    return str(error_obj)[:160]


def normalize_api_call_body(body):
    if body is None:
        return '', None
    if isinstance(body, str):
        text = body
        trimmed = text.strip()
        if not trimmed:
            return text, None
        try:
            return text, json.loads(trimmed)
        except Exception:
            return text, text
    try:
        return json.dumps(body, ensure_ascii=False), body
    except Exception:
        return str(body), body


def is_limit_reached_window(value):
    if not isinstance(value, dict):
        return False
    if value.get('allowed') is False:
        return True
    if value.get('limit_reached') is True:
        return True
    return False


def classify_api_call_response(payload):
    nested_status = payload.get('status_code', payload.get('statusCode', 0))
    try:
        nested_status = int(nested_status)
    except Exception:
        nested_status = 0

    header = payload.get('header') or payload.get('headers') or {}
    body_text, body = normalize_api_call_body(payload.get('body'))

    try:
        header_text = json.dumps(header, ensure_ascii=False)
    except Exception:
        header_text = str(header)

    if isinstance(body, (dict, list)):
        try:
            body_signal = json.dumps(body, ensure_ascii=False)
        except Exception:
            body_signal = body_text
    else:
        body_signal = body_text

    if nested_status == 401:
        return 'delete_401', body_signal or ('api-call status_code=%s' % nested_status)
    if nested_status in (402, 403, 429):
        return 'quota_exhausted', body_signal or ('api-call status_code=%s' % nested_status)

    if isinstance(body, dict):
        error_obj = body.get('error')
        if isinstance(error_obj, dict):
            error_type = str(error_obj.get('type') or '').strip().lower()
            error_message = str(error_obj.get('message') or '').strip()
            error_text = (error_type + '\n' + error_message).lower()
            if error_type == 'usage_limit_reached' or PQUOTA.search(error_text):
                return 'quota_exhausted', body_signal or error_message or error_type
            if P401.search(error_text):
                return 'delete_401', body_signal or error_message or error_type
        rate_limit = body.get('rate_limit')
        code_review_rate_limit = body.get('code_review_rate_limit')
        if is_limit_reached_window(rate_limit) or is_limit_reached_window(code_review_rate_limit):
            return 'quota_exhausted', body_signal or 'rate_limit_reached'
        if nested_status == 200:
            return None, body_signal or 'ok'

    fallback_text = ('%s\n%s\n%s' % (nested_status, header_text, body_signal)).lower()
    if P401.search(fallback_text):
        return 'delete_401', body_signal or ('api-call status_code=%s' % nested_status)
    if nested_status != 200 and PQUOTA.search(fallback_text):
        return 'quota_exhausted', body_signal or ('api-call status_code=%s' % nested_status)
    return None, body_signal or ('api-call status_code=%s' % nested_status if nested_status else 'ok')


def classify(item):
    status = str(item.get('status', '')).strip().lower()
    msg = str(item.get('status_message', '') or '').strip()
    error_type, _ = extract_error_message(msg)
    text = (status + '\n' + msg).lower()

    if P401.search(text):
        return 'delete_401', msg or status or '401/unauthorized'
    if error_type == 'usage_limit_reached' or 'usage_limit_reached' in text:
        return 'quota_exhausted', msg or status or 'usage_limit_reached'
    if PQUOTA.search(text):
        return 'quota_exhausted', msg or status or 'quota'
    if bool(item.get('disabled', False)) or status == 'disabled':
        return 'disabled', msg or status or 'disabled'
    if bool(item.get('unavailable', False)) or status == 'error':
        return 'unavailable', msg or status or 'error'
    return 'available', msg or status or 'active'


def should_probe_api_call(item, args):
    if not args.enable_api_call_check:
        return False
    auth_index = str(item.get('auth_index') or '').strip()
    if not auth_index:
        return False
    provider = str(item.get('provider') or item.get('type') or '').strip().lower()
    if args.api_call_provider_set and provider not in args.api_call_provider_set:
        return False
    if bool(item.get('disabled', False)):
        return False
    initial_kind, _ = classify(item)
    return initial_kind in ('available', 'quota_exhausted')


def api_call_item_key(item):
    auth_index = str(item.get('auth_index') or '').strip()
    if auth_index:
        return 'auth_index:' + auth_index
    return 'name:' + str(item.get('name') or item.get('id') or '').strip()


def choose_account_id(item, args, auth_payload=None):
    candidates = []
    if auth_payload and isinstance(auth_payload, dict):
        candidates.extend([
            auth_payload.get('account_id'),
            auth_payload.get('accountId'),
        ])
        metadata = auth_payload.get('metadata') if isinstance(auth_payload.get('metadata'), dict) else {}
        candidates.extend([metadata.get('account_id'), metadata.get('accountId')])
    candidates.extend([
        item.get('account_id'),
        item.get('accountId'),
        item.get('account'),
    ])
    for candidate in candidates:
        value = str(candidate or '').strip()
        if value:
            return value
    return args.api_call_account_id.strip()


def build_api_call_payload(item, args):
    headers = {
        'Authorization': 'Bearer $TOKEN$',
        'Content-Type': 'application/json',
        'User-Agent': args.api_call_user_agent,
    }
    account_id = choose_account_id(item, args)
    if account_id:
        headers['Chatgpt-Account-Id'] = account_id
    payload = {
        'authIndex': str(item.get('auth_index') or '').strip(),
        'method': args.api_call_method.upper(),
        'url': args.api_call_url.strip(),
        'header': headers,
    }
    if args.api_call_body:
        payload['data'] = args.api_call_body
    return payload


def run_api_call_probe(args, item):
    request_payload = build_api_call_payload(item, args)
    code, payload, _ = api(
        args.base_url,
        args.management_key,
        'POST',
        '/api-call',
        args.timeout,
        expect_json=True,
        body=request_payload,
    )
    if code != 200:
        raise RuntimeError('调用 /api-call 失败: HTTP %s %s' % (code, payload))
    kind, reason = classify_api_call_response(payload)
    return {
        'request': request_payload,
        'response': payload,
        'classification': kind,
        'reason': reason,
        'status_code': payload.get('status_code', payload.get('statusCode')),
    }


def pick_api_call_sleep_seconds(args):
    fixed_sleep = getattr(args, 'api_call_sleep', None)
    if fixed_sleep is not None:
        return max(0.0, float(fixed_sleep))
    return random.uniform(args.api_call_sleep_min, args.api_call_sleep_max)


def run_api_call_full_scan(args, files, counts):
    if not args.enable_api_call_check:
        counts['api-call候选数'] = 0
        counts['api-call批次数'] = 0
        return {}
    if getattr(args, 'api_call_scan_completed', False):
        counts['api-call候选数'] = 0
        counts['api-call批次数'] = 0
        print('[api-call] 当前进程已完成一次全量探测，本轮跳过', flush=True)
        return {}

    eligible = [item for item in files if should_probe_api_call(item, args)]
    counts['api-call候选数'] = len(eligible)
    if not eligible:
        counts['api-call批次数'] = 0
        args.api_call_scan_completed = True
        print('[api-call] 没有需要探测的候选账号，本次进程不再执行 api-call', flush=True)
        return {}

    batch_size = max(1, min(int(args.api_call_max_per_run), DEFAULT_API_CALL_MAX_PER_RUN))
    batch_count = (len(eligible) + batch_size - 1) // batch_size
    counts['api-call批次数'] = batch_count
    sleep_desc = '固定 %.1f 秒' % args.api_call_sleep if args.api_call_sleep is not None else '随机 %.1f-%.1f 秒' % (args.api_call_sleep_min, args.api_call_sleep_max)
    print('[api-call] 已开启全量探测，本次运行将探测 %s 个候选账号，共 %s 批，每批最多 %s 个，批次间隔 %s' % (
        len(eligible), batch_count, batch_size, sleep_desc,
    ), flush=True)

    probe_results = {}
    probed_total = 0
    for batch_index in range(batch_count):
        batch = eligible[batch_index * batch_size:(batch_index + 1) * batch_size]
        print('[api-call批次 %s/%s] 并发探测 %s 个账号' % (batch_index + 1, batch_count, len(batch)), flush=True)
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            future_to_item = {executor.submit(run_api_call_probe, args, item): item for item in batch}
            for future in as_completed(future_to_item):
                item = future_to_item[future]
                counts['api-call已探测'] += 1
                probed_total += 1
                name = str(item.get('name') or item.get('id') or '').strip()
                provider = str(item.get('provider') or item.get('type') or '').strip()
                auth_index = item.get('auth_index')
                try:
                    probe = future.result()
                    probe_results[api_call_item_key(item)] = probe
                    classification = probe.get('classification') or 'ok'
                    if classification == 'delete_401':
                        counts['api-call发现401'] += 1
                    elif classification == 'quota_exhausted':
                        counts['api-call发现配额耗尽'] += 1
                    print(' [api-call完成 %s/%s] %s provider=%s auth_index=%s result=%s' % (
                        probed_total, len(eligible), name, provider, auth_index, classification,
                    ), flush=True)
                except Exception as e:
                    counts['api-call探测失败'] += 1
                    probe_results[api_call_item_key(item)] = {'error': str(e)}
                    print(' [api-call完成 %s/%s] %s provider=%s auth_index=%s result=error error=%s' % (
                        probed_total, len(eligible), name, provider, auth_index, e,
                    ), flush=True)
        if batch_index + 1 < batch_count:
            sleep_seconds = pick_api_call_sleep_seconds(args)
            if sleep_seconds > 0:
                print('[api-call批次 %s/%s] 整批完成，等待 %.1f 秒后继续下一批' % (
                    batch_index + 1, batch_count, sleep_seconds,
                ), flush=True)
                time.sleep(sleep_seconds)

    args.api_call_scan_completed = True
    print('[api-call] 本次运行已完成全部候选账号探测，后续轮次不再重复探测', flush=True)
    return probe_results


def patch_auth_file_disabled(args, name, disabled):
    payload = {'name': name, 'disabled': bool(disabled)}
    attempts = []
    for method in AUTH_FILE_STATUS_METHODS:
        code, resp, _ = api(
            args.base_url,
            args.management_key,
            method,
            '/auth-files/status',
            args.timeout,
            expect_json=True,
            body=payload,
        )
        attempts.append({'method': method, 'code': code, 'response': resp})
        if 200 <= code < 300:
            return attempts[-1]
        if code not in (404, 405, 501):
            break
    raise RuntimeError('更新 auth-files/status 失败: %s' % attempts)


def load_state(path):
    if not path.exists():
        return {'version': 1, 'quota_accounts': {}}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {'version': 1, 'quota_accounts': {}}
    if not isinstance(data, dict):
        data = {}
    data.setdefault('version', 1)
    quota_accounts = data.get('quota_accounts')
    if not isinstance(quota_accounts, dict):
        quota_accounts = {}
    data['quota_accounts'] = quota_accounts
    return data


def save_state(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def ensure_quota_state(state, item, reason, args):
    name = str(item.get('name') or item.get('id') or '').strip()
    if not name:
        return None
    now = datetime.now(timezone.utc)
    due = now + timedelta(days=args.revival_wait_days)
    quota_accounts = state.setdefault('quota_accounts', {})
    entry = quota_accounts.get(name) or {}
    if not entry.get('quota_disabled_at'):
        entry['quota_disabled_at'] = to_iso(now)
    if not entry.get('next_revival_check_at'):
        entry['next_revival_check_at'] = to_iso(due)
    entry['provider'] = str(item.get('provider') or item.get('type') or '').strip()
    entry['reason'] = str(reason or '')
    entry['path'] = str(item.get('path') or entry.get('path') or '').strip()
    entry['auth_index'] = item.get('auth_index')
    entry['email'] = str(item.get('email') or entry.get('email') or '').strip()
    account = str(item.get('account') or item.get('account_id') or entry.get('account_id') or '').strip()
    if account:
        entry['account_id'] = account
    entry['last_seen_at'] = iso_now()
    quota_accounts[name] = entry
    return entry


def clear_quota_state(state, name):
    quota_accounts = state.get('quota_accounts') or {}
    if name in quota_accounts:
        del quota_accounts[name]
        return True
    return False


def backup_bytes(base_dir, name, suffix, raw):
    base_dir.mkdir(parents=True, exist_ok=True)
    file_name = Path(str(name or 'unknown.json')).name
    target = base_dir / (file_name + suffix)
    target.write_bytes(raw)
    return target


def backup_json_file(base_dir, path):
    base_dir.mkdir(parents=True, exist_ok=True)
    src = Path(path)
    target = base_dir / src.name
    target.write_bytes(src.read_bytes())
    return target


def delete_auth_file(args, name, backup_root):
    code, raw, _ = api(args.base_url, args.management_key, 'GET', '/auth-files/download', args.timeout, {'name': name}, False)
    if code != 200:
        raise RuntimeError('下载 auth 文件失败: %s HTTP %s' % (name, code))
    backup_path = backup_bytes(backup_root, name, '', raw)
    code, payload, _ = api(args.base_url, args.management_key, 'DELETE', '/auth-files', args.timeout, {'name': name}, True)
    if code != 200:
        raise RuntimeError('删除 auth 文件失败: %s HTTP %s %s' % (name, code, payload))
    return backup_path, payload


def parse_jwt_payload(token):
    text = str(token or '').strip()
    if not text or text.count('.') < 2:
        return {}
    try:
        payload_part = text.split('.')[1]
        padding = '=' * (-len(payload_part) % 4)
        raw = base64.urlsafe_b64decode(payload_part + padding)
        data = json.loads(raw.decode('utf-8'))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def load_auth_payload_from_path(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise RuntimeError('auth 文件不是对象 JSON')
    return data


def write_auth_payload(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, target)


def refresh_openai_family_tokens(auth_payload, timeout=20):
    refresh_token = str(auth_payload.get('refresh_token') or '').strip()
    if not refresh_token:
        raise RuntimeError('missing refresh token')
    form = parse.urlencode({
        'client_id': OPENAI_CLIENT_ID,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'scope': OPENAI_SCOPE,
    }).encode('utf-8')
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'User-Agent': 'cliproxyapi-cleaner/2.0',
    }
    req = request.Request(OPENAI_TOKEN_URL, data=form, headers=headers, method='POST')
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.getcode()
    except error.HTTPError as e:
        raw = e.read()
        code = e.code
    except error.URLError as e:
        raise RuntimeError('refresh request failed: %s' % e)

    text = raw.decode('utf-8', errors='replace') if raw else ''
    if code != 200:
        raise RuntimeError('token refresh failed with status %s: %s' % (code, text))
    try:
        token_resp = json.loads(text) if text else {}
    except Exception as e:
        raise RuntimeError('failed to parse refresh response: %s' % e)

    access_token = str(token_resp.get('access_token') or '').strip()
    if not access_token:
        raise RuntimeError('refresh response missing access_token: %s' % token_resp)

    new_payload = dict(auth_payload)
    new_payload['access_token'] = access_token
    if token_resp.get('refresh_token'):
        new_payload['refresh_token'] = token_resp.get('refresh_token')
    if token_resp.get('id_token'):
        new_payload['id_token'] = token_resp.get('id_token')
    new_payload['last_refresh'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    new_payload['expired'] = False

    claims = parse_jwt_payload(new_payload.get('id_token'))
    if claims.get('email'):
        new_payload['email'] = claims.get('email')
    account_candidates = [
        claims.get('https://api.openai.com/profile/account_id'),
        claims.get('account_id'),
        claims.get('org_id'),
    ]
    for candidate in account_candidates:
        value = str(candidate or '').strip()
        if value:
            new_payload['account_id'] = value
            break
    return new_payload, token_resp


def direct_probe_auth(args, item, auth_payload):
    access_token = str(auth_payload.get('access_token') or '').strip()
    if not access_token:
        raise RuntimeError('缺少 access_token，无法测活')

    headers = {
        'Authorization': 'Bearer ' + access_token,
        'User-Agent': args.api_call_user_agent,
        'Accept': 'application/json',
    }
    account_id = choose_account_id(item, args, auth_payload)
    if account_id:
        headers['Chatgpt-Account-Id'] = account_id

    body = None
    if args.api_call_body:
        text = args.api_call_body
        try:
            body = json.loads(text)
        except Exception:
            body = text

    response_payload = request_json_or_text(
        args.api_call_url.strip(),
        method=args.api_call_method.upper(),
        timeout=args.timeout,
        body=body,
        headers=headers,
    )
    classification, reason = classify_api_call_response(response_payload)
    return {
        'classification': classification,
        'reason': reason,
        'response': response_payload,
    }


def is_delete_worthy(text):
    signal = str(text or '').strip()
    if not signal:
        return False
    lowered = signal.lower()
    return bool(P401.search(lowered) or PREMOVE.search(lowered))


def next_revival_due(now, args):
    return to_iso(now + timedelta(hours=args.revival_probe_interval_hours))


def run_revival_cycle(args, item, state_entry, counts, backup_root):
    name = str(item.get('name') or item.get('id') or '').strip()
    provider = str(item.get('provider') or item.get('type') or '').strip().lower()
    row = {
        'name': name,
        'provider': provider,
        'auth_index': item.get('auth_index'),
        'path': item.get('path') or state_entry.get('path'),
        'revival_cycle': True,
    }
    counts['复活待检查'] += 1
    now = datetime.now(timezone.utc)
    state_entry['last_revival_check_at'] = to_iso(now)

    if provider not in ('codex', 'openai', 'chatgpt'):
        row['revival_result'] = 'skip_unsupported_provider'
        row['reason'] = 'provider 不在 codex/openai/chatgpt 范围内'
        state_entry['next_revival_check_at'] = next_revival_due(now, args)
        return row

    path = str(item.get('path') or state_entry.get('path') or '').strip()
    if not path:
        row['revival_result'] = 'skip_missing_path'
        row['reason'] = '缺少本地文件路径，无法刷新并写回 token'
        state_entry['next_revival_check_at'] = next_revival_due(now, args)
        return row

    try:
        auth_payload = load_auth_payload_from_path(path)
        row['auth_payload_loaded'] = True
    except Exception as e:
        row['revival_result'] = 'load_failed'
        row['reason'] = str(e)
        if is_delete_worthy(e):
            try:
                backup_path, delete_resp = delete_auth_file(args, name, backup_root / 'delete-on-load-failed')
                counts['复活删除'] += 1
                row['revival_result'] = 'deleted_on_load_failure'
                row['backup_path'] = str(backup_path)
                row['delete_response'] = delete_resp
            except Exception as delete_err:
                row['delete_error'] = str(delete_err)
                state_entry['next_revival_check_at'] = next_revival_due(now, args)
        else:
            state_entry['next_revival_check_at'] = next_revival_due(now, args)
        return row

    counts['refresh尝试'] += 1
    try:
        before_backup = backup_json_file(backup_root / 'before-refresh', path)
        refreshed_payload, refresh_resp = refresh_openai_family_tokens(auth_payload, timeout=args.timeout)
        write_auth_payload(path, refreshed_payload)
        counts['refresh成功'] += 1
        row['refresh_result'] = 'ok'
        row['refresh_backup'] = str(before_backup)
        row['refresh_response_keys'] = sorted(refresh_resp.keys()) if isinstance(refresh_resp, dict) else []
    except Exception as e:
        counts['refresh失败'] += 1
        row['refresh_result'] = 'failed'
        row['reason'] = str(e)
        state_entry['last_error'] = str(e)
        if is_delete_worthy(e):
            try:
                backup_path, delete_resp = delete_auth_file(args, name, backup_root / 'delete-on-refresh-failed')
                counts['复活删除'] += 1
                row['revival_result'] = 'deleted_on_refresh_failure'
                row['backup_path'] = str(backup_path)
                row['delete_response'] = delete_resp
            except Exception as delete_err:
                row['delete_error'] = str(delete_err)
                state_entry['next_revival_check_at'] = next_revival_due(now, args)
        else:
            state_entry['next_revival_check_at'] = next_revival_due(now, args)
        return row

    try:
        current_payload = load_auth_payload_from_path(path)
        probe = direct_probe_auth(args, item, current_payload)
        row['probe'] = probe
        classification = probe.get('classification') or 'ok'
        row['revival_classification'] = classification
        row['reason'] = probe.get('reason') or ''
    except Exception as e:
        row['revival_result'] = 'probe_failed'
        row['reason'] = str(e)
        state_entry['last_error'] = str(e)
        state_entry['next_revival_check_at'] = next_revival_due(now, args)
        return row

    classification = row.get('revival_classification')
    if classification in (None, 'ok'):
        try:
            disable_resp = patch_auth_file_disabled(args, name, False)
            counts['复活成功启用'] += 1
            row['revival_result'] = 'enabled'
            row['enable_response'] = disable_resp
            return row
        except Exception as e:
            row['revival_result'] = 'enable_failed'
            row['reason'] = str(e)
            state_entry['last_error'] = str(e)
            state_entry['next_revival_check_at'] = next_revival_due(now, args)
            return row

    if classification == 'quota_exhausted':
        counts['复活仍限额'] += 1
        row['revival_result'] = 'still_quota_exhausted'
        try:
            row['disable_response'] = patch_auth_file_disabled(args, name, True)
        except Exception as e:
            row['disable_error'] = str(e)
        state_entry['last_error'] = simplify_reason(row.get('reason'))
        state_entry['next_revival_check_at'] = next_revival_due(now, args)
        return row

    if classification == 'delete_401' or is_delete_worthy(row.get('reason')):
        try:
            backup_path, delete_resp = delete_auth_file(args, name, backup_root / 'delete-on-bad-probe')
            counts['复活删除'] += 1
            row['revival_result'] = 'deleted_on_bad_probe'
            row['backup_path'] = str(backup_path)
            row['delete_response'] = delete_resp
            return row
        except Exception as e:
            row['revival_result'] = 'delete_failed'
            row['delete_error'] = str(e)
            state_entry['last_error'] = str(e)
            state_entry['next_revival_check_at'] = next_revival_due(now, args)
            return row

    row['revival_result'] = 'retry_later'
    state_entry['last_error'] = simplify_reason(row.get('reason'))
    state_entry['next_revival_check_at'] = next_revival_due(now, args)
    return row


def run_check(args):
    code, payload, _ = api(args.base_url, args.management_key, 'GET', '/auth-files', args.timeout)
    if code != 200:
        print('[错误] 获取 auth-files 失败: HTTP %s %s' % (code, payload), file=sys.stderr)
        return None

    files = payload.get('files') or []
    if not isinstance(files, list):
        print('[错误] auth-files 返回异常: %s' % payload, file=sys.stderr)
        return None

    rid = run_id()
    backup_root = args.backup_root / rid
    report_root = args.report_root
    report_root.mkdir(parents=True, exist_ok=True)
    state = load_state(args.state_path)

    counts = {
        '检查总数': 0,
        '可用账号': 0,
        '配额耗尽': 0,
        '已禁用': 0,
        '不可用': 0,
        'api-call候选数': 0,
        'api-call批次数': 0,
        'api-call已探测': 0,
        'api-call发现401': 0,
        'api-call发现配额耗尽': 0,
        'api-call探测失败': 0,
        '待删除401': 0,
        '已删除': 0,
        '备份失败': 0,
        '删除失败': 0,
        '额度账号已禁用': 0,
        '禁用失败': 0,
        '复活待检查': 0,
        'refresh尝试': 0,
        'refresh成功': 0,
        'refresh失败': 0,
        '复活成功启用': 0,
        '复活仍限额': 0,
        '复活删除': 0,
        '状态清理': 0,
    }
    results = []
    name_to_item = {}

    print('[%s] 开始检查 %s 个账号' % (get_current_time(), len(files)), flush=True)
    probe_results = run_api_call_full_scan(args, files, counts)

    for item in files:
        counts['检查总数'] += 1
        name = str(item.get('name') or item.get('id') or '').strip()
        provider = str(item.get('provider') or item.get('type') or '').strip()
        kind, reason = classify(item)
        row = {
            'name': name,
            'provider': provider,
            'auth_index': item.get('auth_index'),
            'status': item.get('status'),
            'status_message': item.get('status_message'),
            'disabled': item.get('disabled'),
            'unavailable': item.get('unavailable'),
            'runtime_only': item.get('runtime_only'),
            'source': item.get('source'),
            'path': item.get('path'),
        }
        if name:
            name_to_item[name] = item

        probe = probe_results.get(api_call_item_key(item))
        if probe is not None:
            row['api_call_probe'] = probe
            if probe.get('classification') == 'delete_401':
                kind = 'delete_401'
                reason = probe.get('reason') or reason
            elif probe.get('classification') == 'quota_exhausted':
                kind = 'quota_exhausted'
                reason = probe.get('reason') or reason
            elif kind == 'quota_exhausted':
                kind = 'available'
                reason = probe.get('reason') or 'api-call probe ok'
                row['probe_override'] = 'cleared_quota_exhausted'

        row['final_classification'] = kind
        row['reason'] = reason
        display_reason = simplify_reason(reason)

        if kind == 'available':
            counts['可用账号'] += 1
            if row.get('probe_override') == 'cleared_quota_exhausted':
                print('[api-call纠偏] %s provider=%s 通过主动探测确认仍可用，跳过自动禁用' % (
                    name, provider,
                ), flush=True)
            if name and not bool(item.get('disabled')) and clear_quota_state(state, name):
                counts['状态清理'] += 1
                row['state_cleared'] = 'became_available'

        elif kind == 'quota_exhausted':
            counts['配额耗尽'] += 1
            print('[配额耗尽] %s provider=%s reason=%s' % (name, provider, display_reason), flush=True)
            if args.dry_run:
                row['disable_result'] = 'dry_run_skip'
                print(' [模拟运行] 将调用 /auth-files/status 设置 disabled=true', flush=True)
            elif not name:
                counts['禁用失败'] += 1
                row['disable_result'] = 'skip_no_name'
                row['disable_error'] = '缺少 name，无法调用 /auth-files/status'
                print(' [禁用失败] 缺少 name，无法更新状态', flush=True)
            else:
                try:
                    disable_resp = patch_auth_file_disabled(args, name, True)
                    counts['额度账号已禁用'] += 1
                    row['disable_result'] = 'disabled_true'
                    row['disable_response'] = disable_resp
                    state_entry = ensure_quota_state(state, item, reason, args)
                    row['revival_tracking'] = state_entry
                    print(' [已禁用] method=%s HTTP %s，%s 天后开始 refresh + 测活' % (
                        disable_resp['method'], disable_resp['code'], args.revival_wait_days,
                    ), flush=True)
                except Exception as e:
                    counts['禁用失败'] += 1
                    row['disable_result'] = 'disable_failed'
                    row['disable_error'] = str(e)
                    print(' [禁用失败] %s' % e, flush=True)

        elif kind == 'disabled':
            counts['已禁用'] += 1
            print('[已禁用-不直接删除] %s provider=%s' % (name, provider), flush=True)

        elif kind == 'unavailable':
            counts['不可用'] += 1
            print('[不可用-不删除] %s provider=%s reason=%s' % (name, provider, display_reason), flush=True)

        elif kind == 'delete_401':
            counts['待删除401'] += 1
            print('[待删除-401认证失败] %s provider=%s reason=%s' % (name, provider, display_reason), flush=True)
            if args.dry_run:
                row['delete_result'] = 'dry_run_skip'
                print(' [模拟运行] 将删除此文件', flush=True)
            else:
                runtime_only = bool(item.get('runtime_only', False))
                source = str(item.get('source') or '').strip().lower()
                if runtime_only or (source and source != 'file'):
                    counts['备份失败'] += 1
                    row['delete_result'] = 'skip_runtime_only'
                    row['delete_error'] = 'runtime_only/source!=file，管理 API 无法删除'
                    print(' [跳过] runtime_only 或非磁盘文件，无法通过 /auth-files 删除', flush=True)
                elif not name.lower().endswith('.json'):
                    counts['备份失败'] += 1
                    row['delete_result'] = 'skip_no_json_name'
                    row['delete_error'] = '不是标准 .json 文件名，默认不删'
                    print(' [跳过] 不是 .json 文件', flush=True)
                else:
                    try:
                        backup_path, delete_resp = delete_auth_file(args, name, backup_root / 'delete-401')
                        counts['已删除'] += 1
                        row['delete_result'] = 'deleted'
                        row['backup_path'] = str(backup_path)
                        row['delete_response'] = delete_resp
                        clear_quota_state(state, name)
                        print(' [已删除] 备份路径: %s' % row['backup_path'], flush=True)
                    except Exception as e:
                        counts['删除失败'] += 1
                        row['delete_result'] = 'delete_failed'
                        row['delete_error'] = str(e)
                        print(' [删除失败] %s' % e, flush=True)

        results.append(row)

    for name in list((state.get('quota_accounts') or {}).keys()):
        if name not in name_to_item:
            clear_quota_state(state, name)
            counts['状态清理'] += 1

    if not args.dry_run:
        now = datetime.now(timezone.utc)
        for name, entry in sorted((state.get('quota_accounts') or {}).items()):
            item = name_to_item.get(name)
            if not item:
                continue
            due_at = parse_time(entry.get('next_revival_check_at'))
            if due_at and due_at > now:
                continue
            revival_row = run_revival_cycle(args, item, entry, counts, backup_root)
            results.append(revival_row)
            result_tag = revival_row.get('revival_result')
            if result_tag in ('enabled', 'deleted_on_refresh_failure', 'deleted_on_bad_probe', 'deleted_on_load_failure'):
                clear_quota_state(state, name)

    save_state(args.state_path, state)

    report = {
        'run_id': rid,
        'base_url': normalize_base_url(args.base_url),
        'dry_run': args.dry_run,
        'api_call': {
            'enabled': args.enable_api_call_check,
            'completed_in_this_process': bool(getattr(args, 'api_call_scan_completed', False)),
            'providers': args.api_call_providers,
            'url': args.api_call_url,
            'batch_size': args.api_call_max_per_run,
            'sleep_fixed': args.api_call_sleep,
            'sleep_min': args.api_call_sleep_min,
            'sleep_max': args.api_call_sleep_max,
        },
        'revival': {
            'wait_days': args.revival_wait_days,
            'probe_interval_hours': args.revival_probe_interval_hours,
            'state_path': str(args.state_path),
        },
        'results': results,
        'summary': counts,
        'state': state,
    }
    report_path = report_root / ('report-' + rid + '.json')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\n' + '=' * 60)
    print('【统计结果】')
    print('=' * 60)
    for key, value in counts.items():
        print(' %s: %d' % (key, value))

    print('\n【操作说明】')
    if args.dry_run:
        print(' ✅ 模拟运行模式 - 没有实际删除、禁用或刷新任何账号')
        if counts['待删除401'] > 0:
            print(' 📝 发现 %d 个 401 认证失败账号（去掉 --dry-run 后会备份并删除）' % counts['待删除401'])
        if counts['配额耗尽'] > 0:
            print(' 📝 发现 %d 个额度耗尽账号（去掉 --dry-run 后会调用 /auth-files/status 禁用）' % counts['配额耗尽'])
    else:
        print(' ✅ 已删除 %d 个 401 认证失败账号' % counts['已删除'])
        print(' ✅ 已禁用 %d 个额度耗尽账号' % counts['额度账号已禁用'])
        print(' ✅ 复活成功启用 %d 个账号' % counts['复活成功启用'])
        if counts['复活仍限额'] > 0:
            print(' 🕒 仍有 %d 个账号处于限额，已安排 12h 后再次 refresh + 测活' % counts['复活仍限额'])
        if counts['复活删除'] > 0:
            print(' 🗑️ 复活检查中删除 %d 个异常账号' % counts['复活删除'])
        if counts['删除失败'] > 0:
            print(' ⚠️ 有 %d 个账号删除失败，请查看报告' % counts['删除失败'])
        if counts['禁用失败'] > 0:
            print(' ⚠️ 有 %d 个额度账号禁用失败，请查看报告' % counts['禁用失败'])
        if counts['refresh失败'] > 0:
            print(' ⚠️ 有 %d 次 refresh 失败，请查看报告' % counts['refresh失败'])

    print('\n【报告文件】')
    print(' 📄 %s' % report_path)
    print('=' * 60, flush=True)
    return counts


def build_parser():
    ap = argparse.ArgumentParser(description='CLIProxyAPI 清理工具 - 删除 401 账号、禁用额度耗尽账号，并按 7 天/12 小时策略尝试复活')
    ap.add_argument('--base-url', default=os.environ.get('CLIPROXY_BASE_URL', DEFAULT_BASE_URL))
    ap.add_argument('--management-key', default=os.environ.get('CLIPROXY_MANAGEMENT_KEY', DEFAULT_MANAGEMENT_KEY))
    ap.add_argument('--timeout', type=int, default=int(os.environ.get('CLIPROXY_TIMEOUT', '20')))
    ap.add_argument('--enable-api-call-check', dest='enable_api_call_check', action='store_true', default=env_bool('CLIPROXY_ENABLE_API_CALL_CHECK', True), help='开启 /api-call 全量探测；本次脚本运行只会完整探测一遍')
    ap.add_argument('--disable-api-call-check', dest='enable_api_call_check', action='store_false', help='关闭 /api-call 全量探测')
    ap.add_argument('--api-call-url', default=os.environ.get('CLIPROXY_API_CALL_URL', DEFAULT_API_CALL_URL), help='主动探测时调用的上游 URL')
    ap.add_argument('--api-call-method', default=os.environ.get('CLIPROXY_API_CALL_METHOD', 'GET'), help='主动探测时使用的 HTTP 方法')
    ap.add_argument('--api-call-account-id', default=os.environ.get('CLIPROXY_API_CALL_ACCOUNT_ID', DEFAULT_API_CALL_ACCOUNT_ID), help='主动探测时附带的 Chatgpt-Account-Id（若 auth 文件内有 account_id 会优先使用文件值）')
    ap.add_argument('--api-call-user-agent', default=os.environ.get('CLIPROXY_API_CALL_USER_AGENT', DEFAULT_API_CALL_USER_AGENT), help='主动探测时附带的 User-Agent')
    ap.add_argument('--api-call-body', default=os.environ.get('CLIPROXY_API_CALL_BODY', ''), help='主动探测时透传到 api-call/直连测活的 data 字段')
    ap.add_argument('--api-call-providers', default=os.environ.get('CLIPROXY_API_CALL_PROVIDERS', DEFAULT_API_CALL_PROVIDERS), help='哪些 provider 需要做 /api-call 主动探测，逗号分隔；留空表示全部')
    ap.add_argument('--api-call-max-per-run', type=int, default=int(os.environ.get('CLIPROXY_API_CALL_MAX_PER_RUN', str(DEFAULT_API_CALL_MAX_PER_RUN))), help='每批最多探测多少个账号，最大 50')
    ap.add_argument('--api-call-sleep', type=float, default=None, help='固定批次等待秒数；如不设置则使用随机等待')
    ap.add_argument('--api-call-sleep-min', type=float, default=float(os.environ.get('CLIPROXY_API_CALL_SLEEP_MIN', str(DEFAULT_API_CALL_SLEEP_MIN))), help='批次随机等待最小秒数')
    ap.add_argument('--api-call-sleep-max', type=float, default=float(os.environ.get('CLIPROXY_API_CALL_SLEEP_MAX', str(DEFAULT_API_CALL_SLEEP_MAX))), help='批次随机等待最大秒数')
    ap.add_argument('--revival-wait-days', type=int, default=int(os.environ.get('CLIPROXY_REVIVAL_WAIT_DAYS', str(DEFAULT_REVIVAL_WAIT_DAYS))), help='额度耗尽账号禁用后，等待多少天再用 refresh token 尝试复活')
    ap.add_argument('--revival-probe-interval-hours', type=int, default=int(os.environ.get('CLIPROXY_REVIVAL_PROBE_INTERVAL_HOURS', str(DEFAULT_REVIVAL_INTERVAL_HOURS))), help='7 天后仍未恢复时，后续每隔多少小时再次 refresh + 测活')
    ap.add_argument('--state-file', default=os.environ.get('CLIPROXY_STATE_FILE', str(script_dir() / DEFAULT_STATE_FILE)), help='持久化状态文件路径')
    ap.add_argument('--dry-run', action='store_true', help='模拟运行，不实际删除、禁用或刷新')
    ap.add_argument('--interval', type=int, default=60, help='检测间隔时间（秒），默认 60 秒')
    ap.add_argument('--once', action='store_true', help='只执行一次，不循环')
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()

    args.base_url = normalize_base_url(args.base_url)
    args.api_call_provider_set = parse_csv_set(args.api_call_providers)
    args.api_call_max_per_run = max(0, min(int(args.api_call_max_per_run), DEFAULT_API_CALL_MAX_PER_RUN))
    if args.api_call_sleep is not None:
        args.api_call_sleep = max(0.0, float(args.api_call_sleep))
    args.api_call_sleep_min = max(0.0, float(args.api_call_sleep_min))
    args.api_call_sleep_max = max(args.api_call_sleep_min, float(args.api_call_sleep_max))
    args.api_call_scan_completed = False
    args.revival_wait_days = max(0, int(args.revival_wait_days))
    args.revival_probe_interval_hours = max(1, int(args.revival_probe_interval_hours))
    args.state_path = Path(args.state_file).expanduser().resolve()
    backup_root_env = os.environ.get('CLIPROXY_BACKUP_ROOT')
    report_root_env = os.environ.get('CLIPROXY_REPORT_ROOT')
    args.backup_root = Path(backup_root_env).expanduser().resolve() if backup_root_env else (script_dir() / 'backups' / 'cliproxyapi-auth-cleaner')
    args.report_root = Path(report_root_env).expanduser().resolve() if report_root_env else (script_dir() / 'reports' / 'cliproxyapi-auth-cleaner')

    if not args.management_key.strip():
        print('❌ 缺少 management key：请先设置 CLIPROXY_MANAGEMENT_KEY', file=sys.stderr)
        return 2

    print('\n' + '=' * 60)
    print('【CLIProxyAPI 清理工具】')
    print('=' * 60)
    print(' 🎯 清理目标: 删除 401 认证失败账号 + 禁用额度耗尽账号 + 7 天后 refresh 复活 + 每 12h 测活')
    print(' 🌐 管理地址: %s' % args.base_url)
    if args.enable_api_call_check:
        providers_desc = args.api_call_providers if args.api_call_providers.strip() else '全部 provider'
        sleep_desc = '固定 %.1f 秒' % args.api_call_sleep if args.api_call_sleep is not None else '随机 %.1f-%.1f 秒' % (args.api_call_sleep_min, args.api_call_sleep_max)
        print(' 🔎 主动探测: 已开启 /v0/management/api-call')
        print(' - 上游 URL: %s' % args.api_call_url)
        print(' - 适用 provider: %s' % providers_desc)
        print(' - 单批最多: %s 个' % args.api_call_max_per_run)
        print(' - 批次间隔: %s' % sleep_desc)
        print(' - 探测策略: 本次运行只完整扫描一遍，后续轮次不再重复')
    else:
        print(' 🔎 主动探测: 已关闭 /v0/management/api-call')
    print(' ♻️ 复活策略: 禁用后等待 %d 天，随后每 %d 小时执行一次 refresh + 测活' % (
        args.revival_wait_days, args.revival_probe_interval_hours,
    ))
    if args.dry_run:
        print(' 🔍 运行模式: 模拟运行（不会实际删除、禁用或刷新）')
    else:
        print(' ⚡ 运行模式: 实际运行（将删除/禁用/刷新符合条件的账号）')
    print('=' * 60 + '\n')

    if args.once:
        run_check(args)
        return 0

    print('🔄 自动循环检测模式，间隔 %d 秒' % args.interval)
    print('💡 提示: 按 Ctrl+C 停止程序\n')

    loop_count = 0
    try:
        while True:
            loop_count += 1
            print('\n' + '🔵' * 30)
            print('【第 %d 次检测】%s' % (loop_count, get_current_time()))
            print('🔵' * 30)
            try:
                run_check(args)
            except Exception as e:
                print('❌ 检测过程中发生异常: %s' % e, flush=True)
            print('\n⏰ 等待 %d 秒后进行下一次检测...' % args.interval)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print('\n\n🛑 用户中断程序，共执行 %d 次检测' % loop_count)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
