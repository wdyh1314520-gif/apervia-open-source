# Purpose: account-level cross-session context search for GPT-like "reference chat history".
# Loaded by app3.py before file/tool orchestration, sharing the original global namespace.

ACCOUNT_CONTEXT_MAX_RESULTS = max(1, min(int(app_getenv('ACCOUNT_CONTEXT_MAX_RESULTS', '3') or 3), 8))
ACCOUNT_CONTEXT_SEARCH_MAX_SESSIONS = max(10, min(int(app_getenv('ACCOUNT_CONTEXT_SEARCH_MAX_SESSIONS', '60') or 60), 200))
ACCOUNT_CONTEXT_SESSION_TEXT_MAX_CHARS = max(2000, min(int(app_getenv('ACCOUNT_CONTEXT_SESSION_TEXT_MAX_CHARS', '9000') or 9000), 30000))
ACCOUNT_CONTEXT_READ_MAX_MESSAGES = max(3, min(int(app_getenv('ACCOUNT_CONTEXT_READ_MAX_MESSAGES', '8') or 8), 40))
ACCOUNT_CONTEXT_READ_MAX_CHARS = max(3000, min(int(app_getenv('ACCOUNT_CONTEXT_READ_MAX_CHARS', '12000') or 12000), 60000))
ACCOUNT_CONTEXT_RESUME_STATE_MAX_CHARS = max(700, min(int(app_getenv('ACCOUNT_CONTEXT_RESUME_STATE_MAX_CHARS', '1600') or 1600), 4000))


def _account_context_current_job_record() -> dict:
    try:
        getter = globals().get('_chat_async_current_job_id')
        job_id = str(getter() if callable(getter) else '').strip()
        if not job_id:
            return {}
        with _CHAT_ASYNC_JOB_LOCK:
            return dict((_CHAT_ASYNC_JOBS or {}).get(job_id) or {})
    except Exception:
        return {}


def _account_context_current_email() -> str:
    try:
        email = _normalize_login_email(_current_login_email())
        if email:
            return email
    except Exception:
        pass
    try:
        acc = _current_login_account() if callable(globals().get('_current_login_account')) else {}
        email = _normalize_login_email((acc or {}).get('email') or '')
        if email:
            return email
    except Exception:
        pass
    try:
        rec = _account_context_current_job_record()
        email = _normalize_login_email(rec.get('owner_email') or '')
        if email:
            return email
    except Exception:
        pass
    return ''


def _account_context_current_session_id(args: dict | None = None) -> str:
    args = args if isinstance(args, dict) else {}
    for key in ('current_session_id', 'client_session_id', 'session_id', 'active_session_id'):
        raw = str(args.get(key) or '').strip()
        if raw:
            return raw
    try:
        rec = _account_context_current_job_record()
        payload = rec.get('payload') if isinstance(rec.get('payload'), dict) else {}
        for key in ('client_session_id', 'session_id', 'active_session_id'):
            raw = str(payload.get(key) or '').strip()
            if raw:
                return raw
    except Exception:
        pass
    try:
        data = request.get_json(force=False, silent=True) or {}
        if isinstance(data, dict):
            for key in ('client_session_id', 'session_id', 'active_session_id'):
                raw = str(data.get(key) or '').strip()
                if raw:
                    return raw
    except Exception:
        pass
    return ''


def _account_context_history_enabled(email: str = '') -> bool:
    normalized = _normalize_login_email(email or _account_context_current_email())
    if not normalized:
        return False
    try:
        rec = _auth_personalization_get_effective_record(normalized) or {}
        normalizer = globals().get('_auth_personalization_normalize_state')
        state = normalizer((rec or {}).get('state') or {}) if callable(normalizer) else ((rec or {}).get('state') or {})
        if isinstance(state, dict):
            return bool(state.get('memoryEnabled')) and state.get('historyReferenceEnabled') is not False
    except Exception:
        pass
    return False


def _account_context_store_for_email(email: str = '') -> dict:
    normalized = _normalize_login_email(email or _account_context_current_email())
    if not normalized:
        return {}
    try:
        rec = _auth_chat_store_get(normalized) or {}
        store = rec.get('store') if isinstance(rec.get('store'), dict) else {}
        return dict(store or {})
    except Exception:
        return {}


def _account_context_session_deleted(session_obj: dict | None = None) -> bool:
    try:
        checker = globals().get('_auth_chat_session_deleted')
        if callable(checker):
            return bool(checker(session_obj or {}))
    except Exception:
        pass
    row = session_obj if isinstance(session_obj, dict) else {}
    if not row:
        return False
    if bool(row.get('_deleted') or row.get('deleted') or row.get('is_deleted')):
        return True
    try:
        return float(row.get('deleted_at') or row.get('deletedAt') or 0) > 0
    except Exception:
        return False




def _account_context_session_archived(session_obj: dict | None = None) -> bool:
    row = session_obj if isinstance(session_obj, dict) else {}
    if not row:
        return False
    if bool(row.get('archived')):
        return True
    try:
        return float(row.get('archivedAt') or row.get('archived_at') or row.get('archived_at_ms') or 0) > 0
    except Exception:
        return False


def _account_context_extract_history_summary_text(session_obj: dict | None = None, *, max_chars: int = 900) -> str:
    row = session_obj if isinstance(session_obj, dict) else {}
    text = ''
    try:
        extractor = globals().get('_auth_chat_extract_history_summary')
        text = str(extractor(row) if callable(extractor) else (row.get('historySummary') or row.get('history_summary') or '')).strip()
    except Exception:
        text = str(row.get('historySummary') or row.get('history_summary') or '').strip()
    text = re.sub(r'\s+', ' ', text).strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip() + '…'
    return text


def _account_context_updated_ts(session_obj: dict | None = None) -> float:
    row = session_obj if isinstance(session_obj, dict) else {}
    updated = row.get('updatedAt') or row.get('updated_at') or row.get('createdAt') or row.get('created_at') or 0
    try:
        updated_float = float(updated or 0)
        return updated_float / 1000.0 if updated_float > 100000000000 else updated_float
    except Exception:
        return 0.0


def _account_context_fmt_ts(ts: float = 0.0) -> str:
    try:
        ts = float(ts or 0.0)
    except Exception:
        ts = 0.0
    if ts <= 0:
        return ''
    try:
        if callable(globals().get('_fmt_ts')):
            return str(_fmt_ts(ts) or '').strip()
    except Exception:
        pass
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
    except Exception:
        return str(ts or '')


def _account_context_age_text(ts: float = 0.0) -> str:
    try:
        ts = float(ts or 0.0)
    except Exception:
        ts = 0.0
    if ts <= 0:
        return ''
    try:
        delta = float(time.time() - ts)
    except Exception:
        return ''
    if delta < -60:
        return '未来时间'
    delta = max(0.0, delta)
    minute = 60.0
    hour = 60.0 * minute
    day = 24.0 * hour
    if delta < minute:
        return '刚刚'
    if delta < hour:
        return f'{int(delta // minute)} 分钟前'
    if delta < day:
        return f'{int(delta // hour)} 小时前'
    if delta < 30.0 * day:
        return f'{int(delta // day)} 天前'
    if delta < 365.0 * day:
        return f'{max(1, int(delta // (30.0 * day)))} 个月前'
    return f'{max(1, int(delta // (365.0 * day)))} 年前'


def _account_context_time_label(updated_ts: float = 0.0, *, recency_rank: int = 0) -> str:
    ts_text = _account_context_fmt_ts(updated_ts)
    age_text = _account_context_age_text(updated_ts)
    bits = []
    try:
        rank = int(recency_rank or 0)
    except Exception:
        rank = 0
    if rank > 0:
        bits.append(f'最新第{rank}条')
    if ts_text:
        bits.append('更新时间：' + ts_text)
    if age_text:
        bits.append('距今：' + age_text)
    return '【' + '｜'.join(bits) + '】' if bits else ''


def _account_context_rank_label(*, result_rank: int = 0, relevance_rank: int = 0, recency_rank: int = 0) -> str:
    bits = []
    for label, value in (('结果第', result_rank), ('相关第', relevance_rank), ('最新第', recency_rank)):
        try:
            n = int(value or 0)
        except Exception:
            n = 0
        if n > 0:
            bits.append(f'{label}{n}')
    return ' / '.join(bits)

def _account_context_msg_line(message, *, max_chars: int = 520) -> str:
    if not isinstance(message, dict):
        return ''
    role = str(message.get('role') or '').strip().lower()
    if role == 'system':
        raw = str(message.get('content') or '').strip()
        if str(message.get('_kind') or '') == 'history_summary' or raw.startswith('【历史摘要】') or raw.startswith('[历史摘要]'):
            cleaned = re.sub(r'^[【\[]历史摘要[】\]]\s*', '', raw).strip()
            return _auth_chat_trim_small_text('历史摘要: ' + cleaned, max_chars) if callable(globals().get('_auth_chat_trim_small_text')) else ('历史摘要: ' + cleaned)[:max_chars]
        return ''
    try:
        line_builder = globals().get('_auth_chat_message_to_summary_line')
        if callable(line_builder):
            return str(line_builder(message, max_chars=max_chars) or '').strip()
    except Exception:
        pass
    content = message.get('content')
    text = ''
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        bits = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get('type') == 'text' and str(item.get('text') or '').strip():
                bits.append(str(item.get('text') or '').strip())
            elif item.get('type') == 'image_url':
                bits.append('[图片]')
        text = ' '.join(bits)
    elif isinstance(content, dict):
        kind = str(content.get('_kind') or '').strip()
        if kind == 'file':
            text = '[文件] ' + str(content.get('filename') or '').strip()
        elif kind == 'genfiles':
            names = []
            for item in (content.get('files') or [])[:8]:
                if isinstance(item, dict) and str(item.get('filename') or '').strip():
                    names.append(str(item.get('filename') or '').strip())
            text = '[生成文件] ' + ', '.join(names)
        else:
            text = str(content.get('text') or content.get('answer') or '')
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not text:
        return ''
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + '…'
    return f'{role or "message"}: {text}'


def _account_context_extract_files(session_obj: dict | None = None, *, limit: int = 12) -> list[dict]:
    row = session_obj if isinstance(session_obj, dict) else {}
    out: list[dict] = []
    seen: set[str] = set()

    def push_file(obj, role: str = ''):
        if not isinstance(obj, dict):
            return
        filename = str(obj.get('filename') or obj.get('output_filename') or obj.get('target_filename') or '').strip()
        if not filename:
            reg = obj.get('file_registry') if isinstance(obj.get('file_registry'), dict) else {}
            filename = str((reg or {}).get('filename') or (reg or {}).get('saved_filename') or '').strip()
        if not filename:
            return
        key = (role + '|' + filename).lower()
        if key in seen:
            return
        seen.add(key)
        out.append({
            'filename': filename[:220],
            'source_role': str(obj.get('source_role') or obj.get('sourceRole') or role or '').strip()[:80],
            'download_url': str(obj.get('download_url') or obj.get('url') or '')[:500],
        })

    def scan_content(content, role: str = ''):
        if isinstance(content, dict):
            kind = str(content.get('_kind') or '').strip()
            if kind == 'file':
                push_file(content, role or 'user_upload')
            elif kind == 'genfiles':
                for item in (content.get('files') or []):
                    push_file(item, role or 'assistant_generated')
            elif isinstance(content.get('files'), list):
                for item in content.get('files') or []:
                    push_file(item, role)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    scan_content(item, role)

    for msg in (row.get('messages') or []):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get('role') or '').strip().lower()
        if role == 'assistant':
            default_role = 'assistant_generated'
        elif role == 'user':
            default_role = 'user_upload'
        else:
            default_role = ''
        scan_content(msg.get('content'), default_role)
        if len(out) >= limit:
            break
    return out[:limit]





def _account_context_normalize_stored_resume_state(state, session_obj: dict | None = None, *, max_chars: int = ACCOUNT_CONTEXT_RESUME_STATE_MAX_CHARS) -> dict:
    if not isinstance(state, dict):
        return {}
    row = session_obj if isinstance(session_obj, dict) else {}
    title = str(state.get('title') or row.get('title') or '新对话').strip()[:180] or '新对话'
    text = re.sub(r'\n{3,}', '\n\n', str(state.get('text') or '').strip())
    if not text:
        return {}
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + '\n...【最后状态已截断】'
    try:
        updated_ts = float(state.get('updated_ts') or _account_context_updated_ts(row) or 0.0)
    except Exception:
        updated_ts = _account_context_updated_ts(row)
    recent_raw = state.get('recent') if isinstance(state.get('recent'), list) else []
    recent = [str(x or '').strip()[:520] for x in recent_raw if str(x or '').strip()][:6]
    files_raw = state.get('files') if isinstance(state.get('files'), list) else []
    files = []
    for item in files_raw[:8]:
        if not isinstance(item, dict):
            continue
        filename = str(item.get('filename') or '').strip()
        if not filename:
            continue
        files.append({
            'filename': filename[:220],
            'source_role': str(item.get('source_role') or item.get('sourceRole') or '').strip()[:80],
            'download_url': str(item.get('download_url') or item.get('url') or '').strip()[:500],
        })
    return {
        'schema_version': int(state.get('schema_version') or 1),
        'persisted': True,
        'title': title,
        'updated_at': str(state.get('updated_at') or (_fmt_ts(updated_ts) if callable(globals().get('_fmt_ts')) else updated_ts) or ''),
        'updated_ts': updated_ts,
        'generated_at': state.get('generated_at') or '',
        'source_message_count': state.get('source_message_count') or 0,
        'source_updated_at': state.get('source_updated_at') or '',
        'summary_hint': str(state.get('summary_hint') or '').strip()[:520],
        'last_user': str(state.get('last_user') or '').strip()[:560],
        'last_assistant': str(state.get('last_assistant') or '').strip()[:560],
        'recent': recent,
        'files': files,
        'text': text,
    }


def _account_context_stored_resume_state(session_obj: dict | None = None, *, max_chars: int = ACCOUNT_CONTEXT_RESUME_STATE_MAX_CHARS) -> dict:
    row = session_obj if isinstance(session_obj, dict) else {}
    for key in ('sessionResumeState', 'session_resume_state', 'resumeState', 'resume_state'):
        state = row.get(key)
        normalized = _account_context_normalize_stored_resume_state(state, row, max_chars=max_chars)
        if normalized and str(normalized.get('text') or '').strip():
            return normalized
    return {}

def _account_context_session_resume_state(session_obj: dict | None = None, *, max_chars: int = ACCOUNT_CONTEXT_RESUME_STATE_MAX_CHARS) -> dict:
    """Small last-state view for continuing a past chat.

    Prefer the server-persisted sessionResumeState.  Older sessions without it
    fall back to a compact dynamic view, so the first upgrade remains compatible.
    """
    row = session_obj if isinstance(session_obj, dict) else {}
    stored = _account_context_stored_resume_state(row, max_chars=max_chars)
    if stored:
        return stored
    title = str(row.get('title') or '新对话').strip()[:180] or '新对话'
    summary = _account_context_extract_history_summary_text(row, max_chars=420)
    messages = row.get('messages') if isinstance(row.get('messages'), list) else []

    recent_lines: list[str] = []
    last_user = ''
    last_assistant = ''
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get('role') or '').strip().lower()
        if role not in {'user', 'assistant'}:
            continue
        line = _account_context_msg_line(msg, max_chars=420)
        if not line:
            continue
        if role == 'user' and not last_user:
            last_user = line
        elif role == 'assistant' and not last_assistant:
            last_assistant = line
        recent_lines.append(line)
        if len(recent_lines) >= 6 and last_user and last_assistant:
            break
    recent_lines = list(reversed(recent_lines[:6]))

    files = _account_context_extract_files(row, limit=6)
    file_names = [str(item.get('filename') or '').strip() for item in files if str(item.get('filename') or '').strip()]

    parts: list[str] = []
    if last_user:
        parts.append('最后用户状态: ' + last_user)
    if last_assistant:
        parts.append('最后助手状态: ' + last_assistant)
    if title:
        parts.append('主题: ' + title)
    if summary:
        parts.append('背景摘要: ' + summary)
    if recent_lines:
        parts.append('最近交互: ' + ' / '.join(recent_lines[-4:]))
    if file_names:
        parts.append('相关文件: ' + '、'.join(file_names[:6]))
    text = '\n'.join(part for part in parts if str(part or '').strip()).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + '\n...【最后状态已截断】'
    return {
        'title': title,
        'updated_at': _fmt_ts(_account_context_updated_ts(row)) if callable(globals().get('_fmt_ts')) else str(_account_context_updated_ts(row) or ''),
        'updated_ts': _account_context_updated_ts(row),
        'persisted': False,
        'summary_hint': summary[:420],
        'last_user': last_user[:520],
        'last_assistant': last_assistant[:520],
        'recent': recent_lines[-4:],
        'files': files,
        'text': text,
    }

def _account_context_session_text(session_obj: dict | None = None, *, max_chars: int = ACCOUNT_CONTEXT_SESSION_TEXT_MAX_CHARS) -> str:
    row = session_obj if isinstance(session_obj, dict) else {}
    parts: list[str] = []
    title = str(row.get('title') or '').strip()
    resume_state = _account_context_session_resume_state(row, max_chars=ACCOUNT_CONTEXT_RESUME_STATE_MAX_CHARS)
    resume_text = str(resume_state.get('text') or '').strip()
    if resume_text:
        parts.append('最后状态: ' + resume_text)
    if title:
        parts.append('标题: ' + title)
    summary = _account_context_extract_history_summary_text(row, max_chars=1200)
    if summary:
        parts.append('历史摘要: ' + summary)
    messages = row.get('messages') if isinstance(row.get('messages'), list) else []
    for msg in messages[-40:]:
        line = _account_context_msg_line(msg, max_chars=520)
        if line:
            parts.append(line)
    files = _account_context_extract_files(row, limit=12)
    if files:
        parts.append('相关文件: ' + '；'.join(str(x.get('filename') or '') for x in files if str(x.get('filename') or '').strip()))
    text = '\n'.join(part for part in parts if str(part or '').strip()).strip()
    if len(text) > max_chars:
        text = text[-max_chars:]
        cut = text.find('\n')
        if cut > 0:
            text = text[cut + 1:]
        text = '…\n' + text
    return text


def _account_context_query_terms(query: str = '') -> list[str]:
    q = str(query or '').strip().lower()
    if not q:
        return []
    raw_terms: list[str] = []
    for m in re.finditer(r'[a-z0-9][a-z0-9_.:/@+-]{1,}|[\u4e00-\u9fff]{1,}', q, flags=re.I):
        token = str(m.group(0) or '').strip().lower()
        if not token:
            continue
        if re.fullmatch(r'[\u4e00-\u9fff]+', token):
            raw_terms.append(token)
            if len(token) >= 4:
                raw_terms.extend(token[i:i+2] for i in range(0, len(token) - 1))
        else:
            raw_terms.append(token)
    stop = {'this', 'that', 'what', 'when', 'where', 'which', 'the', 'and', 'or', '我', '你', '他', '她', '它', '这个', '那个'}
    out: list[str] = []
    for term in raw_terms:
        if not term or term in stop or len(term) < 2:
            continue
        if term not in out:
            out.append(term)
        if len(out) >= 24:
            break
    return out


def _account_context_score(query: str, session_obj: dict, text: str) -> float:
    q = str(query or '').strip().lower()
    hay = str(text or '').lower()
    title = str((session_obj or {}).get('title') or '').strip().lower()
    score = 0.0
    if q and q in hay:
        score += 28.0
    if q and q in title:
        score += 24.0
    terms = _account_context_query_terms(q)
    for term in terms:
        if term in title:
            score += 8.0
        count = hay.count(term)
        if count:
            score += min(10.0, 2.0 + count * 1.5)
    try:
        updated = float((session_obj or {}).get('updatedAt') or (session_obj or {}).get('updated_at') or (session_obj or {}).get('createdAt') or 0.0)
        if updated > 100000000000:
            age_s = max(0.0, time.time() - updated / 1000.0)
        else:
            age_s = max(0.0, time.time() - updated)
        score += max(0.0, 3.0 - min(age_s / (30 * 24 * 3600), 3.0))
    except Exception:
        pass
    if not terms and not q:
        score += 1.0
    return score


def _account_context_snippet(text: str = '', query: str = '', *, limit: int = 900) -> str:
    raw = re.sub(r'\n{3,}', '\n\n', str(text or '').strip())
    if not raw:
        return ''
    q = str(query or '').strip().lower()
    terms = _account_context_query_terms(q)
    low = raw.lower()
    pos = -1
    if q:
        pos = low.find(q)
    if pos < 0:
        for term in terms:
            pos = low.find(term)
            if pos >= 0:
                break
    if pos < 0:
        snippet = raw[:limit]
        return snippet.rstrip() + ('…' if len(raw) > len(snippet) else '')
    start = max(0, pos - limit // 3)
    end = min(len(raw), start + limit)
    if end - start < limit:
        start = max(0, end - limit)
    snippet = raw[start:end].strip()
    if start > 0:
        snippet = '…' + snippet
    if end < len(raw):
        snippet += '…'
    return snippet


def _account_context_public_session_row(
    session_id: str,
    session_obj: dict,
    text: str,
    query: str,
    score: float,
    *,
    relevance_rank: int = 0,
    recency_rank: int = 0,
    result_rank: int = 0,
) -> dict:
    row = session_obj if isinstance(session_obj, dict) else {}
    resume_state = _account_context_session_resume_state(row)
    updated_ts = float(resume_state.get('updated_ts') or _account_context_updated_ts(row) or 0.0)
    updated_at = _account_context_fmt_ts(updated_ts)
    summary = _account_context_extract_history_summary_text(row, max_chars=520)
    resume_text = str(resume_state.get('text') or '').strip()
    # Search results should mainly expose the continuation state.  The raw
    # historical snippet is only a small fallback for semantic matching.
    snippet_source = resume_text or text
    rank_label = _account_context_rank_label(
        result_rank=result_rank,
        relevance_rank=relevance_rank,
        recency_rank=recency_rank,
    )
    time_label = _account_context_time_label(updated_ts, recency_rank=recency_rank)
    return {
        'session_id': str(session_id or '').strip(),
        'title': str(row.get('title') or '新对话').strip()[:220] or '新对话',
        'updated_at': updated_at,
        'updated_ts': updated_ts,
        'age_text': _account_context_age_text(updated_ts),
        'time_label': time_label,
        'rank_label': rank_label,
        'result_rank': int(result_rank or 0),
        'relevance_rank': int(relevance_rank or 0),
        'recency_rank': int(recency_rank or 0),
        'score': round(float(score or 0.0), 3),
        'resume_state': resume_state,
        'summary': summary[:520],
        'snippet': _account_context_snippet(snippet_source, query, limit=520),
        'files': _account_context_extract_files(row, limit=6),
    }

def _search_account_context_tool(args: dict | None = None, *, messages: list | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    email = _account_context_current_email()
    if not email:
        return {'ok': False, '_kind': 'account_context', 'error': 'login_required', 'results': []}
    if not _account_context_history_enabled(email):
        return {'ok': False, '_kind': 'account_context', 'error': 'history_reference_disabled', 'message': '账号历史聊天记录参考已关闭。', 'results': []}
    query = str(args.get('query') or args.get('question') or '').strip()
    try:
        limit = max(1, min(int(args.get('limit') or args.get('k') or ACCOUNT_CONTEXT_MAX_RESULTS), 8))
    except Exception:
        limit = ACCOUNT_CONTEXT_MAX_RESULTS
    include_current = bool(args.get('include_current_session') or args.get('include_current'))
    current_session_id = _account_context_current_session_id(args)
    store = _account_context_store_for_email(email)
    sessions = store.get('sessions') if isinstance(store.get('sessions'), dict) else {}
    rows: list[tuple[float, float, str, dict, str]] = []
    for sid, session in list(sessions.items())[:ACCOUNT_CONTEXT_SEARCH_MAX_SESSIONS * 2]:
        sid = str(sid or '').strip()
        if not sid or not isinstance(session, dict):
            continue
        if not include_current and current_session_id and sid == current_session_id:
            continue
        if _account_context_session_deleted(session) or _account_context_session_archived(session):
            continue
        text = _account_context_session_text(session)
        if not text:
            continue
        score = _account_context_score(query, session, text)
        if query and score <= 0:
            continue
        updated = _account_context_updated_ts(session)
        rows.append((score, updated, sid, session, text))

    relevance_sorted = sorted(rows, key=lambda item: (-item[0], -item[1], item[2]))
    recency_sorted = sorted(rows, key=lambda item: (-item[1], -item[0], item[2]))
    relevance_rank_by_sid = {sid: idx for idx, (_score, _updated, sid, _session, _text) in enumerate(relevance_sorted, 1)}
    recency_rank_by_sid = {sid: idx for idx, (_score, _updated, sid, _session, _text) in enumerate(recency_sorted, 1)}

    selected: list[tuple[float, float, str, dict, str]] = []
    selected_sids: set[str] = set()

    def push(item) -> None:
        _score, _updated, sid, _session, _text = item
        if sid in selected_sids:
            return
        selected_sids.add(sid)
        selected.append(item)

    # Keep the strongest semantic hit, then fill the small result set from the
    # latest matching timeline.  Each row still carries both ranks, so the model
    # can choose an old but clearly more relevant session when the user points to it.
    for item in relevance_sorted[:1]:
        push(item)
    for item in recency_sorted:
        if len(selected) >= limit:
            break
        push(item)
    for item in relevance_sorted:
        if len(selected) >= limit:
            break
        push(item)

    selected.sort(key=lambda item: (recency_rank_by_sid.get(item[2], 999999), relevance_rank_by_sid.get(item[2], 999999), item[2]))
    results = [
        _account_context_public_session_row(
            sid,
            session,
            text,
            query,
            score,
            relevance_rank=relevance_rank_by_sid.get(sid, 0),
            recency_rank=recency_rank_by_sid.get(sid, 0),
            result_rank=idx,
        )
        for idx, (score, _updated, sid, session, text) in enumerate(selected[:limit], 1)
    ]
    latest_result = results[0] if results else {}
    return {
        'ok': True,
        '_kind': 'account_context',
        'query': query,
        'email': email,
        'current_session_id': current_session_id,
        'result_count': len(results),
        'result_order': 'timeline_first_with_relevance_rank',
        'latest_result_time_label': str((latest_result or {}).get('time_label') or ''),
        'results': results,
        'instruction': '这些是同一账号历史聊天的低 token 结果，已按时间线优先展示，并附带 relevance_rank、recency_rank、time_label。多个结果都相关时，先核对更新时间更近的 resume_state；旧会话可作为背景，但不要只因 score 更高就把旧阶段当成当前进度。只有最后状态不足时，再按 session_id 调用 read_account_context 补读少量上下文。',
    }


def _read_account_context_tool(args: dict | None = None, *, messages: list | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    email = _account_context_current_email()
    if not email:
        return {'ok': False, '_kind': 'account_context_detail', 'error': 'login_required'}
    if not _account_context_history_enabled(email):
        return {'ok': False, '_kind': 'account_context_detail', 'error': 'history_reference_disabled', 'message': '账号历史聊天记录参考已关闭。'}
    session_id = str(args.get('session_id') or args.get('id') or '').strip()
    query = str(args.get('query') or '').strip()
    store = _account_context_store_for_email(email)
    sessions = store.get('sessions') if isinstance(store.get('sessions'), dict) else {}
    target_session = sessions.get(session_id) if session_id else None
    if not isinstance(target_session, dict):
        search = _search_account_context_tool({'query': query, 'limit': 1, 'include_current_session': args.get('include_current_session')}, messages=messages)
        first = (search.get('results') or [None])[0] if isinstance(search, dict) else None
        if isinstance(first, dict):
            session_id = str(first.get('session_id') or '').strip()
            target_session = sessions.get(session_id) if session_id else None
    if not isinstance(target_session, dict) or _account_context_session_deleted(target_session) or _account_context_session_archived(target_session):
        return {'ok': False, '_kind': 'account_context_detail', 'error': 'session_not_found', 'session_id': session_id}
    try:
        max_messages = max(4, min(int(args.get('max_messages') or ACCOUNT_CONTEXT_READ_MAX_MESSAGES), 80))
    except Exception:
        max_messages = ACCOUNT_CONTEXT_READ_MAX_MESSAGES
    try:
        max_chars = max(2000, min(int(args.get('max_chars') or ACCOUNT_CONTEXT_READ_MAX_CHARS), 120000))
    except Exception:
        max_chars = ACCOUNT_CONTEXT_READ_MAX_CHARS
    lines: list[str] = []
    resume_state = _account_context_session_resume_state(target_session)
    updated_ts = float(resume_state.get('updated_ts') or _account_context_updated_ts(target_session) or 0.0)
    updated_at = _account_context_fmt_ts(updated_ts)
    age_text = _account_context_age_text(updated_ts)
    time_lines = [
        '标题：' + (str(target_session.get('title') or '新对话').strip()[:220] or '新对话'),
    ]
    if updated_at:
        time_lines.append('最后更新：' + updated_at)
    if age_text:
        time_lines.append('距今：' + age_text)
    time_lines.append('说明：这是历史会话；接续前请结合当前问题核对它是否代表最新进度。')
    lines.append('【会话时间】\n' + '\n'.join(time_lines))
    resume_text = str(resume_state.get('text') or '').strip()
    if resume_text:
        lines.append('【最后状态】\n' + resume_text)
    summary = _account_context_extract_history_summary_text(target_session, max_chars=700)
    if summary and summary not in resume_text:
        lines.append('【历史摘要】\n' + summary)
    include_recent_raw = args.get('include_recent_messages')
    include_recent = True if include_recent_raw is None else bool(include_recent_raw)
    if include_recent:
        msg_lines = []
        for msg in (target_session.get('messages') or [])[-max_messages:]:
            line = _account_context_msg_line(msg, max_chars=520)
            if line:
                msg_lines.append(line)
        if msg_lines:
            lines.append('【少量最近消息｜从旧到新】\n' + '\n'.join('- ' + line for line in msg_lines))
    files = _account_context_extract_files(target_session, limit=10)
    if files:
        lines.append('【相关文件】\n' + '\n'.join('- ' + str(item.get('filename') or '') for item in files if str(item.get('filename') or '').strip()))
    text = '\n\n'.join(part for part in lines if str(part or '').strip()).strip()
    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + '\n...【历史上下文过长，已截断】'
        truncated = True
    return {
        'ok': True,
        '_kind': 'account_context_detail',
        'session_id': session_id,
        'title': str(target_session.get('title') or '新对话').strip()[:220] or '新对话',
        'query': query,
        'updated_at': updated_at,
        'updated_ts': updated_ts,
        'age_text': age_text,
        'time_label': _account_context_time_label(updated_ts),
        'resume_state': resume_state,
        'text': text,
        'chars': len(text),
        'truncated': truncated,
        'files': files,
        'instruction': '优先使用【最后状态】接续任务，并结合【会话时间】判断这条历史是否仍代表最新进度。少量最近消息只是校验，不要重新复述整段历史，也不要让旧历史偏离当前问题。',
    }
