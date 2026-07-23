# Split from app3_parts/auth/platform_auth_core_part.py.
# Purpose: email-login public state, configuration, password reset, current-login helpers, and session guard.
# Loaded by platform_auth_core_part.py via _exec_split_file(...), sharing the original global namespace.

def _email_login_public_state(include_private: bool = False) -> dict:
    with _EMAIL_LOGIN_LOCK:
        sender_email = _normalize_login_email(_EMAIL_LOGIN_STATE.get('sender_email') or '')
        sender_auth_code = str(_EMAIL_LOGIN_STATE.get('sender_auth_code') or '').strip()
        registration_open = bool(_EMAIL_LOGIN_STATE.get('registration_open', True))
        invite_required = bool(_EMAIL_LOGIN_STATE.get('invite_required', True))
        allowed_email_domains = _normalize_email_domain_rules(_EMAIL_LOGIN_STATE.get('allowed_email_domains'))
        terms_enabled = bool(_EMAIL_LOGIN_STATE.get('terms_enabled', False))
        terms_display_mode = _auth_terms_display_mode(_EMAIL_LOGIN_STATE.get('terms_display_mode'))
        terms_updated_date = _auth_text_value(_EMAIL_LOGIN_STATE.get('terms_updated_date'), AUTH_TERMS_DEFAULT_UPDATED_DATE, 40)
        terms_documents = _auth_terms_normalize_documents(_EMAIL_LOGIN_STATE.get('terms_documents'))
        enabled = bool(
            _EMAIL_LOGIN_STATE.get('enabled')
            and sender_email
            and sender_auth_code
        )
        max_accounts = max(0, int(_EMAIL_LOGIN_STATE.get('max_accounts') or 0))
        updated_at = _EMAIL_LOGIN_STATE.get('updated_at')
    user_count = _auth_user_count()
    registration_paused = bool((not registration_open) or (max_accounts > 0 and user_count >= max_accounts))
    invite_summary = _auth_invite_code_summary()
    return {
        'enabled': enabled,
        'sender_email': sender_email if include_private else '',
        'sender_email_masked': _mask_login_email(sender_email),
        'sender_auth_code': sender_auth_code if include_private else '',
        'password_configured': user_count > 0,
        'smtp_configured': bool(sender_email and sender_auth_code),
        'user_count': user_count,
        'max_accounts': max_accounts,
        'available_slots': (max_accounts - user_count) if max_accounts > 0 else -1,
        'registration_open': registration_open,
        'registration_paused': registration_paused,
        'registration_paused_title': AUTH_REGISTRATION_PAUSED_TITLE,
        'registration_paused_message': AUTH_REGISTRATION_PAUSED_MESSAGE,
        'allowed_email_domains': allowed_email_domains,
        'email_domain_rules_text': '\n'.join(allowed_email_domains),
        'terms_enabled': terms_enabled,
        'terms_display_mode': terms_display_mode,
        'terms_updated_date': terms_updated_date,
        'terms_documents': _auth_terms_documents_public(terms_documents, include_content=include_private),
        'blacklist_count': _auth_blacklist_count(),
        'invite_required': invite_required,
        'invite_code_length': int(AUTH_INVITE_CODE_LENGTH),
        'invite_code_ttl_s': int(invite_summary.get('ttl_s') or AUTH_INVITE_CODE_TTL_S),
        'invite_code_ttl_text': str(invite_summary.get('ttl_text') or _invite_code_format_ttl(AUTH_INVITE_CODE_TTL_S)),
        'invite_total_count': int(invite_summary.get('total') or 0),
        'invite_active_count': int(invite_summary.get('active') or 0),
        'invite_used_count': int(invite_summary.get('used') or 0),
        'invite_expired_count': int(invite_summary.get('expired') or 0),
        'invite_revoked_count': int(invite_summary.get('revoked') or 0),
        'updated_at': _fmt_ts(updated_at),
    }


def _email_login_configure(
    sender_email: str,
    sender_auth_code: str,
    login_email: str,
    login_password: str,
    *,
    max_accounts=0,
    registration_open=True,
    invite_required=True,
    allowed_email_domains=None,
    terms_enabled=False,
    terms_display_mode='',
    terms_updated_date='',
    terms_documents=None,
) -> dict:
    normalized_sender = _normalize_login_email(sender_email)
    auth_code = str(sender_auth_code or '').strip()
    domain_rules = _normalize_email_domain_rules(allowed_email_domains)
    normalized_terms_enabled = bool(terms_enabled)
    normalized_terms_mode = _auth_terms_display_mode(terms_display_mode)
    normalized_terms_updated_date = _auth_text_value(terms_updated_date, AUTH_TERMS_DEFAULT_UPDATED_DATE, 40)
    normalized_terms_docs = _auth_terms_normalize_documents(terms_documents)
    try:
        limit_accounts = max(0, int(max_accounts or 0))
    except Exception:
        raise ValueError('注册账号上限必须是 0 或正整数')
    with _EMAIL_LOGIN_LOCK:
        old_sender = _normalize_login_email(_EMAIL_LOGIN_STATE.get('sender_email') or '')
        old_auth = str(_EMAIL_LOGIN_STATE.get('sender_auth_code') or '').strip()
        old_max_accounts = max(0, int(_EMAIL_LOGIN_STATE.get('max_accounts') or 0))
    if not normalized_sender:
        normalized_sender = old_sender
    if not auth_code:
        auth_code = old_auth
    if limit_accounts <= 0:
        limit_accounts = old_max_accounts if old_max_accounts > 0 and str(max_accounts or '').strip() == '' else limit_accounts
    if not normalized_sender or not _is_supported_qq_sender_email(normalized_sender):
        raise ValueError('请输入可用的 QQ 发件邮箱')
    if len(auth_code) < 6:
        raise ValueError('请输入 QQ 邮箱 SMTP 授权码')
    with _EMAIL_LOGIN_LOCK:
        _EMAIL_LOGIN_STATE['sender_email'] = normalized_sender
        _EMAIL_LOGIN_STATE['sender_auth_code'] = auth_code
        _EMAIL_LOGIN_STATE['enabled'] = True
        _EMAIL_LOGIN_STATE['registration_open'] = bool(registration_open)
        _EMAIL_LOGIN_STATE['invite_required'] = bool(invite_required)
        _EMAIL_LOGIN_STATE['allowed_email_domains'] = domain_rules
        _EMAIL_LOGIN_STATE['terms_enabled'] = normalized_terms_enabled
        _EMAIL_LOGIN_STATE['terms_display_mode'] = normalized_terms_mode
        _EMAIL_LOGIN_STATE['terms_updated_date'] = normalized_terms_updated_date
        _EMAIL_LOGIN_STATE['terms_documents'] = normalized_terms_docs
        _EMAIL_LOGIN_STATE['max_accounts'] = limit_accounts
        _EMAIL_LOGIN_STATE['updated_at'] = _utc_ts()
    _email_login_save()
    first_email = _normalize_login_email(login_email)
    first_password = str(login_password or '')
    if first_email and '@' in first_email and first_password and len(first_password) >= 6 and not _auth_user_exists(first_email):
        try:
            _auth_create_user(first_email, first_password)
        except Exception:
            app_logger.exception('[auth_users] seed_admin_user_failed')
    return _email_login_public_state(include_private=True)


def _email_login_disable() -> dict:
    with _EMAIL_LOGIN_LOCK:
        _EMAIL_LOGIN_STATE['sender_email'] = ''
        _EMAIL_LOGIN_STATE['sender_auth_code'] = ''
        _EMAIL_LOGIN_STATE['enabled'] = False
        _EMAIL_LOGIN_STATE['max_accounts'] = max(0, int(_EMAIL_LOGIN_STATE.get('max_accounts') or 0))
        _EMAIL_LOGIN_STATE['updated_at'] = _utc_ts()
    _email_login_save()
    return _email_login_public_state(include_private=True)


def _current_login_email() -> str:
    identity_user = _auth_identity_current_user()
    return _normalize_login_email((identity_user or {}).get('email') or '')


def _current_login_account() -> dict:
    return _auth_identity_current_account()


def _require_logged_in_email():
    state = _current_login_account()
    if state.get('session_invalidated'):
        return '', (jsonify(state), 403)
    email = _normalize_login_email(state.get('email') or '')
    if not state.get('logged_in') or not email:
        return '', (jsonify({
            'error': 'login_required',
            'message': AUTH_LOGIN_DISABLED_MESSAGE,
            'login_required': True,
            'login_url': '/login',
        }), 401)
    return email, None
