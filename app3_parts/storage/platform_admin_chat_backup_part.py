# Split from app3_parts/storage/storage_quota_part.py.
# Purpose: platform-admin chat-session inspection, backups, restore, account details, and account actions.
# Loaded by storage_quota_part.py via _exec_split_file(...), sharing the original global namespace.

def _platform_admin_chat_sessions_payload(
    owner: str = '',
    *,
    limit: int = 80,
    page: int = 1,
    page_size: int | None = None,
) -> dict:
    normalized = _storage_quota_norm_owner(owner or '')
    if not normalized:
        return {'ok': False, 'rows': [], 'total': 0, 'error': '账号不能为空'}
    getter = globals().get('_auth_chat_store_get')
    rec = getter(normalized) if callable(getter) else None
    rec = dict(rec or {}) if isinstance(rec, dict) else {}
    store = rec.get('store') if isinstance(rec.get('store'), dict) else {}
    sessions = store.get('sessions') if isinstance(store.get('sessions'), dict) else {}
    deleted_checker = globals().get('_auth_chat_session_deleted')
    rows: list[dict] = []
    for sid, session in sessions.items():
        if not isinstance(session, dict):
            continue
        try:
            deleted = bool(deleted_checker(session)) if callable(deleted_checker) else bool(session.get('deleted') or session.get('deleted_at'))
        except Exception:
            deleted = bool(session.get('deleted') or session.get('deleted_at'))
        messages = session.get('messages') if isinstance(session.get('messages'), list) else []
        updated_ts = float(session.get('updatedAt') or session.get('updated_at') or session.get('lastUpdated') or session.get('createdAt') or 0.0)
        rows.append({
            'id': str(sid or ''),
            'title': str(session.get('title') or session.get('name') or '新会话'),
            'model': str(session.get('model') or ''),
            'message_count': len(messages),
            'deleted': deleted,
            'updated_at': _storage_quota_fmt_ts(updated_ts),
            'updated_ts': updated_ts,
        })
    rows.sort(key=lambda item: (-float(item.get('updated_ts') or 0.0), str(item.get('title') or '')))
    effective_page_size = _platform_admin_safe_int(
        page_size if page_size is not None else limit,
        20,
        minimum=5,
        maximum=200,
    )
    page_rows, page_info = _platform_admin_paginate_rows(
        rows,
        page=page,
        page_size=effective_page_size,
    )
    return {
        'ok': True,
        'revision': int(rec.get('revision') or 0),
        'active_id': str(store.get('activeId') or store.get('active_id') or ''),
        'total': len(rows),
        'rows': page_rows,
        'page': page_info,
    }


class _PlatformAdminChatSessionNotFound(ValueError):
    pass


_PLATFORM_ADMIN_CHAT_ALLOWED_ROLES = {'user', 'assistant'}
_PLATFORM_ADMIN_CHAT_SENSITIVE_KEYS = {
    'token',
    'api_key',
    'apikey',
    'authorization',
    'cookie',
    'headers',
    'password',
    'secret',
    'access_token',
    'accesstoken',
    'refresh_token',
    'refreshtoken',
    'env',
    'raw',
    'request',
    'response',
}
_PLATFORM_ADMIN_CHAT_SOURCE_FIELDS = {
    'id',
    'title',
    'url',
    'link',
    'source',
    'name',
    'site',
    'domain',
    'snippet',
    'summary',
    'text',
    'published_at',
    'updated_at',
}
_PLATFORM_ADMIN_CHAT_ATTACHMENT_FIELDS = {
    'id',
    'file_id',
    'attachment_id',
    'image_id',
    'filename',
    'name',
    'type',
    'mime_type',
    'size',
    'size_bytes',
    'url',
    'view_url',
    'download_url',
    'preview_url',
    'source_role',
}
_PLATFORM_ADMIN_CHAT_URL_FIELDS = {'url', 'link', 'view_url', 'download_url', 'preview_url'}
_PLATFORM_ADMIN_CHAT_SENSITIVE_QUERY_KEYS = {
    'token',
    'api_key',
    'apikey',
    'authorization',
    'cookie',
    'password',
    'secret',
    'access_token',
    'refresh_token',
    'signature',
    'sig',
    'x-amz-signature',
    'x-amz-credential',
    'x-amz-security-token',
}


def _platform_admin_chat_sensitive_key(key: str = '') -> bool:
    lowered = str(key or '').strip().lower()
    collapsed = lowered.replace('-', '').replace('_', '')
    return lowered in _PLATFORM_ADMIN_CHAT_SENSITIVE_KEYS or collapsed in _PLATFORM_ADMIN_CHAT_SENSITIVE_KEYS


def _platform_admin_chat_sanitize_url(value: str = '') -> str:
    raw = str(value or '')
    if not raw:
        return raw
    try:
        urlparse = __import__('urllib.parse', fromlist=['urlsplit', 'urlunsplit', 'parse_qsl', 'urlencode'])
        parts = urlparse.urlsplit(raw)
        if not parts.query:
            return raw
        kept = []
        for key, item in urlparse.parse_qsl(parts.query, keep_blank_values=True):
            key_l = str(key or '').strip().lower()
            key_collapsed = key_l.replace('-', '').replace('_', '')
            if key_l in _PLATFORM_ADMIN_CHAT_SENSITIVE_QUERY_KEYS or key_collapsed in _PLATFORM_ADMIN_CHAT_SENSITIVE_QUERY_KEYS:
                continue
            kept.append((key, item))
        query = urlparse.urlencode(kept, doseq=True)
        return urlparse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    except Exception:
        return raw


def _platform_admin_chat_sanitize_value(value, key: str = ''):
    key_l = str(key or '').strip().lower()
    if isinstance(value, str) and key_l in _PLATFORM_ADMIN_CHAT_URL_FIELDS:
        return _platform_admin_chat_sanitize_url(value)
    if isinstance(value, dict):
        out = {}
        for item_key, item in value.items():
            if _platform_admin_chat_sensitive_key(str(item_key or '')):
                continue
            out[str(item_key)] = _platform_admin_chat_sanitize_value(item, str(item_key or ''))
        return out
    if isinstance(value, list):
        return [_platform_admin_chat_sanitize_value(item, key_l) for item in value]
    return value


def _platform_admin_chat_public_field_map(value, allowed_fields: set[str]) -> list | dict | None:
    if isinstance(value, list):
        rows = []
        for item in value:
            cleaned = _platform_admin_chat_public_field_map(item, allowed_fields)
            if cleaned:
                rows.append(cleaned)
        return rows
    if isinstance(value, dict):
        out = {}
        for key in allowed_fields:
            if key in value and not _platform_admin_chat_sensitive_key(key):
                out[key] = _platform_admin_chat_sanitize_value(value.get(key), key)
        return out
    return None


def _platform_admin_public_chat_message(msg):
    if not isinstance(msg, dict):
        return None
    role = str(msg.get('role') or '').strip().lower()
    if role not in _PLATFORM_ADMIN_CHAT_ALLOWED_ROLES:
        return None
    out = {'role': role}
    for key in ('id', 'createdAt', 'created_at', 'updatedAt', 'updated_at'):
        if key in msg and not _platform_admin_chat_sensitive_key(key):
            out[key] = _platform_admin_chat_sanitize_value(msg.get(key), key)
    if 'content' in msg:
        out['content'] = _platform_admin_chat_sanitize_value(msg.get('content'), 'content')
    cleaned_sources = _platform_admin_chat_public_field_map(msg.get('sources'), _PLATFORM_ADMIN_CHAT_SOURCE_FIELDS)
    if cleaned_sources:
        out['sources'] = cleaned_sources
    for key in ('attachments', 'files', 'images'):
        cleaned = _platform_admin_chat_public_field_map(msg.get(key), _PLATFORM_ADMIN_CHAT_ATTACHMENT_FIELDS)
        if cleaned:
            out[key] = cleaned
    return out


def _platform_admin_public_chat_session(session):
    if not isinstance(session, dict):
        return {'messages': []}
    messages = session.get('messages') if isinstance(session.get('messages'), list) else []
    public_messages = []
    for item in messages:
        public = _platform_admin_public_chat_message(item)
        if public:
            public_messages.append(public)
    out = {
        'id': str(session.get('id') or ''),
        'title': str(session.get('title') or session.get('name') or '新会话'),
        'model': str(session.get('model') or ''),
        'messages': public_messages,
    }
    for key in ('createdAt', 'created_at', 'updatedAt', 'updated_at'):
        if key in session:
            out[key] = _platform_admin_chat_sanitize_value(session.get(key), key)
    return out


def _platform_admin_chat_session_payload(owner: str = '', session_id: str = '', reason: str = '') -> dict:
    normalized = _storage_quota_norm_owner(owner or '')
    sid = str(session_id or '').strip()
    if not normalized or '@' not in normalized:
        raise ValueError('账号无效')
    if not sid:
        raise ValueError('会话 ID 不能为空')
    getter = globals().get('_auth_chat_store_get')
    rec = getter(normalized) if callable(getter) else None
    rec = dict(rec or {}) if isinstance(rec, dict) else {}
    store = rec.get('store') if isinstance(rec.get('store'), dict) else {}
    sessions = store.get('sessions') if isinstance(store.get('sessions'), dict) else {}
    session = sessions.get(sid) if isinstance(sessions, dict) else None
    if not isinstance(session, dict):
        raise _PlatformAdminChatSessionNotFound('会话不存在')
    deleted_checker = globals().get('_auth_chat_session_deleted')
    try:
        deleted = bool(deleted_checker(session)) if callable(deleted_checker) else bool(session.get('deleted') or session.get('deleted_at'))
    except Exception:
        deleted = bool(session.get('deleted') or session.get('deleted_at'))
    if deleted:
        raise _PlatformAdminChatSessionNotFound('会话不存在或已删除')
    title = str(session.get('title') or session.get('name') or '新会话')
    model = str(session.get('model') or '')
    public_session = _platform_admin_public_chat_session(session)
    public_messages = public_session.get('messages') if isinstance(public_session.get('messages'), list) else []
    reason_text = str(reason or '').strip()[:240]
    audit_detail = {
        'title': title[:240],
        'model': model[:160],
        'message_count': len(public_messages),
        'deleted': deleted,
        'reason': reason_text,
    }
    _platform_admin_audit_append('chat_session_view', f'{normalized}:{sid}', audit_detail, ok=True)
    updated_ts = float(session.get('updatedAt') or session.get('updated_at') or session.get('lastUpdated') or session.get('createdAt') or 0.0)
    return {
        'ok': True,
        'owner': normalized,
        'session_id': sid,
        'revision': int(rec.get('revision') or 0),
        'summary': {
            'id': sid,
            'title': title,
            'model': model,
            'message_count': len(public_messages),
            'deleted': deleted,
            'updated_at': _storage_quota_fmt_ts(updated_ts),
            'updated_ts': updated_ts,
        },
        'session': public_session,
    }


def _platform_admin_backup_dir() -> str:
    root = _app_data_path('platform_admin_backups')
    os.makedirs(root, exist_ok=True)
    return root


def _platform_admin_backup_target_specs() -> list[dict]:
    candidates: list[dict] = []

    def add(rel: str, path: str = '', kind: str = 'file') -> None:
        raw = str(path or _app_data_path(rel)).strip()
        if not raw:
            return
        try:
            abs_path = os.path.abspath(raw)
            base = os.path.abspath(APP_DATA_DIR)
            if not (abs_path == base or abs_path.startswith(base + os.sep)):
                return
            candidates.append({
                'path': rel.replace('\\', '/').strip('/'),
                'target': abs_path,
                'kind': str(kind or 'file'),
            })
        except Exception:
            pass
    for rel in (
        'auth_chat_store.json',
        'auth_users_store.json',
        'auth_account_profile_store.json',
        'auth_personalization_memory_store.json',
        'email_login_store.json',
        'auth_invite_codes_store.json',
        'local_admin_store.json',
        'storage_account_files.json',
        'storage_account_quota_limits.json',
        'storage_quota_policy.json',
        'file_registry_store.json',
        'user_personalization_store.json',
        'chat_share_store.json',
        'image_generation_provider_mirrors.json',
        'image_pullback_jobs.json',
        'platform_admin_audit_log.json',
        'platform_admin_recycle/recycle_store.json',
        'host_fetch_state.json',
        'mcp_token.key',
    ):
        add(rel)
    try:
        kb_path = str(globals().get('_kb_db_path')() if callable(globals().get('_kb_db_path')) else _app_data_path('knowledge_base.db'))
        add(_platform_admin_rel_path(kb_path), kb_path, 'sqlite')
    except Exception:
        add('knowledge_base.db', kind='sqlite')
    try:
        chat_db_path = str(globals().get('_auth_chat_db_file_path')() if callable(globals().get('_auth_chat_db_file_path')) else _app_data_path('auth_chat_store.db'))
        add(_platform_admin_rel_path(chat_db_path), chat_db_path, 'sqlite')
    except Exception:
        add('auth_chat_store.db', kind='sqlite')
    for rel in ('knowledge_base.db', 'chat_async_jobs.db', 'host_fetch_state.db'):
        add(rel, kind='sqlite')
    add('mcp_server_store.db', kind='sqlite')
    add('file_text_store', kind='directory')
    add('platform_admin_recycle/files', kind='directory')
    out: dict[str, dict] = {}
    for item in candidates:
        rel = str(item.get('path') or '')
        if rel and rel not in out:
            out[rel] = item
    return list(out.values())


def _platform_admin_backup_resolve_target(rel_path: str = '') -> tuple[str, str, str]:
    rel = str(rel_path or '').strip().replace('\\', '/').strip('/')
    if not rel or '..' in rel.split('/'):
        raise ValueError('备份条目路径无效')
    specs = _platform_admin_backup_target_specs()
    exact = next((item for item in specs if str(item.get('path') or '') == rel and str(item.get('kind') or '') != 'directory'), None)
    if exact:
        return str(exact.get('target') or ''), str(exact.get('kind') or 'file'), str(exact.get('path') or '')
    for spec in specs:
        root_rel = str(spec.get('path') or '')
        if str(spec.get('kind') or '') != 'directory' or not rel.startswith(root_rel + '/'):
            continue
        suffix = rel[len(root_rel) + 1:]
        target_root = os.path.abspath(str(spec.get('target') or ''))
        target = os.path.abspath(os.path.join(target_root, *suffix.split('/')))
        if target.startswith(target_root + os.sep):
            return target, 'directory_file', root_rel
    for suffix in ('-wal', '-shm'):
        if rel.endswith(suffix):
            base_rel = rel[:-len(suffix)]
            db = next((item for item in specs if str(item.get('path') or '') == base_rel and str(item.get('kind') or '') == 'sqlite'), None)
            if db:
                return str(db.get('target') or '') + suffix, 'sqlite_sidecar', base_rel
    raise ValueError(f'备份条目不在允许恢复范围内：{rel}')


def _platform_admin_backup_snapshot_file(source: str, target: str, kind: str = 'file') -> None:
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if kind != 'sqlite':
        shutil.copy2(source, target)
        return
    sql = __import__('sqlite3')
    source_conn = sql.connect(source, timeout=30.0)
    target_conn = sql.connect(target, timeout=30.0)
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()


def _platform_admin_backup_stage_snapshot(stage_root: str) -> tuple[list[dict], list[dict]]:
    entries: list[dict] = []
    targets: list[dict] = []
    data_root = os.path.join(stage_root, 'data')
    for spec in _platform_admin_backup_target_specs():
        rel = str(spec.get('path') or '')
        source = str(spec.get('target') or '')
        kind = str(spec.get('kind') or 'file')
        present = os.path.isdir(source) if kind == 'directory' else os.path.isfile(source)
        targets.append({'path': rel, 'kind': kind, 'present': bool(present)})
        if not present:
            continue
        sources: list[tuple[str, str]] = []
        if kind == 'directory':
            for root, dirs, files in os.walk(source):
                dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(root, name))]
                for name in files:
                    file_path = os.path.join(root, name)
                    if os.path.islink(file_path):
                        continue
                    child = os.path.relpath(file_path, source).replace('\\', '/')
                    sources.append((f'{rel}/{child}', file_path))
        else:
            sources.append((rel, source))
        for entry_rel, file_path in sorted(sources):
            staged = os.path.join(data_root, *entry_rel.split('/'))
            _platform_admin_backup_snapshot_file(file_path, staged, kind)
            size = int(os.path.getsize(staged) or 0)
            digest = _platform_admin_sha256_file(staged)
            if not digest:
                raise ValueError(f'无法计算备份文件校验值：{entry_rel}')
            entries.append({'path': entry_rel, 'size_bytes': size, 'sha256': digest})
    return entries, targets


def _platform_admin_sha256_file(path: str = '') -> str:
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ''


def _platform_admin_create_backup(reason: str = '') -> dict:
    zipfile = __import__('zipfile')
    backup_id = 'backup_' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:8]
    root = _platform_admin_backup_dir()
    path = os.path.join(root, backup_id + '.zip')
    tmp = path + '.tmp'
    stage_root = tempfile.mkdtemp(prefix='.backup-stage-', dir=root)
    reason_text = str(reason or 'manual').strip()[:80] or 'manual'
    try:
        entries, targets = _platform_admin_backup_stage_snapshot(stage_root)
        created_at = time.time()
        manifest = {
            'id': backup_id,
            'kind': 'platform_admin_backup',
            'format_version': 2,
            'created_at': created_at,
            'created_at_text': _storage_quota_fmt_ts(created_at),
            'reason': reason_text,
            'note': '备份平台配置、SQLite 一致性快照、索引、全文索引和回收站实体；不包含 uploads/generated 文件实体。',
            'targets': targets,
            'entries': entries,
        }
        with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for entry in entries:
                rel = str(entry.get('path') or '')
                staged = os.path.join(stage_root, 'data', *rel.split('/'))
                zf.write(staged, 'data/' + rel)
            zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(tmp, path)
        size = int(os.path.getsize(path)) if os.path.isfile(path) else 0
        _platform_admin_audit_append('backup_create', backup_id, {'reason': reason_text, 'entries': len(entries), 'size_bytes': size}, ok=True)
        return {'ok': True, 'backup': {**manifest, 'size_bytes': size, 'size_text': _storage_quota_human(size), 'filename': os.path.basename(path)}}
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        _platform_admin_audit_append('backup_create', backup_id, {'reason': reason_text}, ok=False, error=f'{type(e).__name__}: {e}')
        raise
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def _platform_admin_read_backup_manifest(path: str = '') -> dict:
    zipfile = __import__('zipfile')
    try:
        with zipfile.ZipFile(path, 'r') as zf:
            data = json.loads(zf.read('manifest.json').decode('utf-8', errors='replace'))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _platform_admin_backups_payload(query: str = '', *, page: int = 1, page_size: int = 40) -> dict:
    root = _platform_admin_backup_dir()
    rows: list[dict] = []
    for name in os.listdir(root):
        if not name.endswith('.zip'):
            continue
        fp = os.path.join(root, name)
        if not os.path.isfile(fp):
            continue
        manifest = _platform_admin_read_backup_manifest(fp)
        try:
            st = os.stat(fp)
        except Exception:
            continue
        row = {
            'id': str(manifest.get('id') or os.path.splitext(name)[0]),
            'filename': name,
            'reason': str(manifest.get('reason') or ''),
            'note': str(manifest.get('note') or ''),
            'created_at': float(manifest.get('created_at') or st.st_mtime or 0.0),
            'created_at_text': _storage_quota_fmt_ts(float(manifest.get('created_at') or st.st_mtime or 0.0)),
            'entries_count': len(manifest.get('entries') or []),
            'size_bytes': int(st.st_size or 0),
            'size_text': _storage_quota_human(int(st.st_size or 0)),
        }
        rows.append(row)
    rows.sort(key=lambda item: float(item.get('created_at') or 0.0), reverse=True)
    rows = _platform_admin_filter_rows(rows, query)
    total_bytes = sum(int(item.get('size_bytes') or 0) for item in rows)
    page_rows, page_info = _platform_admin_paginate_rows(rows, page=page, page_size=page_size)
    return {
        'ok': True,
        'rows': page_rows,
        'page': page_info,
        'query': str(query or '').strip(),
        'total_bytes': total_bytes,
        'total_text': _storage_quota_human(total_bytes),
    }


def _platform_admin_backup_delete(backup_id: str = '') -> dict:
    backup_id = str(backup_id or '').strip()
    path = _platform_admin_resolve_backup_path(backup_id)
    try:
        size = int(os.path.getsize(path) or 0)
    except Exception:
        size = 0
    try:
        os.remove(path)
        _platform_admin_audit_append('backup_delete', backup_id, {'size_bytes': size}, ok=True)
    except Exception as e:
        _platform_admin_audit_append('backup_delete', backup_id, {'size_bytes': size}, ok=False, error=f'{type(e).__name__}: {e}')
        raise
    return {'ok': True, 'deleted': 1, 'freed_bytes': size, 'freed_text': _storage_quota_human(size), 'backups': _platform_admin_backups_payload(page=1, page_size=40)}


def _platform_admin_backups_clear(query: str = '') -> dict:
    payload = _platform_admin_backups_payload(query=query, page=1, page_size=500)
    rows = list(payload.get('rows') or [])
    deleted = 0
    freed = 0
    errors: list[dict] = []
    for row in rows:
        bid = str((row or {}).get('id') or '').strip()
        if not bid:
            continue
        try:
            path = _platform_admin_resolve_backup_path(bid)
            try:
                size = int(os.path.getsize(path) or 0)
            except Exception:
                size = 0
            os.remove(path)
            deleted += 1
            freed += size
        except Exception as e:
            errors.append({'id': bid, 'error': f'{type(e).__name__}: {e}'})
    ok = not errors
    _platform_admin_audit_append('backup_clear', 'platform_admin_backups', {'deleted': deleted, 'freed_bytes': freed, 'query': str(query or '').strip(), 'errors': errors[:10]}, ok=ok, error='' if ok else f'{len(errors)} 个备份删除失败')
    return {
        'ok': ok or deleted > 0,
        'partial_ok': bool(errors and deleted > 0),
        'deleted': deleted,
        'freed_bytes': freed,
        'freed_text': _storage_quota_human(freed),
        'errors': errors[:20],
        'backups': _platform_admin_backups_payload(page=1, page_size=40),
    }


def _platform_admin_resolve_backup_path(backup_id: str = '') -> str:
    raw = str(backup_id or '').strip()
    if not re.fullmatch(r'backup_[0-9T]{15,16}_[0-9a-fA-F]{8}', raw or ''):
        raise ValueError('备份不存在')
    path = os.path.abspath(os.path.join(_platform_admin_backup_dir(), raw + '.zip'))
    root = os.path.abspath(_platform_admin_backup_dir())
    if not path.startswith(root + os.sep) or not os.path.isfile(path):
        raise ValueError('备份不存在')
    return path


def _platform_admin_restore_stage_archive(backup_path: str, stage_root: str) -> tuple[dict, list[dict], list[str], list[str]]:
    zipfile = __import__('zipfile')
    extracted: list[dict] = []
    restore_roots: list[str] = []
    skipped: list[str] = []
    with zipfile.ZipFile(backup_path, 'r') as zf:
        names = {name for name in zf.namelist() if not name.endswith('/')}
        if 'manifest.json' not in names:
            raise ValueError('备份清单缺失')
        manifest = json.loads(zf.read('manifest.json').decode('utf-8', errors='strict'))
        if not isinstance(manifest, dict) or str(manifest.get('kind') or '') != 'platform_admin_backup':
            raise ValueError('备份清单格式无效')
        entries = manifest.get('entries') if isinstance(manifest.get('entries'), list) else []
        expected_archives: set[str] = set()
        seen: set[str] = set()
        for raw_entry in entries:
            entry = dict(raw_entry or {}) if isinstance(raw_entry, dict) else {}
            if entry.get('error'):
                raise ValueError('备份包含创建失败的条目，不能恢复')
            rel = str(entry.get('path') or '').strip().replace('\\', '/').strip('/')
            if not rel or rel in seen or '..' in rel.split('/'):
                raise ValueError('备份包含无效或重复路径')
            seen.add(rel)
            target, kind, root_rel = _platform_admin_backup_resolve_target(rel)
            arc = 'data/' + rel
            if arc not in names:
                raise ValueError(f'备份文件缺失：{rel}')
            expected_archives.add(arc)
            staged = os.path.abspath(os.path.join(stage_root, 'data', *rel.split('/')))
            data_root = os.path.abspath(os.path.join(stage_root, 'data'))
            if not staged.startswith(data_root + os.sep):
                raise ValueError('备份条目路径越界')
            os.makedirs(os.path.dirname(staged), exist_ok=True)
            h = hashlib.sha256()
            size = 0
            with zf.open(arc, 'r') as source, open(staged, 'wb') as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
            expected_size = int(entry.get('size_bytes') or 0)
            expected_sha = str(entry.get('sha256') or '').strip().lower()
            if size != expected_size or not expected_sha or h.hexdigest().lower() != expected_sha:
                raise ValueError(f'备份校验失败：{rel}')
            if kind == 'sqlite_sidecar':
                skipped.append(rel)
                continue
            extracted.append({'path': rel, 'target': target, 'kind': kind, 'root': root_rel, 'staged': staged})
        unexpected = sorted(name for name in names if name.startswith('data/') and name not in expected_archives)
        if unexpected:
            raise ValueError('备份包含清单之外的数据文件')
        version = int(manifest.get('format_version') or 1)
        if version >= 2:
            targets = manifest.get('targets') if isinstance(manifest.get('targets'), list) else []
            allowed_dirs = {
                str(spec.get('path') or '')
                for spec in _platform_admin_backup_target_specs()
                if str(spec.get('kind') or '') == 'directory'
            }
            for target in targets:
                item = dict(target or {}) if isinstance(target, dict) else {}
                rel = str(item.get('path') or '').strip().replace('\\', '/').strip('/')
                if str(item.get('kind') or '') == 'directory' and bool(item.get('present')):
                    if rel not in allowed_dirs:
                        raise ValueError(f'备份目录不在允许恢复范围内：{rel}')
                    restore_roots.append(rel)
        else:
            restore_roots = sorted({str(item.get('root') or '') for item in extracted if str(item.get('kind') or '') == 'directory_file'})
        for rel in restore_roots:
            os.makedirs(os.path.join(stage_root, 'data', *rel.split('/')), exist_ok=True)
        return manifest, extracted, sorted(set(restore_roots)), skipped


def _platform_admin_restore_remove_path(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)


def _platform_admin_restore_apply(stage_root: str, rollback_root: str, entries: list[dict], restore_roots: list[str]) -> list[str]:
    applied: list[dict] = []
    restored: list[str] = []

    def swap(staged: str, target: str, rel: str) -> None:
        backup = os.path.join(rollback_root, f'{len(applied):04d}')
        had_previous = os.path.lexists(target)
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        op = {'target': target, 'backup': backup, 'had_previous': had_previous, 'rel': rel}
        if had_previous:
            shutil.move(target, backup)
        applied.append(op)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.move(staged, target)
        restored.append(rel)

    try:
        directory_specs = {
            str(spec.get('path') or ''): str(spec.get('target') or '')
            for spec in _platform_admin_backup_target_specs()
            if str(spec.get('kind') or '') == 'directory'
        }
        for rel in restore_roots:
            staged = os.path.join(stage_root, 'data', *rel.split('/'))
            swap(staged, directory_specs[rel], rel + '/')
        directory_root_set = set(restore_roots)
        file_entries = [
            item for item in entries
            if not (str(item.get('kind') or '') == 'directory_file' and str(item.get('root') or '') in directory_root_set)
        ]
        for item in file_entries:
            if str(item.get('kind') or '') != 'sqlite':
                continue
            target = str(item.get('target') or '')
            for suffix in ('-wal', '-shm'):
                sidecar = target + suffix
                if not os.path.lexists(sidecar):
                    continue
                backup = os.path.join(rollback_root, f'{len(applied):04d}')
                op = {'target': sidecar, 'backup': backup, 'had_previous': True, 'rel': str(item.get('path') or '') + suffix}
                shutil.move(sidecar, backup)
                applied.append(op)
        for item in file_entries:
            swap(str(item.get('staged') or ''), str(item.get('target') or ''), str(item.get('path') or ''))
        return restored
    except Exception as apply_error:
        rollback_errors: list[str] = []
        for op in reversed(applied):
            target = str(op.get('target') or '')
            backup = str(op.get('backup') or '')
            try:
                _platform_admin_restore_remove_path(target)
                if bool(op.get('had_previous')) and os.path.lexists(backup):
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.move(backup, target)
            except Exception as rollback_error:
                rollback_errors.append(f"{op.get('rel')}: {type(rollback_error).__name__}: {rollback_error}")
        if rollback_errors:
            raise RuntimeError(f'恢复失败且自动回滚不完整：{type(apply_error).__name__}: {apply_error}; ' + '; '.join(rollback_errors[:5])) from apply_error
        raise


def _platform_admin_refresh_restored_runtime(restored: list[str]) -> list[dict]:
    paths = {str(value or '').rstrip('/') for value in restored}
    hooks: list[tuple[str, str]] = []
    if 'file_registry_store.json' in paths:
        hooks.append(('file_registry', '_file_registry_load'))
    if 'auth_personalization_memory_store.json' in paths:
        hooks.append(('personalization_memory', '_auth_personalization_memory_load'))
    if 'auth_account_profile_store.json' in paths:
        hooks.append(('account_profiles', '_auth_account_profiles_load'))
    if 'auth_chat_store.db' in paths or 'auth_chat_store.json' in paths:
        hooks.append(('chat_store', '_auth_chat_store_load'))
    if 'email_login_store.json' in paths:
        hooks.extend([('email_login', '_email_login_load'), ('auth_users', '_auth_users_load')])
    if 'auth_invite_codes_store.json' in paths:
        hooks.append(('invite_codes', '_auth_invite_codes_load'))
    if 'storage_quota_policy.json' in paths:
        hooks.append(('storage_quota_policy', '_storage_quota_refresh_runtime_policy_globals'))
    if 'image_pullback_jobs.json' in paths:
        hooks.append(('image_pullback', '_image_pullback_load'))
    errors: list[dict] = []
    called: set[str] = set()
    for label, function_name in hooks:
        if function_name in called:
            continue
        called.add(function_name)
        fn = globals().get(function_name)
        if not callable(fn):
            continue
        try:
            fn()
        except Exception as e:
            errors.append({'hook': label, 'error': f'{type(e).__name__}: {e}'})
    if 'image_generation_provider_mirrors.json' in paths:
        try:
            guard = globals().get('_IMAGE_GENERATION_PROVIDER_MIRROR_LOCKS_GUARD')
            done = globals().get('_IMAGE_GENERATION_PROVIDER_MIRROR_DONE')
            status = globals().get('_IMAGE_GENERATION_PROVIDER_MIRROR_STATUS')
            if guard is not None:
                with guard:
                    if isinstance(done, dict):
                        done.clear()
                    if isinstance(status, dict):
                        status.clear()
        except Exception as e:
            errors.append({'hook': 'image_provider_mirrors', 'error': f'{type(e).__name__}: {e}'})
    return errors


def _platform_admin_restore_backup(backup_id: str = '') -> dict:
    backup_path = _platform_admin_resolve_backup_path(backup_id)
    root = _platform_admin_backup_dir()
    stage_root = tempfile.mkdtemp(prefix='.restore-stage-', dir=root)
    rollback_root = tempfile.mkdtemp(prefix='.restore-rollback-', dir=root)
    before: dict = {}
    try:
        manifest, entries, restore_roots, skipped = _platform_admin_restore_stage_archive(backup_path, stage_root)
        before = _platform_admin_create_backup('before_restore_' + str(backup_id or '')[:40])
        restored = _platform_admin_restore_apply(stage_root, rollback_root, entries, restore_roots)
        reload_errors = _platform_admin_refresh_restored_runtime(restored)
        restart_required = bool(restored)
        _platform_admin_audit_append('backup_restore', str(backup_id), {
            'restored': restored,
            'skipped': skipped,
            'reload_errors': reload_errors,
            'before_backup': (before.get('backup') or {}).get('id'),
            'format_version': int(manifest.get('format_version') or 1),
        }, ok=True)
        return {
            'ok': True,
            'restored': restored,
            'skipped': skipped,
            'reload_errors': reload_errors,
            'restart_required': restart_required,
            'before_backup': before.get('backup') or {},
            'backups': _platform_admin_backups_payload(page=1, page_size=40),
        }
    except Exception as e:
        _platform_admin_audit_append('backup_restore', str(backup_id), {'before_backup': (before.get('backup') or {}).get('id')}, ok=False, error=f'{type(e).__name__}: {e}')
        raise
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
        shutil.rmtree(rollback_root, ignore_errors=True)

def _platform_admin_account_detail_payload(
    owner: str = '',
    *,
    section: str = '',
    page: int = 1,
    page_size: int = 12,
) -> dict:
    normalized = _storage_quota_norm_owner(owner or '')
    if not normalized:
        raise ValueError('账号不能为空')
    storage_payload = _storage_quota_admin_state_payload()
    accounts = _platform_admin_enriched_accounts_payload(storage_payload.get('accounts') or [])
    account = next((dict(item) for item in accounts if str(item.get('owner') or '').strip().lower() == normalized), None)
    if account is None:
        account = _storage_quota_owner_breakdown(normalized)
        account.update({'owner': normalized, 'status': '未注册/仅有文件占用', 'status_kind': 'warn'})
    section_key = str(section or '').strip().lower()
    allowed_sections = {'sessions', 'files', 'kb', 'audit'}
    if section_key and section_key not in allowed_sections:
        raise ValueError('账号详情模块无效')
    page = _platform_admin_safe_int(page, 1, minimum=1, maximum=100000)
    page_size = _platform_admin_safe_int(page_size, 12, minimum=10, maximum=50)
    payload = {
        'ok': True,
        'owner': normalized,
        'account': account,
        'section': section_key,
        'updated_at_text': _storage_quota_fmt_ts(time.time()),
    }
    loaders = {
        'sessions': lambda: _platform_admin_chat_sessions_payload(
            normalized,
            page=page,
            page_size=page_size,
        ),
        'files': lambda: _platform_admin_files_payload(
            owner=normalized,
            page=page,
            page_size=page_size,
        ),
        'kb': lambda: _platform_admin_kb_docs_payload(
            owner=normalized,
            page=page,
            page_size=page_size,
        ),
        'audit': lambda: _platform_admin_audit_payload(
            page=page,
            page_size=page_size,
            target=normalized,
        ),
    }
    if section_key:
        payload[section_key] = loaders[section_key]()
    else:
        for key, loader in loaders.items():
            payload[key] = loader()
    return payload


def _platform_admin_account_action(email: str, action: str, reason: str = '', confirm_email: str = '') -> dict:
    normalized = _storage_quota_norm_owner(email or '')
    action_key = str(action or '').strip().lower()
    if action_key == 'purge_guest':
        if not normalized:
            raise ValueError('游客数据归属无效')
        payload = _platform_admin_purge_guest_account(normalized, confirm_email)
        payload['state'] = _platform_admin_state_payload(include_details=True)
        return payload
    if not normalized or '@' not in normalized:
        raise ValueError('账号无效')
    try:
        if action_key in {'enable', 'disable'}:
            fn = globals().get('_auth_user_set_enabled')
            if not callable(fn):
                raise ValueError('账号启停接口不可用')
            user = fn(normalized, action_key == 'enable')
        elif action_key in {'blacklist', 'unblacklist'}:
            fn = globals().get('_auth_user_set_blacklisted')
            if not callable(fn):
                raise ValueError('拉黑接口不可用')
            user = fn(normalized, action_key == 'blacklist', reason or 'admin')
        elif action_key == 'restore_delete':
            fn = globals().get('_auth_user_restore_account')
            if not callable(fn):
                raise ValueError('撤销删除接口不可用')
            user = fn(normalized, actor='admin')
        else:
            raise ValueError('不支持的账号操作')
        _platform_admin_audit_append('account_' + action_key, normalized, {'reason': reason}, ok=True)
    except Exception as e:
        _platform_admin_audit_append('account_' + action_key, normalized, {'reason': reason}, ok=False, error=f'{type(e).__name__}: {e}')
        raise
    public_fn = globals().get('_auth_user_public')
    try:
        public = public_fn(user, include_private=True) if callable(public_fn) else dict(user or {})
    except Exception:
        public = dict(user or {})
    return {'ok': True, 'user': public, 'state': _platform_admin_state_payload(include_details=True)}
