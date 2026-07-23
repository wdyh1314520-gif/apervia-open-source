# Split from app3_parts/auth/platform_auth_core_part.py.
# Purpose: chat-sync payload slimming, deleted-session tombstones, backups, summaries, and resume-state compaction.
# Loaded by platform_auth_core_part.py via _exec_split_file(...), sharing the original global namespace.

def _auth_chat_limits_payload() -> dict:
    return {
        'max_sessions': int(AUTH_CHAT_ACCOUNT_MAX_SESSIONS),
        'max_messages_per_session': int(AUTH_CHAT_ACCOUNT_MAX_MESSAGES_PER_SESSION),
        'max_text_chars': int(AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS),
        'max_store_bytes': int(AUTH_CHAT_STORE_MAX_BYTES),
    }


def _auth_chat_safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _auth_chat_trim_text(value, max_chars: int) -> str:
    text = str(value or '')
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + '\n...(账号云端同步已自动截断)'



def _auth_chat_trim_small_text(value, max_chars: int = 1600) -> str:
    try:
        text = str(value or '')
    except Exception:
        text = ''
    max_chars = max(0, int(max_chars or 0))
    if max_chars and len(text) > max_chars:
        return text[:max_chars].rstrip() + '…'
    return text


def _auth_chat_slim_symbols(symbols, *, limit: int | None = None) -> list:
    if not isinstance(symbols, list):
        return []
    try:
        max_items = int(AUTH_CHAT_FILE_SYMBOLS_MAX if limit is None else limit)
    except Exception:
        max_items = 80
    if max_items <= 0:
        return []
    out = []
    for item in symbols[:max_items]:
        if not isinstance(item, dict):
            continue
        row = {}
        for key in ('kind', 'line', 'name'):
            if key in item:
                value = item.get(key)
                if isinstance(value, str):
                    value = _auth_chat_trim_small_text(value, 200)
                row[key] = value
        if row:
            out.append(row)
    return out


def _auth_chat_slim_edit_audit(audit) -> dict:
    if not isinstance(audit, dict):
        return {}
    keep = (
        '_kind', 'target_filename', 'output_filename', 'old_sha256', 'new_sha256',
        'diff_summary', 'verification', 'source', 'updated_at', 'created_at',
    )
    out = {}
    for key in keep:
        if key in audit:
            value = audit.get(key)
            if isinstance(value, str):
                value = _auth_chat_trim_small_text(value, 4000)
            elif isinstance(value, list):
                value = [_auth_chat_trim_small_text(x, 1000) if isinstance(x, str) else x for x in value[:40]]
            elif isinstance(value, dict):
                value = {str(k): (_auth_chat_trim_small_text(v, 1000) if isinstance(v, str) else v) for k, v in value.items()}
            out[key] = value
    diff = str(audit.get('diff') or '')
    max_diff = max(0, int(AUTH_CHAT_FILE_AUDIT_DIFF_MAX_CHARS or 0))
    if diff and max_diff > 0:
        out['diff'] = diff[:max_diff] + ('\n...【diff 已按云端聊天同步上限截断，完整文件以生成文件为准】' if len(diff) > max_diff else '')
    return out


def _auth_chat_slim_file_registry(registry, max_chars: int) -> dict:
    if not isinstance(registry, dict):
        return {}
    keep = (
        'file_id', 'filename', 'saved_filename', 'namespace', 'scope', 'source', 'source_type',
        'ext', 'mime', 'size', 'full_text_available', 'full_text_chars', 'full_text_lines',
        'stored_text_chars', 'stored_text_truncated', 'registry_text_truncated', 'is_code_like',
        'summary', 'code_summary', 'url', 'view_url', 'download_url', 'object_url',
        'storage_backend', 'updated_at', 'created_at', 'text_encoding', 'edited_from',
        'full_text_ref', 'model_storage_ref', 'storage_ref', 'sha256', 'content_sha256',
    )
    out = {}
    for key in keep:
        if key not in registry:
            continue
        value = registry.get(key)
        if key in {'summary', 'code_summary'}:
            value = _auth_chat_trim_small_text(value, min(max(1200, max_chars // 8), 4000))
        elif isinstance(value, str):
            value = _auth_chat_trim_small_text(value, 1200)
        elif isinstance(value, dict):
            value = _auth_chat_trim_value(value, min(max_chars, 8000))
        elif isinstance(value, list):
            value = _auth_chat_trim_value(value[:20], min(max_chars, 8000))
        out[key] = value
    if 'preview' in registry and AUTH_CHAT_FILE_PREVIEW_MAX_CHARS > 0:
        out['preview'] = _auth_chat_trim_small_text(registry.get('preview') or '', AUTH_CHAT_FILE_PREVIEW_MAX_CHARS)
        if out['preview']:
            out['preview_is_short_cache'] = True
    symbols = _auth_chat_slim_symbols(registry.get('symbols'))
    if symbols:
        out['symbols'] = symbols
        try:
            out['symbols_total_hint'] = len(registry.get('symbols') or [])
        except Exception:
            pass
    return out


def _auth_chat_slim_file_payload(obj, max_chars: int) -> dict:
    if not isinstance(obj, dict):
        return {}
    kind = str(obj.get('_kind') or '').strip()
    if kind == 'genfiles':
        out = {'_kind': 'genfiles'}
        files = obj.get('files') if isinstance(obj.get('files'), list) else []
        out['files'] = [_auth_chat_slim_file_payload(item, max_chars) for item in files if isinstance(item, dict)]
        for key in ('note', 'created_at', 'updated_at'):
            if key in obj:
                value = obj.get(key)
                out[key] = _auth_chat_trim_small_text(value, 1000) if isinstance(value, str) else value
        return out

    keep = (
        '_kind', 'id', 'file_library_id', 'library_file_id', 'filename', 'generated_by_assistant',
        'source_type', 'source_role', 'scope', 'size',
        'ext', 'mime', 'storage_backend', 'url', 'view_url', 'download_url', 'object_url',
        'preview_url', 'full_text_available', 'parsed_chars', 'parsed_lines', 'text_is_preview',
        'code_summary', 'note', 'created_at', 'updated_at', 'edited_from',
        'model_storage_ref', 'storage_ref', 'full_text_ref', 'sha256', 'content_sha256',
    )
    out = {}
    for key in keep:
        if key not in obj:
            continue
        value = obj.get(key)
        if key in {'code_summary', 'note'}:
            value = _auth_chat_trim_small_text(value, min(max(1200, max_chars // 8), 4000))
        elif isinstance(value, str):
            value = _auth_chat_trim_small_text(value, 1200)
        elif isinstance(value, dict):
            value = _auth_chat_trim_value(value, min(max_chars, 8000))
        out[key] = value
    if 'file_registry' in obj:
        out['file_registry'] = _auth_chat_slim_file_registry(obj.get('file_registry'), max_chars)
    if 'preview' in obj and AUTH_CHAT_FILE_PREVIEW_MAX_CHARS > 0:
        out['preview'] = _auth_chat_trim_small_text(obj.get('preview') or '', AUTH_CHAT_FILE_PREVIEW_MAX_CHARS)
        if out['preview']:
            out['preview_is_short_cache'] = True
    symbols = _auth_chat_slim_symbols(obj.get('symbols'))
    if symbols:
        out['symbols'] = symbols
        try:
            out['symbols_total_hint'] = len(obj.get('symbols') or [])
        except Exception:
            pass
    for audit_key in ('edit_audit', 'file_edit_audit'):
        if isinstance(obj.get(audit_key), dict):
            slim_audit = _auth_chat_slim_edit_audit(obj.get(audit_key))
            if slim_audit:
                out[audit_key] = slim_audit
    return out

def _auth_chat_is_ephemeral_image_url(value: str = '') -> bool:
    low = str(value or '').strip().lower()
    return bool((low.startswith('data:image/') and len(low) > 256) or low.startswith('blob:') or low.startswith('local://'))


def _auth_chat_image_part_id_url(obj, *, download: bool = False) -> str:
    row = obj if isinstance(obj, dict) else {}
    reg = row.get('file_registry') if isinstance(row.get('file_registry'), dict) else {}
    fid = str(row.get('file_library_id') or row.get('library_file_id') or reg.get('file_id') or '').strip()
    if not fid:
        return ''
    namespace = str(row.get('namespace') or reg.get('namespace') or '').strip().lower()
    source_type = str(row.get('source_type') or row.get('sourceType') or reg.get('source_type') or reg.get('source') or '').strip().lower()
    generated = bool(row.get('generated_by_assistant') or namespace == 'generated' or source_type in {'generated', 'assistant_generated'})
    try:
        enc = urllib.parse.quote(fid, safe='')
    except Exception:
        enc = re.sub(r'[^0-9A-Za-z_.:-]+', '', fid)
    if download:
        return ('/api3/generated-download-id/' if generated else '/api3/download-id/') + enc
    return ('/api3/generated-files-id/' if generated else '/api3/uploads-id/') + enc


def _auth_chat_slim_image_part_payload(obj, max_chars: int) -> dict:
    row = obj if isinstance(obj, dict) else {}
    reg = row.get('file_registry') if isinstance(row.get('file_registry'), dict) else {}
    keep = (
        'type', 'image_url', 'file_library_id', 'library_file_id', 'attachment_id', 'image_id',
        'filename', 'alt', 'caption', 'source_role', 'source_type', 'sourceType', 'operation',
        'endpoint_mode', 'api_endpoint_mode', 'apiEndpointMode', 'created_at_ms', 'createdAtMs',
        'image_seq', 'seq', 'url', 'view_url', 'download_url', 'preview_url', 'persisted_url',
        'server_url', 'model_storage_ref', 'storage_ref', 'namespace', 'generated_by_assistant',
        'storage_backend', 'content_length',
    )
    out = {}
    for key in keep:
        if key not in row:
            continue
        value = row.get(key)
        if isinstance(value, str):
            value = '' if _auth_chat_is_ephemeral_image_url(value) else _auth_chat_trim_small_text(value, 1200)
        elif isinstance(value, dict):
            value = _auth_chat_trim_value(value, min(max_chars, 8000))
        elif isinstance(value, list):
            value = _auth_chat_trim_value(value[:20], min(max_chars, 8000))
        out[key] = value
    out['type'] = 'image_url'
    if reg:
        out['file_registry'] = _auth_chat_slim_file_registry(reg, max_chars)
    img = row.get('image_url') if isinstance(row.get('image_url'), dict) else {}
    img_url = str((img or {}).get('url') or row.get('image_url') or '').strip()
    if _auth_chat_is_ephemeral_image_url(img_url):
        img_url = ''
    id_view = _auth_chat_image_part_id_url({**row, 'file_registry': reg}, download=False)
    id_download = _auth_chat_image_part_id_url({**row, 'file_registry': reg}, download=True)
    stable = (
        str(out.get('view_url') or '').strip()
        or str(out.get('url') or '').strip()
        or str(out.get('persisted_url') or '').strip()
        or str(out.get('server_url') or '').strip()
        or str(out.get('model_storage_ref') or '').strip()
        or str(out.get('storage_ref') or '').strip()
        or id_view
    )
    if not img_url:
        img_url = stable
    out['image_url'] = {'url': _auth_chat_trim_small_text(img_url, 1200) if img_url else ''}
    if id_view and not str(out.get('view_url') or '').strip():
        out['view_url'] = id_view
    if id_download and not str(out.get('download_url') or '').strip():
        out['download_url'] = id_download
    if id_view and not str(out.get('url') or '').strip():
        out['url'] = id_view
    return out

def _auth_chat_trim_value(value, max_chars: int):
    if isinstance(value, str):
        text = str(value or '')
        low = text.strip().lower()
        if (low.startswith('data:image/') and len(text) > 256) or low.startswith('blob:') or low.startswith('local://'):
            return ''
        return _auth_chat_trim_text(value, max_chars)
    if isinstance(value, list):
        return [_auth_chat_trim_value(item, max_chars) for item in value]
    if isinstance(value, dict):
        try:
            kind = str(value.get('_kind') or '').strip()
        except Exception:
            kind = ''
        if str(value.get('type') or '').strip() == 'image_url':
            return _auth_chat_slim_image_part_payload(value, max_chars)
        if kind in {'file', 'genfiles'} or isinstance(value.get('file_registry'), dict) or bool(value.get('generated_by_assistant')):
            return _auth_chat_slim_file_payload(value, max_chars)
        trimmed = {}
        for key, item in value.items():
            key_str = str(key or '')
            if key_str in {'data_url', 'base64', 'raw_base64', 'file_bytes', '_preview_url', '_source_url'}:
                trimmed[key] = ''
                continue
            if key_str in {'_upload_pending', '_ocr_pending', '_upload_phase', '_upload_progress', '_upload_error', '_sessionId'}:
                continue
            if key_str == 'image_url' and isinstance(item, dict):
                img = dict(item or {})
                url = str(img.get('url') or '').strip()
                low = url.lower()
                if (low.startswith('data:image/') and len(url) > 256) or low.startswith('blob:') or low.startswith('local://'):
                    img['url'] = ''
                trimmed[key] = _auth_chat_trim_value(img, max_chars)
                continue
            trimmed[key] = _auth_chat_trim_value(item, max_chars)
        return trimmed
    return value



def _auth_chat_ms_from_ts(ts: float | int | None = None) -> int:
    try:
        value = float(ts if ts is not None else _utc_ts())
    except Exception:
        value = time.time()
    if value > 100000000000:
        return int(value)
    return int(value * 1000)


def _auth_chat_session_deleted(session_obj: dict | None = None) -> bool:
    row = session_obj if isinstance(session_obj, dict) else {}
    if not row:
        return False
    if bool(row.get('_deleted') or row.get('deleted') or row.get('is_deleted')):
        return True
    try:
        deleted_at = float(row.get('deleted_at') or row.get('deletedAt') or 0.0)
    except Exception:
        deleted_at = 0.0
    return deleted_at > 0


def _auth_chat_visible_sessions(sessions: dict | None = None) -> dict:
    if not isinstance(sessions, dict):
        return {}
    return {str(sid): sess for sid, sess in sessions.items() if isinstance(sess, dict) and not _auth_chat_session_deleted(sess)}


def _auth_chat_deleted_sessions_from_store(store_obj: dict | None = None) -> dict:
    store = store_obj if isinstance(store_obj, dict) else {}
    raw = (
        store.get('_deleted_sessions') or
        store.get('deleted_sessions') or
        store.get('deletedSessionTombstones') or
        store.get('_deletedSessionTombstones') or
        {}
    )
    if not isinstance(raw, dict):
        return {}
    now_ms = _auth_chat_ms_from_ts()
    cutoff_ms = now_ms - int(AUTH_CHAT_SOFT_DELETE_RETENTION_S * 1000)
    out: dict[str, dict] = {}
    for raw_sid, raw_row in raw.items():
        sid = str(raw_sid or '').strip()
        if not sid:
            continue
        row = raw_row if isinstance(raw_row, dict) else {'deleted_at': raw_row}
        try:
            deleted_at = float(row.get('deleted_at') if row.get('deleted_at') is not None else row.get('deletedAt') or 0)
        except Exception:
            deleted_at = 0.0
        if deleted_at > 0 and deleted_at < 100000000000:
            deleted_at *= 1000
        deleted_at_ms = int(deleted_at or now_ms)
        if deleted_at_ms < cutoff_ms:
            continue
        try:
            revision = int(row.get('server_revision') if row.get('server_revision') is not None else row.get('revision') if row.get('revision') is not None else row.get('deleted_revision') or 0)
        except Exception:
            revision = 0
        out[sid] = {
            'session_id': sid,
            'deleted_at': deleted_at_ms,
            'server_revision': max(0, revision),
            'device_id': str(row.get('device_id') or row.get('deviceId') or '')[:160],
        }
    return out


def _auth_chat_set_deleted_sessions_on_store(store_obj: dict, tombstones: dict | None = None) -> dict:
    if not isinstance(store_obj, dict):
        return store_obj
    rows = _auth_chat_deleted_sessions_from_store({'_deleted_sessions': tombstones or {}})
    if rows:
        store_obj['_deleted_sessions'] = rows
    else:
        store_obj.pop('_deleted_sessions', None)
        store_obj.pop('deleted_sessions', None)
        store_obj.pop('deletedSessionTombstones', None)
        store_obj.pop('_deletedSessionTombstones', None)
    return store_obj


def _auth_chat_add_delete_tombstone(store_obj: dict, session_id: str, *, deleted_at=None, revision: int = 0, device_id: str = '') -> bool:
    if not isinstance(store_obj, dict):
        return False
    sid = str(session_id or '').strip()
    if not sid:
        return False
    rows = _auth_chat_deleted_sessions_from_store(store_obj)
    try:
        deleted_ms = float(deleted_at if deleted_at is not None else _auth_chat_ms_from_ts())
    except Exception:
        deleted_ms = float(_auth_chat_ms_from_ts())
    if deleted_ms > 0 and deleted_ms < 100000000000:
        deleted_ms *= 1000
    prev = rows.get(sid) if isinstance(rows.get(sid), dict) else {}
    prev_rev = int(prev.get('server_revision') or 0) if prev else 0
    prev_at = int(prev.get('deleted_at') or 0) if prev else 0
    rows[sid] = {
        'session_id': sid,
        'deleted_at': max(int(deleted_ms or 0), prev_at),
        'server_revision': max(int(revision or 0), prev_rev),
        'device_id': str(device_id or prev.get('device_id') or '')[:160],
    }
    _auth_chat_set_deleted_sessions_on_store(store_obj, rows)
    return True


def _auth_chat_stamp_delete_tombstone_revision(store_obj: dict, session_id: str, *, revision: int = 0, now_ts: float | None = None, device_id: str = '') -> bool:
    sid = str(session_id or '').strip()
    if not isinstance(store_obj, dict) or not sid:
        return False
    return _auth_chat_add_delete_tombstone(
        store_obj,
        sid,
        deleted_at=_auth_chat_ms_from_ts(now_ts),
        revision=max(0, int(revision or 0)),
        device_id=device_id,
    )


def _auth_chat_session_is_tombstoned_for_client(store_obj: dict | None, session_id: str, client_base_revision: int = 0) -> bool:
    sid = str(session_id or '').strip()
    if not sid:
        return False
    rows = _auth_chat_deleted_sessions_from_store(store_obj)
    row = rows.get(sid)
    if not isinstance(row, dict):
        return False
    # A deleted session has no implicit restore operation.  Revision ordering
    # protects stale writes, but must never turn a tombstone into a writable
    # record once a client catches up with the delete revision.
    _ = client_base_revision
    return True


def _auth_chat_pick_active_visible_session_id(store_obj: dict | None = None) -> str:
    store = store_obj if isinstance(store_obj, dict) else {}
    sessions = store.get('sessions') if isinstance(store.get('sessions'), dict) else {}
    active_id = str(store.get('activeId') or '').strip()
    if active_id and isinstance(sessions.get(active_id), dict) and not _auth_chat_session_deleted(sessions.get(active_id)):
        return active_id
    visible = _auth_chat_visible_sessions(sessions)
    if not visible:
        return ''
    rows = []
    for sid, sess in visible.items():
        rows.append((
            _auth_chat_safe_float(sess.get('updatedAt') or sess.get('updated_at') or sess.get('createdAt') or sess.get('created_at') or 0.0),
            _auth_chat_safe_float(sess.get('createdAt') or sess.get('created_at') or 0.0),
            sid,
        ))
    rows.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return rows[0][2] if rows else ''


def _auth_chat_public_store_for_response(store_obj: dict | None = None) -> dict | None:
    if not isinstance(store_obj, dict):
        return None
    out = _auth_chat_store_clone(store_obj)
    sessions = out.get('sessions') if isinstance(out.get('sessions'), dict) else {}
    visible = _auth_chat_visible_sessions(sessions)
    if not visible:
        out['sessions'] = {}
        out['activeId'] = None
        return out
    out['sessions'] = visible
    out['activeId'] = _auth_chat_pick_active_visible_session_id(out) or next(iter(visible.keys()), '')
    return out


def _auth_chat_store_backup_record(email: str, rec: dict | None = None, reason: str = '') -> None:
    normalized = _normalize_login_email(email)
    if not normalized or not isinstance(rec, dict) or not isinstance(rec.get('store'), dict):
        return
    try:
        os.makedirs(AUTH_CHAT_BACKUP_DIR, exist_ok=True)
        safe_email = re.sub(r'[^0-9A-Za-z_.@-]+', '_', normalized)[:120]
        stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S')
        rev = _auth_chat_store_revision_value(rec)
        safe_reason = re.sub(r'[^0-9A-Za-z_.-]+', '_', str(reason or 'sync')[:40]) or 'sync'
        path = os.path.join(AUTH_CHAT_BACKUP_DIR, f'{stamp}_{safe_email}_rev{rev}_{safe_reason}.json')
        payload = {
            'email': normalized,
            'reason': safe_reason,
            'backup_at': _utc_ts(),
            'record': rec,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
        files = []
        for name in os.listdir(AUTH_CHAT_BACKUP_DIR):
            fp = os.path.join(AUTH_CHAT_BACKUP_DIR, name)
            if os.path.isfile(fp) and name.endswith('.json'):
                try:
                    files.append((os.path.getmtime(fp), fp))
                except Exception:
                    pass
        files.sort(reverse=True)
        for _mtime, fp in files[AUTH_CHAT_BACKUP_MAX_FILES:]:
            try:
                os.remove(fp)
            except Exception:
                pass
        try:
            pruner = globals().get('_storage_quota_prune_dir')
            if callable(pruner):
                pruner(AUTH_CHAT_BACKUP_DIR, AUTH_CHAT_BACKUP_MAX_BYTES)
        except Exception:
            pass
    except Exception:
        try:
            app_logger.exception('[auth_chat_store] backup_failed email=%s reason=%s', normalized, reason)
        except Exception:
            pass


def _auth_chat_message_to_summary_line(message, *, max_chars: int = 360) -> str:
    if not isinstance(message, dict):
        return ''
    role = str(message.get('role') or '').strip() or 'message'
    content = message.get('content')
    bits: list[str] = []
    if isinstance(content, str):
        bits.append(content)
    elif isinstance(content, list):
        has_img = False
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get('type') == 'text':
                txt = str(part.get('text') or '').strip()
                if txt:
                    bits.append(txt)
            elif part.get('type') == 'image_url':
                has_img = True
        if has_img:
            bits.append('[图片]')
    elif isinstance(content, dict):
        kind = str(content.get('_kind') or '').strip()
        if kind == 'file':
            bits.append('[文件] ' + str(content.get('filename') or '').strip())
        elif kind == 'image':
            bits.append('[图片]')
        elif kind == 'genfiles':
            names = []
            for item in (content.get('files') or [])[:10]:
                if isinstance(item, dict) and str(item.get('filename') or '').strip():
                    names.append(str(item.get('filename') or '').strip())
            bits.append('[生成文件] ' + ', '.join(names))
        else:
            try:
                bits.append(json.dumps(content, ensure_ascii=False)[:max_chars])
            except Exception:
                bits.append('[非文本内容]')
    text = ' '.join(str(x or '').replace('\r\n', '\n').replace('\r', '\n').strip() for x in bits if str(x or '').strip())
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return ''
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip() + '…'
    return f'{role}: {text}'


def _auth_chat_extract_history_summary(session_obj: dict | None = None) -> str:
    row = session_obj if isinstance(session_obj, dict) else {}
    candidates = [
        row.get('historySummary'),
        row.get('history_summary'),
        row.get('summaryText'),
    ]
    for candidate in candidates:
        text = str(candidate or '').strip()
        if text:
            return _auth_chat_trim_text(text, AUTH_CHAT_HISTORY_SUMMARY_MAX_CHARS)
    for message in (row.get('messages') or []):
        if not isinstance(message, dict) or str(message.get('role') or '').strip() != 'system':
            continue
        raw = str(message.get('content') or '').strip()
        if raw.startswith('【历史摘要】') or raw.startswith('[历史摘要]') or str(message.get('_kind') or '') == 'history_summary':
            cleaned = re.sub(r'^[【\[]历史摘要[】\]]\s*', '', raw).strip()
            if cleaned:
                return _auth_chat_trim_text(cleaned, AUTH_CHAT_HISTORY_SUMMARY_MAX_CHARS)
    return ''


def _auth_chat_build_history_summary(existing_summary: str, messages: list, *, max_chars: int | None = None) -> str:
    limit = max(1200, int(max_chars or AUTH_CHAT_HISTORY_SUMMARY_MAX_CHARS))
    existing = _auth_chat_trim_text(existing_summary or '', limit)
    lines: list[str] = []
    for message in (messages or []):
        line = _auth_chat_message_to_summary_line(message)
        if line:
            lines.append(line)
    if len(lines) > AUTH_CHAT_HISTORY_SUMMARY_MAX_LINES:
        lines = lines[-AUTH_CHAT_HISTORY_SUMMARY_MAX_LINES:]
    parts = []
    if existing:
        parts.append(existing)
    if lines:
        parts.append('旧消息压缩记录：\n' + '\n'.join(f'- {line}' for line in lines))
    merged = '\n\n'.join(part for part in parts if part).strip()
    if len(merged) <= limit:
        return merged
    tail = merged[-limit:]
    cut = tail.find('\n')
    if cut > 0:
        tail = tail[cut + 1:]
    return ('…\n' + tail).strip()


def _auth_chat_apply_history_summary_to_session(session_obj: dict, dropped_messages: list) -> tuple[dict, bool]:
    if not isinstance(session_obj, dict) or not dropped_messages:
        return session_obj, False
    previous = _auth_chat_extract_history_summary(session_obj)
    merged = _auth_chat_build_history_summary(previous, dropped_messages)
    if not merged:
        return session_obj, False
    changed = False
    if str(session_obj.get('historySummary') or '').strip() != merged:
        session_obj['historySummary'] = merged
        changed = True
    now_ms = int(time.time() * 1000)
    session_obj['historySummaryUpdatedAt'] = now_ms
    try:
        session_obj['historySummaryMessageCount'] = max(
            int(session_obj.get('historySummaryMessageCount') or 0),
            int(session_obj.get('historySummaryUntilMessageCount') or 0),
        ) + len([m for m in dropped_messages if isinstance(m, dict)])
        session_obj['historySummaryUntilMessageCount'] = session_obj['historySummaryMessageCount']
    except Exception:
        session_obj['historySummaryUntilMessageCount'] = len([m for m in dropped_messages if isinstance(m, dict)])
    return session_obj, changed



def _auth_chat_extract_resume_files(session_obj: dict | None = None, *, limit: int | None = None) -> list[dict]:
    row = session_obj if isinstance(session_obj, dict) else {}
    try:
        max_items = AUTH_CHAT_RESUME_STATE_FILES_MAX if limit is None else max(0, int(limit or 0))
    except Exception:
        max_items = AUTH_CHAT_RESUME_STATE_FILES_MAX
    if max_items <= 0:
        return []
    out: list[dict] = []
    seen: set[str] = set()

    def push_file(obj, role: str = '') -> None:
        if len(out) >= max_items or not isinstance(obj, dict):
            return
        filename = str(obj.get('filename') or obj.get('output_filename') or obj.get('target_filename') or '').strip()
        if not filename:
            reg = obj.get('file_registry') if isinstance(obj.get('file_registry'), dict) else {}
            filename = str((reg or {}).get('filename') or (reg or {}).get('saved_filename') or '').strip()
        if not filename:
            return
        source_role = str(obj.get('source_role') or obj.get('sourceRole') or role or '').strip()
        key = (source_role + '|' + filename).lower()
        if key in seen:
            return
        seen.add(key)
        row_obj = {
            'filename': _auth_chat_trim_small_text(filename, 180),
            'source_role': _auth_chat_trim_small_text(source_role, 60),
            'download_url': _auth_chat_trim_small_text(str(obj.get('download_url') or obj.get('url') or ''), 320),
        }
        out.append({k: v for k, v in row_obj.items() if v})

    def scan_content(content, role: str = '') -> None:
        if len(out) >= max_items:
            return
        if isinstance(content, dict):
            kind = str(content.get('_kind') or '').strip()
            if kind == 'file':
                push_file(content, role or 'user_upload')
            elif kind == 'genfiles':
                for item in (content.get('files') or []):
                    push_file(item, role or 'assistant_generated')
                    if len(out) >= max_items:
                        return
            elif isinstance(content.get('files'), list):
                for item in content.get('files') or []:
                    push_file(item, role)
                    if len(out) >= max_items:
                        return
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    scan_content(item, role)
                    if len(out) >= max_items:
                        return

    for msg in reversed(row.get('messages') or []):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get('role') or '').strip().lower()
        default_role = 'assistant_generated' if role == 'assistant' else ('user_upload' if role == 'user' else '')
        scan_content(msg.get('content'), default_role)
        if len(out) >= max_items:
            break
    return out[:max_items]


def _auth_chat_build_session_resume_state(session_obj: dict | None = None, *, max_chars: int | None = None) -> dict:
    row = session_obj if isinstance(session_obj, dict) else {}
    limit = max(700, min(int(max_chars or AUTH_CHAT_RESUME_STATE_MAX_CHARS), 3200))
    title = _auth_chat_trim_small_text(str(row.get('title') or '新对话').strip() or '新对话', 160)
    updated_raw = row.get('updatedAt') or row.get('updated_at') or row.get('createdAt') or row.get('created_at') or 0
    updated_ts = _auth_chat_safe_float(updated_raw)
    if updated_ts > 100000000000:
        updated_ts = updated_ts / 1000.0
    messages = row.get('messages') if isinstance(row.get('messages'), list) else []
    source_message_count = len([m for m in messages if isinstance(m, dict)])
    summary = _auth_chat_trim_small_text(_auth_chat_extract_history_summary(row), 360)

    recent_lines: list[str] = []
    last_user = ''
    last_assistant = ''
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get('role') or '').strip().lower()
        if role not in {'user', 'assistant'}:
            continue
        line = _auth_chat_message_to_summary_line(msg, max_chars=380)
        if not line:
            continue
        if role == 'user' and not last_user:
            last_user = line
        elif role == 'assistant' and not last_assistant:
            last_assistant = line
        recent_lines.append(line)
        if len(recent_lines) >= AUTH_CHAT_RESUME_STATE_RECENT_LINES and last_user and last_assistant:
            break
    recent_lines = list(reversed(recent_lines[:AUTH_CHAT_RESUME_STATE_RECENT_LINES]))
    files = _auth_chat_extract_resume_files(row, limit=AUTH_CHAT_RESUME_STATE_FILES_MAX)
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
        parts.append('最近交互: ' + ' / '.join(recent_lines[-AUTH_CHAT_RESUME_STATE_RECENT_LINES:]))
    if file_names:
        parts.append('相关文件: ' + '、'.join(file_names[:AUTH_CHAT_RESUME_STATE_FILES_MAX]))
    text = '\n'.join(part for part in parts if str(part or '').strip()).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + '\n...【最后状态已截断】'
    now_ms = int(time.time() * 1000)
    state = {
        'schema_version': 1,
        'updated_at': _fmt_ts(updated_ts) if callable(globals().get('_fmt_ts')) else str(updated_ts or ''),
        'updated_ts': updated_ts,
        'generated_at': now_ms,
        'source_message_count': source_message_count,
        'source_updated_at': updated_raw,
        'title': title,
        'summary_hint': summary,
        'last_user': _auth_chat_trim_small_text(last_user, 480),
        'last_assistant': _auth_chat_trim_small_text(last_assistant, 480),
        'recent': [_auth_chat_trim_small_text(x, 420) for x in recent_lines[-AUTH_CHAT_RESUME_STATE_RECENT_LINES:]],
        'files': files,
        'text': text,
    }
    return {k: v for k, v in state.items() if v not in ('', [], None)}


def _auth_chat_resume_state_matches(prev, state: dict) -> bool:
    if not isinstance(prev, dict) or not isinstance(state, dict):
        return False
    for key in ('schema_version', 'source_message_count', 'source_updated_at', 'text'):
        if prev.get(key) != state.get(key):
            return False
    return True


def _auth_chat_apply_resume_state_to_session(session_obj: dict) -> tuple[dict, bool]:
    if not isinstance(session_obj, dict) or _auth_chat_session_deleted(session_obj):
        return session_obj, False
    state = _auth_chat_build_session_resume_state(session_obj)
    if not state or not str(state.get('text') or '').strip():
        return session_obj, False
    prev = session_obj.get('sessionResumeState') if isinstance(session_obj.get('sessionResumeState'), dict) else {}
    if _auth_chat_resume_state_matches(prev, state):
        return session_obj, False
    session_obj['sessionResumeState'] = state
    return session_obj, True

def _auth_chat_compact_store(store_payload, *, max_sessions: int, max_messages: int, max_chars: int) -> tuple[dict, bool]:
    if not isinstance(store_payload, dict):
        raise ValueError('会话数据格式不正确')
    try:
        clean = json.loads(json.dumps(store_payload, ensure_ascii=False))
    except Exception as e:
        raise ValueError('会话数据格式不正确') from e
    sessions = clean.get('sessions')
    active_id = str(clean.get('activeId') or '').strip()
    if not isinstance(sessions, dict):
        raise ValueError('会话数据格式不正确')
    tombstones = _auth_chat_deleted_sessions_from_store(clean)

    changed = False
    if not active_id:
        # Empty chat stores are valid after the last conversation is deleted.
        # Keep non-empty stores self-healing by picking a usable session id below.
        changed = True

    cleaned_items: list[tuple[str, dict]] = []
    now_ms = _auth_chat_ms_from_ts()
    delete_cutoff_ms = now_ms - int(AUTH_CHAT_SOFT_DELETE_RETENTION_S * 1000)
    for raw_sid, raw_session in sessions.items():
        sid = str(raw_sid or '').strip()
        if not sid or not isinstance(raw_session, dict):
            changed = True
            continue
        session_obj = _auth_chat_trim_value(raw_session, max_chars)
        if not isinstance(session_obj, dict):
            changed = True
            continue
        session_obj['id'] = str(session_obj.get('id') or sid).strip() or sid
        if session_obj['id'] != sid:
            changed = True
        if sid in tombstones or _auth_chat_session_deleted(session_obj):
            changed = True
            continue
        messages = session_obj.get('messages')
        if not isinstance(messages, list):
            session_obj['messages'] = []
            if messages is not None:
                changed = True
        elif max_messages > 0 and len(messages) > max_messages:
            dropped_messages = messages[:-max_messages]
            session_obj, summary_changed = _auth_chat_apply_history_summary_to_session(session_obj, dropped_messages)
            session_obj['messages'] = messages[-max_messages:]
            changed = True or summary_changed
        session_obj, resume_changed = _auth_chat_apply_resume_state_to_session(session_obj)
        changed = changed or bool(resume_changed)
        cleaned_items.append((sid, session_obj))

    def _sort_key(item: tuple[str, dict]):
        sid, sess = item
        deleted_rank = 1 if _auth_chat_session_deleted(sess) else 0
        updated_at = _auth_chat_safe_float(sess.get('updatedAt') or sess.get('updated_at') or sess.get('createdAt') or sess.get('created_at') or 0.0)
        created_at = _auth_chat_safe_float(sess.get('createdAt') or sess.get('created_at') or 0.0)
        return (deleted_rank, 0 if sid == active_id else 1, -updated_at, -created_at, sid)

    cleaned_items.sort(key=_sort_key)
    if max_sessions > 0 and len(cleaned_items) > max_sessions:
        changed = True
        cleaned_items = cleaned_items[:max_sessions]

    new_sessions = {sid: sess for sid, sess in cleaned_items}
    active_visible = _auth_chat_pick_active_visible_session_id({'sessions': new_sessions, 'activeId': active_id})
    if active_visible:
        if active_id != active_visible:
            active_id = active_visible
            changed = True
    elif active_id not in new_sessions:
        if cleaned_items:
            active_id = cleaned_items[0][0]
            changed = True
        else:
            if active_id is not None:
                active_id = None
                changed = True

    compact = dict(clean)
    compact['sessions'] = new_sessions
    compact['activeId'] = active_id
    _auth_chat_set_deleted_sessions_on_store(compact, tombstones)
    return compact, changed


def _sanitize_synced_chat_store(store_payload) -> tuple[dict, bool]:
    clean, changed = _auth_chat_compact_store(
        store_payload,
        max_sessions=AUTH_CHAT_ACCOUNT_MAX_SESSIONS,
        max_messages=AUTH_CHAT_ACCOUNT_MAX_MESSAGES_PER_SESSION,
        max_chars=AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS,
    )
    payload_size = len(json.dumps(clean, ensure_ascii=False).encode('utf-8'))
    if payload_size <= AUTH_CHAT_STORE_MAX_BYTES:
        return clean, changed
    raise ValueError(
        f'账号云端会话数据已达到安全上限 '
        f'({_storage_quota_human(payload_size)} / {_storage_quota_human(AUTH_CHAT_STORE_MAX_BYTES)})；'
        '系统未删除任何会话，请提高会话存储额度或导出旧会话后再继续同步'
    )
