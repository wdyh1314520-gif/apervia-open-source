# chat async location permission, start, poll, stream, and stop routes.

def _chat_async_location_wait_timeout_s() -> float:
    try:
        return max(8.0, min(float(app_getenv('CHAT_ASYNC_LOCATION_WAIT_TIMEOUT_S', '45') or 45), 120.0))
    except Exception:
        return 45.0


def _chat_async_wait_location_permission(request_id: str = '', timeout_s: float | None = None) -> dict:
    """Block the current chat job until the browser returns a location decision."""
    job_id = _chat_async_current_job_id()
    req_id = str(request_id or '').strip() or ('loc_' + uuid.uuid4().hex)
    if not job_id:
        return {'ok': False, 'cancelled': True, 'reason': 'no_async_job', 'request_id': req_id}
    wait_s = float(timeout_s if timeout_s is not None else _chat_async_location_wait_timeout_s())
    wait_s = max(1.0, min(wait_s, 180.0))
    now_ts = time.time()
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(job_id)
        if rec is None:
            return {'ok': False, 'cancelled': True, 'reason': 'job_not_found', 'request_id': req_id}
        runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_id, {})
        runtime['location_permission_pending'] = {
            'request_id': req_id,
            'created_at': now_ts,
            'expires_at': now_ts + wait_s,
        }
        runtime.pop('location_permission_result', None)
        rec['status'] = 'waiting_location_permission'
        rec['status_text'] = '等待位置授权…'
        rec['updated_at'] = now_ts
    _chat_async_append_event(job_id, 'status', {
        'text': '等待位置授权…',
        'location_permission_pending': True,
        'request_id': req_id,
    })
    deadline = time.time() + wait_s
    cond = _chat_async_job_cond(job_id)
    while True:
        with _CHAT_ASYNC_JOB_LOCK:
            rec = _CHAT_ASYNC_JOBS.get(job_id)
            runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_id, {})
            if rec is None:
                return {'ok': False, 'cancelled': True, 'reason': 'job_not_found', 'request_id': req_id}
            if bool(rec.get('stop_requested')):
                return {'ok': False, 'cancelled': True, 'reason': 'job_stopped', 'request_id': req_id}
            result = runtime.get('location_permission_result')
            if isinstance(result, dict) and str(result.get('request_id') or '') == req_id:
                runtime.pop('location_permission_result', None)
                runtime.pop('location_permission_pending', None)
                rec['status'] = 'running'
                rec['status_text'] = '正在继续回答…'
                rec['updated_at'] = time.time()
                return dict(result)
        remain = deadline - time.time()
        if remain <= 0:
            with _CHAT_ASYNC_JOB_LOCK:
                runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_id, {})
                pending = runtime.get('location_permission_pending')
                if isinstance(pending, dict) and str(pending.get('request_id') or '') == req_id:
                    runtime.pop('location_permission_pending', None)
                rec = _CHAT_ASYNC_JOBS.get(job_id)
                if rec is not None:
                    rec['status'] = 'running'
                    rec['status_text'] = '定位授权超时，继续回答…'
                    rec['updated_at'] = time.time()
            return {'ok': False, 'cancelled': True, 'timeout': True, 'reason': 'timeout', 'request_id': req_id}
        with cond:
            cond.wait(timeout=min(1.0, remain))


def _chat_async_submit_location_permission(job_id: str, payload: dict | None = None) -> dict:
    job_key = str(job_id or '').strip()
    data = dict(payload or {})
    req_id = str(data.get('request_id') or '').strip()
    if not job_key:
        raise ValueError('缺少 job_id')
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(job_key)
        if rec is None:
            raise KeyError('任务不存在或已过期')
        runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_key, {})
        pending = runtime.get('location_permission_pending') if isinstance(runtime.get('location_permission_pending'), dict) else {}
        pending_req = str((pending or {}).get('request_id') or '').strip()
        if pending_req and req_id and pending_req != req_id:
            raise ValueError('定位请求已过期，请重试')
        if pending_req and not req_id:
            req_id = pending_req
        result = {
            'ok': bool(data.get('ok')),
            'cancelled': bool(data.get('cancelled')),
            'request_id': req_id,
            'reason': str(data.get('reason') or '').strip(),
            'error': str(data.get('error') or '').strip(),
            'user_geo': data.get('user_geo') if isinstance(data.get('user_geo'), dict) else None,
            'location_state': data.get('location_state') if isinstance(data.get('location_state'), dict) else None,
            'ts': time.time(),
        }
        runtime['location_permission_result'] = result
        rec['status'] = 'running'
        rec['status_text'] = '已收到位置授权结果，正在继续…'
        rec['updated_at'] = time.time()
    _chat_async_notify(job_key)
    _chat_async_save_persisted_jobs(force=False)
    return {'ok': True, 'job_id': job_key, 'request_id': req_id, 'accepted': True}


@app.post('/api3/chat_async/location')
def chat_async_location_permission_route():
    payload = request.get_json(force=True, silent=True) or {}
    job_id = str(payload.get('job_id') or payload.get('_job_id') or '').strip()
    if not job_id:
        return jsonify({'error': '缺少 job_id'}), 400
    owner = _chat_async_owner_snapshot()
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(job_id)
        if rec is None:
            return jsonify({'error': '任务不存在或已过期'}), 404
        if not _chat_async_can_access(rec, owner):
            return jsonify({'error': '无权操作该任务'}), 403
    try:
        result = _chat_async_submit_location_permission(job_id, payload)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return _json_no_store_response(result)


def _chat_async_mcp_approval_timeout_s() -> float:
    try:
        return max(15.0, min(float(app_getenv('CHAT_ASYNC_MCP_APPROVAL_TIMEOUT_S', '180') or 180), 600.0))
    except Exception:
        return 180.0


def _chat_async_wait_mcp_approval(
    request_id: str = '',
    *,
    server: dict | None = None,
    tool: dict | None = None,
    arguments: dict | None = None,
    timeout_s: float | None = None,
) -> dict:
    """阻塞当前异步任务，直到浏览器批准或拒绝一次 MCP 工具调用。"""
    job_id = _chat_async_current_job_id()
    req_id = str(request_id or '').strip() or ('mcp_' + uuid.uuid4().hex)
    if not job_id:
        return {'ok': False, 'decision': 'deny', 'reason': 'no_async_job', 'request_id': req_id}
    wait_s = max(1.0, min(float(timeout_s if timeout_s is not None else _chat_async_mcp_approval_timeout_s()), 600.0))
    server_row = dict(server or {})
    tool_row = dict(tool or {})
    event_payload = {
        'request_id': req_id,
        'server_id': str(server_row.get('id') or ''),
        'server_name': str(server_row.get('name') or server_row.get('id') or 'MCP Server'),
        'tool_name': str(tool_row.get('name') or ''),
        'tool_title': str(tool_row.get('title') or tool_row.get('name') or ''),
        'tool_description': str(tool_row.get('description') or '')[:2000],
        'risk': str(tool_row.get('risk') or 'high'),
        'arguments': dict(arguments or {}) if isinstance(arguments, dict) else {},
        'expires_at': int((time.time() + wait_s) * 1000),
    }
    now_ts = time.time()
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(job_id)
        if rec is None:
            return {'ok': False, 'decision': 'deny', 'reason': 'job_not_found', 'request_id': req_id}
        runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_id, {})
        runtime['mcp_approval_pending'] = {'request_id': req_id, 'created_at': now_ts, 'expires_at': now_ts + wait_s, 'payload': dict(event_payload)}
        runtime.pop('mcp_approval_result', None)
        rec['status'] = 'waiting_mcp_approval'
        rec['status_text'] = '等待 MCP 工具授权…'
        rec['updated_at'] = now_ts
    _chat_async_append_event(job_id, 'mcp_approval_request', event_payload)
    _chat_async_append_event(job_id, 'status', {'text': '等待 MCP 工具授权…', 'mcp_approval_pending': True, 'request_id': req_id})
    deadline = time.time() + wait_s
    cond = _chat_async_job_cond(job_id)
    while True:
        with _CHAT_ASYNC_JOB_LOCK:
            rec = _CHAT_ASYNC_JOBS.get(job_id)
            runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_id, {})
            if rec is None:
                return {'ok': False, 'decision': 'deny', 'reason': 'job_not_found', 'request_id': req_id}
            if bool(rec.get('stop_requested')):
                return {'ok': False, 'decision': 'deny', 'reason': 'job_stopped', 'request_id': req_id}
            result = runtime.get('mcp_approval_result')
            if isinstance(result, dict) and str(result.get('request_id') or '') == req_id:
                runtime.pop('mcp_approval_result', None)
                runtime.pop('mcp_approval_pending', None)
                rec['status'] = 'running'
                rec['status_text'] = '正在继续回答…'
                rec['updated_at'] = time.time()
                return dict(result)
        remain = deadline - time.time()
        if remain <= 0:
            with _CHAT_ASYNC_JOB_LOCK:
                runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_id, {})
                pending = runtime.get('mcp_approval_pending')
                if isinstance(pending, dict) and str(pending.get('request_id') or '') == req_id:
                    runtime.pop('mcp_approval_pending', None)
                rec = _CHAT_ASYNC_JOBS.get(job_id)
                if rec is not None:
                    rec['status'] = 'running'
                    rec['status_text'] = 'MCP 工具授权超时，已拒绝调用。'
                    rec['updated_at'] = time.time()
            return {'ok': False, 'decision': 'deny', 'timeout': True, 'reason': 'timeout', 'request_id': req_id}
        with cond:
            cond.wait(timeout=min(1.0, remain))


def _chat_async_submit_mcp_approval(job_id: str, payload: dict | None = None) -> dict:
    job_key = str(job_id or '').strip()
    data = dict(payload or {})
    request_id = str(data.get('request_id') or '').strip()
    decision = str(data.get('decision') or 'deny').strip().lower()
    user_request = str(data.get('user_request') or data.get('userRequest') or '').strip()[:2000]
    if decision not in {'deny', 'allow_once', 'always_allow', 'revise'}:
        raise ValueError('无效的 MCP 授权决定')
    if decision == 'revise' and not user_request:
        raise ValueError('请填写希望模型调整的要求')
    if not job_key:
        raise ValueError('缺少 job_id')
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(job_key)
        if rec is None:
            raise KeyError('任务不存在或已过期')
        runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_key, {})
        pending = runtime.get('mcp_approval_pending') if isinstance(runtime.get('mcp_approval_pending'), dict) else {}
        pending_payload = pending.get('payload') if isinstance(pending.get('payload'), dict) else {}
        pending_request_id = str((pending or {}).get('request_id') or '').strip()
        if not pending_request_id:
            raise ValueError('当前没有待处理的 MCP 授权请求')
        if request_id and request_id != pending_request_id:
            raise ValueError('MCP 授权请求已过期，请重试')
        request_id = pending_request_id
        runtime['mcp_approval_result'] = {
            'ok': decision in {'allow_once', 'always_allow'},
            'decision': decision,
            'request_id': request_id,
            'user_request': user_request,
            'ts': time.time(),
        }
        rec['status'] = 'running'
        rec['status_text'] = '已收到调整要求，正在重新规划…' if decision == 'revise' else ('已拒绝 MCP 工具调用，正在继续…' if decision == 'deny' else '已收到 MCP 授权决定，正在继续…')
        rec['updated_at'] = time.time()
    _chat_async_append_event(job_key, 'mcp_approval_result', {
        **dict(pending_payload or {}),
        'request_id': request_id,
        'decision': decision,
        'user_request': user_request,
        'ok': decision in {'allow_once', 'always_allow'},
    })
    _chat_async_notify(job_key)
    _chat_async_save_persisted_jobs(force=False)
    return {'ok': True, 'job_id': job_key, 'request_id': request_id, 'decision': decision, 'user_request': user_request, 'accepted': True}


@app.post('/api3/chat_async/mcp_approval')
def chat_async_mcp_approval_route():
    payload = request.get_json(force=True, silent=True) or {}
    job_id = str(payload.get('job_id') or payload.get('_job_id') or '').strip()
    if not job_id:
        return jsonify({'error': '缺少 job_id'}), 400
    owner = _chat_async_owner_snapshot()
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(job_id)
        if rec is None:
            return jsonify({'error': '任务不存在或已过期'}), 404
        if not _chat_async_can_access(rec, owner):
            return jsonify({'error': '无权操作该任务'}), 403
    try:
        result = _chat_async_submit_mcp_approval(job_id, payload)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
    return _json_no_store_response(result)


def _chat_async_start_job_response(payload: dict):
    payload = payload if isinstance(payload, dict) else {}
    payload.pop('mcp_servers', None)
    try:
        enricher = globals().get('_enrich_location_payload_from_request')
        if callable(enricher):
            payload = enricher(payload)
    except Exception:
        pass
    limit_resp = _apply_rate_limit('chat_stream')
    if limit_resp is not None:
        return limit_resp
    owner = _chat_async_owner_snapshot()
    _chat_async_cleanup_expired()
    _chat_async_load_persisted_jobs()
    coordinated = _CHAT_ASYNC_RUN_COORDINATOR.coordination(payload, owner)
    existing = None
    if coordinated.get('owner_key') and coordinated.get('conversation_id'):
        existing = _CHAT_ASYNC_RUN_COORDINATOR.find(
            owner,
            coordinated.get('conversation_id') or '',
            turn_id=coordinated.get('turn_id') or '',
            active_only=False,
        )
        if existing and coordinated.get('turn_id') and str(existing.get('turn_id') or '') == str(coordinated.get('turn_id') or ''):
            run = _CHAT_ASYNC_RUN_COORDINATOR.public_run(existing, reused=True)
            return _json_no_store_response({'ok': True, **run})
        if existing and _CHAT_ASYNC_RUN_COORDINATOR.is_active(existing):
            run = _CHAT_ASYNC_RUN_COORDINATOR.public_run(existing, reused=True)
            return _json_no_store_response({
                'ok': False,
                'error': '此会话已在另一设备或页面中生成，请接回当前任务后继续。',
                'code': 'conversation_run_active',
                **run,
            }, 409)
    busy_resp = _chat_async_busy_response(owner)
    if busy_resp is not None:
        return busy_resp
    rec, action = _CHAT_ASYNC_RUN_COORDINATOR.start_or_reuse(payload, owner=owner)
    if action == 'conversation_busy':
        run = _CHAT_ASYNC_RUN_COORDINATOR.public_run(rec, reused=True)
        return _json_no_store_response({
            'ok': False,
            'error': '此会话已在另一设备或页面中生成，请接回当前任务后继续。',
            'code': 'conversation_run_active',
            **run,
        }, 409)
    if action == 'reused':
        run = _CHAT_ASYNC_RUN_COORDINATOR.public_run(rec, reused=True)
        return _json_no_store_response({'ok': True, **run})
    job_id = str(rec.get('job_id') or '')
    try:
        app_logger.info('[chat_async] job_created job=%s public=%s owner=%s', job_id[:12], bool(owner.get('is_public_request')), _chat_async_owner_key(owner))
    except Exception:
        pass
    worker = threading.Thread(target=_chat_async_worker, args=(job_id,), daemon=True)
    with _CHAT_ASYNC_JOB_LOCK:
        runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_id, {})
        runtime['thread'] = worker
    worker.start()
    _chat_async_save_persisted_jobs(force=True)
    return _json_no_store_response({
        'ok': True,
        **_CHAT_ASYNC_RUN_COORDINATOR.public_run(rec),
        'created_at': _fmt_ts(rec.get('created_at')),
    })


@app.post("/api3/chat_async/start")
def chat_async_start_route():
    payload = request.get_json(force=True, silent=True) or {}
    return _chat_async_start_job_response(payload)


@app.get("/api3/chat_async/active")
def chat_async_active_run_route():
    _chat_async_cleanup_expired()
    _chat_async_load_persisted_jobs()
    conversation_id = str(request.args.get('conversation_id') or request.args.get('session_id') or '').strip()
    turn_id = str(request.args.get('turn_id') or '').strip()
    active_only = str(request.args.get('active_only') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    if not conversation_id:
        return _json_no_store_response({'ok': False, 'error': '缺少 conversation_id'}, 400)
    owner = _chat_async_owner_snapshot()
    rec = _CHAT_ASYNC_RUN_COORDINATOR.find(owner, conversation_id, turn_id=turn_id, active_only=active_only)
    if rec is None:
        # “没有活动任务”是发送前探测的正常空结果，不能返回 404；全局 fetch 错误捕获会把
        # 非 2xx 响应展示成系统报错。
        return _json_no_store_response({
            'ok': True,
            'found': False,
            'conversation_id': conversation_id,
            'turn_id': turn_id,
            'active_only': active_only,
        })
    if not _chat_async_can_access(rec, owner):
        return _json_no_store_response({'ok': False, 'error': '无权访问该任务'}, 403)
    return _json_no_store_response({'ok': True, 'found': True, **_CHAT_ASYNC_RUN_COORDINATOR.public_run(rec)})


def _chat_async_poll_job_payload(job_id: str, *, cursor: int = 0, timeout_ms: int = 0) -> tuple[dict, int]:
    _chat_async_cleanup_expired()
    job_id = str(job_id or '').strip()
    if not job_id:
        return {'error': 'missing_job_id'}, 400
    _chat_async_load_persisted_jobs()
    try:
        cursor = max(0, int(cursor or 0))
    except Exception:
        cursor = 0
    try:
        timeout_ms = int(timeout_ms or 0)
    except Exception:
        timeout_ms = 0
    wait_cap_ms = _CHAT_ASYNC_POLL_WAIT_MAX_MS if _is_local_admin_request() else min(_CHAT_ASYNC_POLL_WAIT_MAX_MS, _CHAT_ASYNC_POLL_WAIT_PUBLIC_MS)
    timeout_ms = max(0, min(timeout_ms, wait_cap_ms))
    owner = _chat_async_owner_snapshot()
    deadline_ts = (time.time() + (timeout_ms / 1000.0)) if timeout_ms > 0 else 0.0
    rec = None
    while True:
        with _CHAT_ASYNC_JOB_LOCK:
            rec = _CHAT_ASYNC_JOBS.get(job_id)
            if rec is None:
                return {'error': 'job_not_found_or_expired'}, 404
            if not _chat_async_can_access(rec, owner):
                return {'error': 'job_access_denied'}, 403
            events = [dict(item) for item in list(rec.get('events') or []) if int((item or {}).get('seq') or 0) > cursor][:160]
            done = bool(rec.get('done'))
            status = str(rec.get('status') or 'queued')
            current_seq = int(rec.get('seq') or 0)
            status_text = str(rec.get('status_text') or '')
            stop_requested = bool(rec.get('stop_requested'))
            recovered_from_disk = bool(rec.get('recovered_from_disk'))
            error_text = str(rec.get('error') or '') if done else ''
            artifacts = list(rec.get('artifacts') or []) if done else []
            meta = dict(rec.get('meta') or {}) if done else {}
            file_progress = dict(rec.get('file_progress') or {}) if isinstance(rec.get('file_progress'), dict) else {}
        if events or done or timeout_ms <= 0:
            break
        wait_timeout_s = max(0.0, deadline_ts - time.time())
        if wait_timeout_s <= 0:
            break
        cond = _chat_async_job_cond(job_id)
        with cond:
            cond.wait(timeout=min(wait_timeout_s, 15.0))

    is_public_job = _chat_async_is_public_job(rec or {})
    if done:
        poll_after_ms = 0
    elif events:
        if is_public_job:
            poll_after_ms = max(0, int(_CHAT_ASYNC_POLL_AFTER_PUBLIC_EVENT_MS or _CHAT_ASYNC_POLL_AFTER_EVENT_MS or 10))
        else:
            poll_after_ms = max(0, int(_CHAT_ASYNC_POLL_AFTER_EVENT_MS or 12))
    elif timeout_ms > 0:
        if is_public_job:
            poll_after_ms = max(0, int(_CHAT_ASYNC_POLL_AFTER_PUBLIC_IDLE_MS or _CHAT_ASYNC_POLL_AFTER_IDLE_MS or 16))
        else:
            poll_after_ms = max(0, int(_CHAT_ASYNC_POLL_AFTER_IDLE_MS or 18))
    else:
        poll_after_ms = 350

    data = {
        'ok': True,
        'job_id': job_id,
        'conversation_id': str((rec or {}).get('conversation_id') or ''),
        'turn_id': str((rec or {}).get('turn_id') or ''),
        'conversation_mode': str((rec or {}).get('conversation_mode') or 'chat'),
        'status': status,
        'status_text': status_text,
        'current_seq': current_seq,
        'next_cursor': current_seq,
        'events': events,
        'done': done,
        'stop_requested': stop_requested,
        'recovered_from_disk': recovered_from_disk,
        'poll_after_ms': poll_after_ms,
        'timeout_ms': timeout_ms,
        'waited_ms': int(max(0.0, timeout_ms - max(0.0, deadline_ts - time.time()) * 1000.0)) if timeout_ms > 0 else 0,
        'file_progress': file_progress,
    }
    try:
        if events or done:
            app_logger.info('[chat_async] poll_shared job=%s events=%s done=%s cursor=%s next=%s recovered=%s', job_id[:12], len(events), done, current_seq, poll_after_ms, recovered_from_disk)
    except Exception:
        pass
    if done:
        data['error'] = error_text
        data['artifacts'] = artifacts
        data['meta'] = meta
        data['full_text'] = str((rec or {}).get('full_text') or '')
    return data, 200


@app.get("/api3/chat_async/poll")
def chat_async_poll_route():
    _chat_async_cleanup_expired()
    job_id = str(request.args.get('job_id') or '').strip()
    if not job_id:
        return jsonify({'error': '缺少 job_id'}), 400
    _chat_async_load_persisted_jobs()
    try:
        cursor = max(0, int(request.args.get('cursor') or 0))
    except Exception:
        cursor = 0
    try:
        timeout_ms = int(request.args.get('timeout_ms') or 0)
    except Exception:
        timeout_ms = 0
    wait_cap_ms = _CHAT_ASYNC_POLL_WAIT_MAX_MS if _is_local_admin_request() else min(_CHAT_ASYNC_POLL_WAIT_MAX_MS, _CHAT_ASYNC_POLL_WAIT_PUBLIC_MS)
    timeout_ms = max(0, min(timeout_ms, wait_cap_ms))
    owner = _chat_async_owner_snapshot()
    deadline_ts = (time.time() + (timeout_ms / 1000.0)) if timeout_ms > 0 else 0.0
    wait_timeout_s = 0.0
    while True:
        with _CHAT_ASYNC_JOB_LOCK:
            rec = _CHAT_ASYNC_JOBS.get(job_id)
            if rec is None:
                return jsonify({'error': '任务不存在或已过期'}), 404
            if not _chat_async_can_access(rec, owner):
                return jsonify({'error': '无权访问该任务'}), 403
            events = [dict(item) for item in list(rec.get('events') or []) if int((item or {}).get('seq') or 0) > cursor][:160]
            done = bool(rec.get('done'))
            status = str(rec.get('status') or 'queued')
            current_seq = int(rec.get('seq') or 0)
            status_text = str(rec.get('status_text') or '')
            stop_requested = bool(rec.get('stop_requested'))
            recovered_from_disk = bool(rec.get('recovered_from_disk'))
            error_text = str(rec.get('error') or '') if done else ''
            artifacts = list(rec.get('artifacts') or []) if done else []
            meta = dict(rec.get('meta') or {}) if done else {}
            file_progress = dict(rec.get('file_progress') or {}) if isinstance(rec.get('file_progress'), dict) else {}
        if events or done or timeout_ms <= 0:
            break
        wait_timeout_s = max(0.0, deadline_ts - time.time())
        if wait_timeout_s <= 0:
            break
        cond = _chat_async_job_cond(job_id)
        with cond:
            cond.wait(timeout=min(wait_timeout_s, 15.0))

    is_public_job = _chat_async_is_public_job(rec)
    if done:
        poll_after_ms = 0
    elif events:
        if is_public_job:
            poll_after_ms = max(0, int(_CHAT_ASYNC_POLL_AFTER_PUBLIC_EVENT_MS or _CHAT_ASYNC_POLL_AFTER_EVENT_MS or 10))
        else:
            poll_after_ms = max(0, int(_CHAT_ASYNC_POLL_AFTER_EVENT_MS or 12))
    elif timeout_ms > 0:
        if is_public_job:
            poll_after_ms = max(0, int(_CHAT_ASYNC_POLL_AFTER_PUBLIC_IDLE_MS or _CHAT_ASYNC_POLL_AFTER_IDLE_MS or 16))
        else:
            poll_after_ms = max(0, int(_CHAT_ASYNC_POLL_AFTER_IDLE_MS or 18))
    else:
        poll_after_ms = 350

    data = {
        'ok': True,
        'job_id': job_id,
        'conversation_id': str((rec or {}).get('conversation_id') or ''),
        'turn_id': str((rec or {}).get('turn_id') or ''),
        'conversation_mode': str((rec or {}).get('conversation_mode') or 'chat'),
        'status': status,
        'status_text': status_text,
        'current_seq': current_seq,
        'events': events,
        'done': done,
        'stop_requested': stop_requested,
        'recovered_from_disk': recovered_from_disk,
        'poll_after_ms': poll_after_ms,
        'timeout_ms': timeout_ms,
        'waited_ms': int(max(0.0, timeout_ms - max(0.0, deadline_ts - time.time()) * 1000.0)) if timeout_ms > 0 else 0,
        'file_progress': file_progress,
    }
    try:
        if events or done:
            app_logger.info('[chat_async] poll job=%s events=%s done=%s cursor=%s next=%s recovered=%s', job_id[:12], len(events), done, current_seq, poll_after_ms, recovered_from_disk)
    except Exception:
        pass
    if done:
        data['error'] = error_text
        data['artifacts'] = artifacts
        data['meta'] = meta
        data['full_text'] = str(rec.get('full_text') or '')
    resp = jsonify(data)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp



@app.get("/api3/chat_async/stream")
def chat_async_stream_route():
    _chat_async_cleanup_expired()
    job_id = str(request.args.get('job_id') or '').strip()
    if not job_id:
        return jsonify({'error': '缺少 job_id'}), 400
    try:
        cursor = max(0, int(request.args.get('cursor') or 0))
    except Exception:
        cursor = 0

    owner = _chat_async_owner_snapshot()
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(job_id)
        if rec is None:
            return jsonify({'error': '任务不存在或已过期'}), 404
        if not _chat_async_can_access(rec, owner):
            return jsonify({'error': '无权访问该任务'}), 403

    is_public_stream = False
    try:
        is_public_stream = bool(_is_public_request_scope() or _chat_async_is_public_job(rec))
    except Exception:
        is_public_stream = False
    try:
        app_logger.info('[chat_async] stream_open job=%s public=%s cursor=%s', job_id[:12], is_public_stream, cursor)
    except Exception:
        pass

    @stream_with_context
    def gen():
        nonlocal cursor
        heartbeat_s = 6.0 if is_public_stream else 12.0
        last_ping_ts = 0.0
        yield ": ping\n\n"
        last_ping_ts = time.time()
        while True:
            with _CHAT_ASYNC_JOB_LOCK:
                rec2 = _CHAT_ASYNC_JOBS.get(job_id)
                if rec2 is None:
                    yield sse('error', {'error': '任务不存在或已过期'})
                    yield sse('done', {})
                    return
                if not _chat_async_can_access(rec2, owner):
                    yield sse('error', {'error': '无权访问该任务'})
                    yield sse('done', {})
                    return
                current_seq = int(rec2.get('seq') or 0)
                done = bool(rec2.get('done'))
                events = [
                    dict(item)
                    for item in list(rec2.get('events') or [])
                    if int((item or {}).get('seq') or 0) > cursor
                ][:160]

            if events:
                for item in events:
                    seq = int((item or {}).get('seq') or 0)
                    payload = dict((item or {}).get('payload') or {})
                    payload['_job_seq'] = seq
                    cursor = max(cursor, seq)
                    yield sse(str((item or {}).get('event') or 'message'), payload)
                    last_ping_ts = time.time()
                if done and cursor >= current_seq:
                    # A completed job may have just emitted its last normal event.
                    # Always send a terminal marker as well so the browser can clear
                    # pendingJobId even when the stored event list itself did not
                    # contain an explicit done event.
                    yield sse('done', {'_job_seq': current_seq})
                    return
                continue

            if done and cursor >= current_seq:
                yield sse('done', {'_job_seq': current_seq})
                return

            now_ts = time.time()
            if (now_ts - last_ping_ts) >= heartbeat_s:
                yield ": ping\n\n"
                last_ping_ts = now_ts

            cond = _chat_async_job_cond(job_id)
            with cond:
                cond.wait(timeout=3.0)

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-store, no-cache, no-transform, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.post("/api3/chat_async/stop")
def chat_async_stop_route():
    payload = request.get_json(force=True, silent=True) or {}
    job_id = str(payload.get('job_id') or '').strip()
    if not job_id:
        return jsonify({'error': '缺少 job_id'}), 400
    owner = _chat_async_owner_snapshot()
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(job_id)
        if rec is None:
            return jsonify({'error': '任务不存在或已过期'}), 404
        if not _chat_async_can_access(rec, owner):
            return jsonify({'error': '无权停止该任务'}), 403
    ok = _chat_async_request_stop(job_id)
    return jsonify({'ok': bool(ok), 'job_id': job_id})
