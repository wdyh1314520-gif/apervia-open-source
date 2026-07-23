# 会话公开分享：保存不可变的可见消息快照，不暴露账号、system 消息或内部工具数据。

CHAT_SHARE_STORE_FILE = _app_data_path('chat_share_store.json')
CHAT_SHARE_MAX_ITEMS = 2000
CHAT_SHARE_MAX_ITEMS_PER_OWNER = 200
CHAT_SHARE_MAX_MESSAGES = 120
CHAT_SHARE_MAX_MESSAGE_CHARS = 40000
CHAT_SHARE_MAX_TOTAL_CHARS = 500000
_CHAT_SHARE_LOCK = threading.Lock()


def _chat_share_load_unlocked() -> dict:
    try:
        if os.path.isfile(CHAT_SHARE_STORE_FILE):
            with open(CHAT_SHARE_STORE_FILE, 'r', encoding='utf-8') as f:
                payload = json.load(f) or {}
            shares = payload.get('shares') if isinstance(payload, dict) else {}
            if isinstance(shares, dict):
                return {'version': 1, 'shares': shares}
    except Exception:
        app_logger.exception('[chat_share] load_failed')
    return {'version': 1, 'shares': {}}


def _chat_share_write_unlocked(payload: dict) -> None:
    tmp = CHAT_SHARE_STORE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, CHAT_SHARE_STORE_FILE)


def _chat_share_text(content) -> str:
    text = ''
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get('type') or '').strip().lower()
            if item_type in {'text', 'input_text', 'output_text'}:
                value = str(item.get('text') or item.get('content') or '')
                if value:
                    parts.append(value)
        text = '\n'.join(parts)
    elif isinstance(content, dict):
        text = str(content.get('text') or content.get('answer') or content.get('caption') or '')
        if not text:
            kind = str(content.get('_kind') or content.get('kind') or '').strip().lower()
            text = {'image_reply': '[图片]', 'image': '[图片]', 'file': '[文件]'}.get(kind, '')
    text = str(text or '').replace('\x00', '').strip()
    return text[:CHAT_SHARE_MAX_MESSAGE_CHARS]


def _chat_share_sanitize_messages(raw_messages) -> list[dict]:
    rows = []
    total_chars = 0
    for raw in raw_messages if isinstance(raw_messages, list) else []:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get('role') or '').strip().lower()
        if role not in {'user', 'assistant'}:
            continue
        text = _chat_share_text(raw.get('content'))
        if not text:
            text = _chat_share_text(raw.get('text'))
        if not text:
            continue
        remaining = CHAT_SHARE_MAX_TOTAL_CHARS - total_chars
        if remaining <= 0:
            break
        text = text[:remaining]
        rows.append({'role': role, 'content': text})
        total_chars += len(text)
        if len(rows) >= CHAT_SHARE_MAX_MESSAGES:
            break
    return rows


def _chat_share_public_record(record: dict, token: str) -> dict:
    row = record if isinstance(record, dict) else {}
    return {
        'ok': True,
        'token': str(token or ''),
        'title': str(row.get('title') or '分享的聊天')[:120],
        'model': str(row.get('model') or '')[:160],
        'conversation_mode': str(row.get('conversation_mode') or 'chat'),
        'endpoint_mode': str(row.get('endpoint_mode') or 'chat_completions'),
        'scope': 'conversation',
        'messages': list(row.get('messages') or []),
        'created_at': str(row.get('created_at') or ''),
        'created_ts': float(row.get('created_ts') or 0.0),
    }


@app.post('/api3/chat-shares')
def chat_share_create_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    data = request.get_json(silent=True) or {}
    messages = _chat_share_sanitize_messages(data.get('messages'))
    if not messages:
        return _json_no_store_response({'ok': False, 'error': '没有可分享的消息'}, status=400)
    title = re.sub(r'\s+', ' ', str(data.get('title') or '分享的聊天')).strip()[:120] or '分享的聊天'
    model = re.sub(r'\s+', ' ', str(data.get('model') or '')).strip()[:160]
    mode = 'response' if str(data.get('conversation_mode') or '').strip().lower() == 'response' else 'chat'
    endpoint_mode = 'responses' if mode == 'response' else 'chat_completions'
    owner_hash = hashlib.sha256(str(email or '').strip().lower().encode('utf-8')).hexdigest()[:24]
    created_ts = time.time()
    record = {
        'title': title,
        'model': model,
        'conversation_mode': mode,
        'endpoint_mode': endpoint_mode,
        'scope': 'conversation',
        'messages': messages,
        'created_at': datetime.datetime.fromtimestamp(created_ts, datetime.timezone.utc).isoformat(),
        'created_ts': created_ts,
        'owner_hash': owner_hash,
    }
    with _CHAT_SHARE_LOCK:
        state = _chat_share_load_unlocked()
        shares = state.get('shares') if isinstance(state.get('shares'), dict) else {}
        owner_rows = sorted(
            ((key, value) for key, value in shares.items() if isinstance(value, dict) and value.get('owner_hash') == owner_hash),
            key=lambda item: float((item[1] or {}).get('created_ts') or 0.0),
        )
        for old_key, _old in owner_rows[:max(0, len(owner_rows) - CHAT_SHARE_MAX_ITEMS_PER_OWNER + 1)]:
            shares.pop(old_key, None)
        if len(shares) >= CHAT_SHARE_MAX_ITEMS:
            oldest = sorted(shares.items(), key=lambda item: float((item[1] or {}).get('created_ts') or 0.0))
            for old_key, _old in oldest[:len(shares) - CHAT_SHARE_MAX_ITEMS + 1]:
                shares.pop(old_key, None)
        token = secrets.token_urlsafe(24).rstrip('=')
        while token in shares:
            token = secrets.token_urlsafe(24).rstrip('=')
        shares[token] = record
        state['shares'] = shares
        _chat_share_write_unlocked(state)
    public = _chat_share_public_record(record, token)
    public['url'] = _app_external_url('/share/' + urllib.parse.quote(token))
    return _json_no_store_response(public)


@app.get('/api3/chat-shares/<string:token>')
def chat_share_get_route(token: str):
    safe_token = str(token or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,120}', safe_token):
        return _json_no_store_response({'ok': False, 'error': '分享链接无效'}, status=404)
    with _CHAT_SHARE_LOCK:
        state = _chat_share_load_unlocked()
        record = (state.get('shares') or {}).get(safe_token)
    if not isinstance(record, dict):
        return _json_no_store_response({'ok': False, 'error': '分享内容不存在或已失效'}, status=404)
    return _json_no_store_response(_chat_share_public_record(record, safe_token))


@app.get('/share/<string:token>')
def chat_share_page_route(token: str):
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        next_path = '/share/' + urllib.parse.quote(str(token or '').strip())
        return redirect('/login?next=' + urllib.parse.quote(next_path, safe='/%?=&:#-._~'), code=302)
    safe_token = str(token or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,120}', safe_token):
        return _json_no_store_response({'ok': False, 'error': '分享链接无效'}, status=404)
    with _CHAT_SHARE_LOCK:
        state = _chat_share_load_unlocked()
        record = (state.get('shares') or {}).get(safe_token)
    if not isinstance(record, dict):
        return _json_no_store_response({'ok': False, 'error': '分享内容不存在或已失效'}, status=404)
    return index_gpt()


def _chat_share_continue_for_email(token: str, email: str) -> tuple[dict, int]:
    safe_token = str(token or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,120}', safe_token):
        return {'ok': False, 'error': '分享链接无效'}, 404
    with _CHAT_SHARE_LOCK:
        state = _chat_share_load_unlocked()
        record = (state.get('shares') or {}).get(safe_token)
    if not isinstance(record, dict):
        return {'ok': False, 'error': '分享内容不存在或已失效'}, 404

    rec = _auth_chat_store_get(email) or {}
    store_obj = rec.get('store') if isinstance(rec.get('store'), dict) else {}
    sessions = store_obj.get('sessions') if isinstance(store_obj.get('sessions'), dict) else {}
    for session_id, session in sessions.items():
        if not isinstance(session, dict):
            continue
        source_token = str(session.get('sharedFromToken') or session.get('shared_from_token') or '').strip()
        if source_token == safe_token:
            return {
                'ok': True,
                'session_id': str(session_id or session.get('id') or '').strip(),
                'url': '/c/' + urllib.parse.quote(str(session_id or session.get('id') or '').strip()),
                'conversation_mode': str(session.get('conversationMode') or session.get('conversation_mode') or 'chat'),
                'revision': _auth_chat_store_revision_value(rec),
                'existing': True,
            }, 200

    messages = _chat_share_sanitize_messages(record.get('messages'))
    if not messages:
        return {'ok': False, 'error': '分享内容没有可继续的消息'}, 400
    mode = 'response' if str(record.get('conversation_mode') or '').strip().lower() == 'response' else 'chat'
    endpoint_mode = 'responses' if mode == 'response' else 'chat_completions'
    now_ms = int(time.time() * 1000)
    normalized_email = str(email or '').strip().lower()
    session_key = hashlib.sha256((normalized_email + ':' + safe_token).encode('utf-8')).hexdigest()[:32]
    session_id = 's_shared_' + session_key
    session_messages = []
    for index, item in enumerate(messages):
        session_messages.append({
            'role': str(item.get('role') or 'assistant'),
            'content': str(item.get('content') or ''),
            'createdAt': now_ms + index,
            'created_at': now_ms + index,
            '_webai_shared_snapshot': True,
        })
    session = {
        'id': session_id,
        'title': str(record.get('title') or '分享的聊天')[:120] or '分享的聊天',
        'model': str(record.get('model') or '')[:160],
        'createdAt': now_ms,
        'updatedAt': now_ms + len(session_messages),
        'conversationMode': mode,
        'conversation_mode': mode,
        'api_endpoint_mode': endpoint_mode,
        'endpoint_mode': endpoint_mode,
        'syncStatus': 'active',
        'sync_status': 'active',
        'sharedFromToken': safe_token,
        'shared_from_token': safe_token,
        'messages': session_messages,
    }
    base_revision = _auth_chat_store_revision_value(rec)
    op = {
        'op_id': _auth_chat_normalize_op_id(f'share_continue:{safe_token}:{session_id}'),
        'op_type': 'upsert_session',
        'device_id': 'share_continue',
        'session_id': session_id,
        'payload': {'session': session},
        'created_at': _utc_ts(),
    }
    try:
        next_rec, result = _auth_chat_store_push_ops(
            email,
            [op],
            base_revision=base_revision,
            device_id='share_continue',
        )
    except ValueError as exc:
        return {'ok': False, 'error': str(exc) or '创建会话失败'}, 400
    if not result.get('accepted'):
        return {'ok': False, 'error': '创建会话失败，请刷新后重试'}, 409
    revision = _auth_chat_store_revision_value(next_rec)
    try:
        _chat_sync_realtime_notify(email, revision=revision)
    except Exception:
        pass
    return {
        'ok': True,
        'session_id': session_id,
        'url': '/c/' + urllib.parse.quote(session_id),
        'conversation_mode': mode,
        'revision': revision,
        'existing': False,
    }, 200


@app.post('/api3/chat-shares/<string:token>/continue')
def chat_share_continue_route(token: str):
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    payload, status = _chat_share_continue_for_email(token, email)
    return _json_no_store_response(payload, status=status)
