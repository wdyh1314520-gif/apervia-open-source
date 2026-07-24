"""Authenticated account, profile, session, and chat-sync routes."""

@app.get('/login')
def auth_login_page():
    if _auth_identity_current_user():
        return redirect(_auth_identity_safe_next(request.args.get('next') or '/'), code=302)
    return _admin_html_response(_auth_identity_login_html())


def _json_no_store(payload, status: int = 200):
    resp = jsonify(payload)
    resp.status_code = int(status or 200)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp


@app.get('/api3/auth/me')
def auth_me():
    state = _current_login_account()
    if state.get('session_invalidated'):
        return _json_no_store(state, 403)
    email = _normalize_login_email(state.get('email') or '')
    if state.get('logged_in') and email:
        presence = _auth_presence_mark(email, path=request.path)
        if presence:
            state = dict(state or {})
            state.update(presence)
        try:
            state = dict(state or {})
            state['profile'] = _auth_account_profile_public(email, _auth_account_profile_get(email))
        except Exception:
            app_logger.exception('[auth_account_profile] attach_to_me_failed email=%s', email)
        try:
            state = dict(state or {})
            state['release_announcement'] = _platform_release_announcement_for_user(
                str(state.get('user_id') or ''),
                str((state.get('profile') or {}).get('ui_language') or ''),
            )
        except Exception:
            app_logger.exception('[release_announcement] attach_to_me_failed email=%s', email)
    return _json_no_store(state)


@app.get('/api3/auth/profile')
def auth_profile_get():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    profile = _auth_account_profile_get(email)
    return _json_no_store({
        'ok': True,
        'email': _normalize_login_email(email),
        'app_version': APP_VERSION,
        'profile': _auth_account_profile_public(email, profile),
    })


@app.get('/api3/auth/version-check')
def auth_version_check_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    try:
        payload = _platform_release_update_service.check()
    except Exception as exc:
        app_logger.warning('[release_update] check_failed type=%s', type(exc).__name__)
        return _json_no_store({'ok': False, 'error': 'version_check_failed'}, 502)
    return _json_no_store({'ok': True, **payload})


@app.post('/api3/auth/ui-language')
def auth_ui_language_save():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    data = request.get_json(force=True, silent=True) or {}
    try:
        profile = _auth_account_ui_language_set(
            email,
            (data if isinstance(data, dict) else {}).get('language'),
        )
    except ValueError as exc:
        return _json_no_store({'error': str(exc)}, 400)
    realtime_notify = globals().get('_account_realtime_notify') or globals().get('_chat_sync_realtime_notify')
    if callable(realtime_notify):
        try:
            realtime_notify(email, event_kind='profile')
        except TypeError:
            realtime_notify(email)
        except Exception:
            app_logger.exception('[auth_account_profile] language_notify_failed email=%s', _normalize_login_email(email))
    return _json_no_store({
        'ok': True,
        'language': profile.get('ui_language'),
        'profile': _auth_account_profile_public(email, profile),
    })


@app.post('/api3/auth/release-announcement/acknowledge')
def auth_release_announcement_acknowledge_route():
    user = _auth_identity_current_user()
    if not user:
        return _json_no_store({'error': 'login_required', 'message': '请先登录'}, 401)
    data = request.get_json(force=True, silent=True) or {}
    try:
        payload = _platform_release_announcement_service.acknowledge(
            str(user.get('id') or ''),
            str((data if isinstance(data, dict) else {}).get('id') or ''),
        )
    except ValueError as exc:
        return _json_no_store({'error': str(exc)}, 409)
    return _json_no_store(payload)


@app.post('/api3/auth/profile')
def auth_profile_save():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    try:
        profile = _auth_account_profile_set(email, data)
    except ValueError as e:
        return _json_no_store({'error': str(e)}, 400)
    realtime_notify = globals().get('_account_realtime_notify') or globals().get('_chat_sync_realtime_notify')
    if callable(realtime_notify):
        try:
            realtime_notify(email, event_kind='profile')
        except TypeError:
            realtime_notify(email)
        except Exception:
            app_logger.exception('[auth_account_profile] realtime_notify_failed email=%s', _normalize_login_email(email))
    return _json_no_store({
        'ok': True,
        'email': _normalize_login_email(email),
        'profile': _auth_account_profile_public(email, profile),
    })


@app.get('/api3/auth/status')
def auth_status():
    limit_resp = _apply_rate_limit('auth_status')
    if limit_resp is not None:
        return limit_resp
    count = _auth_identity_user_count()
    return _json_no_store({
        'ok': True,
        'provider': 'local_password',
        'first_user': count == 0,
        'signup_enabled': bool(AUTH_SIGNUP_ENABLED or count == 0),
        'default_role': AUTH_DEFAULT_ROLE,
        'session_max_age_s': AUTH_SESSION_MAX_AGE_S,
    })


@app.post('/api3/auth/register')
def auth_register_route():
    data = request.get_json(force=True, silent=True) or {}
    return _auth_identity_register_http(data)


@app.post('/api3/auth/password-login')
def auth_password_login():
    data = request.get_json(force=True, silent=True) or {}
    return _auth_identity_password_login_http(data)


@app.post('/api3/auth/delete-account')
def auth_delete_account():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    normalized = _normalize_login_email(email)
    data = request.get_json(force=True, silent=True) or {}
    confirm_email = _normalize_login_email(data.get('confirm_email') or data.get('email') or '')
    if confirm_email != normalized:
        return _json_no_store({'error': '请完整输入当前账号邮箱确认删除'}, 400)
    try:
        _auth_identity_validate_delete(normalized)
        result = _auth_user_delete_account(normalized, reason='user_request', actor='user')
        _auth_identity_mark_deleted(normalized)
    except ValueError as e:
        return _json_no_store({'error': str(e)}, 400)
    identity_user = _auth_identity_current_user()
    if identity_user:
        _auth_identity_revoke_user_sessions(str(identity_user.get('id') or ''))
    resp = _json_no_store({
        'ok': True,
        'message': AUTH_ACCOUNT_DELETE_PENDING_MESSAGE,
        'email_masked': _mask_login_email(normalized),
        'delete_pending': True,
        'account_delete_pending': True,
        'delete_requested_at': _fmt_ts(result.get('delete_requested_at')),
        'delete_scheduled_at': _fmt_ts(result.get('delete_scheduled_at')),
        'delete_grace_days': int(result.get('delete_grace_days') or AUTH_ACCOUNT_DELETE_GRACE_DAYS),
        'removed_profile': False,
        'removed_chat': False,
        'removed_memory': False,
        'revoked_sessions': int(result.get('revoked_sessions') or 0),
        'login_required': True,
        'login_url': '/login',
        'reason_code': 'account_delete_pending',
    })
    return _auth_identity_clear_session_cookie(resp)


@app.get('/api3/auth/export-account')
def auth_export_account():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    normalized = _normalize_login_email(email)
    try:
        payload = _auth_account_export_payload(normalized)
    except ValueError as e:
        return _json_no_store({'error': str(e)}, 400)
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    ts = time.strftime('%Y%m%d_%H%M%S', time.localtime())
    filename = f'webai_account_export_{ts}.json'
    resp = Response(raw, mimetype='application/json; charset=utf-8')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


@app.post('/api3/auth/logout')
def auth_logout():
    _auth_identity_revoke_current_session()
    resp = jsonify({'ok': True})
    return _auth_identity_clear_session_cookie(resp)



@app.get('/api3/chat-sync/store')
def chat_sync_store_get_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark(email, path=request.path)
    rec = _auth_chat_store_get(email) or {}
    updated_ts = float(rec.get('updated_at') or 0.0)
    revision = _auth_chat_store_revision_value(rec)
    return _json_no_store({
        'ok': True,
        'email': email,
        'store': _auth_chat_public_store_for_response(rec.get('store')) if isinstance(rec.get('store'), dict) else None,
        'updated_at': _fmt_ts(updated_ts),
        'updated_ts': updated_ts,
        'revision': revision,
        'server_revision': revision,
        'sync_protocol': 'ops_v2',
        'limits': _auth_chat_limits_payload(),
    })


@app.post('/api3/chat-sync/store')
def chat_sync_store_save_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark(email, path=request.path)
    return _json_no_store({
        'ok': False,
        'error': 'snapshot_sync_disabled',
        'message': '账号会话已切换为增量同步，拒绝整库覆盖',
        'sync_protocol': 'ops_v2',
        'limits': _auth_chat_limits_payload(),
    }, 409)

@app.post('/api3/chat-sync/push')
def chat_sync_push_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark(email, path=request.path)
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    try:
        rec, result = _auth_chat_store_push_ops(
            email,
            data.get('ops') or [],
            base_revision=data.get('base_revision'),
            device_id=str(data.get('device_id') or ''),
        )
    except ValueError as e:
        message = str(e)
        status = 413 if ('过大' in message or '过多' in message) else 400
        return _json_no_store({'error': message, 'sync_protocol': 'ops_v2'}, status)
    updated_ts = float(rec.get('updated_at') or 0.0)
    revision = _auth_chat_store_revision_value(rec)
    has_conflict = bool(result.get('conflict') or result.get('conflicts'))
    sync_from_store = globals().get('_auth_personalization_sync_from_store')
    if callable(sync_from_store):
        try:
            if isinstance(rec.get('store'), dict) and 'personalization' in rec.get('store'):
                sync_from_store(email, store_payload=rec.get('store'), updated_at=updated_ts)
        except Exception:
            app_logger.exception('[auth_personalization] mirror_from_chat_store_failed email=%s', _normalize_login_email(email))
    return _json_no_store({
        'ok': not has_conflict,
        'email': email,
        'updated_at': _fmt_ts(updated_ts),
        'updated_ts': updated_ts,
        'revision': revision,
        'server_revision': revision,
        'sync_protocol': 'ops_v2',
        'accepted': result.get('accepted') or [],
        'duplicates': result.get('duplicates') or [],
        'conflict': has_conflict,
        'conflicts': result.get('conflicts') or [],
        'store': _auth_chat_public_store_for_response(rec.get('store')) if isinstance(rec.get('store'), dict) else None,
        'store_changed': bool(result.get('store_changed')),
        'message': '账号云端会话已按限制自动精简' if result.get('store_changed') else '',
        'limits': _auth_chat_limits_payload(),
    })


@app.get('/api3/chat-sync/pull')
def chat_sync_pull_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark(email, path=request.path)
    try:
        since_revision = int(request.args.get('since_revision') or request.args.get('since') or 0)
    except Exception:
        since_revision = 0
    include_store = str(request.args.get('include_store') or request.args.get('store') or '').strip().lower() in {'1', 'true', 'yes', 'full'}
    try:
        rec, ops, need_snapshot = _auth_chat_store_ops_since(email, since_revision)
    except Exception:
        rec = _auth_chat_store_get(email) or {}
        ops = []
        need_snapshot = True
    updated_ts = float(rec.get('updated_at') or 0.0)
    revision = _auth_chat_store_revision_value(rec)
    store_obj = rec.get('store') if isinstance(rec.get('store'), dict) else {}
    public_store = _auth_chat_public_store_for_response(store_obj)
    return _json_no_store({
        'ok': True,
        'email': email,
        'updated_at': _fmt_ts(updated_ts),
        'updated_ts': updated_ts,
        'revision': revision,
        'server_revision': revision,
        'sync_protocol': 'ops_v2',
        'ops': ops if isinstance(ops, list) else [],
        'snapshot_required': bool(need_snapshot),
        'store': public_store if (include_store and need_snapshot and isinstance(public_store, dict)) else None,
        'limits': _auth_chat_limits_payload(),
    })
