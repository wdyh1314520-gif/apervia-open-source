# Invite-code store and lifecycle helpers. Loaded after platform_auth_core_part.py and before auth runtime init/routes.

AUTH_INVITE_CODES_FILE = _app_data_path('auth_invite_codes_store.json')
AUTH_INVITE_CODE_LENGTH = 6
AUTH_INVITE_CODE_TTL_S = 72 * 3600
AUTH_INVITE_CODE_AUTO_CLEANUP_RETENTION_S = 7 * 86400
AUTH_INVITE_CODE_ALPHABET = string.ascii_letters + string.digits
_AUTH_INVITE_CODES_LOCK = threading.Lock()
_AUTH_INVITE_CODES_STATE = {
    'codes': {},
    'updated_at': 0.0,
}


def _invite_code_format_ttl(seconds: int | float | None = None) -> str:
    try:
        total = max(0, int(seconds or 0))
    except Exception:
        total = 0
    if total <= 0:
        return '0 秒'
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f'{days} 天')
    if hours:
        parts.append(f'{hours} 小时')
    if minutes and not days:
        parts.append(f'{minutes} 分钟')
    return ''.join(parts[:2]) or '0 秒'


def _auth_invite_codes_load() -> None:
    state = {'codes': {}, 'updated_at': _utc_ts()}
    try:
        if os.path.exists(AUTH_INVITE_CODES_FILE):
            with open(AUTH_INVITE_CODES_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f) or {}
            if isinstance(loaded, dict):
                codes = loaded.get('codes') or {}
                if isinstance(codes, dict):
                    clean = {}
                    for code, rec in codes.items():
                        raw_code = str(code or (rec or {}).get('code') or '').strip()
                        if not re.fullmatch(r'[0-9A-Za-z]{%s}' % AUTH_INVITE_CODE_LENGTH, raw_code or ''):
                            continue
                        obj = dict(rec or {})
                        obj['code'] = raw_code
                        obj['created_at'] = float(obj.get('created_at') or _utc_ts())
                        obj['updated_at'] = float(obj.get('updated_at') or obj['created_at'])
                        obj['expires_at'] = float(obj.get('expires_at') or (obj['created_at'] + AUTH_INVITE_CODE_TTL_S))
                        obj['used'] = bool(obj.get('used'))
                        obj['used_at'] = float(obj.get('used_at') or 0.0)
                        obj['used_by'] = _normalize_login_email(obj.get('used_by') or '')
                        obj['revoked'] = bool(obj.get('revoked'))
                        obj['revoked_at'] = float(obj.get('revoked_at') or 0.0)
                        clean[raw_code] = obj
                    state['codes'] = clean
                try:
                    state['updated_at'] = float(loaded.get('updated_at') or _utc_ts())
                except Exception:
                    state['updated_at'] = _utc_ts()
    except Exception:
        app_logger.exception('[auth_invite_codes] load_failed')
    with _AUTH_INVITE_CODES_LOCK:
        _AUTH_INVITE_CODES_STATE.clear()
        _AUTH_INVITE_CODES_STATE.update(state)


def _auth_invite_codes_save() -> None:
    with _AUTH_INVITE_CODES_LOCK:
        payload = {
            'codes': _AUTH_INVITE_CODES_STATE.get('codes') or {},
            'updated_at': _utc_ts(),
        }
        _AUTH_INVITE_CODES_STATE['updated_at'] = payload['updated_at']
    tmp = AUTH_INVITE_CODES_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, AUTH_INVITE_CODES_FILE)
    except Exception:
        app_logger.exception('[auth_invite_codes] save_failed')
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _invite_code_normalize(code: str) -> str:
    return str(code or '').strip()


def _invite_code_record_snapshot(rec: dict | None, *, now: float | None = None) -> dict:
    obj = dict(rec or {})
    ts = float(now or _utc_ts())
    code = _invite_code_normalize(obj.get('code') or '')
    expires_at = float(obj.get('expires_at') or 0.0)
    used = bool(obj.get('used'))
    revoked = bool(obj.get('revoked'))
    expired = bool(expires_at > 0 and expires_at <= ts)
    active = bool(code and (not used) and (not revoked) and (not expired))
    status_text = '可用'
    if used:
        status_text = '已使用'
    elif revoked:
        status_text = '已作废'
    elif expired:
        status_text = '已过期'
    remaining_s = max(0, int(expires_at - ts)) if expires_at > ts else 0
    return {
        'code': code,
        'created_at': float(obj.get('created_at') or 0.0),
        'updated_at': float(obj.get('updated_at') or 0.0),
        'expires_at': expires_at,
        'used': used,
        'used_at': float(obj.get('used_at') or 0.0),
        'used_by': _normalize_login_email(obj.get('used_by') or ''),
        'revoked': revoked,
        'revoked_at': float(obj.get('revoked_at') or 0.0),
        'expired': expired,
        'active': active,
        'remaining_s': remaining_s,
        'status_text': status_text,
    }


def _invite_code_public(rec: dict | None, include_private: bool = False) -> dict:
    snap = _invite_code_record_snapshot(rec)
    used_by = _normalize_login_email(snap.get('used_by') or '')
    return {
        'code': str(snap.get('code') or ''),
        'status_text': str(snap.get('status_text') or ''),
        'active': bool(snap.get('active')),
        'expired': bool(snap.get('expired')),
        'used': bool(snap.get('used')),
        'revoked': bool(snap.get('revoked')),
        'created_at': _fmt_ts(snap.get('created_at')),
        'updated_at': _fmt_ts(snap.get('updated_at')),
        'expires_at': _fmt_ts(snap.get('expires_at')),
        'used_at': _fmt_ts(snap.get('used_at')),
        'remaining_s': int(snap.get('remaining_s') or 0),
        'used_by': used_by if include_private else '',
        'used_by_masked': _mask_login_email(used_by),
    }


def _auth_invite_code_summary() -> dict:
    now = _utc_ts()
    with _AUTH_INVITE_CODES_LOCK:
        rows = [dict(item or {}) for item in ((_AUTH_INVITE_CODES_STATE.get('codes') or {}).values())]
    total = len(rows)
    active = used = expired = revoked = 0
    for item in rows:
        snap = _invite_code_record_snapshot(item, now=now)
        if snap.get('active'):
            active += 1
        elif snap.get('used'):
            used += 1
        elif snap.get('revoked'):
            revoked += 1
        elif snap.get('expired'):
            expired += 1
    return {
        'total': total,
        'active': active,
        'used': used,
        'expired': expired,
        'revoked': revoked,
        'ttl_s': int(AUTH_INVITE_CODE_TTL_S),
        'ttl_text': _invite_code_format_ttl(AUTH_INVITE_CODE_TTL_S),
    }


def _auth_invite_codes_public_list(include_private: bool = False, *, only_current: bool = False) -> list[dict]:
    with _AUTH_INVITE_CODES_LOCK:
        rows = [dict(item or {}) for item in ((_AUTH_INVITE_CODES_STATE.get('codes') or {}).values())]
    rows.sort(key=lambda item: float((item or {}).get('created_at') or 0.0), reverse=True)
    publics = [_invite_code_public(item, include_private=include_private) for item in rows]
    if not only_current:
        return publics
    active_rows = [item for item in publics if bool((item or {}).get('active'))]
    return active_rows or publics[:1]


def _auth_invite_code_random_from_existing(existing: set[str]) -> str:
    letters = string.ascii_letters
    digits = string.digits
    extra_len = max(0, AUTH_INVITE_CODE_LENGTH - 2)
    for _ in range(256):
        chars = [
            secrets.choice(letters),
            secrets.choice(digits),
            *[secrets.choice(AUTH_INVITE_CODE_ALPHABET) for _i in range(extra_len)],
        ]
        random.shuffle(chars)
        code = ''.join(chars[:AUTH_INVITE_CODE_LENGTH])
        if code not in existing:
            return code
    raise ValueError('邀请码生成失败，请稍后重试')


def _auth_invite_code_random() -> str:
    with _AUTH_INVITE_CODES_LOCK:
        existing = set((_AUTH_INVITE_CODES_STATE.get('codes') or {}).keys())
    return _auth_invite_code_random_from_existing(existing)


def _auth_require_valid_invite_code(code: str) -> dict:
    raw = _invite_code_normalize(code)
    if not re.fullmatch(r'[0-9A-Za-z]{%s}' % AUTH_INVITE_CODE_LENGTH, raw or ''):
        raise ValueError(f'请输入 {AUTH_INVITE_CODE_LENGTH} 位邀请码')
    with _AUTH_INVITE_CODES_LOCK:
        rec = dict(((_AUTH_INVITE_CODES_STATE.get('codes') or {}).get(raw) or {}))
    if not rec:
        raise ValueError('邀请码不存在，请联系管理员获取')
    snap = _invite_code_record_snapshot(rec)
    if snap.get('used'):
        raise ValueError('邀请码已被使用，请联系管理员重新获取')
    if snap.get('revoked'):
        raise ValueError('邀请码已失效，请联系管理员重新获取')
    if snap.get('expired'):
        raise ValueError('邀请码已过期，请联系管理员重新获取')
    return rec


def _auth_create_invite_codes(count: int = 1, ttl_s: int | None = None) -> list[dict]:
    try:
        total = int(count or 1)
    except Exception:
        total = 1
    total = max(1, min(50, total))
    now = _utc_ts()
    ttl = max(300, int(ttl_s or AUTH_INVITE_CODE_TTL_S))
    new_records: list[dict] = []
    with _AUTH_INVITE_CODES_LOCK:
        codes = _AUTH_INVITE_CODES_STATE.setdefault('codes', {})
        existing = set(codes.keys())
        for _i in range(total):
            code = _auth_invite_code_random_from_existing(existing)
            existing.add(code)
            rec = {
                'code': code,
                'created_at': now,
                'updated_at': now,
                'expires_at': now + ttl,
                'used': False,
                'used_at': 0.0,
                'used_by': '',
                'revoked': False,
                'revoked_at': 0.0,
            }
            codes[code] = rec
            new_records.append(dict(rec))
        _AUTH_INVITE_CODES_STATE['updated_at'] = now
    _auth_invite_codes_save()
    return [_invite_code_public(rec, include_private=True) for rec in new_records]


def _auth_create_invite_code(ttl_s: int | None = None) -> dict:
    records = _auth_create_invite_codes(1, ttl_s=ttl_s)
    if not records:
        raise ValueError('邀请码生成失败，请稍后重试')
    return records[0]


def _auth_revoke_invite_code(code: str) -> dict:
    raw = _invite_code_normalize(code)
    with _AUTH_INVITE_CODES_LOCK:
        codes = _AUTH_INVITE_CODES_STATE.setdefault('codes', {})
        rec = dict(codes.get(raw) or {})
        if not rec:
            raise ValueError('邀请码不存在')
        rec['code'] = raw
        if not bool(rec.get('revoked')):
            rec['revoked'] = True
            rec['revoked_at'] = _utc_ts()
        rec['updated_at'] = _utc_ts()
        codes[raw] = rec
        _AUTH_INVITE_CODES_STATE['updated_at'] = rec['updated_at']
    _auth_invite_codes_save()
    return _invite_code_public(rec, include_private=True)


def _auth_regenerate_invite_code(code: str, ttl_s: int | None = None) -> dict:
    raw = _invite_code_normalize(code)
    now = _utc_ts()
    with _AUTH_INVITE_CODES_LOCK:
        codes = _AUTH_INVITE_CODES_STATE.setdefault('codes', {})
        rec = dict(codes.get(raw) or {})
        if not rec:
            raise ValueError('邀请码不存在')
        rec['code'] = raw
        if not bool(rec.get('used')):
            rec['revoked'] = True
            rec['revoked_at'] = now
            rec['updated_at'] = now
            codes[raw] = rec
        _AUTH_INVITE_CODES_STATE['updated_at'] = now
    _auth_invite_codes_save()
    new_rec = _auth_create_invite_code(ttl_s=ttl_s)
    return {
        'old_code': raw,
        'new_invite': new_rec,
    }


def _auth_consume_invite_code(code: str, email: str) -> dict:
    raw = _invite_code_normalize(code)
    normalized_email = _normalize_login_email(email)
    if not normalized_email or '@' not in normalized_email:
        raise ValueError('请输入正确的邮箱地址')
    now = _utc_ts()
    with _AUTH_INVITE_CODES_LOCK:
        codes = _AUTH_INVITE_CODES_STATE.setdefault('codes', {})
        rec = dict((codes.get(raw) or {}))
        if not rec:
            raise ValueError('邀请码不存在，请联系管理员获取')
        snap = _invite_code_record_snapshot(rec, now=now)
        if snap.get('used'):
            raise ValueError('邀请码已被使用，请联系管理员重新获取')
        if snap.get('revoked'):
            raise ValueError('邀请码已失效，请联系管理员重新获取')
        if snap.get('expired'):
            raise ValueError('邀请码已过期，请联系管理员重新获取')
        rec['code'] = raw
        rec['used'] = True
        rec['used_at'] = now
        rec['used_by'] = normalized_email
        rec['updated_at'] = now
        codes[raw] = rec
        _AUTH_INVITE_CODES_STATE['updated_at'] = now
    _auth_invite_codes_save()
    return _invite_code_public(rec, include_private=True)


def _auth_cleanup_invite_codes(retention_s: int | float | None = 0) -> dict:
    now = _utc_ts()
    try:
        retention = max(0, int(retention_s or 0))
    except Exception:
        retention = 0
    removed_codes: list[str] = []
    with _AUTH_INVITE_CODES_LOCK:
        codes = _AUTH_INVITE_CODES_STATE.setdefault('codes', {})
        for raw_code, rec in list(codes.items()):
            item = dict(rec or {})
            code = _invite_code_normalize(item.get('code') or raw_code)
            if not code:
                continue
            item['code'] = code
            snap = _invite_code_record_snapshot(item, now=now)
            if snap.get('active'):
                continue
            remove_after = 0.0
            if snap.get('used'):
                remove_after = float(snap.get('used_at') or snap.get('updated_at') or snap.get('created_at') or 0.0)
            elif snap.get('revoked'):
                remove_after = float(snap.get('revoked_at') or snap.get('updated_at') or snap.get('created_at') or 0.0)
            elif snap.get('expired'):
                remove_after = float(snap.get('expires_at') or 0.0)
            if retention <= 0 or (remove_after > 0 and now - remove_after >= retention):
                codes.pop(raw_code, None)
                removed_codes.append(code)
        if removed_codes:
            _AUTH_INVITE_CODES_STATE['updated_at'] = now
    if removed_codes:
        _auth_invite_codes_save()
    return {'removed_count': len(removed_codes), 'removed_codes': removed_codes}
