# account online presence state keyed by the server-side identity session.

AUTH_ACCOUNT_ONLINE_WINDOW_S = max(20.0, float(app_getenv('AUTH_ACCOUNT_ONLINE_WINDOW_S', '35') or 35))
AUTH_ACCOUNT_ONLINE_PRUNE_S = max(1800.0, AUTH_ACCOUNT_ONLINE_WINDOW_S * 12.0)
_AUTH_PRESENCE_LOCK = threading.Lock()
_AUTH_PRESENCE_STATE = {
    'accounts': {},
    'updated_at': 0.0,
}

def _auth_presence_prune_locked(now_ts: float | None = None) -> None:
    now = float(now_ts or _utc_ts())
    cutoff = now - float(AUTH_ACCOUNT_ONLINE_PRUNE_S)
    accounts = _AUTH_PRESENCE_STATE.setdefault('accounts', {})
    changed = False
    for email in list(accounts.keys()):
        acc = dict(accounts.get(email) or {})
        sessions = dict(acc.get('sessions') or {})
        for session_id in list(sessions.keys()):
            rec = dict(sessions.get(session_id) or {})
            try:
                last_seen = float(rec.get('last_seen') or 0.0)
            except Exception:
                last_seen = 0.0
            if last_seen < cutoff:
                sessions.pop(session_id, None)
                changed = True
        if sessions:
            latest_seen = max(float((item or {}).get('last_seen') or 0.0) for item in sessions.values())
            acc['sessions'] = sessions
            acc['updated_at'] = latest_seen
            accounts[email] = acc
        else:
            accounts.pop(email, None)
            changed = True
    if changed:
        _AUTH_PRESENCE_STATE['updated_at'] = now


def _auth_presence_mark(email: str, session_id: str = '', path: str = '') -> dict:
    normalized = _normalize_login_email(email)
    if not normalized:
        return {}
    raw_session_id = str(session_id or _auth_current_session_key() or '').strip()
    if not raw_session_id:
        return {}
    now = _utc_ts()
    ip = _client_ip()
    ua = str(request.headers.get('User-Agent') or '').strip()[:240]
    req_path = str(path or request.path or '').strip()[:120]
    with _AUTH_PRESENCE_LOCK:
        _auth_presence_prune_locked(now)
        accounts = _AUTH_PRESENCE_STATE.setdefault('accounts', {})
        acc = dict(accounts.get(normalized) or {})
        sessions = dict(acc.get('sessions') or {})
        rec = dict(sessions.get(raw_session_id) or {})
        if not rec.get('first_seen'):
            rec['first_seen'] = now
        rec['session_id'] = raw_session_id
        rec['short_session_id'] = _auth_session_short_id(raw_session_id)
        rec['email'] = normalized
        rec['last_seen'] = now
        rec['ip'] = ip
        rec['ua'] = ua
        rec['path'] = req_path
        sessions[raw_session_id] = rec
        acc['sessions'] = sessions
        acc['updated_at'] = now
        accounts[normalized] = acc
        _AUTH_PRESENCE_STATE['updated_at'] = now
    return _auth_presence_public_map([normalized]).get(normalized) or {}


def _auth_presence_remove_session(session_id: str, email: str = '') -> None:
    raw_session_id = str(session_id or '').strip()
    normalized = _normalize_login_email(email)
    if not raw_session_id:
        return
    with _AUTH_PRESENCE_LOCK:
        accounts = _AUTH_PRESENCE_STATE.setdefault('accounts', {})
        candidates = [normalized] if normalized else list(accounts.keys())
        changed = False
        for account_email in list(candidates):
            acc = dict(accounts.get(account_email) or {})
            sessions = dict(acc.get('sessions') or {})
            if raw_session_id in sessions:
                sessions.pop(raw_session_id, None)
                changed = True
                if sessions:
                    latest_seen = max(float((item or {}).get('last_seen') or 0.0) for item in sessions.values())
                    acc['sessions'] = sessions
                    acc['updated_at'] = latest_seen
                    accounts[account_email] = acc
                else:
                    accounts.pop(account_email, None)
        if changed:
            _AUTH_PRESENCE_STATE['updated_at'] = _utc_ts()


def _auth_presence_clear_account(email: str) -> None:
    normalized = _normalize_login_email(email)
    if not normalized:
        return
    with _AUTH_PRESENCE_LOCK:
        accounts = _AUTH_PRESENCE_STATE.setdefault('accounts', {})
        if normalized in accounts:
            accounts.pop(normalized, None)
            _AUTH_PRESENCE_STATE['updated_at'] = _utc_ts()


def _auth_presence_public_map(emails: list[str] | None = None) -> dict[str, dict]:
    now = _utc_ts()
    normalized_targets = None
    if emails is not None:
        normalized_targets = {
            _normalize_login_email(email)
            for email in (emails or [])
            if _normalize_login_email(email)
        }
    with _AUTH_PRESENCE_LOCK:
        _auth_presence_prune_locked(now)
        accounts = dict(_AUTH_PRESENCE_STATE.get('accounts') or {})
    online_cutoff = now - float(AUTH_ACCOUNT_ONLINE_WINDOW_S)
    out: dict[str, dict] = {}
    for email, acc in accounts.items():
        normalized = _normalize_login_email(email)
        if not normalized:
            continue
        if normalized_targets is not None and normalized not in normalized_targets:
            continue
        sessions = [dict(item or {}) for item in (dict(acc or {}).get('sessions') or {}).values()]
        sessions.sort(key=lambda item: float(item.get('last_seen') or 0.0), reverse=True)
        latest = sessions[0] if sessions else {}
        online_sessions = [item for item in sessions if float(item.get('last_seen') or 0.0) >= online_cutoff]
        out[normalized] = {
            'online': bool(online_sessions),
            'online_text': '在线' if online_sessions else '离线',
            'online_session_count': len(online_sessions),
            'last_active_at': _fmt_ts(latest.get('last_seen')),
            'last_active_ts': float(latest.get('last_seen') or 0.0),
            'recent_active_ip': str(latest.get('ip') or '').strip(),
            'recent_active_session': str(latest.get('short_session_id') or _auth_session_short_id(str(latest.get('session_id') or '')) or '').strip(),
        }
    if normalized_targets is not None:
        for normalized in normalized_targets:
            out.setdefault(normalized, {
                'online': False,
                'online_text': '离线',
                'online_session_count': 0,
                'last_active_at': '',
                'last_active_ts': 0.0,
                'recent_active_ip': '',
                'recent_active_session': '',
            })
    return out


def _auth_presence_other_active_session(email: str, current_session_id: str = '') -> dict:
    normalized = _normalize_login_email(email)
    current_session = str(current_session_id or '').strip()
    if not normalized:
        return {}
    now = _utc_ts()
    online_cutoff = now - float(AUTH_ACCOUNT_ONLINE_WINDOW_S)
    with _AUTH_PRESENCE_LOCK:
        _auth_presence_prune_locked(now)
        accounts = _AUTH_PRESENCE_STATE.get('accounts') or {}
        acc = dict(accounts.get(normalized) or {})
        sessions = [dict(item or {}) for item in (dict(acc or {}).get('sessions') or {}).values()]
    online_sessions = []
    for item in sessions:
        session_id = str(item.get('session_id') or '').strip()
        if not session_id or (current_session and session_id == current_session):
            continue
        try:
            last_seen = float(item.get('last_seen') or 0.0)
        except Exception:
            last_seen = 0.0
        if last_seen < online_cutoff:
            continue
        item['session_id'] = session_id
        online_sessions.append(item)
    if not online_sessions:
        return {}
    online_sessions.sort(key=lambda item: float(item.get('last_seen') or 0.0), reverse=True)
    latest = online_sessions[0]
    return {
        'conflict': True,
        'session_id': str(latest.get('session_id') or '').strip(),
        'short_session_id': str(latest.get('short_session_id') or _auth_session_short_id(str(latest.get('session_id') or '')) or '').strip(),
        'last_active_at': _fmt_ts(latest.get('last_seen')),
        'ip': str(latest.get('ip') or '').strip(),
        'online_session_count': len(online_sessions),
    }
