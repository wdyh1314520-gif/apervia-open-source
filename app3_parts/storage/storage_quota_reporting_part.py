# Split from app3_parts/storage/storage_quota_part.py.
# Purpose: quota owner/module reporting, category breakdown, maintenance payloads, and admin state.
# Loaded by storage_quota_part.py via _exec_split_file(...), sharing the original global namespace.

def _storage_quota_known_owner_keys() -> list[str]:
    # 账号目录只显示真实账号或确实拥有数据的游客归属，不制造空占位账号。
    keys: set[str] = set()
    try:
        users_fn = globals().get('_auth_users_public_list')
        if callable(users_fn):
            for item in users_fn(include_private=True) or []:
                key = _storage_quota_owner_key((item or {}).get('email') or '')
                if key:
                    keys.add(key)
    except Exception:
        pass
    try:
        data = _storage_quota_load_owner_index()
        for rec in (data.get('files') or {}).values():
            key = _storage_quota_owner_key((rec or {}).get('owner') or '')
            if key:
                keys.add(key)
    except Exception:
        pass
    try:
        data = _storage_quota_load_account_limits()
        for key in (data.get('limits') or {}).keys():
            owner = _storage_quota_owner_key(key)
            if owner:
                keys.add(owner)
    except Exception:
        pass
    try:
        chat_keys_fn = globals().get('_auth_chat_store_known_emails')
        if callable(chat_keys_fn):
            for key in chat_keys_fn() or []:
                owner = _storage_quota_owner_key(key)
                if owner:
                    keys.add(owner)
    except Exception:
        pass
    try:
        state = globals().get('_AUTH_CHAT_STATE') or {}
        for key in ((state.get('accounts') or {}).keys() if isinstance(state, dict) else []):
            owner = _storage_quota_owner_key(key)
            if owner:
                keys.add(owner)
    except Exception:
        pass
    for state_name, bucket_names, owner_field in (
        ('_AUTH_ACCOUNT_PROFILE_STATE', ('profiles',), ''),
        ('_AUTH_PERSONALIZATION_MEMORY_STATE', ('accounts',), ''),
        ('_CHAT_ASYNC_JOBS', ('',), 'owner_email'),
        ('_AUTH_INVITE_CODES_STATE', ('codes',), 'used_by'),
        ('_AUTH_ACCOUNT_DELETE_LOG_STATE', ('events',), 'email'),
    ):
        try:
            state = globals().get(state_name) or {}
            for bucket_name in bucket_names:
                bucket = state.get(bucket_name) if bucket_name else state
                if isinstance(bucket, dict):
                    rows = bucket.values() if owner_field else bucket.keys()
                else:
                    rows = bucket if isinstance(bucket, list) else []
                for item in rows:
                    if owner_field:
                        owner = _storage_quota_owner_key((item or {}).get(owner_field) or '') if isinstance(item, dict) else ''
                    else:
                        owner = _storage_quota_owner_key(item if isinstance(item, str) else '')
                    if owner:
                        keys.add(owner)
                    elif state_name == '_CHAT_ASYNC_JOBS':
                        keys.add('anonymous')
        except Exception:
            pass
    try:
        kb_conn = globals().get('_kb_db_connect')
        kb_ensure = globals().get('_kb_db_ensure')
        if callable(kb_conn):
            if callable(kb_ensure):
                kb_ensure()
            with kb_conn() as conn:
                for row in conn.execute('SELECT DISTINCT owner_key FROM kb_documents LIMIT 5000').fetchall():
                    try:
                        owner = _storage_quota_owner_key((dict(row) if hasattr(row, 'keys') else {'owner_key': row[0]}).get('owner_key') or '')
                    except Exception:
                        owner = ''
                    if owner:
                        keys.add(owner)
    except Exception:
        pass
    cleaned = [k for k in keys if k]
    cleaned.sort(key=lambda k: (k == 'anonymous', k))
    return cleaned


def _storage_quota_owner_role(owner_key: str) -> str:
    owner = _storage_quota_owner_key(owner_key)
    if owner == 'anonymous':
        return '未识别兜底'
    return '普通账号'


def _storage_quota_owner_breakdown(owner_key: str | None = None) -> dict:
    owner = _storage_quota_owner_key(owner_key)
    tracked = _storage_quota_owner_tracked_bytes(owner)
    kb = _storage_quota_owner_kb_bytes(owner)
    chat = _storage_quota_owner_chat_bytes(owner)
    sandbox = _storage_quota_owner_sandbox_bytes(owner)
    used = max(0, int(tracked or 0) + int(kb or 0) + int(chat or 0) + int(sandbox or 0))
    limit = _storage_quota_owner_limit_bytes(owner)
    default_limit = _storage_quota_default_owner_limit_bytes(owner)
    override = _storage_quota_owner_limit_override_bytes(owner)
    pct = min(999.0, (used / float(limit)) * 100.0) if limit > 0 else 0.0
    return {
        'owner': owner,
        'role': _storage_quota_owner_role(owner),
        'used_bytes': used,
        'limit_bytes': limit,
        'default_limit_bytes': default_limit,
        'override_limit_bytes': override,
        'custom_limit': bool(override > 0),
        'available_bytes': max(0, limit - used),
        'used_text': _storage_quota_human(used),
        'limit_text': _storage_quota_human(limit),
        'default_limit_text': _storage_quota_human(default_limit),
        'available_text': _storage_quota_human(max(0, limit - used)),
        'percent': round(pct, 1),
        'tracked_files_bytes': tracked,
        'knowledge_base_bytes': kb,
        'chat_store_bytes': chat,
        'sandbox_bytes': sandbox,
        'tracked_files_text': _storage_quota_human(tracked),
        'knowledge_base_text': _storage_quota_human(kb),
        'chat_store_text': _storage_quota_human(chat),
        'sandbox_text': _storage_quota_human(sandbox),
    }


def _storage_quota_module_item(key: str, label: str, used: int, limit: int = 0) -> dict:
    used_i = max(0, int(used or 0))
    limit_i = max(0, int(limit or 0))
    pct = round((used_i / float(limit_i)) * 100.0, 1) if limit_i > 0 else 0.0
    return {'key': key, 'label': label, 'used_bytes': used_i, 'limit_bytes': limit_i, 'used_text': _storage_quota_human(used_i), 'limit_text': _storage_quota_human(limit_i) if limit_i > 0 else '未限制', 'percent': pct}


_STORAGE_QUOTA_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg', '.avif', '.heic', '.heif'}


def _storage_quota_count_text(count: int, unit: str, empty: str) -> str:
    try:
        n = max(0, int(count or 0))
    except Exception:
        n = 0
    return f'{n} {unit}' if n > 0 else str(empty or '')


def _storage_quota_owner_tracked_breakdown(owner_key: str | None = None) -> dict:
    owner = _storage_quota_owner_key(owner_key)
    out = {
        'tracked_bytes': 0,
        'tracked_count': 0,
        'image_bytes': 0,
        'image_count': 0,
        'file_bytes': 0,
        'file_count': 0,
    }
    with _STORAGE_QUOTA_LOCK:
        data = _storage_quota_load_owner_index()
        data, changed = _storage_quota_prune_owner_index_locked(data)
        files = data.setdefault('files', {}) if isinstance(data, dict) else {}
        for rec in list((files or {}).values()):
            if not isinstance(rec, dict):
                continue
            if _storage_quota_owner_key(rec.get('owner') or '') != owner:
                continue
            path = str(rec.get('path') or '').strip()
            try:
                size = int(os.path.getsize(path)) if path and os.path.isfile(path) else int(rec.get('size') or 0)
            except Exception:
                size = int(rec.get('size') or 0)
            if size <= 0:
                continue
            filename = str(rec.get('filename') or path or '').strip()
            ext = os.path.splitext(os.path.basename(filename))[1].lower()
            out['tracked_bytes'] += size
            out['tracked_count'] += 1
            if ext in _STORAGE_QUOTA_IMAGE_EXTS:
                out['image_bytes'] += size
                out['image_count'] += 1
            else:
                out['file_bytes'] += size
                out['file_count'] += 1
        if changed:
            try:
                _storage_quota_save_owner_index(data)
            except Exception:
                pass
    return out


def _storage_quota_owner_kb_doc_count(owner_key: str | None = None) -> int:
    owner = _storage_quota_owner_key(owner_key)
    try:
        kb_conn = globals().get('_kb_db_connect')
        if callable(kb_conn):
            with kb_conn() as conn:
                row = conn.execute('SELECT COUNT(1) AS c FROM kb_documents WHERE owner_key=?', (owner,)).fetchone()
                obj = dict(row) if row is not None else {}
                return max(0, int((obj or {}).get('c') or 0))
    except Exception:
        return 0
    return 0


def _storage_quota_owner_chat_session_count(owner_key: str | None = None) -> int:
    owner = _storage_quota_owner_key(owner_key)
    try:
        getter = globals().get('_auth_chat_store_get')
        if callable(getter):
            rec = getter(owner) or {}
            store = rec.get('store') if isinstance(rec.get('store'), dict) else {}
            sessions = store.get('sessions') if isinstance(store.get('sessions'), dict) else {}
            visible_fn = globals().get('_auth_chat_visible_sessions')
            if callable(visible_fn):
                sessions = visible_fn(sessions)
            return len(sessions or {})
    except Exception:
        return 0
    return 0


def _storage_quota_category_item(key: str, label: str, used: int, count: int = 0, *, count_text: str = '', action: str = '') -> dict:
    used_i = max(0, int(used or 0))
    count_i = max(0, int(count or 0))
    return {
        'key': str(key or '').strip(),
        'label': str(label or '').strip(),
        'used_bytes': used_i,
        'used_text': _storage_quota_human(used_i),
        'count': count_i,
        'count_text': str(count_text or '').strip(),
        'action': str(action or '').strip(),
    }


def _storage_quota_owner_storage_space_categories(owner_key: str | None = None) -> list[dict]:
    owner = _storage_quota_owner_key(owner_key)
    tracked = _storage_quota_owner_tracked_breakdown(owner)
    kb_bytes = _storage_quota_owner_kb_bytes(owner)
    kb_docs = _storage_quota_owner_kb_doc_count(owner)
    chat_bytes = _storage_quota_owner_chat_bytes(owner)
    chat_sessions = _storage_quota_owner_chat_session_count(owner)
    sandbox = _storage_quota_owner_sandbox_breakdown(owner)
    sandbox_bytes = max(0, int(sandbox.get('sandbox_bytes') or 0))
    sandbox_sessions = max(0, int(sandbox.get('sandbox_session_count') or 0))
    file_bytes = max(0, int(tracked.get('file_bytes') or 0) + int(kb_bytes or 0))
    file_count = max(0, int(tracked.get('file_count') or 0) + int(kb_docs or 0))
    image_bytes = max(0, int(tracked.get('image_bytes') or 0))
    image_count = max(0, int(tracked.get('image_count') or 0))
    return [
        _storage_quota_category_item('files', '文件', file_bytes, file_count, count_text=_storage_quota_count_text(file_count, '个文件', '暂无文件'), action='library'),
        _storage_quota_category_item('images', '图片', image_bytes, image_count, count_text=_storage_quota_count_text(image_count, '张图片', '暂无图片'), action='library'),
        _storage_quota_category_item('sandboxes', '沙盒', sandbox_bytes, sandbox_sessions, count_text=_storage_quota_count_text(sandbox_sessions, '个会话沙盒', '暂无沙盒'), action='library'),
        _storage_quota_category_item('chats', '聊天数据', chat_bytes, chat_sessions, count_text=_storage_quota_count_text(chat_sessions, '个会话', '暂无会话'), action='backup'),
    ]



try:
    APP_DEFAULTS.setdefault('STORAGE_MAINTENANCE_CHAT_ASYNC_VACUUM_THRESHOLD_BYTES', str(200 * 1024 * 1024))
    APP_DEFAULTS.setdefault('STORAGE_MAINTENANCE_DEEP_MIN_INTERVAL_S', str(24 * 3600))
except Exception:
    pass

_STORAGE_MAINTENANCE_LOCK = threading.Lock()


def _storage_quota_fmt_ts(value) -> str:
    try:
        fmt = globals().get('_fmt_ts')
        if callable(fmt):
            return fmt(value)
    except Exception:
        pass
    try:
        ts = float(value or 0.0)
        if ts <= 0:
            return ''
        return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return ''


def _storage_quota_known_file_item(key: str, label: str, path: str, *, kind: str = 'file', limit_bytes: int = 0, note: str = '') -> dict:
    raw_path = str(path or '').strip()
    used = _storage_quota_sqlite_group_size(raw_path) if kind == 'sqlite' else _storage_quota_file_size(raw_path)
    limit = max(0, int(limit_bytes or 0))
    pct = round((used / float(limit)) * 100.0, 1) if limit > 0 else 0.0
    exists = bool(raw_path and (os.path.exists(raw_path) or any(os.path.exists(raw_path + suffix) for suffix in ('-wal', '-shm'))))
    updated_at = 0.0
    try:
        if os.path.exists(raw_path):
            updated_at = float(os.path.getmtime(raw_path) or 0.0)
    except Exception:
        updated_at = 0.0
    return {
        'key': str(key or '').strip(),
        'label': str(label or key or '').strip(),
        'kind': str(kind or 'file'),
        'path': raw_path,
        'exists': exists,
        'used_bytes': int(used or 0),
        'used_text': _storage_quota_human(used),
        'limit_bytes': limit,
        'limit_text': _storage_quota_human(limit) if limit > 0 else '未设置',
        'percent': pct,
        'updated_at': updated_at,
        'updated_at_text': _storage_quota_fmt_ts(updated_at),
        'note': str(note or '').strip(),
    }


def _storage_quota_chat_async_db_file() -> str:
    return str(globals().get('CHAT_ASYNC_DB_FILE') or _app_data_path('chat_async_jobs.db'))


def _storage_quota_auth_chat_db_file() -> str:
    try:
        fn = globals().get('_auth_chat_db_file_path')
        if callable(fn):
            path = str(fn() or '').strip()
            if path:
                return path
    except Exception:
        pass
    return str(app_getenv('AUTH_CHAT_DB_FILE', _app_data_path('auth_chat_store.db')) or _app_data_path('auth_chat_store.db'))


def _storage_quota_host_fetch_db_file() -> str:
    try:
        fn = globals().get('_host_fetch_db_file_path')
        if callable(fn):
            path = str(fn() or '').strip()
            if path:
                return path
    except Exception:
        pass
    return str(app_getenv('HOST_FETCH_DB_FILE', _app_data_path('host_fetch_state.db')) or _app_data_path('host_fetch_state.db'))


def _storage_quota_maintenance_items_payload() -> list[dict]:
    chat_async_threshold = _storage_quota_int('STORAGE_MAINTENANCE_CHAT_ASYNC_VACUUM_THRESHOLD_BYTES', 200 * 1024 * 1024, minimum=16 * 1024 * 1024)
    kb_file = str(app_getenv('KB_DB_FILE', _app_data_path('knowledge_base.db')) or _app_data_path('knowledge_base.db'))
    items = [
        _storage_quota_known_file_item('chat_async_jobs', '后台聊天任务库', _storage_quota_chat_async_db_file(), kind='sqlite', limit_bytes=chat_async_threshold, note='超过维护阈值时可在空闲时深度压缩'),
        _storage_quota_known_file_item('knowledge_base', '知识库数据库', kb_file, kind='sqlite', limit_bytes=_storage_quota_int('KB_DB_MAX_BYTES', 2 * 1024 * 1024 * 1024, minimum=64 * 1024 * 1024), note='知识库文档与切片'),
        _storage_quota_known_file_item('host_fetch_state', '网页读取状态库', _storage_quota_host_fetch_db_file(), kind='sqlite', note='网页抓取状态与统计'),
        _storage_quota_known_file_item('auth_chat_store', '账号云端会话数据库', _storage_quota_auth_chat_db_file(), kind='sqlite', limit_bytes=_storage_quota_int('AUTH_CHAT_DB_MAX_BYTES', 512 * 1024 * 1024, minimum=64 * 1024 * 1024), note='按账号/会话分表存储'),
        _storage_quota_known_file_item('file_registry_store', '文件索引 JSON', _app_data_path('file_registry_store.json'), limit_bytes=_storage_quota_int('FILE_REGISTRY_MAX_BYTES', 32 * 1024 * 1024, minimum=512 * 1024), note='上传/生成文件索引'),
        _storage_quota_known_file_item('memory_store', '记忆 JSON', _app_data_path('auth_personalization_memory_store.json'), note='账号记忆与历史版本'),
        _storage_quota_known_file_item('image_pullback_jobs', '图片拉回任务 JSON', _app_data_path('image_pullback_jobs.json'), note='图片生成拉回状态'),
    ]
    return items


def _storage_quota_chat_async_idle_payload() -> dict:
    snapshot = {'active': 0, 'waiting': 0, 'limit': 0}
    try:
        snap_fn = globals().get('_chat_async_worker_slot_snapshot')
        if callable(snap_fn):
            raw = snap_fn() or {}
            if isinstance(raw, dict):
                snapshot.update({
                    'active': int(raw.get('active') or 0),
                    'waiting': int(raw.get('waiting') or 0),
                    'limit': int(raw.get('limit') or 0),
                })
    except Exception:
        pass
    not_done = 0
    try:
        lock = globals().get('_CHAT_ASYNC_JOB_LOCK')
        jobs = globals().get('_CHAT_ASYNC_JOBS')
        if isinstance(jobs, dict):
            if lock is not None:
                with lock:
                    not_done = sum(1 for rec in jobs.values() if not bool((rec or {}).get('done')))
            else:
                not_done = sum(1 for rec in jobs.values() if not bool((rec or {}).get('done')))
    except Exception:
        not_done = 0
    idle = bool(snapshot.get('active', 0) <= 0 and snapshot.get('waiting', 0) <= 0 and not_done <= 0)
    return {'idle': idle, 'active': int(snapshot.get('active') or 0), 'waiting': int(snapshot.get('waiting') or 0), 'not_done': int(not_done or 0), 'limit': int(snapshot.get('limit') or 0)}


def _storage_quota_sqlite_maintenance(path: str, *, deep: bool = False) -> dict:
    raw_path = str(path or '').strip()
    before = _storage_quota_sqlite_group_size(raw_path)
    row = {
        'path': raw_path,
        'kind': 'sqlite',
        'deep': bool(deep),
        'before_bytes': before,
        'before_text': _storage_quota_human(before),
        'after_bytes': before,
        'after_text': _storage_quota_human(before),
        'freed_bytes': 0,
        'freed_text': _storage_quota_human(0),
        'ok': False,
        'skipped': False,
    }
    if not raw_path or not os.path.exists(raw_path):
        row.update({'ok': True, 'skipped': True, 'reason': 'not_exists'})
        return row
    sql = __import__('sqlite3')
    conn = None
    try:
        conn = sql.connect(raw_path, timeout=8.0, check_same_thread=False)
        try:
            conn.execute('PRAGMA busy_timeout=8000')
        except Exception:
            pass
        try:
            ck = conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
            row['checkpoint'] = [list(x) for x in ck]
        except Exception as e:
            row['checkpoint_error'] = f'{type(e).__name__}: {e}'
        try:
            conn.execute('PRAGMA optimize')
        except Exception as e:
            row['optimize_error'] = f'{type(e).__name__}: {e}'
        if deep:
            try:
                conn.execute('VACUUM')
                row['vacuum'] = True
            except Exception as e:
                row['vacuum_error'] = f'{type(e).__name__}: {e}'
        try:
            conn.commit()
        except Exception:
            pass
        if deep and not row.get('vacuum_error'):
            try:
                ck_after = conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
                row['checkpoint_after'] = [list(x) for x in ck_after]
            except Exception as e:
                row['checkpoint_after_error'] = f'{type(e).__name__}: {e}'
        row['ok'] = not bool(row.get('vacuum_error'))
    except Exception as e:
        row.update({'ok': False, 'error': f'{type(e).__name__}: {e}'})
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
    # WAL/SHM may still contain the VACUUM output until the connection closes.
    # Measure only after close so the reported release matches final disk use.
    after = _storage_quota_sqlite_group_size(raw_path)
    freed = max(0, before - after)
    row.update({
        'after_bytes': after,
        'after_text': _storage_quota_human(after),
        'freed_bytes': freed,
        'freed_text': _storage_quota_human(freed),
    })
    return row



def _storage_quota_sum_freed_bytes(obj) -> int:
    total = 0
    try:
        if isinstance(obj, dict):
            if 'freed_bytes' in obj:
                try:
                    total += max(0, int(obj.get('freed_bytes') or 0))
                except Exception:
                    pass
            for value in obj.values():
                total += _storage_quota_sum_freed_bytes(value)
        elif isinstance(obj, list):
            for value in obj:
                total += _storage_quota_sum_freed_bytes(value)
    except Exception:
        return total
    return total

def _storage_quota_run_safe_maintenance() -> dict:
    with _STORAGE_MAINTENANCE_LOCK:
        started = time.time()
        cleanup_detail = _storage_quota_cleanup('admin_safe_maintenance')
        expired_jobs = False
        try:
            cleanup_jobs = globals().get('_chat_async_cleanup_expired')
            if callable(cleanup_jobs):
                cleanup_jobs()
                expired_jobs = True
        except Exception:
            expired_jobs = False
        try:
            save_jobs = globals().get('_chat_async_save_persisted_jobs')
            if callable(save_jobs):
                save_jobs(force=True)
        except Exception:
            pass
        sqlite_results = []
        for target in ('chat_async_jobs', 'knowledge_base', 'host_fetch_state'):
            path = ''
            if target == 'chat_async_jobs':
                path = _storage_quota_chat_async_db_file()
            elif target == 'knowledge_base':
                path = str(app_getenv('KB_DB_FILE', _app_data_path('knowledge_base.db')) or _app_data_path('knowledge_base.db'))
            elif target == 'host_fetch_state':
                path = _storage_quota_host_fetch_db_file()
            sqlite_results.append({'target': target, **_storage_quota_sqlite_maintenance(path, deep=False)})
        return {
            'ok': True,
            'mode': 'safe',
            'started_at': started,
            'finished_at': time.time(),
            'cleanup': cleanup_detail,
            'expired_jobs_cleanup_called': expired_jobs,
            'sqlite': sqlite_results,
            'freed_bytes': sum(int((x or {}).get('freed_bytes') or 0) for x in sqlite_results) + _storage_quota_sum_freed_bytes(cleanup_detail),
        }


def _storage_quota_deep_maintenance_targets() -> dict:
    kb_file = str(app_getenv('KB_DB_FILE', _app_data_path('knowledge_base.db')) or _app_data_path('knowledge_base.db'))
    return {
        'chat_async_jobs': {'label': '后台聊天任务库', 'path': _storage_quota_chat_async_db_file(), 'lock_name': '', 'needs_chat_idle': True},
        'knowledge_base': {'label': '知识库数据库', 'path': kb_file, 'lock_name': '_KB_DB_GUARD', 'needs_chat_idle': False},
        'auth_chat_store': {'label': '账号云端会话数据库', 'path': _storage_quota_auth_chat_db_file(), 'lock_name': '_AUTH_CHAT_DB_LOCK', 'needs_chat_idle': False},
        'host_fetch_state': {'label': '网页读取状态库', 'path': _storage_quota_host_fetch_db_file(), 'lock_name': '_HOST_FETCH_DB_GUARD', 'needs_chat_idle': False},
    }


def _storage_quota_run_one_deep_maintenance(target: str, spec: dict) -> dict:
    path = str((spec or {}).get('path') or '').strip()
    lock_name = str((spec or {}).get('lock_name') or '').strip()
    lock = globals().get(lock_name) if lock_name else None
    if lock is not None:
        try:
            with lock:
                result = _storage_quota_sqlite_maintenance(path, deep=True)
        except Exception as e:
            result = {'ok': False, 'error': f'{type(e).__name__}: {e}', 'path': path, 'kind': 'sqlite', 'deep': True}
    else:
        result = _storage_quota_sqlite_maintenance(path, deep=True)
    result.update({
        'target': str(target or '').strip(),
        'label': str((spec or {}).get('label') or target or '').strip(),
    })
    return result


def _storage_quota_run_deep_maintenance(target: str = 'chat_async_jobs', *, force: bool = False) -> dict:
    target = str(target or 'chat_async_jobs').strip() or 'chat_async_jobs'
    targets = _storage_quota_deep_maintenance_targets()
    if target not in targets and target != 'all':
        return {
            'ok': False,
            'error': '未知的深度压缩目标',
            'target': target,
            'available_targets': ['all', *targets.keys()],
        }
    selected = list(targets.keys()) if target == 'all' else [target]
    idle = _storage_quota_chat_async_idle_payload()
    if (not bool(force)) and any(bool((targets.get(k) or {}).get('needs_chat_idle')) for k in selected) and not bool(idle.get('idle')):
        return {'ok': False, 'code': 'not_idle', 'error': '当前还有后台任务或排队任务，稍后再压缩。', 'idle': idle, 'target': target}

    with _STORAGE_MAINTENANCE_LOCK:
        if 'chat_async_jobs' in selected:
            try:
                cleanup_jobs = globals().get('_chat_async_cleanup_expired')
                if callable(cleanup_jobs):
                    cleanup_jobs()
            except Exception:
                pass
            try:
                save_jobs = globals().get('_chat_async_save_persisted_jobs')
                if callable(save_jobs):
                    save_jobs(force=True)
            except Exception:
                pass
        results = [_storage_quota_run_one_deep_maintenance(k, targets[k]) for k in selected]

    freed = sum(max(0, int((item or {}).get('freed_bytes') or 0)) for item in results)
    ok = all(bool((item or {}).get('ok')) for item in results)
    errors = [str((item or {}).get('error') or (item or {}).get('vacuum_error') or '').strip() for item in results if not bool((item or {}).get('ok'))]
    if len(results) == 1:
        result = dict(results[0])
        result.update({'mode': 'deep', 'target': target, 'idle': idle, 'freed_bytes': freed, 'freed_text': _storage_quota_human(freed)})
        return result
    return {
        'ok': ok,
        'mode': 'deep',
        'target': target,
        'idle': idle,
        'results': results,
        'freed_bytes': freed,
        'freed_text': _storage_quota_human(freed),
        'error': '；'.join([x for x in errors if x])[:500] if errors else '',
    }

def _storage_quota_modules_payload() -> list[dict]:
    kb_file = app_getenv('KB_DB_FILE', _app_data_path('knowledge_base.db'))
    return [
        _storage_quota_module_item('uploads_public', '公网上传目录', _storage_quota_dir_size(UPLOAD_DIR_PUBLIC), _storage_quota_int('UPLOAD_DIR_PUBLIC_MAX_BYTES', 1024 * 1024 * 1024, minimum=64 * 1024 * 1024)),
        _storage_quota_module_item('uploads_local', '本地上传目录', _storage_quota_dir_size(UPLOAD_DIR_LOCAL), _storage_quota_int('UPLOAD_DIR_LOCAL_MAX_BYTES', 512 * 1024 * 1024, minimum=64 * 1024 * 1024)),
        _storage_quota_module_item('generated_public', '公网生成文件', _storage_quota_dir_size(GENERATED_DIR_PUBLIC), _storage_quota_int('GENERATED_DIR_PUBLIC_MAX_BYTES', 2 * 1024 * 1024 * 1024, minimum=64 * 1024 * 1024)),
        _storage_quota_module_item('generated_local', '本地生成文件', _storage_quota_dir_size(GENERATED_DIR_LOCAL), _storage_quota_int('GENERATED_DIR_LOCAL_MAX_BYTES', 512 * 1024 * 1024, minimum=64 * 1024 * 1024)),
        _storage_quota_module_item('sandboxes', '沙盒目录', _storage_quota_dir_size(_storage_quota_sandbox_root()), _storage_quota_int('SANDBOX_ROOT_MAX_BYTES', 4 * 1024 * 1024 * 1024, minimum=128 * 1024 * 1024)),
        _storage_quota_module_item('knowledge_base', '知识库总库', _storage_quota_sqlite_group_size(kb_file), _storage_quota_int('KB_DB_MAX_BYTES', 2 * 1024 * 1024 * 1024, minimum=64 * 1024 * 1024)),
        _storage_quota_module_item('upload_chunks', '上传分片临时目录', _storage_quota_dir_size(_app_data_path('upload_chunks')), _storage_quota_int('UPLOAD_CHUNKS_MAX_BYTES', 1024 * 1024 * 1024, minimum=64 * 1024 * 1024)),
        _storage_quota_module_item('auth_chat_backups', '会话备份', _storage_quota_dir_size(_app_data_path('auth_chat_store_backups')), _storage_quota_int('AUTH_CHAT_BACKUP_MAX_BYTES', 512 * 1024 * 1024, minimum=16 * 1024 * 1024)),
        _storage_quota_module_item('file_text_store', '文件全文索引', _storage_quota_dir_size(_app_data_path('file_text_store')), _storage_quota_int('FILE_TEXT_STORE_MAX_BYTES', 1024 * 1024 * 1024, minimum=64 * 1024 * 1024)),
        _storage_quota_module_item('remote_image_cache', '远程图片缓存', _storage_quota_dir_size(app_getenv('REMOTE_IMAGE_CACHE_DIR', REMOTE_IMAGE_CACHE_DIR_DEFAULT)), _storage_quota_int('REMOTE_IMAGE_CACHE_MAX_BYTES', 256 * 1024 * 1024, minimum=16 * 1024 * 1024)),
        _storage_quota_module_item('favicon_cache', '网站图标缓存', _storage_quota_dir_size(_app_data_path('favicon_cache')), _storage_quota_int('FAVICON_CACHE_MAX_BYTES', 32 * 1024 * 1024, minimum=4 * 1024 * 1024)),
        _storage_quota_module_item('chat_async_jobs', '后台聊天任务库', _storage_quota_sqlite_group_size(_storage_quota_chat_async_db_file()), _storage_quota_int('STORAGE_MAINTENANCE_CHAT_ASYNC_VACUUM_THRESHOLD_BYTES', 200 * 1024 * 1024, minimum=16 * 1024 * 1024)),
        _storage_quota_module_item('file_registry_store', '文件索引 JSON', _storage_quota_file_size(_app_data_path('file_registry_store.json')), _storage_quota_int('FILE_REGISTRY_MAX_BYTES', 32 * 1024 * 1024, minimum=512 * 1024)),
        _storage_quota_module_item('auth_chat_store', '账号云端会话库', _storage_quota_sqlite_group_size(_storage_quota_auth_chat_db_file()), _storage_quota_int('AUTH_CHAT_DB_MAX_BYTES', 512 * 1024 * 1024, minimum=64 * 1024 * 1024)),
    ]


def _storage_quota_admin_state_payload() -> dict:
    disk_free = _storage_quota_disk_free(APP_DATA_DIR)
    app_used = _storage_quota_app_used_bytes()
    app_limit = _storage_quota_int('APP_STORAGE_MAX_BYTES', 12 * 1024 * 1024 * 1024, minimum=1024 * 1024 * 1024)
    accounts = [_storage_quota_owner_breakdown(owner) for owner in _storage_quota_known_owner_keys()]
    accounts.sort(key=lambda item: (-int(item.get('used_bytes') or 0), str(item.get('owner') or '')))
    cleanup_free = _storage_quota_int('STORAGE_CLEANUP_FREE_BYTES', 8 * 1024 * 1024 * 1024, minimum=512 * 1024 * 1024)
    min_free = _storage_quota_int('STORAGE_MIN_FREE_BYTES', 5 * 1024 * 1024 * 1024, minimum=512 * 1024 * 1024)
    account_default = _storage_quota_int('ACCOUNT_STORAGE_DEFAULT_MAX_BYTES', 1024 * 1024 * 1024, minimum=128 * 1024 * 1024)
    account_anonymous = _storage_quota_int('ACCOUNT_STORAGE_ANONYMOUS_MAX_BYTES', 128 * 1024 * 1024, minimum=16 * 1024 * 1024)
    kb_owner = _storage_quota_int('KB_OWNER_MAX_BYTES', 512 * 1024 * 1024, minimum=32 * 1024 * 1024)
    return {
        'ok': True,
        'updated_at': time.time(),
        'updated_at_text': _fmt_ts(time.time()) if callable(globals().get('_fmt_ts')) else '',
        'disk': {'free_bytes': disk_free, 'free_text': _storage_quota_human(disk_free), 'cleanup_free_bytes': cleanup_free, 'min_free_bytes': min_free, 'cleanup_free_text': _storage_quota_human(cleanup_free), 'min_free_text': _storage_quota_human(min_free)},
        'app': {'used_bytes': app_used, 'limit_bytes': app_limit, 'available_bytes': max(0, app_limit - app_used), 'used_text': _storage_quota_human(app_used), 'limit_text': _storage_quota_human(app_limit), 'available_text': _storage_quota_human(max(0, app_limit - app_used)), 'percent': round((app_used / float(app_limit)) * 100.0, 1) if app_limit > 0 else 0.0},
        'defaults': {'account_default_bytes': account_default, 'account_anonymous_bytes': account_anonymous, 'kb_owner_bytes': kb_owner, 'account_default_text': _storage_quota_human(account_default), 'account_anonymous_text': _storage_quota_human(account_anonymous), 'kb_owner_text': _storage_quota_human(kb_owner)},
        'modules': _storage_quota_modules_payload(),
        'maintenance': {'items': _storage_quota_maintenance_items_payload(), 'chat_async_idle': _storage_quota_chat_async_idle_payload()},
        'accounts': accounts,
    }
