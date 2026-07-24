# lightweight auth presence, chat-sync manifest/session routes, realtime SSE, and incremental sync.

# ==============================
# Big-platform stability layer: light auth/presence and manifest cache
# ==============================
_AUTH_LIGHT_PRESENCE_LOCK = threading.Lock()
_AUTH_LIGHT_PRESENCE_LAST: dict[str, float] = {}
_AUTH_LIGHT_PRESENCE_INTERVAL_S = 18.0
_CHAT_SYNC_MANIFEST_CACHE_LOCK = threading.Lock()
_CHAT_SYNC_MANIFEST_CACHE: dict[str, dict] = {}
_CHAT_SYNC_MANIFEST_CACHE_TTL_S = 30.0


def _auth_presence_mark_light(email: str, path: str = '') -> dict:
    """Throttle presence updates so cheap endpoints stay cheap under public traffic."""
    normalized = _normalize_login_email(email)
    if not normalized:
        return {}
    session_id = _auth_current_session_key()
    key = normalized + '|' + (session_id or '-')
    now_ts = _utc_ts()
    should_mark = False
    with _AUTH_LIGHT_PRESENCE_LOCK:
        last_ts = float(_AUTH_LIGHT_PRESENCE_LAST.get(key) or 0.0)
        if (now_ts - last_ts) >= _AUTH_LIGHT_PRESENCE_INTERVAL_S:
            _AUTH_LIGHT_PRESENCE_LAST[key] = now_ts
            should_mark = True
        if len(_AUTH_LIGHT_PRESENCE_LAST) > 2048:
            cutoff = now_ts - 3600.0
            for old_key, old_ts in list(_AUTH_LIGHT_PRESENCE_LAST.items())[:512]:
                try:
                    if float(old_ts or 0.0) < cutoff:
                        _AUTH_LIGHT_PRESENCE_LAST.pop(old_key, None)
                except Exception:
                    _AUTH_LIGHT_PRESENCE_LAST.pop(old_key, None)
    if not should_mark:
        return {}
    try:
        marker = globals().get('_auth_presence_mark')
        if callable(marker):
            return marker(normalized, path=path) or {}
    except Exception:
        try:
            app_logger.warning('[auth_presence_light] mark_failed email=%s', normalized)
        except Exception:
            pass
    return {}


def auth_me_light():
    """Fast auth/me override: never make public auth probing pay for full presence every time."""
    state = _current_login_account()
    if state.get('session_invalidated'):
        return _json_no_store_response(state, 403)
    email = _normalize_login_email(state.get('email') or '')
    if state.get('logged_in') and email:
        presence = _auth_presence_mark_light(email, path=request.path)
        if presence:
            state = dict(state or {})
            state.update(presence)
        try:
            state = dict(state or {})
            profile = _auth_account_profile_public(email, _auth_account_profile_get(email))
            state['profile'] = profile
            announcement_getter = globals().get('_platform_release_announcement_for_user')
            if callable(announcement_getter):
                state['release_announcement'] = announcement_getter(
                    str(state.get('user_id') or ''),
                    str(profile.get('ui_language') or ''),
                )
        except Exception:
            try:
                app_logger.exception('[release_announcement] attach_to_me_light_failed email=%s', email)
            except Exception:
                pass
    try:
        state = dict(state or {})
        state['auth_fast'] = True
        state['presence_throttled'] = True
    except Exception:
        pass
    return _json_no_store_response(state)


try:
    app.view_functions['auth_me'] = auth_me_light
except Exception:
    pass


def _chat_sync_manifest_cache_key(email: str, revision, updated_ts, limit: int) -> str:
    return '|'.join([
        _normalize_login_email(email),
        str(int(float(revision or 0))),
        str(int(float(updated_ts or 0) * 1000)),
        str(int(limit or 0)),
    ])


def _chat_sync_manifest_cache_get(email: str, revision, updated_ts, limit: int) -> dict | None:
    key = _chat_sync_manifest_cache_key(email, revision, updated_ts, limit)
    now_ts = _utc_ts()
    with _CHAT_SYNC_MANIFEST_CACHE_LOCK:
        rec = _CHAT_SYNC_MANIFEST_CACHE.get(key)
        if not isinstance(rec, dict):
            return None
        created_at = float(rec.get('_cache_created_at') or 0.0)
        if created_at <= 0 or (now_ts - created_at) > _CHAT_SYNC_MANIFEST_CACHE_TTL_S:
            _CHAT_SYNC_MANIFEST_CACHE.pop(key, None)
            return None
        payload = rec.get('payload') if isinstance(rec.get('payload'), dict) else None
        return dict(payload or {}) if payload else None


def _chat_sync_manifest_cache_set(email: str, revision, updated_ts, limit: int, payload: dict | None = None) -> None:
    if not isinstance(payload, dict):
        return
    key = _chat_sync_manifest_cache_key(email, revision, updated_ts, limit)
    now_ts = _utc_ts()
    with _CHAT_SYNC_MANIFEST_CACHE_LOCK:
        if len(_CHAT_SYNC_MANIFEST_CACHE) > 256:
            for old_key in list(_CHAT_SYNC_MANIFEST_CACHE.keys())[:64]:
                _CHAT_SYNC_MANIFEST_CACHE.pop(old_key, None)
        _CHAT_SYNC_MANIFEST_CACHE[key] = {'_cache_created_at': now_ts, 'payload': dict(payload)}


def _chat_sync_safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return float(default)


def _chat_sync_message_text_preview(content, max_chars: int = 180) -> str:
    text = ''
    try:
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get('type') == 'text':
                        parts.append(str(item.get('text') or ''))
                    elif item.get('type') == 'image_url':
                        parts.append('[图片]')
            text = ' '.join(parts)
        elif isinstance(content, dict):
            kind = str(content.get('_kind') or content.get('kind') or '').strip()
            text = str(content.get('text') or content.get('answer') or content.get('filename') or '')
            if not text and kind:
                text = {'image_reply': '[图片]', 'file': '[文件]', 'image': '[图片]', 'weather': '[天气]'}.get(kind, kind)
    except Exception:
        text = ''
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip() + '…'
    return text


def _chat_sync_session_summary(session_id: str, session: dict | None = None) -> dict:
    s = dict(session or {}) if isinstance(session, dict) else {}
    sid = str(s.get('id') or session_id or '').strip()
    messages = s.get('messages') if isinstance(s.get('messages'), list) else []
    visible_messages = [m for m in messages if isinstance(m, dict) and str(m.get('role') or '').strip().lower() != 'system']
    last_preview = ''
    for msg in reversed(visible_messages):
        last_preview = _chat_sync_message_text_preview(msg.get('content'))
        if last_preview:
            break
    created_at = _chat_sync_safe_float(s.get('createdAt') or s.get('created_at') or s.get('created_at_ms') or 0.0)
    updated_at = _chat_sync_safe_float(s.get('updatedAt') or s.get('updated_at') or s.get('updated_at_ms') or created_at)
    mode_fn = globals().get('_auth_chat_session_mode')
    mode = mode_fn(s) if callable(mode_fn) else str(s.get('conversationMode') or s.get('conversation_mode') or 'chat').strip().lower()
    if mode not in {'chat', 'response'}:
        mode = 'response' if str(s.get('api_endpoint_mode') or s.get('endpoint_mode') or '').strip().lower() in {'response', 'responses', '/responses'} else 'chat'
    endpoint_mode = str(s.get('api_endpoint_mode') or s.get('endpoint_mode') or ('responses' if mode == 'response' else 'chat_completions')).strip()
    local_id = str(s.get('localId') or s.get('local_id') or sid).strip()
    op_id = str(s.get('opId') or s.get('op_id') or '').strip()
    server_version = int(_chat_sync_safe_float(s.get('serverVersion') or s.get('server_version') or s.get('_cloudRevision') or 0.0))
    sync_status = str(s.get('syncStatus') or s.get('sync_status') or ('active' if server_version > 0 else 'pending')).strip().lower()
    return {
        'id': sid,
        'localId': local_id,
        'local_id': local_id,
        'opId': op_id,
        'op_id': op_id,
        'conversationMode': mode,
        'conversation_mode': mode,
        'api_endpoint_mode': endpoint_mode,
        'endpoint_mode': endpoint_mode,
        'syncStatus': sync_status,
        'sync_status': sync_status,
        'serverVersion': server_version,
        'server_version': server_version,
        'conversationRecovery': s.get('conversationRecovery') if isinstance(s.get('conversationRecovery'), dict) else {
            'mode': mode,
            'local_id': local_id,
            'server_id': sid,
            'op_id': op_id,
            'server_version': server_version,
            'status': sync_status,
            'updated_at': updated_at,
        },
        'runRecovery': s.get('runRecovery') if isinstance(s.get('runRecovery'), dict) else None,
        'title': str(s.get('title') or '新会话').strip()[:120] or '新会话',
        'model': str(s.get('model') or '').strip()[:160],
        'createdAt': created_at,
        'updatedAt': updated_at,
        'webEnabled': bool(s.get('webEnabled')),
        'imageGenerationEnabled': bool(s.get('imageGenerationEnabled')),
        'chatThinkingType': str(s.get('chatThinkingType') or '').strip()[:40],
        'archived': bool(s.get('archived')) or _chat_sync_safe_float(s.get('archivedAt') or s.get('archived_at') or 0.0) > 0,
        'archivedAt': _chat_sync_safe_float(s.get('archivedAt') or s.get('archived_at') or 0.0),
        'archived_at': _chat_sync_safe_float(s.get('archived_at') or s.get('archivedAt') or 0.0),
        'pinned': bool(s.get('pinned')),
        'pinnedAt': _chat_sync_safe_float(s.get('pinnedAt') or s.get('pinned_at') or 0.0),
        'pinned_at': _chat_sync_safe_float(s.get('pinned_at') or s.get('pinnedAt') or 0.0),
        'message_count': len(visible_messages),
        'last_preview': last_preview,
    }


def _chat_sync_store_manifest(store_obj: dict | None = None, *, limit: int = 300) -> dict:
    store = dict(store_obj or {}) if isinstance(store_obj, dict) else {}
    sessions = store.get('sessions') if isinstance(store.get('sessions'), dict) else {}
    rows = []
    for sid, session in sessions.items():
        if not isinstance(session, dict):
            continue
        deleted_checker = globals().get('_auth_chat_session_deleted')
        if callable(deleted_checker) and deleted_checker(session):
            continue
        summary = _chat_sync_session_summary(str(sid or ''), session)
        if summary.get('id'):
            rows.append(summary)
    rows.sort(key=lambda item: _chat_sync_safe_float(item.get('updatedAt')), reverse=True)
    total_sessions = len(rows)
    try:
        max_rows = max(1, min(int(limit or 300), 1000))
    except Exception:
        max_rows = 300
    truncated = total_sessions > max_rows
    rows = rows[:max_rows]
    active_id = str(store.get('activeId') or '').strip()
    if active_id and active_id not in {str(x.get('id') or '') for x in rows}:
        active_id = ''
    if not active_id and rows:
        active_id = str(rows[0].get('id') or '')
    deleted_fn = globals().get('_auth_chat_deleted_sessions_from_store')
    deleted_sessions = deleted_fn(store) if callable(deleted_fn) else (store.get('_deleted_sessions') if isinstance(store.get('_deleted_sessions'), dict) else {})
    return {
        'active_id': active_id,
        'activeId': active_id,
        'sessions': rows,
        'total_sessions': total_sessions,
        'truncated': truncated,
        'personalization': store.get('personalization') if isinstance(store.get('personalization'), dict) else {},
        'deleted_sessions': deleted_sessions if isinstance(deleted_sessions, dict) else {},
    }


def chat_sync_manifest_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    try:
        limit = max(1, min(int(request.args.get('limit') or 300), 1000))
    except Exception:
        limit = 300
    rec = _auth_chat_store_get(email) or {}
    updated_ts = float(rec.get('updated_at') or 0.0)
    revision = _auth_chat_store_revision_value(rec) if callable(globals().get('_auth_chat_store_revision_value')) else int(rec.get('revision') or 0)
    cached = _chat_sync_manifest_cache_get(email, revision, updated_ts, limit)
    if cached:
        cached['cache_hit'] = True
        return _json_no_store_response(cached)
    store_obj = rec.get('store') if isinstance(rec.get('store'), dict) else {}
    manifest = _chat_sync_store_manifest(store_obj, limit=limit)
    payload = {
        'ok': True,
        'email': email,
        'updated_at': _fmt_ts(updated_ts),
        'updated_ts': updated_ts,
        'revision': revision,
        'server_revision': revision,
        'sync_protocol': 'manifest_v2_cached',
        'active_id': manifest.get('active_id') or '',
        'activeId': manifest.get('activeId') or '',
        'sessions': manifest.get('sessions') or [],
        'total_sessions': int(manifest.get('total_sessions') or len(manifest.get('sessions') or [])),
        'truncated': bool(manifest.get('truncated')),
        'personalization': manifest.get('personalization') or {},
        'deleted_sessions': manifest.get('deleted_sessions') or {},
        'limits': _auth_chat_limits_payload(),
        'cache_hit': False,
    }
    _chat_sync_manifest_cache_set(email, revision, updated_ts, limit, payload)
    return _json_no_store_response(payload)


def chat_sync_session_get_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    session_id = str(request.args.get('id') or request.args.get('session_id') or '').strip()
    if not session_id:
        return _json_no_store_response({'error': 'missing_session_id', 'sync_protocol': 'session_v1'}, status=400)
    rec = _auth_chat_store_get(email) or {}
    store_obj = rec.get('store') if isinstance(rec.get('store'), dict) else {}
    sessions = store_obj.get('sessions') if isinstance(store_obj.get('sessions'), dict) else {}
    session = sessions.get(session_id) if isinstance(sessions, dict) else None
    deleted_checker = globals().get('_auth_chat_session_deleted')
    if not isinstance(session, dict) or (callable(deleted_checker) and deleted_checker(session)):
        return _json_no_store_response({'error': 'session_not_found', 'sync_protocol': 'session_v1'}, status=404)
    updated_ts = float(rec.get('updated_at') or 0.0)
    revision = _auth_chat_store_revision_value(rec) if callable(globals().get('_auth_chat_store_revision_value')) else int(rec.get('revision') or 0)
    return _json_no_store_response({
        'ok': True,
        'email': email,
        'updated_at': _fmt_ts(updated_ts),
        'updated_ts': updated_ts,
        'revision': revision,
        'server_revision': revision,
        'sync_protocol': 'session_v1',
        'session_id': session_id,
        'session': session,
        'summary': _chat_sync_session_summary(session_id, session),
        'limits': _auth_chat_limits_payload(),
    })


def chat_sync_session_push_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    session = data.get('session') if isinstance(data.get('session'), dict) else None
    session_id = str(data.get('session_id') or data.get('id') or (session or {}).get('id') or '').strip()
    if not session_id or not isinstance(session, dict):
        return _json_no_store_response({'error': 'missing_session', 'sync_protocol': 'session_v1'}, status=400)
    op = {
        'op_id': _auth_chat_normalize_op_id(str(data.get('op_id') or '') or f"session:{session_id}:{time.time_ns()}"),
        'op_type': 'upsert_session',
        'device_id': _auth_chat_normalize_device_id(str(data.get('device_id') or '')),
        'session_id': session_id,
        'payload': {'session': session},
        'created_at': _utc_ts(),
    }
    try:
        rec, result = _auth_chat_store_push_ops(
            email,
            [op],
            base_revision=data.get('base_revision'),
            device_id=str(data.get('device_id') or ''),
        )
    except ValueError as e:
        message = str(e)
        status = 413 if ('过大' in message or '过多' in message) else 400
        return _json_no_store_response({'error': message, 'sync_protocol': 'session_v1'}, status=status)
    updated_ts = float(rec.get('updated_at') or 0.0)
    revision = _auth_chat_store_revision_value(rec) if callable(globals().get('_auth_chat_store_revision_value')) else int(rec.get('revision') or 0)
    has_conflict = bool(result.get('conflict') or result.get('conflicts'))
    if result.get('accepted'):
        _chat_sync_realtime_notify(email, revision=revision)
    try:
        if isinstance(rec.get('store'), dict) and 'personalization' in rec.get('store'):
            _auth_personalization_sync_from_store(email, store_payload=rec.get('store'), updated_at=updated_ts)
    except Exception:
        app_logger.exception('[auth_personalization] mirror_from_chat_store_failed email=%s', _normalize_login_email(email))
    store_obj = rec.get('store') if isinstance(rec.get('store'), dict) else None
    public_store_fn = globals().get('_auth_chat_public_store_for_response')
    public_store_obj = public_store_fn(store_obj) if callable(public_store_fn) else store_obj
    return _json_no_store_response({
        'ok': not has_conflict,
        'email': email,
        'updated_at': _fmt_ts(updated_ts),
        'updated_ts': updated_ts,
        'revision': revision,
        'server_revision': revision,
        'sync_protocol': 'session_v1',
        'accepted': result.get('accepted') or [],
        'duplicates': result.get('duplicates') or [],
        'conflict': has_conflict,
        'conflicts': result.get('conflicts') or [],
        'store': public_store_obj,
        'store_changed': bool(result.get('store_changed')),
        'limits': _auth_chat_limits_payload(),
    })


try:
    if 'chat_sync_manifest_route' in app.view_functions:
        app.view_functions['chat_sync_manifest_route'] = chat_sync_manifest_route
    else:
        app.add_url_rule('/api3/chat-sync/manifest', 'chat_sync_manifest_route', chat_sync_manifest_route, methods=['GET'])
    if 'chat_sync_session_get_route' in app.view_functions:
        app.view_functions['chat_sync_session_get_route'] = chat_sync_session_get_route
    else:
        app.add_url_rule('/api3/chat-sync/session', 'chat_sync_session_get_route', chat_sync_session_get_route, methods=['GET'])
    if 'chat_sync_session_push_route' in app.view_functions:
        app.view_functions['chat_sync_session_push_route'] = chat_sync_session_push_route
    else:
        app.add_url_rule('/api3/chat-sync/session/push', 'chat_sync_session_push_route', chat_sync_session_push_route, methods=['POST'])
except Exception:
    pass


# Incremental pull override: keep foreground refresh light.  When the client is too
# far behind, return a manifest snapshot by default and only include full store if
# explicitly requested for legacy recovery.
_CHAT_SYNC_REALTIME_CONDITION = threading.Condition()
_CHAT_SYNC_REALTIME_SEQ = 0


def _chat_sync_realtime_notify(email: str = '', *, revision: int = 0) -> None:
    normalized = _normalize_login_email(email)
    if not normalized:
        return
    global _CHAT_SYNC_REALTIME_SEQ
    try:
        with _CHAT_SYNC_REALTIME_CONDITION:
            _CHAT_SYNC_REALTIME_SEQ += 1
            _CHAT_SYNC_REALTIME_CONDITION.notify_all()
    except Exception:
        app_logger.exception('[chat_sync_realtime] notify_failed email=%s revision=%s', normalized, revision)


def _account_realtime_notify(email: str = '', *, event_kind: str = 'account', revision: int = 0) -> None:
    _chat_sync_realtime_notify(email, revision=revision)


def _account_realtime_profile_payload(email: str = '') -> dict:
    normalized = _normalize_login_email(email)
    profile = _auth_account_profile_public(normalized, _auth_account_profile_get(normalized)) if normalized else {}
    return {
        'ok': True,
        'email': normalized,
        'profile': profile,
        'profile_updated_ts': float((profile or {}).get('updated_ts') or 0.0),
    }


def _account_realtime_profile_version(profile_payload: dict | None = None) -> tuple[float, bool]:
    payload = profile_payload if isinstance(profile_payload, dict) else {}
    profile = payload.get('profile') if isinstance(payload.get('profile'), dict) else {}
    return (
        float(payload.get('profile_updated_ts') or profile.get('updated_ts') or 0.0),
        bool(profile.get('has_custom_profile')),
    )


def _chat_sync_sse_payload(event_name: str, data: dict | None = None, *, event_id: str = '') -> str:
    payload = json.dumps(data or {}, ensure_ascii=False, separators=(',', ':'))
    lines = []
    if event_id:
        lines.append(f'id: {event_id}')
    if event_name:
        lines.append(f'event: {event_name}')
    for line in payload.splitlines() or ['{}']:
        lines.append(f'data: {line}')
    lines.append('')
    return '\n'.join(lines) + '\n'


def _chat_sync_realtime_event_payload(email: str, since_revision: int = 0, *, include_empty: bool = False) -> dict | None:
    try:
        rec, ops, need_snapshot = _auth_chat_store_ops_since(email, since_revision)
    except Exception:
        rec = _auth_chat_store_get(email) or {}
        ops = []
        need_snapshot = True
    updated_ts = float(rec.get('updated_at') or 0.0)
    revision = _auth_chat_store_revision_value(rec) if callable(globals().get('_auth_chat_store_revision_value')) else int(rec.get('revision') or 0)
    if not include_empty and revision <= int(since_revision or 0):
        return None
    store_obj = rec.get('store') if isinstance(rec.get('store'), dict) else {}
    payload = {
        'ok': True,
        'email': email,
        'updated_at': _fmt_ts(updated_ts),
        'updated_ts': updated_ts,
        'revision': revision,
        'server_revision': revision,
        'sync_protocol': 'ops_v3_realtime_sse',
        'ops': ops if isinstance(ops, list) else [],
        'snapshot_required': bool(need_snapshot),
        'limits': _auth_chat_limits_payload(),
    }
    if need_snapshot:
        try:
            manifest = _chat_sync_store_manifest(store_obj, limit=300)
            payload.update({
                'active_id': manifest.get('active_id') or '',
                'activeId': manifest.get('activeId') or '',
                'sessions': manifest.get('sessions') or [],
                'total_sessions': int(manifest.get('total_sessions') or len(manifest.get('sessions') or [])),
                'truncated': bool(manifest.get('truncated')),
                'personalization': manifest.get('personalization') or {},
                'deleted_sessions': manifest.get('deleted_sessions') or {},
                'snapshot_kind': 'manifest',
            })
        except Exception:
            payload['snapshot_kind'] = 'none'
    return payload


def _chat_sync_pull_route_incremental():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
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
    revision = _auth_chat_store_revision_value(rec) if callable(globals().get('_auth_chat_store_revision_value')) else int(rec.get('revision') or 0)
    store_obj = rec.get('store') if isinstance(rec.get('store'), dict) else {}
    public_store_fn = globals().get('_auth_chat_public_store_for_response')
    public_store_obj = public_store_fn(store_obj) if callable(public_store_fn) else store_obj
    payload = {
        'ok': True,
        'email': email,
        'updated_at': _fmt_ts(updated_ts),
        'updated_ts': updated_ts,
        'revision': revision,
        'server_revision': revision,
        'sync_protocol': 'ops_v3_incremental',
        'ops': ops if isinstance(ops, list) else [],
        'snapshot_required': bool(need_snapshot),
        'store': public_store_obj if (include_store and need_snapshot and isinstance(public_store_obj, dict)) else None,
        'limits': _auth_chat_limits_payload(),
    }
    if need_snapshot and not include_store:
        try:
            manifest = _chat_sync_store_manifest(store_obj, limit=max(1, min(int(request.args.get('limit') or 300), 1000)))
            payload.update({
                'active_id': manifest.get('active_id') or '',
                'activeId': manifest.get('activeId') or '',
                'sessions': manifest.get('sessions') or [],
                'total_sessions': int(manifest.get('total_sessions') or len(manifest.get('sessions') or [])),
                'truncated': bool(manifest.get('truncated')),
                'personalization': manifest.get('personalization') or {},
                'deleted_sessions': manifest.get('deleted_sessions') or {},
                'snapshot_kind': 'manifest',
            })
        except Exception:
            payload['snapshot_kind'] = 'none'
    return _json_no_store_response(payload)

try:
    if 'chat_sync_pull_route' in app.view_functions:
        app.view_functions['chat_sync_pull_route'] = _chat_sync_pull_route_incremental
    else:
        app.add_url_rule('/api3/chat-sync/pull', 'chat_sync_pull_route', _chat_sync_pull_route_incremental, methods=['GET'])
except Exception:
    pass


def chat_sync_events_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    try:
        since_revision = max(
            int(request.args.get('since_revision') or request.args.get('since') or 0),
            int(request.headers.get('Last-Event-ID') or 0),
        )
    except Exception:
        since_revision = 0
    since_revision = max(0, since_revision)

    @stream_with_context
    def gen():
        nonlocal since_revision
        last_heartbeat = time.time()
        profile_payload = _account_realtime_profile_payload(email)
        profile_version = _account_realtime_profile_version(profile_payload)
        yield _chat_sync_sse_payload('hello', {
            'ok': True,
            'email': email,
            'server_revision': _auth_chat_store_revision_value(_auth_chat_store_get(email) or {}),
            'sync_protocol': 'ops_v3_realtime_sse',
            'profile': profile_payload.get('profile') or {},
            'profile_updated_ts': profile_payload.get('profile_updated_ts') or 0.0,
        })
        initial = _chat_sync_realtime_event_payload(email, since_revision, include_empty=False)
        if initial:
            since_revision = max(since_revision, int(initial.get('server_revision') or initial.get('revision') or since_revision))
            yield _chat_sync_sse_payload('ops', initial, event_id=str(since_revision))
        while True:
            try:
                with _CHAT_SYNC_REALTIME_CONDITION:
                    _CHAT_SYNC_REALTIME_CONDITION.wait(timeout=25.0)
                next_profile_payload = _account_realtime_profile_payload(email)
                next_profile_version = _account_realtime_profile_version(next_profile_payload)
                if next_profile_version != profile_version:
                    profile_version = next_profile_version
                    last_heartbeat = time.time()
                    yield _chat_sync_sse_payload('profile', next_profile_payload)
                payload = _chat_sync_realtime_event_payload(email, since_revision, include_empty=False)
                if payload:
                    since_revision = max(since_revision, int(payload.get('server_revision') or payload.get('revision') or since_revision))
                    last_heartbeat = time.time()
                    yield _chat_sync_sse_payload('ops', payload, event_id=str(since_revision))
                elif time.time() - last_heartbeat >= 20.0:
                    last_heartbeat = time.time()
                    yield _chat_sync_sse_payload('heartbeat', {
                        'ok': True,
                        'email': email,
                        'server_revision': _auth_chat_store_revision_value(_auth_chat_store_get(email) or {}),
                    })
            except GeneratorExit:
                break
            except Exception:
                app_logger.exception('[chat_sync_realtime] stream_loop_failed email=%s', _normalize_login_email(email))
                yield _chat_sync_sse_payload('error', {'ok': False, 'error': 'realtime_stream_error'})
                break

    return Response(gen(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
        'X-Accel-Buffering': 'no',
    })

try:
    if 'chat_sync_events_route' in app.view_functions:
        app.view_functions['chat_sync_events_route'] = chat_sync_events_route
    else:
        app.add_url_rule('/api3/chat-sync/events', 'chat_sync_events_route', chat_sync_events_route, methods=['GET'])
except Exception:
    pass

def _chat_sync_store_get_route_incremental():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    rec = _auth_chat_store_get(email) or {}
    updated_ts = float(rec.get('updated_at') or 0.0)
    revision = _auth_chat_store_revision_value(rec) if callable(globals().get('_auth_chat_store_revision_value')) else int(rec.get('revision') or 0)
    store_obj = rec.get('store') if isinstance(rec.get('store'), dict) else None
    public_store_fn = globals().get('_auth_chat_public_store_for_response')
    public_store_obj = public_store_fn(store_obj) if callable(public_store_fn) else store_obj
    return _json_no_store_response({
        'ok': True,
        'email': email,
        'store': public_store_obj,
        'updated_at': _fmt_ts(updated_ts),
        'updated_ts': updated_ts,
        'revision': revision,
        'server_revision': revision,
        'sync_protocol': 'ops_v2',
        'limits': _auth_chat_limits_payload(),
    })


def _chat_sync_store_save_route_incremental():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    return _json_no_store_response({
        'ok': False,
        'error': 'snapshot_sync_disabled',
        'message': '账号会话已切换为增量同步，拒绝整库覆盖',
        'sync_protocol': 'ops_v2',
        'limits': _auth_chat_limits_payload(),
    }, status=409)

try:
    app.view_functions['chat_sync_store_get_route'] = _chat_sync_store_get_route_incremental
    app.view_functions['chat_sync_store_save_route'] = _chat_sync_store_save_route_incremental
except Exception:
    pass


def _chat_sync_push_route_incremental():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
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
        status = 413 if ('过大' in message or '过多' in message or 'too_large' in message or 'too_many' in message) else 400
        return _json_no_store_response({'error': message, 'sync_protocol': 'ops_v2'}, status=status)
    updated_ts = float(rec.get('updated_at') or 0.0)
    revision = _auth_chat_store_revision_value(rec) if callable(globals().get('_auth_chat_store_revision_value')) else int(rec.get('revision') or 0)
    has_conflict = bool(result.get('conflict') or result.get('conflicts'))
    if result.get('accepted'):
        _chat_sync_realtime_notify(email, revision=revision)
    try:
        if isinstance(rec.get('store'), dict) and 'personalization' in rec.get('store'):
            _auth_personalization_sync_from_store(email, store_payload=rec.get('store'), updated_at=updated_ts)
    except Exception:
        app_logger.exception('[auth_personalization] mirror_from_chat_store_failed email=%s', _normalize_login_email(email))
    store_obj = rec.get('store') if isinstance(rec.get('store'), dict) else None
    public_store_fn = globals().get('_auth_chat_public_store_for_response')
    public_store_obj = public_store_fn(store_obj) if callable(public_store_fn) else store_obj
    return _json_no_store_response({
        'ok': not has_conflict,
        'email': email,
        'updated_at': _fmt_ts(updated_ts),
        'updated_ts': updated_ts,
        'revision': revision,
        'server_revision': revision,
        'sync_protocol': 'ops_v3_incremental',
        'accepted': result.get('accepted') or [],
        'duplicates': result.get('duplicates') or [],
        'conflict': has_conflict,
        'conflicts': result.get('conflicts') or [],
        'store': public_store_obj,
        'store_changed': bool(result.get('store_changed')),
        'limits': _auth_chat_limits_payload(),
    })
