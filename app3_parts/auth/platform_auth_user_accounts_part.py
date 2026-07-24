# account limits, blacklist/delete state, user CRUD, password checks, and login flags.

def _auth_user_count() -> int:
    with _AUTH_USERS_LOCK:
        return len(_AUTH_USERS_STATE.get('users') or {})


def _auth_user_blacklist_deadline(rec: dict | None) -> float:
    obj = dict(rec or {})
    blacklisted_at = float(obj.get('blacklisted_at') or 0)
    deadline = float(obj.get('blacklist_expires_at') or 0)
    if deadline > 0:
        return deadline
    if blacklisted_at > 0:
        return blacklisted_at + AUTH_ACCOUNT_BLACKLIST_GRACE_S
    return 0.0


def _auth_user_blacklist_snapshot(rec: dict | None) -> dict:
    obj = dict(rec or {})
    blocked = bool(obj.get('blacklisted'))
    blacklisted_at = float(obj.get('blacklisted_at') or 0)
    deadline = _auth_user_blacklist_deadline(obj) if blocked else 0.0
    now = _utc_ts()
    permanent = bool(blocked and (obj.get('blacklist_permanent') or (deadline > 0 and deadline <= now)))
    remaining_s = max(0, int(math.ceil(deadline - now))) if blocked and not permanent and deadline > 0 else 0
    remaining_days = max(0, int(math.ceil(remaining_s / 86400))) if remaining_s > 0 else 0
    status_text = '正常'
    message = ''
    if permanent:
        status_text = '永久封禁'
        message = AUTH_ACCOUNT_PERMANENT_BAN_MESSAGE
    elif blocked:
        status_text = f'已拉黑（{AUTH_ACCOUNT_BLACKLIST_GRACE_DAYS} 天内可解封）'
        message = AUTH_ACCOUNT_TEMP_BLACKLIST_MESSAGE
    return {
        'blacklisted': blocked,
        'blacklist_permanent': permanent,
        'blacklist_temporary': bool(blocked and not permanent),
        'blacklist_reason': str(obj.get('blacklist_reason') or '').strip(),
        'blacklisted_at': blacklisted_at,
        'blacklist_deadline_at': deadline,
        'blacklist_remaining_s': remaining_s,
        'blacklist_remaining_days': remaining_days,
        'blacklist_status_text': status_text,
        'blacklist_message': message,
        'blacklist_permanent_at': float(obj.get('blacklist_permanent_at') or 0),
    }


def _auth_user_blacklist_message(rec: dict | None) -> str:
    snap = _auth_user_blacklist_snapshot(rec)
    return str(snap.get('blacklist_message') or '') if snap.get('blacklisted') else ''


def _auth_user_deleted_message(rec: dict | None) -> str:
    return AUTH_ACCOUNT_DELETED_MESSAGE if bool((rec or {}).get('deleted')) else ''


def _auth_user_delete_pending(rec: dict | None) -> bool:
    row = rec or {}
    if bool(row.get('deleted')):
        return False
    if bool(row.get('delete_pending')):
        return True
    try:
        scheduled_at = float(row.get('delete_scheduled_at') or 0)
    except Exception:
        scheduled_at = 0.0
    try:
        requested_at = float(row.get('delete_requested_at') or 0)
    except Exception:
        requested_at = 0.0
    return bool(requested_at > 0 and scheduled_at > 0)


def _auth_user_delete_pending_message(rec: dict | None) -> str:
    return AUTH_ACCOUNT_DELETE_PENDING_MESSAGE if _auth_user_delete_pending(rec) else ''


def _auth_user_delete_pending_payload(rec: dict | None) -> dict:
    row = rec or {}
    return {
        'reason_code': 'account_delete_pending',
        'message': _auth_user_delete_pending_message(row),
        'account_delete_pending': True,
        'can_restore_delete': True,
        'can_undo_delete': True,
        'delete_requested_at': _fmt_ts(row.get('delete_requested_at')),
        'delete_scheduled_at': _fmt_ts(row.get('delete_scheduled_at')),
        'delete_grace_days': AUTH_ACCOUNT_DELETE_GRACE_DAYS,
        'email_masked': _mask_login_email(_normalize_login_email(row.get('email') or '')),
    }


def _auth_finalize_deleted_account_data(email: str) -> dict:
    normalized = _normalize_login_email(email)
    if not normalized:
        return {}
    removed_profile = False
    removed_chat = False
    removed_memory = False
    removed_mcp_servers = 0
    try:
        removed_profile = bool(_auth_account_profile_delete(normalized))
    except Exception:
        app_logger.exception('[auth_account_delete] profile_delete_failed email=%s', normalized)
    try:
        removed_chat = bool(_auth_chat_store_delete(normalized))
    except Exception:
        app_logger.exception('[auth_account_delete] chat_delete_failed email=%s', normalized)
    try:
        memory_delete = globals().get('_auth_personalization_memory_delete_account')
        if callable(memory_delete):
            removed_memory = bool(memory_delete(normalized))
    except Exception:
        app_logger.exception('[auth_account_delete] memory_delete_failed email=%s', normalized)
    try:
        mcp_delete = globals().get('_mcp_client_delete_owner')
        if callable(mcp_delete):
            removed_mcp_servers = int(mcp_delete(normalized) or 0)
    except Exception:
        app_logger.exception('[auth_account_delete] mcp_delete_failed email=%s', normalized)
    try:
        _auth_presence_clear_account(normalized)
    except Exception:
        pass
    return {
        'removed_profile': bool(removed_profile),
        'removed_chat': bool(removed_chat),
        'removed_memory': bool(removed_memory),
        'removed_mcp_servers': int(removed_mcp_servers),
    }


def _auth_finalize_expired_account_deletions(now: float | int | None = None) -> bool:
    current = float(now if now is not None else _utc_ts())
    due_accounts: list[dict] = []
    changed = False
    with _AUTH_USERS_LOCK:
        users = _AUTH_USERS_STATE.setdefault('users', {})
        for email, raw_rec in list(users.items()):
            rec = dict(raw_rec or {})
            if bool(rec.get('deleted')) or not _auth_user_delete_pending(rec):
                continue
            try:
                scheduled_at = float(rec.get('delete_scheduled_at') or 0)
            except Exception:
                scheduled_at = 0.0
            if scheduled_at <= 0 or scheduled_at > current:
                continue
            normalized = _normalize_login_email(email or rec.get('email') or '')
            requested_at = float(rec.get('delete_requested_at') or 0.0)
            reason = str(rec.get('delete_reason') or '').strip()
            rec['email'] = normalized
            rec['enabled'] = False
            rec['delete_pending'] = False
            rec['deleted'] = True
            rec['deleted_at'] = float(rec.get('deleted_at') or current)
            rec['delete_finalized_at'] = current
            rec['updated_at'] = current
            users[normalized or email] = rec
            due_accounts.append({'email': normalized, 'requested_at': requested_at, 'scheduled_at': scheduled_at, 'reason': reason})
            changed = True
        if changed:
            _AUTH_USERS_STATE['updated_at'] = current
    if changed:
        _auth_users_save()
        for item in due_accounts:
            email = _normalize_login_email((item or {}).get('email') or '')
            if not email:
                continue
            cleanup = {}
            try:
                cleanup = _auth_finalize_deleted_account_data(email)
            except Exception:
                app_logger.exception('[auth_account_delete] finalize_failed email=%s', email)
                _auth_account_delete_log_append('delete_finalize_failed', email, actor='system', reason=str((item or {}).get('reason') or ''), requested_at=float((item or {}).get('requested_at') or 0.0), scheduled_at=float((item or {}).get('scheduled_at') or 0.0), finalized_at=current)
                continue
            _auth_account_delete_log_append('delete_finalized', email, actor='system', reason=str((item or {}).get('reason') or ''), requested_at=float((item or {}).get('requested_at') or 0.0), scheduled_at=float((item or {}).get('scheduled_at') or 0.0), finalized_at=current, metadata=cleanup)
    return changed


def _auth_users_refresh_blacklist_states() -> bool:
    now = _utc_ts()
    changed = _auth_finalize_expired_account_deletions(now)
    with _AUTH_USERS_LOCK:
        users = _AUTH_USERS_STATE.setdefault('users', {})
        for email, raw_rec in list(users.items()):
            rec = dict(raw_rec or {})
            snap = _auth_user_blacklist_snapshot(rec)
            if not snap.get('blacklisted'):
                continue
            if snap.get('blacklist_permanent') and not bool(rec.get('blacklist_permanent')):
                rec['blacklist_permanent'] = True
                rec['blacklist_permanent_at'] = float(rec.get('blacklist_permanent_at') or now)
                rec['blacklist_expires_at'] = float(snap.get('blacklist_deadline_at') or rec.get('blacklist_expires_at') or now)
                rec['updated_at'] = now
                users[email] = rec
                changed = True
        if changed:
            _AUTH_USERS_STATE['updated_at'] = now
    if changed:
        _auth_users_save()
    return changed


def _auth_blacklist_count() -> int:
    _auth_users_refresh_blacklist_states()
    with _AUTH_USERS_LOCK:
        users = list((_AUTH_USERS_STATE.get('users') or {}).values())
    return sum(1 for item in users if _auth_user_blacklist_snapshot(item).get('blacklisted'))


def _auth_user_public(rec: dict, include_private: bool = False) -> dict:
    obj = dict(rec or {})
    email = _normalize_login_email(obj.get('email') or '')
    presence = _auth_presence_public_map([email]).get(email) or {}
    blacklist = _auth_user_blacklist_snapshot(obj)
    recent_active_ip = str(presence.get('recent_active_ip') or '').strip()
    raw_last_login_ip = str(obj.get('last_login_ip') or '').strip()
    display_last_login_ip = _auth_display_ip_with_active_fallback(raw_last_login_ip, recent_active_ip)
    return {
        'email': email if include_private else '',
        'email_masked': _mask_login_email(email),
        'enabled': bool(obj.get('enabled', True)) and not bool(obj.get('deleted')) and not _auth_user_delete_pending(obj),
        'deleted': bool(obj.get('deleted')),
        'delete_pending': _auth_user_delete_pending(obj),
        'account_delete_pending': _auth_user_delete_pending(obj),
        'deleted_at': _fmt_ts(obj.get('deleted_at')),
        'delete_requested_at': _fmt_ts(obj.get('delete_requested_at')),
        'delete_scheduled_at': _fmt_ts(obj.get('delete_scheduled_at')),
        'delete_grace_days': AUTH_ACCOUNT_DELETE_GRACE_DAYS,
        'password_configured': bool(obj.get('password_hash') and obj.get('password_salt')),
        'created_at': _fmt_ts(obj.get('created_at')),
        'updated_at': _fmt_ts(obj.get('updated_at')),
        'last_login_at': _fmt_ts(obj.get('last_login_at')),
        'last_login_ip': display_last_login_ip,
        'last_login_ip_raw': raw_last_login_ip,
        'online': bool(presence.get('online')),
        'online_text': str(presence.get('online_text') or '离线'),
        'online_session_count': int(presence.get('online_session_count') or 0),
        'last_active_at': str(presence.get('last_active_at') or ''),
        'recent_active_ip': recent_active_ip,
        'recent_active_session': str(presence.get('recent_active_session') or '').strip(),
        'blacklisted': bool(blacklist.get('blacklisted')),
        'blacklist_permanent': bool(blacklist.get('blacklist_permanent')),
        'blacklist_temporary': bool(blacklist.get('blacklist_temporary')),
        'blacklist_reason': str(blacklist.get('blacklist_reason') or ''),
        'blacklisted_at': _fmt_ts(blacklist.get('blacklisted_at')),
        'blacklist_deadline_at': _fmt_ts(blacklist.get('blacklist_deadline_at')),
        'blacklist_remaining_days': int(blacklist.get('blacklist_remaining_days') or 0),
        'blacklist_status_text': str(blacklist.get('blacklist_status_text') or '正常'),
        'blacklist_message': str(blacklist.get('blacklist_message') or ''),
        'blacklist_permanent_at': _fmt_ts(blacklist.get('blacklist_permanent_at')),
        'allow_private_search_upstreams': _auth_user_allows_private_search_upstreams(obj),
    }


def _auth_users_public_list(include_private: bool = False) -> list[dict]:
    _auth_users_refresh_blacklist_states()
    with _AUTH_USERS_LOCK:
        items = [dict(v or {}) for v in (_AUTH_USERS_STATE.get('users') or {}).values()]
    items.sort(key=lambda x: float(x.get('updated_at') or x.get('created_at') or 0), reverse=True)
    return [_auth_user_public(item, include_private=include_private) for item in items]


def _auth_blacklisted_users_public_list(include_private: bool = False) -> list[dict]:
    rows = [item for item in _auth_users_public_list(include_private=include_private) if item.get('blacklisted')]
    rows.sort(key=lambda item: (0 if item.get('blacklist_permanent') else 1, item.get('blacklisted_at') or ''), reverse=False)
    return rows


def _auth_user_allows_private_search_upstreams(rec: dict | None) -> bool:
    try:
        return bool((rec or {}).get('allow_private_search_upstreams'))
    except Exception:
        return False


def _auth_get_user(email: str) -> dict | None:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        return None
    with _AUTH_USERS_LOCK:
        rec = (_AUTH_USERS_STATE.get('users') or {}).get(normalized)
        return dict(rec or {}) if rec else None


def _auth_user_exists(email: str) -> bool:
    return _auth_get_user(email) is not None


def _auth_validate_password_policy(password: str, *, label: str = '密码') -> None:
    raw = str(password or '')
    name = str(label or '密码').strip() or '密码'
    if len(raw) < 6:
        raise ValueError(f'{name}至少 6 位，并且必须包含大写字母、小写字母和数字')
    if not re.search(r'[A-Z]', raw) or not re.search(r'[a-z]', raw) or not re.search(r'\d', raw):
        raise ValueError(f'{name}必须包含大写字母、小写字母和数字')


def _auth_create_user_record_locked(normalized: str, password: str) -> None:
    with _AUTH_USERS_LOCK:
        users = _AUTH_USERS_STATE.setdefault('users', {})
        if normalized in users:
            raise ValueError('该邮箱已经注册')
        password_hash, password_salt = _hash_login_password(password)
        now = _utc_ts()
        rec = {
            'email': normalized,
            'password_hash': password_hash,
            'password_salt': password_salt,
            'enabled': True,
            'created_at': now,
            'updated_at': now,
            'last_login_at': 0.0,
            'last_login_ip': '',
            'blacklisted': False,
            'blacklist_reason': '',
            'blacklisted_at': 0.0,
            'blacklist_expires_at': 0.0,
            'blacklist_permanent': False,
            'blacklist_permanent_at': 0.0,
            'allow_private_search_upstreams': False,
        }
        users[normalized] = rec
        _AUTH_USERS_STATE['updated_at'] = now


def _auth_create_user(email: str, password: str) -> dict:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        raise ValueError('请输入正确的邮箱地址')
    _auth_validate_password_policy(password, label='密码')
    purge_lock = globals().get('_PLATFORM_ADMIN_GUEST_PURGE_LOCK')
    purge_owners = globals().get('_PLATFORM_ADMIN_GUEST_PURGE_OWNERS')
    if purge_lock is not None and isinstance(purge_owners, set):
        # 固定按“游客清理锁 -> 账号锁”的顺序执行，避免注册和后台清理形成锁反转。
        with purge_lock:
            if normalized in purge_owners:
                raise ValueError('该游客数据正在由后台清理，请稍后再注册')
            _auth_create_user_record_locked(normalized, password)
    else:
        _auth_create_user_record_locked(normalized, password)
    _auth_users_save()
    return _auth_get_user(normalized) or {}


def _auth_user_set_enabled(email: str, enabled: bool) -> dict:
    normalized = _normalize_login_email(email)
    with _AUTH_USERS_LOCK:
        users = _AUTH_USERS_STATE.setdefault('users', {})
        rec = dict(users.get(normalized) or {})
        if not rec:
            raise ValueError('账号不存在')
        if bool(enabled):
            if bool(rec.get('deleted')):
                raise ValueError(AUTH_ACCOUNT_DELETED_MESSAGE)
            if _auth_user_delete_pending(rec):
                raise ValueError(AUTH_ACCOUNT_DELETE_PENDING_MESSAGE)
        rec['email'] = normalized
        rec['enabled'] = bool(enabled) and not bool(rec.get('deleted')) and not _auth_user_delete_pending(rec)
        rec['updated_at'] = _utc_ts()
        users[normalized] = rec
        _AUTH_USERS_STATE['updated_at'] = rec['updated_at']
    _auth_users_save()
    return _auth_get_user(normalized) or {}


def _auth_user_delete_account(email: str, reason: str = 'user_request', actor: str = 'user') -> dict:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        raise ValueError('账号不存在')
    now = _utc_ts()
    scheduled_at = now + AUTH_ACCOUNT_DELETE_GRACE_S
    with _AUTH_USERS_LOCK:
        users = _AUTH_USERS_STATE.setdefault('users', {})
        rec = dict(users.get(normalized) or {})
        if not rec:
            raise ValueError('账号不存在')
        if bool(rec.get('deleted')):
            raise ValueError(AUTH_ACCOUNT_DELETED_MESSAGE)
        rec['email'] = normalized
        rec['enabled'] = False
        rec['delete_pending'] = True
        rec['deleted'] = False
        rec['deleted_at'] = 0.0
        rec['delete_requested_at'] = now
        rec['delete_scheduled_at'] = scheduled_at
        rec['delete_reason'] = str(reason or 'user_request').strip()[:120]
        rec['updated_at'] = now
        users[normalized] = rec
        _AUTH_USERS_STATE['updated_at'] = now
    _auth_users_save()
    _auth_account_delete_log_append('delete_requested', normalized, actor=actor, reason=reason, requested_at=now, scheduled_at=scheduled_at)
    revoked_sessions = _auth_identity_revoke_email_sessions(normalized)
    try:
        _auth_presence_clear_account(normalized)
    except Exception:
        pass
    return {
        'user': _auth_get_user(normalized) or rec,
        'removed_profile': False,
        'removed_chat': False,
        'removed_memory': False,
        'delete_pending': True,
        'delete_requested_at': now,
        'delete_scheduled_at': scheduled_at,
        'delete_grace_days': AUTH_ACCOUNT_DELETE_GRACE_DAYS,
        'revoked_sessions': int(revoked_sessions or 0),
    }


def _auth_user_restore_account(email: str, actor: str = 'user') -> dict:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        raise ValueError('账号不存在')
    now = _utc_ts()
    with _AUTH_USERS_LOCK:
        users = _AUTH_USERS_STATE.setdefault('users', {})
        rec = dict(users.get(normalized) or {})
        if not rec:
            raise ValueError('账号不存在')
        if bool(rec.get('deleted')):
            raise ValueError(AUTH_ACCOUNT_DELETED_MESSAGE)
        if not _auth_user_delete_pending(rec):
            raise ValueError('该账号不在删除期内')
        rec['email'] = normalized
        rec['enabled'] = True
        rec['delete_pending'] = False
        rec['delete_requested_at'] = 0.0
        rec['delete_scheduled_at'] = 0.0
        rec['delete_reason'] = ''
        rec['updated_at'] = now
        users[normalized] = rec
        _AUTH_USERS_STATE['updated_at'] = now
    _auth_users_save()
    _auth_account_delete_log_append('delete_restored', normalized, actor=actor, reason='restore_delete')
    return _auth_get_user(normalized) or {}


def _auth_user_set_private_search_access(email: str, allowed: bool) -> dict:
    normalized = _normalize_login_email(email)
    with _AUTH_USERS_LOCK:
        users = _AUTH_USERS_STATE.setdefault('users', {})
        rec = dict(users.get(normalized) or {})
        if not rec:
            raise ValueError('账号不存在')
        rec['email'] = normalized
        rec['allow_private_search_upstreams'] = bool(allowed)
        rec['updated_at'] = _utc_ts()
        users[normalized] = rec
        _AUTH_USERS_STATE['updated_at'] = rec['updated_at']
    _auth_users_save()
    return _auth_get_user(normalized) or {}


def _auth_user_set_blacklisted(email: str, blocked: bool, reason: str = '') -> dict:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        raise ValueError('账号不存在')
    now = _utc_ts()
    with _AUTH_USERS_LOCK:
        users = _AUTH_USERS_STATE.setdefault('users', {})
        rec = dict(users.get(normalized) or {})
        if not rec:
            raise ValueError('账号不存在')
        rec['email'] = normalized
        if blocked:
            rec['blacklisted'] = True
            rec['blacklist_reason'] = str(reason or '').strip()[:120]
            rec['blacklisted_at'] = now
            rec['blacklist_expires_at'] = now + AUTH_ACCOUNT_BLACKLIST_GRACE_S
            rec['blacklist_permanent'] = False
            rec['blacklist_permanent_at'] = 0.0
        else:
            rec['blacklisted'] = False
            rec['blacklist_reason'] = ''
            rec['blacklisted_at'] = 0.0
            rec['blacklist_expires_at'] = 0.0
            rec['blacklist_permanent'] = False
            rec['blacklist_permanent_at'] = 0.0
        rec['updated_at'] = now
        users[normalized] = rec
        _AUTH_USERS_STATE['updated_at'] = now
    _auth_users_save()
    return _auth_get_user(normalized) or {}


def _auth_user_set_password(email: str, password: str) -> dict:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        raise ValueError('请输入邮箱地址')
    _auth_validate_password_policy(password, label='新密码')
    with _AUTH_USERS_LOCK:
        users = _AUTH_USERS_STATE.setdefault('users', {})
        rec = dict(users.get(normalized) or {})
        if not rec:
            raise ValueError('账号不存在')
        password_hash, password_salt = _hash_login_password(password)
        rec['email'] = normalized
        rec['password_hash'] = password_hash
        rec['password_salt'] = password_salt
        rec['enabled'] = bool(rec.get('enabled', True))
        rec['updated_at'] = _utc_ts()
        users[normalized] = rec
        _AUTH_USERS_STATE['updated_at'] = rec['updated_at']
    _auth_users_save()
    return _auth_get_user(normalized) or {}


def _auth_user_verify_password(email: str, password: str) -> bool:
    user = _auth_get_user(email)
    if not user or not bool(user.get('enabled', True)):
        return False
    saved_hash = str(user.get('password_hash') or '').strip()
    saved_salt = str(user.get('password_salt') or '').strip()
    if not (saved_hash and saved_salt):
        return False
    calc_hash, _ = _hash_login_password(password, saved_salt)
    return calc_hash == saved_hash


def _auth_user_touch_login(email: str) -> dict | None:
    normalized = _normalize_login_email(email)
    with _AUTH_USERS_LOCK:
        users = _AUTH_USERS_STATE.setdefault('users', {})
        rec = dict(users.get(normalized) or {})
        if not rec:
            return None
        rec['last_login_at'] = _utc_ts()
        rec['last_login_ip'] = _client_ip()
        rec['updated_at'] = rec['last_login_at']
        users[normalized] = rec
        _AUTH_USERS_STATE['updated_at'] = rec['updated_at']
    _auth_users_save()
    return _auth_get_user(normalized)
