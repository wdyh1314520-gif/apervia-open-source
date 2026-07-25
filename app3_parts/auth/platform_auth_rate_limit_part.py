# Rate-limit configuration, automatic cooldowns, and request gate helpers. Loaded after auth core and before runtime init/routes.

RATE_LIMIT_CONFIG_FILE = _app_data_path('rate_limit_store.json')
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_CONFIG: dict = {}
_RATE_LIMIT_STATE = {
    'buckets': {},
    'blocks': {},
    'stats': {},
    'events': [],
    'violations': {},
    'updated_at': 0.0,
}
_RATE_LIMIT_ENDPOINT_ORDER = [
    'chat_stream',
    'upload',
    'auth_status',
    'auth_password_login',
    'auth_register',
]
_RATE_LIMIT_ENDPOINT_LABELS = {
    'chat_stream': '聊天',
    'upload': '上传',
    'auth_status': '登录状态',
    'auth_password_login': '密码登录',
    'auth_register': '注册',
}
_RATE_LIMIT_REPEAT_BLOCK_WINDOW_S = 1800
_RATE_LIMIT_REPEAT_BLOCK_MAX_MULTIPLIER = 8


def _json_clone(data):
    try:
        return json.loads(json.dumps(data, ensure_ascii=False))
    except Exception:
        return data


def _rate_limit_default_config() -> dict:
    return {
        'global_enabled': True,
        'events_keep': 120,
        'updated_at': _utc_ts(),
        'endpoints': {
            'chat_stream': {
                'label': '聊天', 'enabled': True,
                'ip_limit': 18, 'ip_window_s': 60,
                'session_limit': 14, 'session_window_s': 60,
                'account_limit': 12, 'account_window_s': 60,
                'block_s': 120,
            },
            'upload': {
                'label': '上传', 'enabled': True,
                'ip_limit': 16, 'ip_window_s': 60,
                'session_limit': 12, 'session_window_s': 60,
                'account_limit': 10, 'account_window_s': 60,
                'block_s': 120,
            },
            'auth_status': {
                'label': '登录状态', 'enabled': True,
                'ip_limit': 60, 'ip_window_s': 60,
                'session_limit': 30, 'session_window_s': 60,
                'account_limit': 0, 'account_window_s': 0,
                'block_s': 60,
            },
            'auth_password_login': {
                'label': '密码登录', 'enabled': True,
                'ip_limit': 12, 'ip_window_s': 300,
                'session_limit': 10, 'session_window_s': 300,
                'account_limit': 8, 'account_window_s': 300,
                'block_s': 900,
            },
            'auth_register': {
                'label': '注册', 'enabled': True,
                'ip_limit': 5, 'ip_window_s': 3600,
                'session_limit': 4, 'session_window_s': 3600,
                'account_limit': 2, 'account_window_s': 3600,
                'block_s': 3600,
            },
        },
    }


def _rate_limit_load() -> None:
    defaults = _rate_limit_default_config()
    loaded = {}
    try:
        if os.path.exists(RATE_LIMIT_CONFIG_FILE):
            with open(RATE_LIMIT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f) or {}
    except Exception:
        app_logger.exception('[rate_limit] load_failed')
        loaded = {}
    if not isinstance(loaded, dict):
        loaded = {}
    loaded_endpoints = loaded.get('endpoints') if isinstance(loaded.get('endpoints'), dict) else {}
    default_endpoints = dict(defaults.get('endpoints') or {})
    config = {
        'global_enabled': bool(loaded.get('global_enabled', defaults['global_enabled'])),
        'events_keep': _rate_limit_int(loaded.get('events_keep'), defaults['events_keep'], 20, 400),
        'updated_at': float(loaded.get('updated_at') or _utc_ts()),
    }
    config['endpoints'] = {
        name: {
            key: dict(loaded_endpoints.get(name) or {}).get(key, default_value)
            for key, default_value in dict(default_endpoints.get(name) or {}).items()
        }
        for name in _RATE_LIMIT_ENDPOINT_ORDER
    }
    rewrite_required = loaded != config
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_CONFIG.clear()
        _RATE_LIMIT_CONFIG.update(config)
        _RATE_LIMIT_STATE['updated_at'] = _utc_ts()
    if rewrite_required:
        # 只持久化当前支持的字段，启动时清除旧版废弃封禁和其他无效配置。
        _rate_limit_save()


def _rate_limit_save() -> None:
    with _RATE_LIMIT_LOCK:
        payload = _json_clone(_RATE_LIMIT_CONFIG)
        payload['updated_at'] = _utc_ts()
        _RATE_LIMIT_CONFIG['updated_at'] = payload['updated_at']
    tmp = RATE_LIMIT_CONFIG_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, RATE_LIMIT_CONFIG_FILE)
    except Exception:
        app_logger.exception('[rate_limit] save_failed')
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _rate_limit_scope_label(scope: str) -> str:
    return {'ip': 'IP', 'session': '会话', 'account': '账号'}.get(str(scope or '').strip(), str(scope or '').strip())


def _rate_limit_key_display(scope: str, key: str) -> str:
    raw = str(key or '').strip()
    if not raw:
        return '-'
    if scope == 'account':
        masked = _mask_login_email(raw)
        return masked or raw
    if scope == 'session':
        return _auth_session_short_id(raw)
    return raw


def _rate_limit_current_session_id() -> str:
    return _auth_current_session_key()


def _rate_limit_current_account(email: str = '') -> str:
    explicit = _normalize_login_email(email)
    if explicit:
        return explicit
    try:
        return _current_login_email()
    except Exception:
        return ''


def _rate_limit_build_subjects(email: str = '') -> dict:
    return {
        'ip': str(_client_ip() or '').strip(),
        'session': _rate_limit_current_session_id(),
        'account': _rate_limit_current_account(email),
    }


def _rate_limit_prune_locked(now: float | None = None) -> None:
    now = float(now or _utc_ts())
    buckets = _RATE_LIMIT_STATE.setdefault('buckets', {})
    for bucket_key, bucket in list(buckets.items()):
        hits = [float(ts) for ts in (bucket.get('hits') or []) if float(ts) > now - float(bucket.get('window_s') or 0)]
        if hits:
            bucket['hits'] = hits
        else:
            buckets.pop(bucket_key, None)
    blocks = _RATE_LIMIT_STATE.setdefault('blocks', {})
    for block_key, item in list(blocks.items()):
        if float((item or {}).get('until') or 0) <= now:
            blocks.pop(block_key, None)
    violations = _RATE_LIMIT_STATE.setdefault('violations', {})
    repeat_window_s = max(60, int(_RATE_LIMIT_REPEAT_BLOCK_WINDOW_S or 1800))
    for violation_key, marks in list(violations.items()):
        kept = [float(ts) for ts in (marks or []) if float(ts) > now - repeat_window_s]
        if kept:
            violations[violation_key] = kept[-8:]
        else:
            violations.pop(violation_key, None)
    keep = max(20, min(int((_RATE_LIMIT_CONFIG.get('events_keep') or 120)), 400))
    events = _RATE_LIMIT_STATE.setdefault('events', [])
    if len(events) > keep:
        del events[:-keep]


def _rate_limit_stats_entry(endpoint: str) -> dict:
    stats = _RATE_LIMIT_STATE.setdefault('stats', {})
    entry = stats.get(endpoint)
    if not isinstance(entry, dict):
        entry = {
            'allowed': 0,
            'blocked': 0,
            'last_allowed_at': 0.0,
            'last_blocked_at': 0.0,
            'last_reason': '',
        }
        stats[endpoint] = entry
    return entry


def _rate_limit_violation_multiplier(endpoint: str, scope: str, key: str, now: float | None = None) -> tuple[int, int]:
    now = float(now or _utc_ts())
    violation_key = f'{endpoint}|{scope}|{key}'
    violations = _RATE_LIMIT_STATE.setdefault('violations', {})
    repeat_window_s = max(60, int(_RATE_LIMIT_REPEAT_BLOCK_WINDOW_S or 1800))
    kept = [float(ts) for ts in (violations.get(violation_key) or []) if float(ts) > now - repeat_window_s]
    prior_count = len(kept)
    multiplier = 1
    max_multiplier = max(1, int(_RATE_LIMIT_REPEAT_BLOCK_MAX_MULTIPLIER or 8))
    for _ in range(prior_count):
        multiplier = min(max_multiplier, multiplier * 2)
    violations[violation_key] = kept
    return multiplier, repeat_window_s


def _rate_limit_record_event(endpoint: str, scope: str, key: str, limit: int, window_s: int, block_s: int, remaining_s: int, reason: str, *, multiplier: int = 1, base_block_s: int = 0) -> None:
    now = _utc_ts()
    events = _RATE_LIMIT_STATE.setdefault('events', [])
    endpoint_name = str(endpoint or '').strip()
    endpoint_label = '全部接口' if endpoint_name == '*' else _RATE_LIMIT_ENDPOINT_LABELS.get(endpoint_name, endpoint_name)
    event = {
        'ts': now,
        'ts_text': _fmt_ts(now),
        'endpoint': endpoint_name,
        'endpoint_label': endpoint_label,
        'scope': scope,
        'scope_label': _rate_limit_scope_label(scope),
        'key_display': _rate_limit_key_display(scope, key),
        'limit': int(limit or 0),
        'window_s': int(window_s or 0),
        'block_s': int(block_s or 0),
        'base_block_s': int(base_block_s or block_s or 0),
        'multiplier': max(1, int(multiplier or 1)),
        'remaining_s': int(max(1, remaining_s or 0)),
        'reason': str(reason or 'too_many_requests'),
    }
    events.append(event)
    keep = max(20, min(int((_RATE_LIMIT_CONFIG.get('events_keep') or 120)), 400))
    if len(events) > keep:
        del events[:-keep]


def _rate_limit_block_response(endpoint: str, remaining_s: int, scope: str, reason: str) -> Response:
    endpoint_label = _RATE_LIMIT_ENDPOINT_LABELS.get(endpoint, endpoint)
    retry_after = max(1, int(math.ceil(float(remaining_s or 1))))
    resp = jsonify({
        'error': 'rate_limited',
        'message': f'{endpoint_label}请求过于频繁，请 {retry_after} 秒后再试',
        'retry_after': retry_after,
        'endpoint': endpoint,
        'endpoint_label': endpoint_label,
        'scope': scope,
        'scope_label': _rate_limit_scope_label(scope),
        'reason': str(reason or 'too_many_requests'),
    })
    resp.status_code = 429
    try:
        resp.headers['Retry-After'] = str(retry_after)
    except Exception:
        pass
    return resp


def _apply_rate_limit(endpoint: str, *, email: str = '') -> Response | None:
    now = _utc_ts()
    with _RATE_LIMIT_LOCK:
        _rate_limit_prune_locked(now)
        if not bool(_RATE_LIMIT_CONFIG.get('global_enabled', True)):
            return None
        endpoint_cfg = dict(((_RATE_LIMIT_CONFIG.get('endpoints') or {}).get(endpoint) or {}))
        if not endpoint_cfg or not bool(endpoint_cfg.get('enabled', True)):
            return None
        subjects = _rate_limit_build_subjects(email)
        rules = []
        for scope in ('ip', 'session', 'account'):
            key = str(subjects.get(scope) or '').strip()
            limit = int(endpoint_cfg.get(f'{scope}_limit') or 0)
            window_s = int(endpoint_cfg.get(f'{scope}_window_s') or 0)
            if key and limit > 0 and window_s > 0:
                rules.append((scope, key, limit, window_s))
        if not rules:
            return None
        blocks = _RATE_LIMIT_STATE.setdefault('blocks', {})
        for scope, key, limit, window_s in rules:
            block_key = f'{endpoint}|{scope}|{key}'
            block = dict(blocks.get(block_key) or {})
            until = float(block.get('until') or 0)
            if until > now:
                remaining_s = int(math.ceil(until - now))
                stats = _rate_limit_stats_entry(endpoint)
                stats['blocked'] = int(stats.get('blocked') or 0) + 1
                stats['last_blocked_at'] = now
                stats['last_reason'] = str(block.get('reason') or 'blocked')
                _RATE_LIMIT_STATE['updated_at'] = now
                _rate_limit_record_event(
                    endpoint,
                    scope,
                    key,
                    limit,
                    window_s,
                    int(block.get('block_s') or endpoint_cfg.get('block_s') or 0),
                    remaining_s,
                    str(block.get('reason') or 'blocked'),
                    multiplier=int(block.get('multiplier') or 1),
                    base_block_s=int(block.get('base_block_s') or block.get('block_s') or endpoint_cfg.get('block_s') or 0),
                )
                return _rate_limit_block_response(endpoint, remaining_s, scope, str(block.get('reason') or 'blocked'))
        buckets = _RATE_LIMIT_STATE.setdefault('buckets', {})
        base_block_s = max(1, int(endpoint_cfg.get('block_s') or 60))
        for scope, key, limit, window_s in rules:
            bucket_key = f'{endpoint}|{scope}|{key}|{window_s}'
            bucket = buckets.setdefault(bucket_key, {'hits': [], 'window_s': int(window_s)})
            hits = [float(ts) for ts in (bucket.get('hits') or []) if float(ts) > now - float(window_s)]
            bucket['hits'] = hits
            if len(hits) + 1 > int(limit):
                multiplier, repeat_window_s = _rate_limit_violation_multiplier(endpoint, scope, key, now)
                block_s = min(86400, max(1, int(base_block_s * multiplier)))
                until = now + block_s
                reason = f'{_rate_limit_scope_label(scope)}超过 {limit}/{window_s}s'
                if multiplier > 1:
                    reason += f'（重复触发，冷却×{multiplier}，参考窗口 {repeat_window_s}s）'
                blocks[f'{endpoint}|{scope}|{key}'] = {
                    'until': until,
                    'scope': scope,
                    'key': key,
                    'endpoint': endpoint,
                    'reason': reason,
                    'block_s': block_s,
                    'base_block_s': base_block_s,
                    'multiplier': multiplier,
                }
                violation_key = f'{endpoint}|{scope}|{key}'
                violations = _RATE_LIMIT_STATE.setdefault('violations', {})
                kept = list(violations.get(violation_key) or [])
                kept.append(now)
                violations[violation_key] = kept[-8:]
                stats = _rate_limit_stats_entry(endpoint)
                stats['blocked'] = int(stats.get('blocked') or 0) + 1
                stats['last_blocked_at'] = now
                stats['last_reason'] = reason
                _RATE_LIMIT_STATE['updated_at'] = now
                _rate_limit_record_event(endpoint, scope, key, limit, window_s, block_s, block_s, reason, multiplier=multiplier, base_block_s=base_block_s)
                return _rate_limit_block_response(endpoint, block_s, scope, reason)
        for scope, key, _limit, window_s in rules:
            bucket_key = f'{endpoint}|{scope}|{key}|{window_s}'
            bucket = buckets.setdefault(bucket_key, {'hits': [], 'window_s': int(window_s)})
            hits = [float(ts) for ts in (bucket.get('hits') or []) if float(ts) > now - float(window_s)]
            hits.append(now)
            bucket['hits'] = hits
            bucket['window_s'] = int(window_s)
        stats = _rate_limit_stats_entry(endpoint)
        stats['allowed'] = int(stats.get('allowed') or 0) + 1
        stats['last_allowed_at'] = now
        _RATE_LIMIT_STATE['updated_at'] = now
    return None


def _rate_limit_active_blocks_snapshot(now: float | None = None) -> list[dict]:
    now = float(now or _utc_ts())
    blocks = _RATE_LIMIT_STATE.setdefault('blocks', {})
    items = []
    for item in list(blocks.values()):
        until = float((item or {}).get('until') or 0)
        remaining_s = int(math.ceil(until - now))
        if remaining_s <= 0:
            continue
        endpoint = str((item or {}).get('endpoint') or '')
        scope = str((item or {}).get('scope') or '')
        key = str((item or {}).get('key') or '')
        endpoint_label = '全部接口' if endpoint == '*' else _RATE_LIMIT_ENDPOINT_LABELS.get(endpoint, endpoint)
        items.append({
            'endpoint': endpoint,
            'endpoint_label': endpoint_label,
            'scope': scope,
            'scope_label': _rate_limit_scope_label(scope),
            'key_display': _rate_limit_key_display(scope, key),
            'remaining_s': remaining_s,
            'until_text': _fmt_ts(until),
            'reason': str((item or {}).get('reason') or ''),
            'block_s': int((item or {}).get('block_s') or 0),
            'base_block_s': int((item or {}).get('base_block_s') or (item or {}).get('block_s') or 0),
            'multiplier': max(1, int((item or {}).get('multiplier') or 1)),
        })
    items.sort(key=lambda x: int(x.get('remaining_s') or 0), reverse=True)
    return items


def _rate_limit_public_state() -> dict:
    now = _utc_ts()
    with _RATE_LIMIT_LOCK:
        _rate_limit_prune_locked(now)
        cfg = _json_clone(_RATE_LIMIT_CONFIG)
        stats = _json_clone(_RATE_LIMIT_STATE.get('stats') or {})
        events = list(_RATE_LIMIT_STATE.get('events') or [])
        updated_at = float(_RATE_LIMIT_STATE.get('updated_at') or now)
        active_blocks = _rate_limit_active_blocks_snapshot(now)
    endpoints = []
    total_allowed = 0
    total_blocked = 0
    for name in _RATE_LIMIT_ENDPOINT_ORDER:
        ep_cfg = dict(((cfg.get('endpoints') or {}).get(name) or {}))
        stat = dict(stats.get(name) or {})
        active_count = sum(1 for item in active_blocks if item.get('endpoint') == name)
        allowed = int(stat.get('allowed') or 0)
        blocked = int(stat.get('blocked') or 0)
        total_allowed += allowed
        total_blocked += blocked
        endpoints.append({
            'name': name,
            'label': ep_cfg.get('label') or _RATE_LIMIT_ENDPOINT_LABELS.get(name, name),
            'enabled': bool(ep_cfg.get('enabled', True)),
            'ip_limit': int(ep_cfg.get('ip_limit') or 0),
            'ip_window_s': int(ep_cfg.get('ip_window_s') or 0),
            'session_limit': int(ep_cfg.get('session_limit') or 0),
            'session_window_s': int(ep_cfg.get('session_window_s') or 0),
            'account_limit': int(ep_cfg.get('account_limit') or 0),
            'account_window_s': int(ep_cfg.get('account_window_s') or 0),
            'block_s': int(ep_cfg.get('block_s') or 0),
            'allowed': allowed,
            'blocked': blocked,
            'active_blocks': active_count,
            'last_allowed_at': _fmt_ts(stat.get('last_allowed_at')),
            'last_blocked_at': _fmt_ts(stat.get('last_blocked_at')),
            'last_reason': str(stat.get('last_reason') or ''),
        })
    return {
        'ok': True,
        'global_enabled': bool(cfg.get('global_enabled', True)),
        'events_keep': int(cfg.get('events_keep') or 120),
        'updated_at': _fmt_ts(updated_at),
        'summary': {
            'endpoint_count': len(endpoints),
            'total_allowed': total_allowed,
            'total_blocked': total_blocked,
            'active_blocks': len(active_blocks),
        },
        'endpoints': endpoints,
        'active_blocks': active_blocks[:50],
        'recent_events': list(reversed(events[-40:])),
    }


def _rate_limit_int(value, default: int, minimum: int = 0, maximum: int = 86400) -> int:
    try:
        num = int(str(value).strip())
    except Exception:
        num = int(default)
    return max(int(minimum), min(int(maximum), num))


def _rate_limit_update_config(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError('invalid_payload')
    with _RATE_LIMIT_LOCK:
        if 'global_enabled' in payload:
            _RATE_LIMIT_CONFIG['global_enabled'] = bool(payload.get('global_enabled'))
        if 'events_keep' in payload:
            _RATE_LIMIT_CONFIG['events_keep'] = _rate_limit_int(payload.get('events_keep'), int(_RATE_LIMIT_CONFIG.get('events_keep') or 120), 20, 400)
        incoming = payload.get('endpoints') or {}
        if isinstance(incoming, dict):
            endpoints = _RATE_LIMIT_CONFIG.setdefault('endpoints', {})
            for endpoint, item in incoming.items():
                if endpoint not in _RATE_LIMIT_ENDPOINT_ORDER or not isinstance(item, dict):
                    continue
                ep = endpoints.setdefault(endpoint, {})
                if 'enabled' in item:
                    ep['enabled'] = bool(item.get('enabled'))
                for field, mx in (
                    ('ip_limit', 500), ('ip_window_s', 86400),
                    ('session_limit', 500), ('session_window_s', 86400),
                    ('account_limit', 500), ('account_window_s', 86400),
                    ('block_s', 86400),
                ):
                    if field in item:
                        ep[field] = _rate_limit_int(item.get(field), int(ep.get(field) or 0), 0, mx)
                ep['label'] = _RATE_LIMIT_ENDPOINT_LABELS.get(endpoint, ep.get('label') or endpoint)
        _RATE_LIMIT_CONFIG['updated_at'] = _utc_ts()
        _RATE_LIMIT_STATE['updated_at'] = _utc_ts()
    _rate_limit_save()
    return _rate_limit_public_state()


def _rate_limit_reset(clear_blocks: bool = True, clear_events: bool = True, clear_stats: bool = False) -> dict:
    with _RATE_LIMIT_LOCK:
        if clear_blocks:
            _RATE_LIMIT_STATE['blocks'] = {}
            _RATE_LIMIT_STATE['buckets'] = {}
            _RATE_LIMIT_STATE['violations'] = {}
        if clear_events:
            _RATE_LIMIT_STATE['events'] = []
        if clear_stats:
            _RATE_LIMIT_STATE['stats'] = {}
        _RATE_LIMIT_STATE['updated_at'] = _utc_ts()
    return _rate_limit_public_state()
