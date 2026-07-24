"""Account records, deletion audit, export, and cleanup storage."""

def _auth_users_load() -> None:
    state = {'users': {}, 'updated_at': _utc_ts()}
    try:
        if os.path.exists(AUTH_USERS_FILE):
            with open(AUTH_USERS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f) or {}
            if isinstance(loaded, dict):
                users = loaded.get('users') or {}
                if isinstance(users, dict):
                    clean = {}
                    for email, rec in users.items():
                        norm = _normalize_login_email(email or (rec or {}).get('email') or '')
                        if not norm or '@' not in norm:
                            continue
                        obj = dict(rec or {})
                        obj['email'] = norm
                        obj['password_hash'] = str(obj.get('password_hash') or '').strip()
                        obj['password_salt'] = str(obj.get('password_salt') or '').strip()
                        obj['enabled'] = bool(obj.get('enabled', True))
                        obj['created_at'] = float(obj.get('created_at') or _utc_ts())
                        obj['updated_at'] = float(obj.get('updated_at') or obj['created_at'])
                        obj['last_login_at'] = float(obj.get('last_login_at') or 0)
                        obj['last_login_ip'] = str(obj.get('last_login_ip') or '').strip()
                        obj['blacklisted'] = bool(obj.get('blacklisted'))
                        obj['blacklist_reason'] = str(obj.get('blacklist_reason') or '').strip()[:120]
                        obj['blacklisted_at'] = float(obj.get('blacklisted_at') or 0)
                        obj['blacklist_expires_at'] = float(obj.get('blacklist_expires_at') or 0)
                        obj['blacklist_permanent'] = bool(obj.get('blacklist_permanent'))
                        obj['blacklist_permanent_at'] = float(obj.get('blacklist_permanent_at') or 0)
                        obj['deleted'] = bool(obj.get('deleted'))
                        obj['deleted_at'] = float(obj.get('deleted_at') or 0)
                        obj['delete_pending'] = bool(obj.get('delete_pending'))
                        obj['delete_requested_at'] = float(obj.get('delete_requested_at') or obj.get('deleted_at') or 0)
                        obj['delete_scheduled_at'] = float(obj.get('delete_scheduled_at') or 0)
                        obj['delete_finalized_at'] = float(obj.get('delete_finalized_at') or 0)
                        obj['delete_reason'] = str(obj.get('delete_reason') or '').strip()[:120]
                        clean[norm] = obj
                    state['users'] = clean
                try:
                    state['updated_at'] = float(loaded.get('updated_at') or _utc_ts())
                except Exception:
                    state['updated_at'] = _utc_ts()
    except Exception:
        app_logger.exception('[auth_users] load_failed')
    with _AUTH_USERS_LOCK:
        _AUTH_USERS_STATE.clear()
        _AUTH_USERS_STATE.update(state)


def _auth_users_save() -> None:
    with _AUTH_USERS_LOCK:
        payload = {
            'users': _AUTH_USERS_STATE.get('users') or {},
            'updated_at': _utc_ts(),
        }
        _AUTH_USERS_STATE['updated_at'] = payload['updated_at']
    tmp = AUTH_USERS_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, AUTH_USERS_FILE)
    except Exception:
        app_logger.exception('[auth_users] save_failed')
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _auth_account_delete_log_load() -> None:
    state = {'events': [], 'updated_at': _utc_ts()}
    try:
        if os.path.exists(AUTH_ACCOUNT_DELETE_LOG_FILE):
            with open(AUTH_ACCOUNT_DELETE_LOG_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f) or {}
            if isinstance(loaded, dict):
                events = loaded.get('events') or []
                if isinstance(events, list):
                    clean = []
                    for raw in events[-AUTH_ACCOUNT_DELETE_LOG_MAX_EVENTS:]:
                        if not isinstance(raw, dict):
                            continue
                        email = _normalize_login_email(raw.get('email') or '')
                        event = {
                            'id': str(raw.get('id') or uuid.uuid4().hex),
                            'action': str(raw.get('action') or '').strip()[:64],
                            'email': email,
                            'actor': str(raw.get('actor') or '').strip()[:32],
                            'reason': str(raw.get('reason') or '').strip()[:160],
                            'created_at': float(raw.get('created_at') or 0.0),
                            'requested_at': float(raw.get('requested_at') or 0.0),
                            'scheduled_at': float(raw.get('scheduled_at') or 0.0),
                            'finalized_at': float(raw.get('finalized_at') or 0.0),
                            'ip': str(raw.get('ip') or '').strip()[:96],
                            'metadata': raw.get('metadata') if isinstance(raw.get('metadata'), dict) else {},
                        }
                        if event.get('action') and event.get('created_at'):
                            clean.append(event)
                    state['events'] = clean
                try:
                    state['updated_at'] = float(loaded.get('updated_at') or _utc_ts())
                except Exception:
                    state['updated_at'] = _utc_ts()
    except Exception:
        app_logger.exception('[auth_account_delete_log] load_failed')
    with _AUTH_ACCOUNT_DELETE_LOG_LOCK:
        _AUTH_ACCOUNT_DELETE_LOG_STATE.clear()
        _AUTH_ACCOUNT_DELETE_LOG_STATE.update(state)


def _auth_account_delete_log_save() -> None:
    with _AUTH_ACCOUNT_DELETE_LOG_LOCK:
        events = list((_AUTH_ACCOUNT_DELETE_LOG_STATE.get('events') or [])[-AUTH_ACCOUNT_DELETE_LOG_MAX_EVENTS:])
        payload = {'events': events, 'updated_at': _utc_ts()}
        _AUTH_ACCOUNT_DELETE_LOG_STATE['events'] = events
        _AUTH_ACCOUNT_DELETE_LOG_STATE['updated_at'] = payload['updated_at']
    tmp = AUTH_ACCOUNT_DELETE_LOG_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, AUTH_ACCOUNT_DELETE_LOG_FILE)
    except Exception:
        app_logger.exception('[auth_account_delete_log] save_failed')
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _auth_account_delete_log_append(action: str, email: str, *, actor: str = 'system', reason: str = '', requested_at: float = 0.0, scheduled_at: float = 0.0, finalized_at: float = 0.0, metadata: dict | None = None) -> dict:
    normalized = _normalize_login_email(email)
    now_ts = _utc_ts()
    ip = ''
    try:
        ip = _client_ip()
    except Exception:
        ip = ''
    event = {
        'id': uuid.uuid4().hex,
        'action': str(action or '').strip()[:64],
        'email': normalized,
        'actor': str(actor or '').strip()[:32],
        'reason': str(reason or '').strip()[:160],
        'created_at': now_ts,
        'requested_at': float(requested_at or 0.0),
        'scheduled_at': float(scheduled_at or 0.0),
        'finalized_at': float(finalized_at or 0.0),
        'ip': ip,
        'metadata': metadata if isinstance(metadata, dict) else {},
    }
    if not event.get('action') or not normalized:
        return {}
    with _AUTH_ACCOUNT_DELETE_LOG_LOCK:
        events = list(_AUTH_ACCOUNT_DELETE_LOG_STATE.setdefault('events', []))
        events.append(event)
        _AUTH_ACCOUNT_DELETE_LOG_STATE['events'] = events[-AUTH_ACCOUNT_DELETE_LOG_MAX_EVENTS:]
        _AUTH_ACCOUNT_DELETE_LOG_STATE['updated_at'] = now_ts
    _auth_account_delete_log_save()
    return event


def _auth_account_delete_event_public(event: dict | None, include_private: bool = False) -> dict:
    row = dict(event or {})
    email = _normalize_login_email(row.get('email') or '')
    metadata = row.get('metadata') if isinstance(row.get('metadata'), dict) else {}
    return {
        'id': str(row.get('id') or ''),
        'action': str(row.get('action') or ''),
        'email': email if include_private else '',
        'email_masked': _mask_login_email(email),
        'actor': str(row.get('actor') or ''),
        'reason': str(row.get('reason') or ''),
        'created_at': _fmt_ts(row.get('created_at')),
        'requested_at': _fmt_ts(row.get('requested_at')),
        'scheduled_at': _fmt_ts(row.get('scheduled_at')),
        'finalized_at': _fmt_ts(row.get('finalized_at')),
        'ip': str(row.get('ip') or '') if include_private else '',
        'metadata': metadata if include_private else {},
    }


def _auth_account_delete_logs_public(limit: int = 80, include_private: bool = False) -> list[dict]:
    try:
        limit_num = max(1, min(int(limit or 80), 300))
    except Exception:
        limit_num = 80
    with _AUTH_ACCOUNT_DELETE_LOG_LOCK:
        events = list(_AUTH_ACCOUNT_DELETE_LOG_STATE.get('events') or [])
    events.sort(key=lambda item: float((item or {}).get('created_at') or 0.0), reverse=True)
    return [_auth_account_delete_event_public(item, include_private=include_private) for item in events[:limit_num]]




def _auth_account_delete_logs_clear() -> int:
    with _AUTH_ACCOUNT_DELETE_LOG_LOCK:
        cleared = len(_AUTH_ACCOUNT_DELETE_LOG_STATE.get('events') or [])
        _AUTH_ACCOUNT_DELETE_LOG_STATE['events'] = []
        _AUTH_ACCOUNT_DELETE_LOG_STATE['updated_at'] = _utc_ts()
    _auth_account_delete_log_save()
    return int(cleared or 0)

def _auth_account_export_payload(email: str) -> dict:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        raise ValueError('未找到登录账号')
    user = _auth_get_user(normalized) or {}
    if not user:
        raise ValueError('账号不存在')
    memory_rec = None
    try:
        memory_get = globals().get('_auth_personalization_memory_get')
        if callable(memory_get):
            memory_rec = memory_get(normalized)
    except Exception:
        app_logger.exception('[auth_account_export] memory_get_failed email=%s', normalized)
    return {
        'schema': 'webai_account_export_v1',
        'exported_at': _fmt_ts(_utc_ts()),
        'email': normalized,
        'user': _auth_user_public(user, include_private=True),
        'profile': _auth_account_profile_get(normalized),
        'chat_store': _auth_chat_store_get(normalized) or {},
        'personalization_memory': memory_rec or {},
    }


def _auth_account_delete_sweep_loop() -> None:
    while True:
        try:
            _auth_finalize_expired_account_deletions()
        except Exception:
            app_logger.exception('[auth_account_delete_sweep] run_failed')
        try:
            time.sleep(AUTH_ACCOUNT_DELETE_SWEEP_INTERVAL_S)
        except Exception:
            time.sleep(3600)


def _auth_start_account_delete_sweeper() -> None:
    global _AUTH_ACCOUNT_DELETE_SWEEP_THREAD_STARTED
    with _AUTH_ACCOUNT_DELETE_SWEEP_START_LOCK:
        if _AUTH_ACCOUNT_DELETE_SWEEP_THREAD_STARTED:
            return
        _AUTH_ACCOUNT_DELETE_SWEEP_THREAD_STARTED = True
    try:
        t = threading.Thread(target=_auth_account_delete_sweep_loop, name='auth-account-delete-sweeper', daemon=True)
        t.start()
        app_logger.info('[auth_account_delete_sweep] started interval_s=%s', AUTH_ACCOUNT_DELETE_SWEEP_INTERVAL_S)
    except Exception:
        app_logger.exception('[auth_account_delete_sweep] start_failed')
