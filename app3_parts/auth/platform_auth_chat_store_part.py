# chat SQLite/JSON store, account profiles, sync metadata, and sync op merge logic.

def _auth_chat_store_revision_value(rec: dict | None = None) -> int:
    try:
        return max(0, int((rec or {}).get('revision') or 0))
    except Exception:
        return 0


def _auth_chat_normalize_op_id(value) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    raw = re.sub(r'[^0-9A-Za-z_.:-]', '_', raw)
    return raw[:160]


def _auth_chat_normalize_device_id(value) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    raw = re.sub(r'[^0-9A-Za-z_.:-]', '_', raw)
    return raw[:120]


def _auth_chat_prune_applied_ops(applied_ops) -> dict:
    if not isinstance(applied_ops, dict):
        return {}
    rows = []
    for op_id, value in applied_ops.items():
        key = _auth_chat_normalize_op_id(op_id)
        if not key:
            continue
        if isinstance(value, dict):
            try:
                rev = int(value.get('revision') or 0)
            except Exception:
                rev = 0
            try:
                ts = float(value.get('updated_at') or value.get('applied_at') or 0.0)
            except Exception:
                ts = 0.0
            rows.append((rev, ts, key, {'revision': max(0, rev), 'updated_at': ts}))
        else:
            try:
                rev = int(value or 0)
            except Exception:
                rev = 0
            rows.append((rev, 0.0, key, {'revision': max(0, rev), 'updated_at': 0.0}))
    rows.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    keep = rows[:AUTH_CHAT_SYNC_APPLIED_OP_MAX]
    return {key: rec for _rev, _ts, key, rec in keep}


def _auth_chat_prune_ops_log(ops_log) -> list[dict]:
    if not isinstance(ops_log, list) or AUTH_CHAT_SYNC_OPS_LOG_MAX <= 0:
        return []
    rows = []
    for item in ops_log:
        if not isinstance(item, dict):
            continue
        try:
            rev = int(item.get('revision') or 0)
        except Exception:
            rev = 0
        if rev <= 0:
            continue
        op_type = str(item.get('op_type') or item.get('type') or '').strip().lower()[:80]
        if not op_type or op_type in _AUTH_CHAT_SNAPSHOT_OP_TYPES:
            # Snapshot/replace-store operations can contain the full chat store.
            # Do not keep them in the long-term incremental log; pull will fall
            # back to the compact server snapshot when a client is behind.
            continue
        row = dict(item)
        row['revision'] = rev
        row['op_id'] = _auth_chat_normalize_op_id(row.get('op_id') or row.get('id'))
        row['device_id'] = _auth_chat_normalize_device_id(row.get('device_id'))
        row['op_type'] = op_type
        row.pop('_snapshot_omitted', None)
        try:
            row_size = len(json.dumps(row, ensure_ascii=False).encode('utf-8'))
        except Exception:
            row_size = AUTH_CHAT_SYNC_LOG_OP_MAX_BYTES + 1
        if row_size > AUTH_CHAT_SYNC_LOG_OP_MAX_BYTES:
            # Oversized incremental ops are not worth storing. The canonical
            # state remains in store.sessions; clients behind this revision
            # will receive need_snapshot and reload that compact state.
            continue
        rows.append(row)
    rows.sort(key=lambda item: int(item.get('revision') or 0), reverse=True)
    rows = rows[:AUTH_CHAT_SYNC_OPS_LOG_MAX]
    rows.sort(key=lambda item: int(item.get('revision') or 0))
    return rows


def _auth_chat_build_sync_log_op(op: dict, *, op_id: str, device_id: str, op_type: str, revision: int, now_ts: float) -> dict | None:
    normalized_type = str(op_type or '').strip().lower()[:80]
    if not normalized_type or normalized_type in _AUTH_CHAT_SNAPSHOT_OP_TYPES:
        return None
    row = _auth_chat_store_clone(op)
    try:
        payload = row.get('payload') if isinstance(row.get('payload'), dict) else {}
        if isinstance(payload, dict):
            if isinstance(payload.get('session'), dict):
                payload['session'] = _auth_chat_trim_value(payload.get('session'), AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS)
            if isinstance(payload.get('store'), dict):
                payload['store'] = _auth_chat_trim_value(payload.get('store'), AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS)
            row['payload'] = payload
        if isinstance(row.get('session'), dict):
            row['session'] = _auth_chat_trim_value(row.get('session'), AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS)
        if isinstance(row.get('store'), dict):
            row['store'] = _auth_chat_trim_value(row.get('store'), AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS)
    except Exception:
        pass
    row['op_id'] = _auth_chat_normalize_op_id(op_id)
    row['device_id'] = _auth_chat_normalize_device_id(device_id)
    row['op_type'] = normalized_type
    row['revision'] = int(revision or 0)
    row['applied_at'] = float(now_ts or 0.0)
    try:
        row_size = len(json.dumps(row, ensure_ascii=False).encode('utf-8'))
    except Exception:
        row_size = AUTH_CHAT_SYNC_LOG_OP_MAX_BYTES + 1
    if row_size > AUTH_CHAT_SYNC_LOG_OP_MAX_BYTES:
        return None
    return row


def _auth_chat_clean_sync_record(raw_rec: dict | None, email: str = '', *, now_ts: float | None = None) -> tuple[dict | None, bool]:
    obj = dict(raw_rec or {})
    normalized = _normalize_login_email(email or obj.get('email') or '')
    store = obj.get('store')
    if not normalized or '@' not in normalized or not isinstance(store, dict):
        return None, True
    changed = False
    try:
        sanitized_store, sanitized_changed = _sanitize_synced_chat_store(store)
    except Exception:
        return None, True
    changed = changed or bool(sanitized_changed)
    try:
        updated_at = float(obj.get('updated_at') or (now_ts if now_ts is not None else _utc_ts()))
    except Exception:
        updated_at = float(now_ts if now_ts is not None else _utc_ts())
    revision = _auth_chat_store_revision_value(obj)
    sessions = sanitized_store.get('sessions') if isinstance(sanitized_store.get('sessions'), dict) else {}
    visible_sessions = _auth_chat_visible_sessions(sessions)
    tombstones = _auth_chat_deleted_sessions_from_store(sanitized_store)
    if not visible_sessions:
        personalization = sanitized_store.get('personalization') if isinstance(sanitized_store.get('personalization'), dict) else {}
        compact_empty_store = {'sessions': {}, 'activeId': None}
        if personalization:
            compact_empty_store['personalization'] = personalization
        if tombstones:
            compact_empty_store['_deleted_sessions'] = tombstones
        if sanitized_store != compact_empty_store:
            changed = True
        sanitized_store = compact_empty_store
        if tombstones:
            applied_ops = _auth_chat_prune_applied_ops(obj.get('applied_ops') or {})
            ops_log = _auth_chat_prune_ops_log(obj.get('ops_log') or [])
            if len(applied_ops) != len(obj.get('applied_ops') or {}) or len(ops_log) != len(obj.get('ops_log') or []):
                changed = True
        else:
            applied_ops = {}
            ops_log = []
            if obj.get('applied_ops') or obj.get('ops_log'):
                changed = True
    else:
        applied_ops = _auth_chat_prune_applied_ops(obj.get('applied_ops') or {})
        ops_log = _auth_chat_prune_ops_log(obj.get('ops_log') or [])
        if len(applied_ops) != len(obj.get('applied_ops') or {}) or len(ops_log) != len(obj.get('ops_log') or []):
            changed = True
    rec = {
        'email': normalized,
        'store': sanitized_store,
        'updated_at': updated_at,
        'revision': revision,
        'applied_ops': applied_ops,
        'ops_log': ops_log,
    }
    return rec, changed



def _auth_account_profile_trim(value, max_chars: int) -> str:
    text = str(value or '').replace('\r', ' ').replace('\n', ' ').strip()
    text = re.sub(r'\s+', ' ', text)
    return text[:max(1, int(max_chars or 1))].strip()


def _auth_account_profile_avatar_data_url(value) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    match = re.fullmatch(r'data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\s]+)', text, flags=re.IGNORECASE)
    if not match:
        raise ValueError('头像格式不支持，请选择 JPG、PNG 或 WebP 图片')
    encoded = re.sub(r'\s+', '', match.group(2) or '')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError('头像图片数据无效') from exc
    if not raw:
        return ''
    if len(raw) > 768 * 1024:
        raise ValueError('头像图片过大，请选择较小的图片')
    mime = str(match.group(1) or '').lower()
    signatures_ok = (
        (mime == 'image/jpeg' and raw.startswith(b'\xff\xd8\xff'))
        or (mime == 'image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n'))
        or (mime == 'image/webp' and len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP')
    )
    if not signatures_ok:
        raise ValueError('头像图片内容与格式不匹配')
    return f'data:{mime};base64,{base64.b64encode(raw).decode("ascii")}'


AUTH_UI_LANGUAGE_DEFAULT = 'en'
AUTH_UI_LANGUAGES = frozenset({'en', 'zh-CN'})


def _auth_ui_language_normalize(value, *, default: str | None = AUTH_UI_LANGUAGE_DEFAULT) -> str:
    raw = str(value or '').strip().replace('_', '-').lower()
    if raw in {'en', 'en-us', 'en-gb'}:
        return 'en'
    if raw in {'zh', 'zh-cn', 'zh-hans', 'zh-sg'}:
        return 'zh-CN'
    if default is None:
        return ''
    return default if default in AUTH_UI_LANGUAGES else AUTH_UI_LANGUAGE_DEFAULT


def _auth_account_profile_normalize(profile_payload, *, email: str = '', updated_at: float | None = None) -> dict:
    row = dict(profile_payload or {}) if isinstance(profile_payload, dict) else {}
    display_name = _auth_account_profile_trim(
        row.get('display_name') or row.get('displayName') or row.get('name') or '',
        80,
    )
    username = _auth_account_profile_trim(
        row.get('username') or row.get('user_name') or row.get('handle') or '',
        48,
    ).lstrip('@')
    username = re.sub(r'\s+', '', username)[:48]
    avatar_data_url = _auth_account_profile_avatar_data_url(
        row.get('avatar_data_url') or row.get('avatarDataUrl') or row.get('avatar') or '',
    )
    ui_language = _auth_ui_language_normalize(
        row.get('ui_language') or row.get('uiLanguage') or '',
    )
    ts_raw = updated_at if updated_at is not None else row.get('updated_at') or row.get('updatedAt') or 0.0
    try:
        ts = float(ts_raw or 0.0)
    except Exception:
        ts = 0.0
    out = {
        'display_name': display_name,
        'username': username,
        'avatar_data_url': avatar_data_url,
        'ui_language': ui_language,
        'updated_at': ts,
    }
    normalized_email = _normalize_login_email(email or row.get('email') or '')
    if normalized_email:
        out['email'] = normalized_email
    return out


def _auth_account_profile_public(email: str = '', profile_payload=None) -> dict:
    normalized = _normalize_login_email(email)
    profile = _auth_account_profile_normalize(profile_payload, email=normalized)
    display_name = str(profile.get('display_name') or '').strip()
    username = str(profile.get('username') or '').strip()
    avatar_data_url = str(profile.get('avatar_data_url') or '').strip()
    ui_language = _auth_ui_language_normalize(profile.get('ui_language'))
    email_masked = _mask_login_email(normalized) if normalized else ''
    return {
        'display_name': display_name,
        'username': username,
        'avatar_data_url': avatar_data_url,
        'ui_language': ui_language,
        'email': normalized,
        'email_masked': email_masked,
        'has_custom_profile': bool(display_name or username or avatar_data_url),
        'updated_at': _fmt_ts(profile.get('updated_at')),
        'updated_ts': float(profile.get('updated_at') or 0.0),
    }


def _auth_account_profiles_load() -> None:
    state = {'profiles': {}, 'updated_at': _utc_ts()}
    try:
        if os.path.exists(AUTH_ACCOUNT_PROFILE_FILE):
            with open(AUTH_ACCOUNT_PROFILE_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f) or {}
            if isinstance(loaded, dict):
                profiles = loaded.get('profiles') or {}
                if isinstance(profiles, dict):
                    clean = {}
                    for email, rec in profiles.items():
                        normalized = _normalize_login_email(email or (rec or {}).get('email') or '')
                        if not normalized:
                            continue
                        clean[normalized] = _auth_account_profile_normalize(rec, email=normalized)
                    state['profiles'] = clean
                try:
                    state['updated_at'] = float(loaded.get('updated_at') or _utc_ts())
                except Exception:
                    state['updated_at'] = _utc_ts()
    except Exception:
        app_logger.exception('[auth_account_profile] load_failed')
    with _AUTH_ACCOUNT_PROFILE_LOCK:
        _AUTH_ACCOUNT_PROFILE_STATE.clear()
        _AUTH_ACCOUNT_PROFILE_STATE.update(state)


def _auth_account_profiles_save() -> None:
    with _AUTH_ACCOUNT_PROFILE_LOCK:
        payload = {
            'profiles': _AUTH_ACCOUNT_PROFILE_STATE.get('profiles') or {},
            'updated_at': _utc_ts(),
        }
        _AUTH_ACCOUNT_PROFILE_STATE['updated_at'] = payload['updated_at']
    tmp = AUTH_ACCOUNT_PROFILE_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, AUTH_ACCOUNT_PROFILE_FILE)
    except Exception:
        app_logger.exception('[auth_account_profile] save_failed')
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _auth_account_profiles_payload_size(profiles, updated_at: float | None = None) -> int:
    payload = {
        'profiles': profiles if isinstance(profiles, dict) else {},
        'updated_at': float(updated_at if updated_at is not None else _utc_ts()),
    }
    return len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def _auth_account_profile_get(email: str) -> dict:
    normalized = _normalize_login_email(email)
    if not normalized:
        return {}
    with _AUTH_ACCOUNT_PROFILE_LOCK:
        rec = dict((_AUTH_ACCOUNT_PROFILE_STATE.get('profiles') or {}).get(normalized) or {})
    return _auth_account_profile_normalize(rec, email=normalized)


def _auth_account_profile_set(email: str, profile_payload) -> dict:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        raise ValueError('未找到登录账号')
    now_ts = _utc_ts()
    payload = dict(profile_payload or {}) if isinstance(profile_payload, dict) else {}
    with _AUTH_ACCOUNT_PROFILE_LOCK:
        profiles = _AUTH_ACCOUNT_PROFILE_STATE.setdefault('profiles', {})
        current = dict(profiles.get(normalized) or {})
        if 'ui_language' not in payload and 'uiLanguage' not in payload:
            payload['ui_language'] = current.get('ui_language') or AUTH_UI_LANGUAGE_DEFAULT
        profile = _auth_account_profile_normalize(payload, email=normalized, updated_at=now_ts)
        current_size = _auth_account_profiles_payload_size(profiles, now_ts)
        next_profiles = dict(profiles)
        if (
            profile.get('display_name')
            or profile.get('username')
            or profile.get('avatar_data_url')
            or profile.get('ui_language') != AUTH_UI_LANGUAGE_DEFAULT
        ):
            next_profiles[normalized] = profile
        else:
            next_profiles.pop(normalized, None)
        next_size = _auth_account_profiles_payload_size(next_profiles, now_ts)
        if next_size > AUTH_ACCOUNT_PROFILE_MAX_BYTES and next_size > current_size:
            raise ValueError('账号头像资料存储已达到全局上限，请先清理或缩小头像')
        profiles.clear()
        profiles.update(next_profiles)
        _AUTH_ACCOUNT_PROFILE_STATE['updated_at'] = now_ts
    _auth_account_profiles_save()
    return profile


def _auth_account_ui_language_set(email: str, language) -> dict:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        raise ValueError('未找到登录账号')
    requested = _auth_ui_language_normalize(language, default=None)
    if requested not in AUTH_UI_LANGUAGES:
        raise ValueError('界面语言无效')
    current = _auth_account_profile_get(normalized)
    current['ui_language'] = requested
    return _auth_account_profile_set(normalized, current)


def _auth_account_profile_delete(email: str) -> bool:
    normalized = _normalize_login_email(email)
    if not normalized:
        return False
    removed = False
    now_ts = _utc_ts()
    with _AUTH_ACCOUNT_PROFILE_LOCK:
        profiles = _AUTH_ACCOUNT_PROFILE_STATE.setdefault('profiles', {})
        if normalized in profiles:
            profiles.pop(normalized, None)
            _AUTH_ACCOUNT_PROFILE_STATE['updated_at'] = now_ts
            removed = True
    if removed:
        _auth_account_profiles_save()
    return removed

def _auth_chat_json_clone(value):
    try:
        return json.loads(json.dumps(value if value is not None else {}, ensure_ascii=False))
    except Exception:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, list):
            return list(value)
        return value


def _auth_chat_db_file_path() -> str:
    raw = str(app_getenv('AUTH_CHAT_DB_FILE', AUTH_CHAT_DB_FILE) or '').strip()
    return raw or AUTH_CHAT_DB_FILE


def _auth_chat_sqlite_module():
    return __import__('sqlite3')


def _auth_chat_db_connect():
    sql = _auth_chat_sqlite_module()
    path = _auth_chat_db_file_path()
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sql.connect(path, timeout=30.0, check_same_thread=False)
    try:
        conn.row_factory = sql.Row
    except Exception:
        pass
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except Exception:
        pass
    try:
        conn.execute('PRAGMA synchronous=NORMAL')
    except Exception:
        pass
    return conn


def _auth_chat_db_ensure() -> None:
    if getattr(_auth_chat_db_ensure, '_ready', False):
        return
    with _AUTH_CHAT_DB_LOCK:
        if getattr(_auth_chat_db_ensure, '_ready', False):
            return
        conn = _auth_chat_db_connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS auth_chat_accounts (
                    email TEXT PRIMARY KEY,
                    active_id TEXT DEFAULT '',
                    personalization_json TEXT DEFAULT '',
                    store_meta_json TEXT DEFAULT '',
                    updated_at REAL DEFAULT 0,
                    revision INTEGER DEFAULT 0,
                    applied_ops_json TEXT DEFAULT '',
                    ops_log_json TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS auth_chat_sessions (
                    email TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    session_json TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    updated_at REAL DEFAULT 0,
                    created_at REAL DEFAULT 0,
                    deleted INTEGER DEFAULT 0,
                    message_count INTEGER DEFAULT 0,
                    PRIMARY KEY (email, session_id)
                )
            """)
            conn.execute('CREATE INDEX IF NOT EXISTS idx_auth_chat_sessions_email_updated ON auth_chat_sessions(email, updated_at DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_auth_chat_sessions_updated ON auth_chat_sessions(updated_at DESC)')
            conn.commit()
            setattr(_auth_chat_db_ensure, '_ready', True)
        finally:
            conn.close()


def _auth_chat_db_json_load(text: str = '', fallback=None):
    raw = str(text or '').strip()
    if not raw:
        return {} if fallback is None else fallback
    try:
        obj = json.loads(raw)
        return obj if obj is not None else ({} if fallback is None else fallback)
    except Exception:
        return {} if fallback is None else fallback


def _auth_chat_db_json_dump(obj) -> str:
    try:
        return json.dumps(obj if obj is not None else {}, ensure_ascii=False, separators=(',', ':'))
    except Exception:
        return '{}'


def _auth_chat_db_session_ts(session_obj: dict, *keys: str) -> float:
    if not isinstance(session_obj, dict):
        return 0.0
    for key in keys:
        try:
            value = session_obj.get(key)
            if value is None or value == '':
                continue
            return float(value)
        except Exception:
            continue
    return 0.0


def _auth_chat_db_record_from_rows(account_row, session_rows) -> dict:
    try:
        acc = dict(account_row)
    except Exception:
        acc = account_row if isinstance(account_row, dict) else {}
    email = _normalize_login_email(acc.get('email') or '')
    store_meta = _auth_chat_db_json_load(acc.get('store_meta_json') or '', {})
    store = dict(store_meta) if isinstance(store_meta, dict) else {}
    sessions: dict[str, dict] = {}
    for row in session_rows or []:
        try:
            item = dict(row)
        except Exception:
            item = row if isinstance(row, dict) else {}
        sid = str(item.get('session_id') or '').strip()
        sess = _auth_chat_db_json_load(item.get('session_json') or '', {})
        if not sid or not isinstance(sess, dict):
            continue
        sess['id'] = str(sess.get('id') or sid).strip() or sid
        sessions[sid] = sess
    store['sessions'] = sessions
    active_id = str(acc.get('active_id') or '').strip()
    store['activeId'] = active_id if active_id else (next(iter(sessions.keys()), '') if sessions else None)
    personalization = _auth_chat_db_json_load(acc.get('personalization_json') or '', {})
    if isinstance(personalization, dict) and personalization:
        store['personalization'] = personalization
    rec = {
        'email': email,
        'store': store,
        'updated_at': float(acc.get('updated_at') or 0.0),
        'revision': int(acc.get('revision') or 0),
        'applied_ops': _auth_chat_db_json_load(acc.get('applied_ops_json') or '', {}),
        'ops_log': _auth_chat_db_json_load(acc.get('ops_log_json') or '', []),
    }
    return rec


def _auth_chat_db_get_record(email: str) -> dict | None:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        return None
    _auth_chat_db_ensure()
    conn = _auth_chat_db_connect()
    try:
        row = conn.execute('SELECT * FROM auth_chat_accounts WHERE email=? LIMIT 1', (normalized,)).fetchone()
        if row is None:
            return None
        sessions = conn.execute('SELECT * FROM auth_chat_sessions WHERE email=? ORDER BY updated_at DESC, created_at DESC, session_id', (normalized,)).fetchall()
        rec = _auth_chat_db_record_from_rows(row, sessions)
        clean_rec, changed = _auth_chat_clean_sync_record(rec, email=normalized, now_ts=_utc_ts())
        if clean_rec and changed:
            try:
                _auth_chat_db_upsert_record(clean_rec, conn=conn, commit=True)
            except Exception:
                pass
        return clean_rec or rec
    except Exception:
        app_logger.exception('[auth_chat_store_db] get_failed email=%s', normalized)
        return None
    finally:
        conn.close()


def _auth_chat_db_list_records() -> dict[str, dict]:
    _auth_chat_db_ensure()
    conn = _auth_chat_db_connect()
    out: dict[str, dict] = {}
    try:
        rows = conn.execute('SELECT * FROM auth_chat_accounts ORDER BY updated_at DESC, email').fetchall()
        for row in rows or []:
            try:
                email = _normalize_login_email((dict(row)).get('email') or '')
            except Exception:
                email = ''
            if not email:
                continue
            sessions = conn.execute('SELECT * FROM auth_chat_sessions WHERE email=? ORDER BY updated_at DESC, created_at DESC, session_id', (email,)).fetchall()
            rec = _auth_chat_db_record_from_rows(row, sessions)
            clean_rec, changed = _auth_chat_clean_sync_record(rec, email=email, now_ts=_utc_ts())
            if clean_rec:
                out[email] = clean_rec
                if changed:
                    try:
                        _auth_chat_db_upsert_record(clean_rec, conn=conn, commit=False)
                    except Exception:
                        pass
        try:
            conn.commit()
        except Exception:
            pass
    except Exception:
        app_logger.exception('[auth_chat_store_db] list_failed')
    finally:
        conn.close()
    return out


def _auth_chat_db_upsert_record(rec: dict | None = None, *, conn=None, commit: bool = True) -> bool:
    if not isinstance(rec, dict):
        return False
    normalized = _normalize_login_email(rec.get('email') or '')
    if not normalized or '@' not in normalized:
        return False
    clean_rec, _clean_changed = _auth_chat_clean_sync_record(rec, email=normalized, now_ts=rec.get('updated_at') or _utc_ts())
    if clean_rec:
        rec = clean_rec
    _auth_chat_db_ensure()
    own_conn = conn is None
    conn = conn or _auth_chat_db_connect()
    try:
        store = _auth_chat_json_clone(rec.get('store') if isinstance(rec.get('store'), dict) else {})
        if not isinstance(store, dict):
            store = {}
        sessions = store.get('sessions') if isinstance(store.get('sessions'), dict) else {}
        active_id = str(store.get('activeId') or store.get('active_id') or '').strip()
        personalization = store.get('personalization') if isinstance(store.get('personalization'), dict) else {}
        store_meta = _auth_chat_json_clone(store)
        if isinstance(store_meta, dict):
            store_meta.pop('sessions', None)
            store_meta.pop('activeId', None)
            store_meta.pop('active_id', None)
            store_meta.pop('personalization', None)
        else:
            store_meta = {}
        updated_at = float(rec.get('updated_at') or _utc_ts())
        revision = int(rec.get('revision') or 0)
        conn.execute(
            """INSERT INTO auth_chat_accounts
               (email, active_id, personalization_json, store_meta_json, updated_at, revision, applied_ops_json, ops_log_json)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(email) DO UPDATE SET
                 active_id=excluded.active_id,
                 personalization_json=excluded.personalization_json,
                 store_meta_json=excluded.store_meta_json,
                 updated_at=excluded.updated_at,
                 revision=excluded.revision,
                 applied_ops_json=excluded.applied_ops_json,
                 ops_log_json=excluded.ops_log_json""",
            (
                normalized,
                active_id,
                _auth_chat_db_json_dump(personalization if isinstance(personalization, dict) else {}),
                _auth_chat_db_json_dump(store_meta),
                updated_at,
                revision,
                _auth_chat_db_json_dump(rec.get('applied_ops') if isinstance(rec.get('applied_ops'), dict) else {}),
                _auth_chat_db_json_dump(rec.get('ops_log') if isinstance(rec.get('ops_log'), list) else []),
            ),
        )
        kept: set[str] = set()
        for raw_sid, raw_session in (sessions or {}).items():
            sid = str(raw_sid or '').strip()
            if not sid or not isinstance(raw_session, dict):
                continue
            sess = _auth_chat_json_clone(raw_session)
            if not isinstance(sess, dict):
                continue
            sess['id'] = str(sess.get('id') or sid).strip() or sid
            kept.add(sid)
            messages = sess.get('messages') if isinstance(sess.get('messages'), list) else []
            conn.execute(
                """INSERT INTO auth_chat_sessions
                   (email, session_id, session_json, title, model, updated_at, created_at, deleted, message_count)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(email, session_id) DO UPDATE SET
                     session_json=excluded.session_json,
                     title=excluded.title,
                     model=excluded.model,
                     updated_at=excluded.updated_at,
                     created_at=excluded.created_at,
                     deleted=excluded.deleted,
                     message_count=excluded.message_count""",
                (
                    normalized,
                    sid,
                    _auth_chat_db_json_dump(sess),
                    str(sess.get('title') or sess.get('name') or '新会话')[:260],
                    str(sess.get('model') or '')[:160],
                    _auth_chat_db_session_ts(sess, 'updatedAt', 'updated_at', 'lastUpdated', 'createdAt', 'created_at'),
                    _auth_chat_db_session_ts(sess, 'createdAt', 'created_at', 'updatedAt', 'updated_at'),
                    1 if _auth_chat_session_deleted(sess) else 0,
                    len(messages),
                ),
            )
        if kept:
            placeholders = ','.join('?' for _ in kept)
            conn.execute(f'DELETE FROM auth_chat_sessions WHERE email=? AND session_id NOT IN ({placeholders})', (normalized, *sorted(kept)))
        else:
            conn.execute('DELETE FROM auth_chat_sessions WHERE email=?', (normalized,))
        if commit:
            conn.commit()
        return True
    except Exception:
        if commit:
            try:
                conn.rollback()
            except Exception:
                pass
        app_logger.exception('[auth_chat_store_db] upsert_failed email=%s', normalized)
        return False
    finally:
        if own_conn:
            conn.close()


def _auth_chat_db_delete_record(email: str) -> bool:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        return False
    _auth_chat_db_ensure()
    conn = _auth_chat_db_connect()
    try:
        cur = conn.execute('DELETE FROM auth_chat_accounts WHERE email=?', (normalized,))
        conn.execute('DELETE FROM auth_chat_sessions WHERE email=?', (normalized,))
        conn.commit()
        return bool(cur.rowcount and cur.rowcount > 0)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        app_logger.exception('[auth_chat_store_db] delete_failed email=%s', normalized)
        return False
    finally:
        conn.close()


def _auth_chat_store_known_emails() -> list[str]:
    records = _auth_chat_db_list_records()
    keys = set(records.keys())
    try:
        with _AUTH_CHAT_LOCK:
            keys.update((_AUTH_CHAT_STATE.get('accounts') or {}).keys())
    except Exception:
        pass
    out = [_normalize_login_email(k) for k in keys if _normalize_login_email(k)]
    out.sort()
    return out


def _auth_chat_store_account_bytes(email: str) -> int:
    normalized = _normalize_login_email(email)
    if not normalized:
        return 0
    try:
        rec = _auth_chat_db_get_record(normalized) or {}
        store = rec.get('store') if isinstance(rec.get('store'), dict) else {}
        sessions = store.get('sessions') if isinstance(store.get('sessions'), dict) else {}
        visible_sessions = _auth_chat_visible_sessions(sessions)
        if not visible_sessions:
            return 0
        store_meta = _auth_chat_json_clone(store)
        if isinstance(store_meta, dict):
            store_meta.pop('sessions', None)
        else:
            store_meta = {}
        total = len(_auth_chat_db_json_dump({
            'active_id': store.get('activeId') or store.get('active_id') or '',
            'store_meta': store_meta,
            'revision': int(rec.get('revision') or 0),
        }).encode('utf-8', 'ignore'))
        for session in visible_sessions.values():
            try:
                total += len(_auth_chat_db_json_dump(session).encode('utf-8', 'ignore'))
            except Exception:
                pass
        return max(0, int(total))
    except Exception:
        return 0


def _auth_chat_store_load_legacy_json() -> tuple[dict, bool]:
    state = {'accounts': {}, 'updated_at': _utc_ts()}
    changed = False
    try:
        if os.path.exists(AUTH_CHAT_STORE_FILE):
            with open(AUTH_CHAT_STORE_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f) or {}
            if isinstance(loaded, dict):
                accounts = loaded.get('accounts') or {}
                if isinstance(accounts, dict):
                    clean = {}
                    for email, rec in accounts.items():
                        clean_rec, rec_changed = _auth_chat_clean_sync_record(dict(rec or {}), email=email, now_ts=_utc_ts())
                        if not clean_rec:
                            changed = True
                            continue
                        clean[clean_rec['email']] = clean_rec
                        if rec_changed:
                            changed = True
                    state['accounts'] = clean
                try:
                    state['updated_at'] = float(loaded.get('updated_at') or _utc_ts())
                except Exception:
                    state['updated_at'] = _utc_ts()
    except Exception:
        app_logger.exception('[auth_chat_store] legacy_load_failed')
    return state, changed


def _auth_chat_store_load() -> None:
    state = {'accounts': {}, 'updated_at': _utc_ts()}
    changed = False
    try:
        _auth_chat_db_ensure()
        db_accounts = _auth_chat_db_list_records()
        state['accounts'] = db_accounts
        if db_accounts:
            try:
                state['updated_at'] = max([float((rec or {}).get('updated_at') or 0.0) for rec in db_accounts.values()] + [_utc_ts()])
            except Exception:
                state['updated_at'] = _utc_ts()
        legacy_state, legacy_changed = _auth_chat_store_load_legacy_json()
        legacy_accounts = legacy_state.get('accounts') if isinstance(legacy_state.get('accounts'), dict) else {}
        migrated = False
        for email, rec in legacy_accounts.items():
            normalized = _normalize_login_email(email)
            if not normalized or normalized in state['accounts']:
                continue
            if _auth_chat_db_upsert_record(rec):
                state['accounts'][normalized] = rec
                migrated = True
        if migrated:
            state['updated_at'] = _utc_ts()
            try:
                app_logger.info('[auth_chat_store] migrated_legacy_json_to_sqlite accounts=%s', len(legacy_accounts))
            except Exception:
                pass
        changed = bool(legacy_changed or migrated)
    except Exception:
        app_logger.exception('[auth_chat_store] load_failed')
        try:
            legacy_state, changed = _auth_chat_store_load_legacy_json()
            state = legacy_state
        except Exception:
            state = {'accounts': {}, 'updated_at': _utc_ts()}
            changed = False
    with _AUTH_CHAT_LOCK:
        _AUTH_CHAT_STATE.clear()
        _AUTH_CHAT_STATE.update(state)
    if changed:
        try:
            _auth_chat_store_save()
        except Exception:
            app_logger.exception('[auth_chat_store] normalize_save_failed')



def _auth_chat_store_save() -> None:
    with _AUTH_CHAT_LOCK:
        accounts = dict((_AUTH_CHAT_STATE.get('accounts') or {}) if isinstance(_AUTH_CHAT_STATE.get('accounts'), dict) else {})
        _AUTH_CHAT_STATE['updated_at'] = _utc_ts()
    try:
        _auth_chat_db_ensure()
        conn = _auth_chat_db_connect()
        try:
            for rec in accounts.values():
                if isinstance(rec, dict):
                    _auth_chat_db_upsert_record(rec, conn=conn, commit=False)
            conn.commit()
        finally:
            conn.close()
    except Exception:
        app_logger.exception('[auth_chat_store] sqlite_save_failed')



def _auth_chat_store_get(email: str) -> dict | None:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        return None
    rec = _auth_chat_db_get_record(normalized)
    if rec:
        with _AUTH_CHAT_LOCK:
            _AUTH_CHAT_STATE.setdefault('accounts', {})[normalized] = rec
            _AUTH_CHAT_STATE['updated_at'] = max(float(_AUTH_CHAT_STATE.get('updated_at') or 0.0), float(rec.get('updated_at') or 0.0))
        try:
            return json.loads(json.dumps(rec, ensure_ascii=False))
        except Exception:
            return dict(rec)
    with _AUTH_CHAT_LOCK:
        rec = (_AUTH_CHAT_STATE.get('accounts') or {}).get(normalized)
        if not rec:
            return None
        try:
            return json.loads(json.dumps(rec, ensure_ascii=False))
        except Exception:
            return dict(rec)


def _auth_chat_store_delete(email: str) -> bool:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        return False
    removed = False
    now_ts = _utc_ts()
    with _AUTH_CHAT_LOCK:
        accounts = _AUTH_CHAT_STATE.setdefault('accounts', {})
        existing = accounts.get(normalized) or _auth_chat_db_get_record(normalized)
        if existing:
            try:
                _auth_chat_store_backup_record(normalized, existing, reason='account_delete')
            except Exception:
                app_logger.exception('[auth_account_delete] chat_backup_failed email=%s', normalized)
            accounts.pop(normalized, None)
            _AUTH_CHAT_STATE['updated_at'] = now_ts
            removed = True
    db_removed = _auth_chat_db_delete_record(normalized)
    return bool(removed or db_removed)


def _auth_chat_store_set(email: str, store_payload) -> tuple[dict, bool]:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        raise ValueError('未找到登录账号')
    clean_store, store_changed = _sanitize_synced_chat_store(store_payload)
    now_ts = _utc_ts()
    with _AUTH_CHAT_LOCK:
        accounts = _AUTH_CHAT_STATE.setdefault('accounts', {})
        prev = dict(_auth_chat_db_get_record(normalized) or accounts.get(normalized) or {})
        revision = _auth_chat_store_revision_value(prev) + 1
        applied_ops = _auth_chat_prune_applied_ops(prev.get('applied_ops') or {})
        ops_log = []
        rec = {
            'email': normalized,
            'store': clean_store,
            'updated_at': now_ts,
            'revision': revision,
            'applied_ops': applied_ops,
            'ops_log': ops_log,
        }
        accounts[normalized] = rec
        _AUTH_CHAT_STATE['updated_at'] = now_ts
    _auth_chat_db_upsert_record(rec)
    return (_auth_chat_store_get(normalized) or {}), bool(store_changed)



def _auth_chat_store_clone(store_payload) -> dict:
    try:
        return json.loads(json.dumps(store_payload or {}, ensure_ascii=False))
    except Exception:
        return dict(store_payload or {})


def _auth_chat_message_identity_key(message) -> str:
    if not isinstance(message, dict):
        return ''
    for key in ('_client_msg_id', 'client_msg_id', 'clientMessageId'):
        raw = str(message.get(key) or '').strip()
        if raw:
            return 'client:' + raw[:220]
    return ''


def _auth_chat_normalize_message_sync_metadata(message: dict | None, *, session_id: str = '', mode: str = '', revision: int = 0) -> dict:
    msg = _auth_chat_store_clone(message if isinstance(message, dict) else {})
    normalized_mode = _auth_chat_normalize_conversation_mode(mode or msg.get('conversationMode') or msg.get('conversation_mode') or '')
    identity = _auth_chat_message_identity_key(msg)
    raw_identity = identity[7:] if identity.startswith('client:') else identity
    if not raw_identity:
        role = re.sub(r'[^0-9A-Za-z_.:-]+', '_', str(msg.get('role') or 'msg'))[:24] or 'msg'
        created = int(_auth_chat_safe_float(msg.get('created_at_ms') or msg.get('createdAtMs') or msg.get('created_at') or msg.get('createdAt') or _auth_chat_ms_from_ts()))
        sid = re.sub(r'[^0-9A-Za-z_.:-]+', '_', str(session_id or ''))[:48]
        raw_identity = f"msg_{sid}_{role}_{created}_{uuid.uuid4().hex[:10]}"[:220]
        msg['_client_msg_id'] = raw_identity
    local_id = str(msg.get('localId') or msg.get('local_id') or msg.get('messageLocalId') or msg.get('message_local_id') or raw_identity).strip()
    msg['localId'] = local_id
    msg['local_id'] = local_id
    msg['messageLocalId'] = local_id
    msg['message_local_id'] = local_id
    op_id = str(msg.get('opId') or msg.get('op_id') or msg.get('messageOpId') or msg.get('message_op_id') or '').strip()
    if not op_id:
        role = str(msg.get('role') or '').strip().lower()
        prefix = 'append_assistant_message' if role == 'assistant' else 'append_message'
        op_id = f"{prefix}:{local_id}"[:220]
    msg['opId'] = op_id
    msg['op_id'] = op_id
    msg['messageOpId'] = op_id
    msg['message_op_id'] = op_id
    msg['conversationMode'] = normalized_mode
    msg['conversation_mode'] = normalized_mode
    server_version = max(
        int(revision or 0),
        int(_auth_chat_safe_float(msg.get('serverVersion') or msg.get('server_version') or (msg.get('messageRecovery') if isinstance(msg.get('messageRecovery'), dict) else {}).get('server_version') or 0)),
    )
    if server_version > 0:
        msg['serverVersion'] = server_version
        msg['server_version'] = server_version
    status = str(msg.get('syncStatus') or msg.get('sync_status') or (msg.get('messageRecovery') if isinstance(msg.get('messageRecovery'), dict) else {}).get('status') or '').strip().lower()
    role = str(msg.get('role') or '').strip().lower()
    if status in {'pending', 'sending'} and server_version > 0:
        status = 'complete' if role == 'assistant' else 'sent'
    if status not in {'pending', 'sending', 'streaming', 'complete', 'sent', 'failed', 'failed_retryable', 'server_owned_inflight'}:
        status = ('complete' if role == 'assistant' else 'sent') if server_version > 0 else ('pending' if role == 'assistant' else 'sending')
    msg['syncStatus'] = status
    msg['sync_status'] = status
    recovery = msg.get('messageRecovery') if isinstance(msg.get('messageRecovery'), dict) else {}
    msg['messageRecovery'] = {
        **recovery,
        'mode': normalized_mode,
        'local_id': local_id,
        'op_id': op_id,
        'server_version': server_version,
        'status': status,
        'created_at': _auth_chat_safe_float(msg.get('created_at_ms') or msg.get('createdAtMs') or msg.get('created_at') or msg.get('createdAt') or _auth_chat_ms_from_ts()),
    }
    return msg


def _auth_chat_message_has_protected_local_state(message: dict | None) -> bool:
    if not isinstance(message, dict):
        return False
    recovery = message.get('messageRecovery') if isinstance(message.get('messageRecovery'), dict) else {}
    status = str(message.get('syncStatus') or message.get('sync_status') or recovery.get('status') or '').strip().lower()
    return status in {'pending', 'sending', 'streaming', 'failed_retryable', 'server_owned_inflight'}


def _auth_chat_merge_message_sync_metadata(target: dict, source: dict, *, mode: str = '', revision: int = 0) -> bool:
    if not isinstance(target, dict) or not isinstance(source, dict):
        return False
    before = _auth_chat_message_fingerprint({
        'syncStatus': target.get('syncStatus'),
        'serverVersion': target.get('serverVersion'),
        'messageRecovery': target.get('messageRecovery'),
    })
    src = _auth_chat_normalize_message_sync_metadata(source, mode=mode, revision=revision)
    target_version = int(_auth_chat_safe_float(target.get('serverVersion') or target.get('server_version') or 0))
    source_version = int(_auth_chat_safe_float(src.get('serverVersion') or src.get('server_version') or 0))
    for key in ('localId', 'local_id', 'messageLocalId', 'message_local_id', 'opId', 'op_id', 'messageOpId', 'message_op_id', 'conversationMode', 'conversation_mode'):
        if target.get(key) in (None, '', [], {}) and src.get(key) not in (None, '', [], {}):
            target[key] = src.get(key)
    if source_version > target_version:
        target['serverVersion'] = source_version
        target['server_version'] = source_version
        if not _auth_chat_message_has_protected_local_state(target) or str(target.get('syncStatus') or '').lower() in {'pending', 'sending'}:
            target['syncStatus'] = 'complete' if str(target.get('role') or src.get('role') or '').lower() == 'assistant' else 'sent'
            target['sync_status'] = target['syncStatus']
    elif not _auth_chat_message_has_protected_local_state(target) and src.get('syncStatus'):
        target['syncStatus'] = src.get('syncStatus')
        target['sync_status'] = src.get('sync_status') or src.get('syncStatus')
    if isinstance(src.get('messageRecovery'), dict):
        target_recovery = target.get('messageRecovery') if isinstance(target.get('messageRecovery'), dict) else {}
        target['messageRecovery'] = {**target_recovery, **src.get('messageRecovery')}
    return before != _auth_chat_message_fingerprint({
        'syncStatus': target.get('syncStatus'),
        'serverVersion': target.get('serverVersion'),
        'messageRecovery': target.get('messageRecovery'),
    })




def _auth_chat_cloud_body_text_hash(text: str) -> str:
    raw = str(text or '')
    h1 = 0x811C9DC5
    h2 = 0x27D4EB2D
    for ch in raw:
        c = ord(ch)
        h1 ^= c
        h1 = (h1 * 16777619) & 0xFFFFFFFF
        h2 = ((h2 ^ c) * 2246822519) & 0xFFFFFFFF
    return f"{h1:08x}{h2:08x}:{len(raw)}"[:80]


def _auth_chat_find_message_index_by_identity(messages, identity: str) -> int:
    ident = str(identity or '').strip()
    if not ident or not isinstance(messages, list):
        return -1
    client_ident = ident if ident.startswith('client:') else f'client:{ident}'
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        if _auth_chat_message_identity_key(msg) == client_ident:
            return idx
        for key in ('_client_msg_id', 'client_msg_id', 'clientMessageId'):
            if str(msg.get(key) or '').strip() == ident:
                return idx
    return -1


def _auth_chat_apply_message_body_chunk_to_session(session: dict, payload: dict) -> tuple[dict, bool]:
    current = _auth_chat_store_clone(session if isinstance(session, dict) else {})
    if not isinstance(current.get('messages'), list):
        current['messages'] = []
    p = payload if isinstance(payload, dict) else {}
    identity = str(p.get('message_identity') or p.get('messageIdentity') or '').strip()
    field = str(p.get('field') or 'content').strip() or 'content'
    if field not in {'content', 'reasoning', 'process'}:
        field = 'content'
    try:
        chunk_index = int(p.get('chunk_index') if p.get('chunk_index') is not None else p.get('chunkIndex'))
        chunk_count = int(p.get('chunk_count') if p.get('chunk_count') is not None else p.get('chunkCount'))
    except Exception:
        raise ValueError('同步正文分块序号不正确')
    if not identity or chunk_index < 0 or chunk_count <= 0 or chunk_index >= chunk_count:
        raise ValueError('同步正文分块参数不正确')
    chunk_text = str(p.get('chunk_text') if p.get('chunk_text') is not None else p.get('text') or '')
    # Keep every chunk comfortably below the per-field trim limit.  The full body is authoritative in cloud chunks,
    # not in a single oversized message.content string.
    chunk_text_limit = max(8000, AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS - 128) if AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS > 0 else 2 * 1024 * 1024
    if len(chunk_text) > chunk_text_limit:
        raise ValueError('同步正文分块过大，请稍后重试')
    idx = _auth_chat_find_message_index_by_identity(current.get('messages'), identity)
    if idx < 0:
        seed = p.get('message_seed') if isinstance(p.get('message_seed'), dict) else None
        if seed:
            seed_obj = _auth_chat_store_clone(seed)
            seed_obj['_client_msg_id'] = str(seed_obj.get('_client_msg_id') or seed_obj.get('client_msg_id') or identity).strip()[:220]
            current['messages'].append(seed_obj)
            idx = len(current['messages']) - 1
        else:
            # Chunk ops may arrive after the placeholder in the same batch. If the placeholder is missing, make the op
            # idempotent instead of failing the whole sync batch.
            return current, False
    msg = _auth_chat_store_clone(current['messages'][idx] if isinstance(current['messages'][idx], dict) else {})
    body = msg.get('__cloud_sync_body') if isinstance(msg.get('__cloud_sync_body'), dict) else {}
    state = body.get(field) if isinstance(body.get(field), dict) else {}
    chunks = state.get('chunks') if isinstance(state.get('chunks'), list) else []
    if len(chunks) < chunk_count:
        chunks = list(chunks) + [None] * (chunk_count - len(chunks))
    before = chunks[chunk_index] if chunk_index < len(chunks) else None
    chunks[chunk_index] = chunk_text
    received = sum(1 for item in chunks[:chunk_count] if isinstance(item, str))
    text_hash = str(p.get('text_hash') or p.get('textHash') or state.get('hash') or '').strip()
    try:
        text_length = int(p.get('text_length') if p.get('text_length') is not None else p.get('textLength') or state.get('length') or 0)
    except Exception:
        text_length = 0
    state.update({
        'version': 1,
        'field': field,
        'mode': 'chunks',
        'chunk_count': chunk_count,
        'received_count': received,
        'length': text_length,
        'hash': text_hash,
        'chunks': chunks,
        'complete': received >= chunk_count,
    })
    if state.get('complete'):
        full_text = ''.join(chunks[:chunk_count])
        if text_length > 0 and len(full_text) != text_length:
            state['complete'] = False
        elif text_hash and _auth_chat_cloud_body_text_hash(full_text) != text_hash:
            state['complete'] = False
        # Do not persist a giant single content string. Cross-device clients rehydrate content from these cloud chunks.
    body[field] = state
    msg['__cloud_sync_body'] = body
    current['messages'][idx] = msg
    return current, before != chunk_text

def _auth_chat_user_text_key(message) -> str:
    if not isinstance(message, dict) or str(message.get('role') or '').strip().lower() != 'user':
        return ''
    content = message.get('content')
    text = ''
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and str(item.get('type') or '') == 'text':
                raw = str(item.get('text') or '').strip()
                if raw:
                    parts.append(raw)
        text = '\n'.join(parts)
    elif isinstance(content, dict):
        text = str(content.get('text') or content.get('filename') or content.get('name') or '').strip()
    text = re.sub(r'\s+', ' ', str(text or '')).strip()[:260]
    if not text:
        return ''
    try:
        ts = int(float(message.get('created_at_ms') or message.get('createdAtMs') or message.get('createdAt') or message.get('created_at') or 0) // 1000)
    except Exception:
        ts = 0
    return f'usertext:{ts}:{text}'


def _auth_chat_user_image_parts(message) -> list:
    if not isinstance(message, dict):
        return []
    content = message.get('content')
    if not isinstance(content, list):
        return []
    return [item for item in content if isinstance(item, dict) and str(item.get('type') or '') == 'image_url']


def _auth_chat_user_file_attachment_rows(message) -> list:
    if not isinstance(message, dict):
        return []
    rows = []
    for key in ('file_attachments', 'attachments', '_composer_file_attachments', 'files'):
        value = message.get(key)
        if isinstance(value, list):
            rows.extend([item for item in value if isinstance(item, dict)])
    content = message.get('content')
    if isinstance(content, dict) and str(content.get('_kind') or '') == 'file':
        rows.append(content)
    return rows


def _auth_chat_user_attachment_score(message) -> int:
    if not isinstance(message, dict) or str(message.get('role') or '').strip().lower() != 'user':
        return 0
    score = 0
    content = message.get('content')
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or str(item.get('type') or '') != 'image_url':
                continue
            score += 4
            img = item.get('image_url') if isinstance(item.get('image_url'), dict) else {}
            values = [
                img.get('url') if isinstance(img, dict) else '',
                item.get('preview_url'), item.get('view_url'), item.get('download_url'),
                item.get('persisted_url'), item.get('server_url'), item.get('storage_ref'),
                item.get('model_storage_ref'), item.get('file_library_id'), item.get('library_file_id'),
            ]
            if any(str(v or '').strip() for v in values):
                score += 2
    elif isinstance(content, dict):
        if str(content.get('_kind') or '') in {'file', 'image'}:
            score += 6
    rows = _auth_chat_user_file_attachment_rows(message)
    if rows:
        score += len(rows) * 5
    return score


def _auth_chat_same_user_attachment_identity(left, right) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    lk = _auth_chat_message_identity_key(left)
    rk = _auth_chat_message_identity_key(right)
    if lk and rk and lk == rk:
        return True
    lt = _auth_chat_user_text_key(left)
    rt = _auth_chat_user_text_key(right)
    return bool(lt and rt and lt == rt)


def _auth_chat_merge_user_attachments_into(target, source) -> bool:
    if not isinstance(target, dict) or not isinstance(source, dict):
        return False
    if str(target.get('role') or '').strip().lower() != 'user' or str(source.get('role') or '').strip().lower() != 'user':
        return False
    if not _auth_chat_same_user_attachment_identity(target, source):
        return False
    source_score = _auth_chat_user_attachment_score(source)
    if source_score <= 0:
        return False
    target_score = _auth_chat_user_attachment_score(target)
    changed = False
    source_images = _auth_chat_user_image_parts(source)
    target_images = _auth_chat_user_image_parts(target)
    source_content = source.get('content')
    if source_images and (len(source_images) > len(target_images) or source_score > target_score):
        target['content'] = _auth_chat_store_clone(source_content)
        changed = True
    elif isinstance(source_content, dict) and source_score > target_score:
        target['content'] = _auth_chat_store_clone(source_content)
        changed = True
    for key in ('file_attachments', 'attachments', '_composer_file_attachments'):
        src = source.get(key) if isinstance(source.get(key), list) else []
        dst = target.get(key) if isinstance(target.get(key), list) else []
        if src and (not dst or len(src) > len(dst)):
            target[key] = _auth_chat_store_clone(src)
            changed = True
    return changed


def _auth_chat_preserve_user_attachments_in_messages(target_messages, source_messages) -> list:
    target = _auth_chat_store_clone(target_messages if isinstance(target_messages, list) else [])
    source = source_messages if isinstance(source_messages, list) else []
    if not target or not source:
        return target
    by_identity = {}
    by_text = {}
    for msg in source:
        if not isinstance(msg, dict) or str(msg.get('role') or '').strip().lower() != 'user':
            continue
        if _auth_chat_user_attachment_score(msg) <= 0:
            continue
        ik = _auth_chat_message_identity_key(msg)
        if ik and ik not in by_identity:
            by_identity[ik] = msg
        tk = _auth_chat_user_text_key(msg)
        if tk and tk not in by_text:
            by_text[tk] = msg
    for msg in target:
        if not isinstance(msg, dict) or str(msg.get('role') or '').strip().lower() != 'user':
            continue
        src = by_identity.get(_auth_chat_message_identity_key(msg)) or by_text.get(_auth_chat_user_text_key(msg))
        if src:
            _auth_chat_merge_user_attachments_into(msg, src)
    return target


def _auth_chat_message_fingerprint(message) -> str:
    try:
        return json.dumps(message if message is not None else None, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    except Exception:
        return str(message or '')


class _AuthChatSyncConflict(ValueError):
    def __init__(self, session_id: str = '', op_type: str = '', reason: str = 'cloud_conflict_refresh_required'):
        super().__init__(reason)
        self.session_id = str(session_id or '').strip()
        self.op_type = str(op_type or '').strip().lower()
        self.reason = str(reason or 'cloud_conflict_refresh_required')

    def public_payload(self) -> dict:
        return {
            'session_id': self.session_id,
            'op_type': self.op_type,
            'reason': self.reason,
        }


def _auth_chat_message_list_has_prefix(base_messages, candidate_messages) -> bool:
    base = base_messages if isinstance(base_messages, list) else []
    candidate = candidate_messages if isinstance(candidate_messages, list) else []
    if len(candidate) < len(base):
        return False
    for idx, msg in enumerate(base):
        if _auth_chat_message_fingerprint(msg) != _auth_chat_message_fingerprint(candidate[idx]):
            return False
    return True


def _auth_chat_merge_message_lists(existing_messages, incoming_messages) -> list:
    existing = [
        _auth_chat_normalize_message_sync_metadata(msg) if isinstance(msg, dict) else msg
        for msg in _auth_chat_store_clone(existing_messages if isinstance(existing_messages, list) else [])
    ]
    incoming = [
        _auth_chat_normalize_message_sync_metadata(msg) if isinstance(msg, dict) else msg
        for msg in _auth_chat_store_clone(incoming_messages if isinstance(incoming_messages, list) else [])
    ]
    if not existing:
        return incoming
    if not incoming:
        return existing
    if _auth_chat_message_list_has_prefix(existing, incoming):
        return _auth_chat_preserve_user_attachments_in_messages(incoming, existing)
    if _auth_chat_message_list_has_prefix(incoming, existing):
        return _auth_chat_preserve_user_attachments_in_messages(existing, incoming)
    seen = {_auth_chat_message_fingerprint(msg) for msg in existing}
    seen_identity = {_auth_chat_message_identity_key(msg) for msg in existing if _auth_chat_message_identity_key(msg)}
    merged = list(existing)
    for msg in incoming:
        identity_key = _auth_chat_message_identity_key(msg)
        if identity_key and identity_key in seen_identity:
            for existing_msg in merged:
                if _auth_chat_message_identity_key(existing_msg) == identity_key:
                    _auth_chat_merge_user_attachments_into(existing_msg, msg)
                    _auth_chat_merge_message_sync_metadata(existing_msg, msg)
                    break
            continue
        key = _auth_chat_message_fingerprint(msg)
        if key in seen:
            continue
        seen.add(key)
        if identity_key:
            seen_identity.add(identity_key)
        merged.append(msg)
    return _auth_chat_preserve_user_attachments_in_messages(merged, incoming)


def _auth_chat_payload_base_guard_matches(payload: dict, current_session: dict | None) -> bool:
    if not isinstance(current_session, dict):
        return True
    messages = current_session.get('messages') if isinstance(current_session.get('messages'), list) else []
    try:
        expected_count = int((payload or {}).get('base_message_count') or 0)
    except Exception:
        expected_count = -1
    expected_fingerprint = str((payload or {}).get('base_message_fingerprint') or '').strip()
    expected_identity = str((payload or {}).get('base_message_identity') or '').strip()
    if expected_count < 0 or expected_count != len(messages):
        return False
    if expected_count <= 0:
        return True
    last = messages[-1] if messages else None
    if expected_identity and expected_identity == _auth_chat_message_identity_key(last):
        return True
    if expected_fingerprint and expected_fingerprint == _auth_chat_message_fingerprint(last):
        return True
    return False


def _auth_chat_incoming_session_safe_for_stale_upsert(existing_session: dict | None, incoming_session: dict | None) -> bool:
    if not isinstance(existing_session, dict) or not isinstance(incoming_session, dict):
        return True
    existing_messages = existing_session.get('messages') if isinstance(existing_session.get('messages'), list) else []
    incoming_messages = incoming_session.get('messages') if isinstance(incoming_session.get('messages'), list) else []
    if not existing_messages:
        return True
    if not incoming_messages:
        return False
    return _auth_chat_message_list_has_prefix(existing_messages, incoming_messages)


def _auth_chat_store_equal(a, b) -> bool:
    try:
        return json.dumps(a, ensure_ascii=False, sort_keys=True, separators=(',', ':')) == json.dumps(b, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    except Exception:
        return a == b


def _auth_chat_normalize_conversation_mode(value: str | None = None, fallback: str = '') -> str:
    raw = str(value or '').strip().lower().replace('-', '_').replace(' ', '_')
    if raw in {'response', 'responses', '/responses'}:
        return 'response'
    if raw in {'chat', 'chat_completion', 'chat_completions', 'completions'}:
        return 'chat'
    if fallback:
        return _auth_chat_normalize_conversation_mode(fallback)
    return 'chat'


def _auth_chat_session_mode(session: dict | None = None, fallback: str = '') -> str:
    row = session if isinstance(session, dict) else {}
    explicit = row.get('conversationMode') or row.get('conversation_mode') or row.get('syncMode') or row.get('sync_mode')
    if explicit:
        return _auth_chat_normalize_conversation_mode(explicit, fallback)
    endpoint = row.get('api_endpoint_mode') or row.get('endpoint_mode') or row.get('apiEndpointMode') or row.get('endpointMode')
    return _auth_chat_normalize_conversation_mode(endpoint, fallback)


def _auth_chat_normalize_session_sync_metadata(session: dict | None, sid: str, *, op: dict | None = None, revision: int = 0) -> dict:
    row = _auth_chat_store_clone(session if isinstance(session, dict) else {})
    session_id = str(sid or row.get('id') or '').strip()
    if session_id:
        row['id'] = session_id
    mode = _auth_chat_session_mode(row)
    endpoint_mode = 'responses' if mode == 'response' else 'chat_completions'
    row['conversationMode'] = mode
    row['conversation_mode'] = mode
    row['api_endpoint_mode'] = str(row.get('api_endpoint_mode') or row.get('endpoint_mode') or endpoint_mode).strip() or endpoint_mode
    row['endpoint_mode'] = str(row.get('endpoint_mode') or row.get('api_endpoint_mode') or endpoint_mode).strip() or endpoint_mode
    local_id = str(row.get('localId') or row.get('local_id') or session_id or '').strip()
    if not local_id:
        local_id = 'local_' + uuid.uuid4().hex
    row['localId'] = local_id
    row['local_id'] = local_id
    op_obj = op if isinstance(op, dict) else {}
    op_id = str(row.get('opId') or row.get('op_id') or op_obj.get('op_id') or op_obj.get('id') or '').strip()
    if not op_id:
        op_id = f"conversation:{local_id}"
    row['opId'] = op_id
    row['op_id'] = op_id
    server_version = max(
        int(revision or 0),
        int(_auth_chat_safe_float(row.get('serverVersion') or row.get('server_version') or row.get('_cloudRevision') or 0)),
    )
    row['serverVersion'] = server_version
    row['server_version'] = server_version
    status = str(row.get('syncStatus') or row.get('sync_status') or '').strip().lower()
    if status in {'pending', 'sending'} and server_version > 0:
        status = 'active'
    if status not in {'pending', 'sending', 'generating', 'server_owned_inflight', 'failed_retryable', 'failed_final', 'active', 'archived', 'deleted', 'auth_suspended'}:
        status = 'active' if server_version > 0 else 'pending'
    row['syncStatus'] = status
    row['sync_status'] = status
    recovery = row.get('conversationRecovery') if isinstance(row.get('conversationRecovery'), dict) else {}
    updated_at = _auth_chat_safe_float(row.get('updatedAt') or row.get('updated_at') or row.get('createdAt') or row.get('created_at') or _auth_chat_ms_from_ts())
    row['conversationRecovery'] = {
        **recovery,
        'mode': mode,
        'local_id': local_id,
        'server_id': session_id,
        'op_id': op_id,
        'server_version': server_version,
        'status': status,
        'updated_at': updated_at,
    }
    run_recovery = row.get('runRecovery') if isinstance(row.get('runRecovery'), dict) else None
    if isinstance(run_recovery, dict):
        run_recovery = dict(run_recovery)
        run_recovery['mode'] = _auth_chat_normalize_conversation_mode(run_recovery.get('mode'), mode)
        run_recovery['conversation_id'] = str(run_recovery.get('conversation_id') or session_id)
        run_recovery['conversation_local_id'] = str(run_recovery.get('conversation_local_id') or local_id)
        row['runRecovery'] = run_recovery
    return row


def _auth_chat_merge_upsert_session(existing_session, incoming_session: dict, sid: str) -> dict:
    incoming = _auth_chat_normalize_session_sync_metadata(incoming_session if isinstance(incoming_session, dict) else {}, sid)
    incoming['id'] = str(incoming.get('id') or sid).strip() or sid
    if not isinstance(existing_session, dict):
        mode = _auth_chat_session_mode(incoming)
        server_version = int(_auth_chat_safe_float(incoming.get('serverVersion') or incoming.get('server_version') or 0))
        if isinstance(incoming.get('messages'), list):
            incoming['messages'] = [
                _auth_chat_normalize_message_sync_metadata(msg, session_id=sid, mode=mode, revision=server_version)
                if isinstance(msg, dict) else msg
                for msg in incoming.get('messages')
            ]
        return incoming
    existing = _auth_chat_normalize_session_sync_metadata(existing_session, sid)
    existing['id'] = str(existing.get('id') or sid).strip() or sid
    incoming_deleted = _auth_chat_session_deleted(incoming)
    existing_deleted = _auth_chat_session_deleted(existing)
    incoming_updated = _auth_chat_safe_float(incoming.get('updatedAt') or incoming.get('updated_at') or incoming.get('createdAt') or incoming.get('created_at') or 0.0)
    existing_updated = _auth_chat_safe_float(existing.get('updatedAt') or existing.get('updated_at') or existing.get('createdAt') or existing.get('created_at') or 0.0)
    if existing_deleted and not incoming_deleted and incoming_updated <= existing_updated:
        return existing
    if incoming_deleted and incoming_updated >= existing_updated:
        return incoming
    if incoming_updated >= existing_updated:
        merged = dict(existing)
        for key, value in incoming.items():
            if key == 'messages':
                continue
            merged[key] = value
    else:
        merged = dict(existing)
        for key, value in incoming.items():
            if key in {'id', 'messages'}:
                continue
            if key not in merged or merged.get(key) in (None, '', [], {}):
                merged[key] = value
    if incoming_updated or existing_updated:
        merged['updatedAt'] = max(incoming_updated, existing_updated)
    merged['id'] = sid
    merged_messages = _auth_chat_merge_message_lists(existing.get('messages'), incoming.get('messages'))
    mode = _auth_chat_session_mode(merged)
    server_version = int(_auth_chat_safe_float(merged.get('serverVersion') or merged.get('server_version') or 0))
    merged['messages'] = [
        _auth_chat_normalize_message_sync_metadata(msg, session_id=sid, mode=mode, revision=server_version)
        if isinstance(msg, dict) else msg
        for msg in merged_messages
    ]
    return merged


def _auth_chat_apply_sync_op(base_store, op_payload, *, client_base_revision: int = 0, server_revision: int = 0) -> tuple[dict, bool]:
    op = dict(op_payload or {})
    op_type = str(op.get('op_type') or op.get('type') or '').strip().lower()
    payload = op.get('payload') if isinstance(op.get('payload'), dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    store_obj = _auth_chat_store_clone(base_store if isinstance(base_store, dict) else {})

    if op_type in {'replace_store', 'snapshot', 'store_snapshot'}:
        op_type = 'merge_store_snapshot'

    if op_type == 'merge_store_snapshot':
        incoming = payload.get('store') if isinstance(payload.get('store'), dict) else op.get('store')
        if not isinstance(incoming, dict):
            raise ValueError('同步操作缺少会话快照')
        existing_sessions = store_obj.get('sessions') if isinstance(store_obj.get('sessions'), dict) else {}
        if existing_sessions or int(server_revision or 0) > 0:
            raise _AuthChatSyncConflict('', op_type, 'snapshot_push_disabled_refresh_required')
        before = _auth_chat_store_clone(store_obj)
        merged = store_obj
        merged_sessions = merged.get('sessions') if isinstance(merged.get('sessions'), dict) else {}
        incoming_sessions = incoming.get('sessions') if isinstance(incoming.get('sessions'), dict) else {}
        if not incoming_sessions and merged_sessions:
            return merged, False
        for sid, session in incoming_sessions.items():
            sid = str(sid or '').strip()
            if not sid or not isinstance(session, dict):
                continue
            old_session = merged_sessions.get(sid) if isinstance(merged_sessions.get(sid), dict) else {}
            merged_sessions[sid] = _auth_chat_trim_value(
                _auth_chat_merge_upsert_session(old_session, session, sid),
                AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS,
            )
        merged['sessions'] = merged_sessions
        incoming_active = str(incoming.get('activeId') or '').strip()
        if not str(merged.get('activeId') or '').strip() and incoming_active and incoming_active in merged_sessions:
            merged['activeId'] = incoming_active
        elif not str(merged.get('activeId') or '').strip() and merged_sessions:
            merged['activeId'] = next(iter(merged_sessions.keys()), '')
        if isinstance(incoming.get('personalization'), dict):
            merged['personalization'] = _auth_chat_trim_value(incoming.get('personalization'), AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS)
        return merged, not _auth_chat_store_equal(before, merged)

    sessions = store_obj.get('sessions')
    if not isinstance(sessions, dict):
        sessions = {}
        store_obj['sessions'] = sessions
    active_id = str(store_obj.get('activeId') or '').strip()

    if op_type == 'upsert_session':
        session = payload.get('session') if isinstance(payload.get('session'), dict) else op.get('session')
        if not isinstance(session, dict):
            raise ValueError('同步操作缺少会话内容')
        sid = str(op.get('session_id') or payload.get('session_id') or session.get('id') or '').strip()
        if not sid:
            raise ValueError('同步操作缺少会话 ID')
        if _auth_chat_session_is_tombstoned_for_client(store_obj, sid, client_base_revision):
            return store_obj, False
        session_obj = _auth_chat_trim_value(session, AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS)
        if not isinstance(session_obj, dict):
            raise ValueError('同步操作会话格式不正确')
        session_obj = _auth_chat_normalize_session_sync_metadata(session_obj, sid, op=op, revision=int(server_revision or 0) + 1)
        current_session = sessions.get(sid) if isinstance(sessions.get(sid), dict) else None
        if current_session is not None and int(client_base_revision or 0) < int(server_revision or 0):
            if not _auth_chat_incoming_session_safe_for_stale_upsert(current_session, session_obj):
                raise _AuthChatSyncConflict(sid, op_type, 'cloud_session_changed_refresh_required')
        sessions[sid] = _auth_chat_trim_value(
            _auth_chat_merge_upsert_session(current_session, session_obj, sid),
            AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS,
        )
        if not active_id or active_id not in sessions:
            store_obj['activeId'] = sid
        return store_obj, True

    if op_type == 'append_messages':
        sid = str(op.get('session_id') or payload.get('session_id') or '').strip()
        if not sid:
            raise ValueError('同步操作缺少会话 ID')
        if _auth_chat_session_is_tombstoned_for_client(store_obj, sid, client_base_revision):
            return store_obj, False
        messages_to_add = payload.get('messages') if isinstance(payload.get('messages'), list) else []
        if not messages_to_add:
            raise ValueError('同步操作缺少新增消息')
        current_session = sessions.get(sid) if isinstance(sessions.get(sid), dict) else None
        if current_session is not None and int(client_base_revision or 0) < int(server_revision or 0):
            if not _auth_chat_payload_base_guard_matches(payload, current_session):
                raise _AuthChatSyncConflict(sid, op_type, 'cloud_session_changed_refresh_required')
        if current_session is None:
            seed = payload.get('session_seed') if isinstance(payload.get('session_seed'), dict) else {}
            current_session = _auth_chat_store_clone(seed)
            current_session = _auth_chat_normalize_session_sync_metadata(current_session, sid, op=op, revision=int(server_revision or 0) + 1)
            if not isinstance(current_session.get('messages'), list):
                current_session['messages'] = []
        else:
            current_session = _auth_chat_store_clone(current_session)
            current_session = _auth_chat_normalize_session_sync_metadata(current_session, sid, op=op, revision=int(server_revision or 0) + 1)
            if not isinstance(current_session.get('messages'), list):
                current_session['messages'] = []
        current_session['messages'] = _auth_chat_merge_message_lists(
            current_session.get('messages'),
            _auth_chat_store_clone(messages_to_add),
        )
        patch = payload.get('session_patch') if isinstance(payload.get('session_patch'), dict) else {}
        for key, value in patch.items():
            key = str(key or '').strip()
            if not key or key in {'id', 'messages'}:
                continue
            current_session[key] = value
        current_session = _auth_chat_normalize_session_sync_metadata(current_session, sid, op=op, revision=int(server_revision or 0) + 1)
        mode = _auth_chat_session_mode(current_session)
        message_revision = int(_auth_chat_safe_float(current_session.get('serverVersion') or current_session.get('server_version') or 0))
        current_session['messages'] = [
            _auth_chat_normalize_message_sync_metadata(msg, session_id=sid, mode=mode, revision=message_revision)
            if isinstance(msg, dict) else msg
            for msg in (current_session.get('messages') if isinstance(current_session.get('messages'), list) else [])
        ]
        sessions[sid] = _auth_chat_trim_value(current_session, AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS)
        if not active_id or active_id not in sessions:
            store_obj['activeId'] = sid
        return store_obj, True

    if op_type == 'message_body_chunk':
        sid = str(op.get('session_id') or payload.get('session_id') or '').strip()
        if not sid:
            raise ValueError('同步操作缺少会话 ID')
        if _auth_chat_session_is_tombstoned_for_client(store_obj, sid, client_base_revision):
            return store_obj, False
        current_session = sessions.get(sid) if isinstance(sessions.get(sid), dict) else None
        if current_session is None:
            seed = payload.get('session_seed') if isinstance(payload.get('session_seed'), dict) else {}
            current_session = _auth_chat_store_clone(seed)
            current_session = _auth_chat_normalize_session_sync_metadata(current_session, sid, op=op, revision=int(server_revision or 0) + 1)
            if not isinstance(current_session.get('messages'), list):
                current_session['messages'] = []
        current_session, changed = _auth_chat_apply_message_body_chunk_to_session(current_session, payload)
        current_session = _auth_chat_normalize_session_sync_metadata(current_session, sid, op=op, revision=int(server_revision or 0) + 1)
        if changed:
            sessions[sid] = _auth_chat_trim_value(current_session, AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS)
            if not active_id or active_id not in sessions:
                store_obj['activeId'] = sid
        return store_obj, bool(changed)

    if op_type == 'update_session_meta':
        sid = str(op.get('session_id') or payload.get('session_id') or '').strip()
        if not sid:
            raise ValueError('同步操作缺少会话 ID')
        if _auth_chat_session_is_tombstoned_for_client(store_obj, sid, client_base_revision):
            return store_obj, False
        current_session = sessions.get(sid) if isinstance(sessions.get(sid), dict) else None
        if current_session is None:
            # Metadata updates are idempotent. If the target session is absent,
            # keep the server state unchanged instead of failing the whole batch.
            return store_obj, False
        patch = payload.get('patch') if isinstance(payload.get('patch'), dict) else {}
        next_session = _auth_chat_store_clone(current_session)
        changed = False
        for key, value in patch.items():
            key = str(key or '').strip()
            if not key or key in {'id', 'messages'}:
                continue
            next_session[key] = value
            changed = True
        if changed:
            next_session = _auth_chat_normalize_session_sync_metadata(next_session, sid, op=op, revision=int(server_revision or 0) + 1)
            sessions[sid] = _auth_chat_trim_value(next_session, AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS)
        return store_obj, bool(changed)

    if op_type == 'delete_session':
        sid = str(op.get('session_id') or payload.get('session_id') or '').strip()
        if not sid:
            raise ValueError('同步操作缺少会话 ID')
        _auth_chat_add_delete_tombstone(
            store_obj,
            sid,
            deleted_at=payload.get('deleted_at') if payload.get('deleted_at') is not None else payload.get('deletedAt') or op.get('created_at') or op.get('createdAt') or _auth_chat_ms_from_ts(),
            revision=0,
            device_id=str(op.get('device_id') or payload.get('device_id') or ''),
        )
        existing = sessions.get(sid) if isinstance(sessions.get(sid), dict) else None
        if existing is not None:
            try:
                del sessions[sid]
            except KeyError:
                pass
        active_now = str(store_obj.get('activeId') or '').strip()
        if active_now == sid or (active_now and active_now not in sessions):
            store_obj['activeId'] = _auth_chat_pick_active_visible_session_id(store_obj) or None
        elif not sessions:
            store_obj['activeId'] = None
        return store_obj, bool(existing is not None)

    if op_type == 'set_active':
        sid = str(op.get('session_id') or payload.get('session_id') or payload.get('activeId') or op.get('activeId') or '').strip()
        if not sid:
            raise ValueError('同步操作缺少 activeId')
        if sessions and not str(store_obj.get('activeId') or '').strip():
            picked = _auth_chat_pick_active_visible_session_id(store_obj)
            if picked:
                store_obj['activeId'] = picked
                return store_obj, True
        return store_obj, False

    if op_type == 'set_personalization':
        state = payload.get('personalization') if isinstance(payload.get('personalization'), dict) else payload.get('state')
        if not isinstance(state, dict):
            state = {}
        store_obj['personalization'] = _auth_chat_trim_value(state, AUTH_CHAT_ACCOUNT_MAX_TEXT_CHARS)
        return store_obj, True

    raise ValueError('不支持的同步操作')


def _auth_chat_store_push_ops(email: str, ops_payload, *, base_revision=None, device_id: str = '') -> tuple[dict, dict]:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        raise ValueError('未找到登录账号')
    if not isinstance(ops_payload, list):
        raise ValueError('同步操作格式不正确')
    ops = [dict(item or {}) for item in ops_payload if isinstance(item, dict)]
    if not ops:
        rec = _auth_chat_store_get(normalized) or {}
        return rec, {'accepted': [], 'duplicates': [], 'store_changed': False}
    if len(ops) > AUTH_CHAT_SYNC_MAX_OPS_PER_PUSH:
        raise ValueError('同步操作过多，请稍后重试')
    try:
        payload_size = len(json.dumps(ops, ensure_ascii=False).encode('utf-8'))
    except Exception:
        payload_size = AUTH_CHAT_SYNC_OP_MAX_BYTES + 1
    if payload_size > AUTH_CHAT_SYNC_OP_MAX_BYTES:
        raise ValueError('同步操作过大，请稍后重试')

    now_ts = _utc_ts()
    device = _auth_chat_normalize_device_id(device_id)
    accepted: list[dict] = []
    duplicates: list[str] = []
    store_changed = False
    try:
        setattr(_auth_chat_store_push_ops, '_backup_done', False)
    except Exception:
        pass

    with _AUTH_CHAT_LOCK:
        accounts = _AUTH_CHAT_STATE.setdefault('accounts', {})
        prev = dict(_auth_chat_db_get_record(normalized) or accounts.get(normalized) or {})
        server_revision = _auth_chat_store_revision_value(prev)
        initial_server_revision = server_revision
        applied_ops = _auth_chat_prune_applied_ops(prev.get('applied_ops') or {})
        ops_log = _auth_chat_prune_ops_log(prev.get('ops_log') or [])
        store_obj = _auth_chat_store_clone(prev.get('store') if isinstance(prev.get('store'), dict) else {})

        if not isinstance(store_obj.get('sessions'), dict):
            store_obj['sessions'] = {}
        if not str(store_obj.get('activeId') or '').strip() and store_obj.get('sessions'):
            store_obj['activeId'] = next(iter(store_obj['sessions'].keys()), '')

        for raw_op in ops:
            op = dict(raw_op or {})
            op_id = _auth_chat_normalize_op_id(op.get('op_id') or op.get('id'))
            if not op_id:
                op_id = _auth_chat_normalize_op_id(f"{device or 'device'}:{time.time_ns()}:{uuid.uuid4().hex[:12]}")
            if op_id in applied_ops:
                duplicates.append(op_id)
                continue
            op_device = _auth_chat_normalize_device_id(op.get('device_id') or device)
            op_type = str(op.get('op_type') or op.get('type') or '').strip().lower()
            if not op_type:
                raise ValueError('同步操作缺少类型')
            try:
                client_base_revision = max(0, int(base_revision or 0))
            except Exception:
                client_base_revision = 0
            if op_type in {'replace_store', 'snapshot', 'store_snapshot'}:
                op = dict(op)
                op['op_type'] = 'merge_store_snapshot'
                op['type'] = 'merge_store_snapshot'
                op_type = 'merge_store_snapshot'
            if op_type == 'merge_store_snapshot' and not getattr(_auth_chat_store_push_ops, '_backup_done', False):
                try:
                    _auth_chat_store_backup_record(normalized, prev, reason=op_type)
                    setattr(_auth_chat_store_push_ops, '_backup_done', True)
                except Exception:
                    pass
            try:
                next_store, local_changed = _auth_chat_apply_sync_op(
                    store_obj,
                    op,
                    client_base_revision=client_base_revision,
                    server_revision=initial_server_revision,
                )
            except _AuthChatSyncConflict as conflict:
                conflict_rec = prev if isinstance(prev, dict) else {}
                return conflict_rec, {
                    'accepted': [],
                    'duplicates': duplicates,
                    'conflicts': [conflict.public_payload()],
                    'conflict': True,
                    'store_changed': False,
                }
            store_obj = next_store
            server_revision += 1
            if op_type == 'delete_session':
                try:
                    sid_for_delete = str(op.get('session_id') or (op.get('payload') if isinstance(op.get('payload'), dict) else {}).get('session_id') or '').strip()
                    _auth_chat_stamp_delete_tombstone_revision(store_obj, sid_for_delete, revision=server_revision, now_ts=now_ts, device_id=op_device)
                except Exception:
                    pass
            applied_ops[op_id] = {'revision': server_revision, 'updated_at': now_ts}
            log_op = _auth_chat_build_sync_log_op(
                op,
                op_id=op_id,
                device_id=op_device,
                op_type=op_type,
                revision=server_revision,
                now_ts=now_ts,
            )
            if log_op is not None:
                ops_log.append(log_op)
            accepted.append({'op_id': op_id, 'revision': server_revision, 'op_type': op_type})
            store_changed = store_changed or bool(local_changed)

        if accepted:
            clean_store, sanitized_changed = _sanitize_synced_chat_store(store_obj)
            store_changed = store_changed or bool(sanitized_changed)
            applied_ops = _auth_chat_prune_applied_ops(applied_ops)
            ops_log = _auth_chat_prune_ops_log(ops_log)
            accounts[normalized] = {
                'email': normalized,
                'store': clean_store,
                'updated_at': now_ts,
                'revision': server_revision,
                'applied_ops': applied_ops,
                'ops_log': ops_log,
            }
            _AUTH_CHAT_STATE['updated_at'] = now_ts
        else:
            accounts[normalized] = {
                'email': normalized,
                'store': prev.get('store') if isinstance(prev.get('store'), dict) else store_obj,
                'updated_at': float(prev.get('updated_at') or now_ts),
                'revision': server_revision,
                'applied_ops': applied_ops,
                'ops_log': ops_log,
            }

    if accepted:
        with _AUTH_CHAT_LOCK:
            latest_rec = (_AUTH_CHAT_STATE.get('accounts') or {}).get(normalized)
        if isinstance(latest_rec, dict):
            _auth_chat_db_upsert_record(latest_rec)
        else:
            _auth_chat_store_save()
    rec = _auth_chat_store_get(normalized) or {}
    return rec, {'accepted': accepted, 'duplicates': duplicates, 'store_changed': store_changed}


def _auth_chat_store_ops_since(email: str, since_revision: int = 0) -> tuple[dict, list[dict], bool]:
    rec = _auth_chat_store_get(email) or {}
    try:
        since = max(0, int(since_revision or 0))
    except Exception:
        since = 0
    revision = _auth_chat_store_revision_value(rec)
    ops_log = _auth_chat_prune_ops_log(rec.get('ops_log') or [])
    ops = [dict(item or {}) for item in ops_log if int((item or {}).get('revision') or 0) > since]
    if not ops and revision > since:
        return rec, [], True
    if since <= 0:
        return rec, ops, True
    if ops_log:
        min_rev = min(int((item or {}).get('revision') or 0) for item in ops_log if int((item or {}).get('revision') or 0) > 0)
        if since < max(0, min_rev - 1) and revision > since:
            return rec, ops, True
    return rec, ops, False
