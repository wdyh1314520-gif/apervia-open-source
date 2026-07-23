# Split from app3_parts/platform/platform_auth_part.py.
# Purpose: auth, account, rate-limit, blacklist, and chat-sync bootstrap routes.
# Loaded by app3.py via _exec_split_file(...), sharing the original global namespace.
# Runtime chat-sync endpoints are finalized in user_personalization_runtime_part.py
# so manifest/session/push/pull/store share the same light-presence behavior.

@app.get('/rate-admin')
def rate_limit_admin_page():
    gate = _local_admin_page_guard('/rate-admin', '限流')
    if gate is not None:
        return gate
    return _local_admin_html_response(_rate_limit_admin_html())


@app.get('/blacklist-admin')
def blacklist_admin_page():
    gate = _local_admin_page_guard('/blacklist-admin', '黑名单面板')
    if gate is not None:
        return gate
    return _local_admin_html_response(_blacklist_admin_html())


@app.get('/api3/rate-limit/state')
def rate_limit_state_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    return jsonify(_rate_limit_public_state())


@app.post('/api3/rate-limit/config')
def rate_limit_config_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        state = _rate_limit_update_config(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(state)


@app.post('/api3/rate-limit/reset')
def rate_limit_reset_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    state = _rate_limit_reset(
        clear_blocks=bool(data.get('clear_blocks', True)),
        clear_events=bool(data.get('clear_events', True)),
        clear_stats=bool(data.get('clear_stats', False)),
    )
    return jsonify(state)


@app.post('/api3/rate-limit/manual-block')
def rate_limit_manual_block_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        state = _rate_limit_add_manual_block(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(state)


@app.post('/api3/rate-limit/manual-unblock')
def rate_limit_manual_unblock_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        state = _rate_limit_remove_manual_block(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(state)


@app.get('/legal/<path:slug>')
def auth_legal_doc_page(slug):
    return Response(_auth_legal_doc_html(slug), content_type='text/html; charset=utf-8')


@app.get('/login')
def email_login_page():
    if _auth_identity_current_user():
        return redirect(_auth_identity_safe_next(request.args.get('next') or '/'), code=302)
    return _local_admin_html_response(_auth_identity_login_html())


def _json_no_store(payload, status: int = 200):
    resp = jsonify(payload)
    resp.status_code = int(status or 200)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp


@app.get('/api3/auth/me')
def email_login_me():
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
def email_login_profile_get():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    profile = _auth_account_profile_get(email)
    return _json_no_store({
        'ok': True,
        'email': _normalize_login_email(email),
        'profile': _auth_account_profile_public(email, profile),
    })


@app.post('/api3/auth/ui-language')
def email_login_ui_language_save():
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
def email_login_profile_save():
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
def email_login_status():
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


@app.get('/api3/auth/users')
def auth_users_list_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    return jsonify({'ok': True, 'users': _auth_users_public_list(include_private=True)})


@app.get('/api3/auth/account-delete-logs')
def auth_account_delete_logs_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    try:
        limit = int(request.args.get('limit') or 80)
    except Exception:
        limit = 80
    return jsonify({'ok': True, 'events': _auth_account_delete_logs_public(limit=limit, include_private=True)})




@app.post('/api3/auth/account-delete-logs-clear')
def auth_account_delete_logs_clear_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    cleared = _auth_account_delete_logs_clear()
    return jsonify({'ok': True, 'cleared': cleared, 'events': []})

@app.post('/api3/auth/user-restore-delete')
def auth_user_restore_delete_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    email = str(data.get('email') or '')
    try:
        rec = _auth_user_restore_account(email, actor='admin')
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'ok': True, 'message': '已撤销删除', 'user': _auth_user_public(rec, include_private=True)})


@app.post('/api3/auth/finalize-account-deletions')
def auth_finalize_account_deletions_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    changed = bool(_auth_finalize_expired_account_deletions())
    return jsonify({'ok': True, 'changed': changed})


@app.get('/api3/auth/invite-codes')
def auth_invite_codes_list_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    _auth_cleanup_invite_codes(AUTH_INVITE_CODE_AUTO_CLEANUP_RETENTION_S)
    return jsonify({'ok': True, 'codes': _auth_invite_codes_public_list(include_private=True), 'summary': _auth_invite_code_summary()})


@app.post('/api3/auth/invite-code-create')
def auth_invite_code_create_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    try:
        invite = _auth_create_invite_code()
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'ok': True, 'invite': invite, 'summary': _auth_invite_code_summary()})


@app.post('/api3/auth/invite-code-create-batch')
def auth_invite_code_create_batch_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        invites = _auth_create_invite_codes(data.get('count') or 1)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    first_invite = invites[0] if invites else {}
    return jsonify({'ok': True, 'invite': first_invite, 'invites': invites, 'count': len(invites), 'summary': _auth_invite_code_summary()})


@app.post('/api3/auth/invite-code-revoke')
def auth_invite_code_revoke_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        invite = _auth_revoke_invite_code(str(data.get('code') or ''))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'ok': True, 'invite': invite, 'summary': _auth_invite_code_summary()})


@app.post('/api3/auth/invite-code-regenerate')
def auth_invite_code_regenerate_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        payload = _auth_regenerate_invite_code(str(data.get('code') or ''))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'ok': True, **payload, 'invite': dict(payload.get('new_invite') or {}), 'summary': _auth_invite_code_summary()})


@app.post('/api3/auth/invite-code-cleanup')
def auth_invite_code_cleanup_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    result = _auth_cleanup_invite_codes(0)
    return jsonify({'ok': True, **result, 'summary': _auth_invite_code_summary()})


@app.post('/api3/auth/user-toggle')
def auth_user_toggle_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    email = str(data.get('email') or '')
    enabled = bool(data.get('enabled'))
    try:
        rec = _auth_user_set_enabled(email, enabled)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    revoked_sessions = 0 if enabled else _auth_identity_revoke_email_sessions(email)
    return jsonify({'ok': True, 'user': _auth_user_public(rec, include_private=True), 'revoked_sessions': revoked_sessions})


@app.post('/api3/auth/user-private-search-toggle')
def auth_user_private_search_toggle_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    email = str(data.get('email') or '')
    allowed = bool(data.get('allowed'))
    try:
        rec = _auth_user_set_private_search_access(email, allowed)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'ok': True, 'user': _auth_user_public(rec, include_private=True)})


@app.get('/api3/auth/blacklist')
def auth_blacklist_list_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    return jsonify({'ok': True, 'users': _auth_blacklisted_users_public_list(include_private=True)})


@app.post('/api3/auth/user-blacklist')
def auth_user_blacklist_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    email = str(data.get('email') or '')
    blocked = bool(data.get('blocked'))
    reason = str(data.get('reason') or '').strip()[:120]
    try:
        rec = _auth_user_set_blacklisted(email, blocked, reason)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    revoked_sessions = _auth_identity_revoke_email_sessions(email) if blocked else 0
    message = '已解除拉黑/封禁' if not blocked else f'已拉黑，{AUTH_ACCOUNT_BLACKLIST_GRACE_DAYS} 天内可由管理员解封'
    return jsonify({'ok': True, 'message': message, 'user': _auth_user_public(rec, include_private=True), 'revoked_sessions': revoked_sessions})


@app.post('/api3/auth/config')
def email_login_config():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        state = _email_login_configure(
            str(data.get('sender_email') or ''),
            str(data.get('sender_auth_code') or ''),
            str(data.get('login_email') or ''),
            str(data.get('login_password') or ''),
            max_accounts=data.get('max_accounts'),
            registration_open=bool(data.get('registration_open', True)),
            invite_required=bool(data.get('invite_required', True)),
            allowed_email_domains=data.get('allowed_email_domains') if isinstance(data, dict) else None,
            terms_enabled=bool(data.get('terms_enabled', False)),
            terms_display_mode=str(data.get('terms_display_mode') or ''),
            terms_updated_date=str(data.get('terms_updated_date') or ''),
            terms_documents=data.get('terms_documents') if isinstance(data, dict) else None,
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'ok': True, **state})


@app.post('/api3/auth/disable')
def email_login_disable_route():
    guard = _require_local_admin_grant(scope=LOCAL_ADMIN_SCOPE)
    if guard is not None:
        return guard
    state = _email_login_disable()
    return jsonify({'ok': True, **state})


@app.post('/api3/auth/register')
def auth_register_route():
    data = request.get_json(force=True, silent=True) or {}
    return _auth_identity_register_http(data)


@app.post('/api3/auth/password-login')
def email_password_login():
    data = request.get_json(force=True, silent=True) or {}
    return _auth_identity_password_login_http(data)


@app.post('/api3/auth/delete-account')
def email_login_delete_account():
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
def email_login_export_account():
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
def email_login_logout():
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
