# Split from app3_parts/auth/platform_auth_core_part.py.
# Purpose: email-login store, auth user store, account-delete log, export, and delete sweeper.
# Loaded by platform_auth_core_part.py via _exec_split_file(...), sharing the original global namespace.

def _email_login_load() -> None:
    state = {
        'sender_email': '',
        'sender_auth_code': '',
        'enabled': False,
        'registration_open': True,
        'invite_required': True,
        'allowed_email_domains': [],
        'terms_enabled': False,
        'terms_display_mode': AUTH_TERMS_DEFAULT_DISPLAY_MODE,
        'terms_updated_date': AUTH_TERMS_DEFAULT_UPDATED_DATE,
        'terms_documents': _auth_terms_default_documents(),
        'max_accounts': 0,
        'updated_at': _utc_ts(),
    }
    try:
        if os.path.exists(EMAIL_LOGIN_FILE):
            with open(EMAIL_LOGIN_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f) or {}
            if isinstance(loaded, dict):
                state['sender_email'] = _normalize_login_email(loaded.get('sender_email') or loaded.get('email') or '')
                state['sender_auth_code'] = str(loaded.get('sender_auth_code') or '').strip()
                state['registration_open'] = bool(loaded.get('registration_open', True))
                state['invite_required'] = bool(loaded.get('invite_required', True))
                state['allowed_email_domains'] = _normalize_email_domain_rules(loaded.get('allowed_email_domains') if 'allowed_email_domains' in loaded else loaded.get('email_domain_whitelist'))
                state['terms_enabled'] = bool(loaded.get('terms_enabled', False))
                state['terms_display_mode'] = _auth_terms_display_mode(loaded.get('terms_display_mode'))
                state['terms_updated_date'] = _auth_text_value(loaded.get('terms_updated_date'), AUTH_TERMS_DEFAULT_UPDATED_DATE, 40)
                state['terms_documents'] = _auth_terms_normalize_documents(loaded.get('terms_documents'))
                state['enabled'] = bool(
                    loaded.get('enabled')
                    and state['sender_email']
                    and state['sender_auth_code']
                )
                try:
                    state['max_accounts'] = max(0, int(loaded.get('max_accounts') or 0))
                except Exception:
                    state['max_accounts'] = 0
                try:
                    state['updated_at'] = float(loaded.get('updated_at') or _utc_ts())
                except Exception:
                    state['updated_at'] = _utc_ts()
    except Exception:
        app_logger.exception('[email_login] load_failed')
    with _EMAIL_LOGIN_LOCK:
        _EMAIL_LOGIN_STATE.clear()
        _EMAIL_LOGIN_STATE.update(state)


def _email_login_save() -> None:
    with _EMAIL_LOGIN_LOCK:
        sender_email = _normalize_login_email(_EMAIL_LOGIN_STATE.get('sender_email') or '')
        sender_auth_code = str(_EMAIL_LOGIN_STATE.get('sender_auth_code') or '').strip()
        payload = {
            'sender_email': sender_email,
            'sender_auth_code': sender_auth_code,
            'enabled': bool(_EMAIL_LOGIN_STATE.get('enabled') and sender_email and sender_auth_code),
            'registration_open': bool(_EMAIL_LOGIN_STATE.get('registration_open', True)),
            'invite_required': bool(_EMAIL_LOGIN_STATE.get('invite_required', True)),
            'allowed_email_domains': _normalize_email_domain_rules(_EMAIL_LOGIN_STATE.get('allowed_email_domains')),
            'terms_enabled': bool(_EMAIL_LOGIN_STATE.get('terms_enabled', False)),
            'terms_display_mode': _auth_terms_display_mode(_EMAIL_LOGIN_STATE.get('terms_display_mode')),
            'terms_updated_date': _auth_text_value(_EMAIL_LOGIN_STATE.get('terms_updated_date'), AUTH_TERMS_DEFAULT_UPDATED_DATE, 40),
            'terms_documents': _auth_terms_normalize_documents(_EMAIL_LOGIN_STATE.get('terms_documents')),
            'max_accounts': max(0, int(_EMAIL_LOGIN_STATE.get('max_accounts') or 0)),
            'updated_at': _utc_ts(),
        }
        for key, value in payload.items():
            _EMAIL_LOGIN_STATE[key] = value
    tmp = EMAIL_LOGIN_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, EMAIL_LOGIN_FILE)
    except Exception:
        app_logger.exception('[email_login] save_failed')
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

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

def _send_account_notice_email(recipient_email: str, subject: str, body: str, *, html_body: str = '') -> bool:
    recipient = _normalize_login_email(recipient_email)
    if not recipient:
        return False
    with _EMAIL_LOGIN_LOCK:
        sender_email = _normalize_login_email(_EMAIL_LOGIN_STATE.get('sender_email') or '')
        sender_auth_code = str(_EMAIL_LOGIN_STATE.get('sender_auth_code') or '').strip()
    if not sender_email or not sender_auth_code:
        return False
    msg = EmailMessage()
    msg['Subject'] = str(subject or 'Apervia 账号通知').strip()[:120]
    msg['From'] = email.utils.formataddr(('Apervia 账号通知', sender_email))
    msg['To'] = recipient
    msg.set_content(str(body or '').strip() or '你的 Apervia 账号状态已更新。')
    if str(html_body or '').strip():
        clean_html_body = str(html_body).strip()
        msg.add_alternative(clean_html_body, subtype='html')
        if 'cid:apervia-product-icon' in clean_html_body:
            icon_path = os.path.join(BASE_DIR, 'static', 'index3', 'assets', 'email-icon-256x256.png')
            try:
                with open(icon_path, 'rb') as icon_handle:
                    msg.get_payload()[-1].add_related(
                        icon_handle.read(),
                        maintype='image',
                        subtype='png',
                        cid='<apervia-product-icon>',
                        filename='apervia-icon.png',
                        disposition='inline',
                    )
            except Exception as exc:
                app_logger.warning('[auth_account_notice] inline_icon_failed %s: %s', type(exc).__name__, exc)
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=20, context=context) as smtp:
            smtp.login(sender_email, sender_auth_code)
            smtp.send_message(msg)
        return True
    except Exception as e:
        app_logger.warning('[auth_account_notice] send_failed email=%s %s: %s', recipient, type(e).__name__, e)
        return False


def _auth_notify_account_delete_requested(email: str, requested_at: float, scheduled_at: float) -> bool:
    body = (
        '你的 Apervia 账号已进入删除期。\n\n'
        f'申请时间：{_fmt_ts(requested_at)}\n'
        f'正式删除时间：{_fmt_ts(scheduled_at)}\n\n'
        f'在 {AUTH_ACCOUNT_DELETE_GRACE_DAYS} 天内，你可以重新登录并撤销删除。'
    )
    return _send_account_notice_email(email, 'Apervia 账号已进入删除期', body)


def _auth_notify_account_delete_restored(email: str) -> bool:
    body = '你的 Apervia 账号删除申请已撤销，账号已恢复正常使用。\n\n如果不是你本人操作，请尽快修改密码。'
    return _send_account_notice_email(email, 'Apervia 账号删除已撤销', body)


def _auth_notify_account_delete_finalized(email: str, finalized_at: float) -> bool:
    body = f'你的 Apervia 账号已于 {_fmt_ts(finalized_at)} 正式删除。\n\n聊天记录、记忆和个人资料已进入清理流程。'
    return _send_account_notice_email(email, 'Apervia 账号已正式删除', body)


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
